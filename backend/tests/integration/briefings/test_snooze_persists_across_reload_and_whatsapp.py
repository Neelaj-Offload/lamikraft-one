"""SCN-B4: snoozed and handled state is per user and server-side, so it survives a reload and a channel switch; the
daily WhatsApp summary (Slice 3) is built from the same visible, overlaid briefing and acknowledgements sync both
ways: "Got it" on WhatsApp is the web's "Seen", and a web acknowledgement voids the WhatsApp buttons."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.modules.briefings import service, summary
from app.modules.briefings.models import SummaryPush
from app.modules.briefings.schemas import ItemActionRequest
from app.modules.channels.models import ActionRef, ChannelIdentity
from app.modules.channels.whatsapp import consent
from app.platform.uow import UnitOfWork
from app.seed.world import keys
from tests.integration.briefings.world import FakeWorld, d0, ist
from tests.integration.channels.conftest import WhatsApp

pytestmark = pytest.mark.db


class _Personas:
    """The briefings world in the shape the channels driver expects (company, actors, user ids)."""

    def __init__(self, world: FakeWorld) -> None:
        self.world = world
        self.company_id = world.company_id

    def actor(self, persona: str):  # type: ignore[no-untyped-def]
        return self.world.actor(persona)

    def user_id(self, persona: str) -> uuid.UUID:
        return self.world.refs[persona]


def linked(world: FakeWorld, persona: str, *, opt_in: bool = True) -> tuple[WhatsApp, ChannelIdentity]:
    wa = WhatsApp(_Personas(world))  # type: ignore[arg-type]
    identity = wa.enrol(persona)  # LINK <code> through the real signed webhook and worker
    if opt_in:
        with UnitOfWork(wa.system()) as uow:
            row = uow.session.get(ChannelIdentity, identity.id)
            consent.record(uow, row, "daily_briefing", "opted_in", source="test")  # type: ignore[arg-type]
    return wa, identity


def summary_messages(wa: WhatsApp, identity: ChannelIdentity) -> list[dict]:  # type: ignore[type-arg]
    return [m for m in wa.messages(identity.id, "outbound") if m["buttons"]]


def test_snooze_reload_and_whatsapp_sync(world: FakeWorld) -> None:
    with UnitOfWork(world.actor(keys.USERS.MEERA, channel="web")) as uow:
        view = service.get_today(uow)
        target = next(i for i in view.items if any(a.action == "snooze" for a in i.allowed_actions))
        service.run_item_action(uow, target.issue_id, ItemActionRequest(action="snooze", until=d0(11, 0)))
    for channel in ("web", "whatsapp"):  # a reload on the web, then the same person on another channel
        with UnitOfWork(world.actor(keys.USERS.MEERA, channel=channel)) as uow:
            again = service.get_today(uow)
        assert target.issue_id not in {i.issue_id for i in again.items}
        (snoozed,) = [i for i in again.snoozed if i.issue_id == target.issue_id]
        assert snoozed.state.snoozed_until == d0(11, 0)
    with UnitOfWork(world.actor(keys.USERS.NEHA)) as uow:  # per user: nobody else's view changes
        assert all(i.issue_id != target.issue_id for i in service.get_today(uow).snoozed)

    # the WhatsApp summary is built from the same overlaid briefing: the snoozed item is not in it
    wa, identity = linked(world, keys.USERS.MEERA)
    with UnitOfWork(world.actor(keys.USERS.MEERA)) as uow:
        sent = service.send_summary_now(uow)
    assert (sent.outcome, sent.kind, sent.simulated) == ("queued", "interactive", True)
    world.drain()
    (message,) = summary_messages(wa, identity)
    assert message["body"].startswith("Demo: Your briefing for Mon 12 Oct. ") and target.title not in message["body"]
    assert [b["title"] for b in message["buttons"]] == ["Got it", "Open Today"]
    assert message["status"] in ("accepted", "sent", "delivered", "read")  # through the real outbox and Demo provider

    # "Got it" on WhatsApp acknowledges the summarised version: the web shows it as seen
    wa.button(wa.wa_id(keys.USERS.MEERA), message["buttons"][0]["id"])
    with UnitOfWork(world.actor(keys.USERS.MEERA, channel="web")) as uow:
        web = service.get_today(uow)
    assert web.up_to_date and web.last_ack is not None and (web.last_ack.method, web.last_ack.channel) == ("whatsapp", "whatsapp")
    assert web.whatsapp_summary is not None and web.whatsapp_summary.ack_channel == "whatsapp"
    assert "Marked as seen" in wa.replies(identity.id)[-1]
    wa.button(wa.wa_id(keys.USERS.MEERA), message["buttons"][0]["id"])  # pressing again acknowledges nothing more
    assert "already used" in wa.replies(identity.id)[-1]
    with UnitOfWork(world.actor(keys.USERS.MEERA)) as uow:  # idempotent per work date
        assert service.send_summary_now(uow).outcome == "queued"
        rows = list(uow.session.scalars(select(SummaryPush).where(SummaryPush.user_id == world.refs[keys.USERS.MEERA])))
        assert len(rows) == 1


def test_web_acknowledgement_marks_the_summary_and_voids_its_buttons(world: FakeWorld) -> None:
    wa, identity = linked(world, keys.USERS.MEERA)
    with UnitOfWork(world.actor(keys.USERS.MEERA)) as uow:
        service.send_summary_now(uow)
    world.drain()
    (message,) = summary_messages(wa, identity)
    with UnitOfWork(world.actor(keys.USERS.MEERA, channel="web")) as uow:
        view = service.get_today(uow)
        service.acknowledge(uow, view.briefing_id, version=view.version, method="explicit")  # type: ignore[arg-type]
    world.drain()  # channels.ack_sync voids the armed "Got it"
    with UnitOfWork(wa.system()) as uow:
        refs = list(uow.session.scalars(select(ActionRef).where(ActionRef.identity_id == identity.id,
                                                               ActionRef.option_payload["kind"].astext == summary.ACK_BUTTON_KIND)))
        assert refs and all(r.voided_at is not None for r in refs)
        row = uow.session.scalars(select(SummaryPush).where(SummaryPush.user_id == world.refs[keys.USERS.MEERA])).one()
        assert row.acknowledged_at is not None and row.ack_channel == "web"
    wa.button(wa.wa_id(keys.USERS.MEERA), message["buttons"][0]["id"])
    assert "Nothing was done" in wa.replies(identity.id)[-1]
    wa.button(wa.wa_id(keys.USERS.MEERA), message["buttons"][1]["id"])  # "Open Today" still answers with a fresh link
    assert "/r/" in wa.replies(identity.id)[-1]


def test_summary_needs_a_link_opt_in_and_a_working_day(world: FakeWorld) -> None:
    with UnitOfWork(world.actor(keys.USERS.MEERA)) as uow:
        assert service.send_summary_now(uow).reason == "not_linked"
    world.at(ist(2026, 10, 13, 9, 0))  # a new work date
    wa, identity = linked(world, keys.USERS.MEERA, opt_in=False)
    with UnitOfWork(world.actor(keys.USERS.MEERA)) as uow:
        skipped = service.send_summary_now(uow)
    assert (skipped.outcome, skipped.reason) == ("skipped", "consent_missing")
    assert not summary_messages(wa, identity)
    with UnitOfWork(wa.system()) as uow:  # opting in later and asking again sends it (a skip is not final)
        consent.record(uow, uow.session.get(ChannelIdentity, identity.id), "daily_briefing", "opted_in", source="test")  # type: ignore[arg-type]
    with UnitOfWork(world.actor(keys.USERS.MEERA)) as uow:
        assert service.send_summary_now(uow).outcome == "queued"
    world.at(ist(2026, 10, 18, 10, 0))  # Sunday: no push on a non-working day
    with UnitOfWork(world.actor(keys.USERS.MEERA)) as uow:
        assert service.send_summary_now(uow).reason == "non_working_day"


def test_scheduled_summary_runs_at_shift_start_for_linked_members(world: FakeWorld) -> None:
    from app.modules.briefings.jobs import summaries_due_company

    world.at(ist(2026, 10, 13, 9, 0))
    linked(world, keys.USERS.MEERA)
    with world.uow() as uow:
        assert summaries_due_company(uow) == 0  # before the 09:30 shift start
    world.at(ist(2026, 10, 13, 9, 35))
    with world.uow() as uow:
        assert summaries_due_company(uow) == 1  # only the linked member
    world.drain()
    with world.uow() as uow:
        row = uow.session.scalars(select(SummaryPush).where(SummaryPush.user_id == world.refs[keys.USERS.MEERA])).one()
        assert row.outcome == "queued" and row.kind == "interactive"
        assert summaries_due_company(uow) == 0  # once per work date
