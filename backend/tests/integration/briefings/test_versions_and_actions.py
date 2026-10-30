"""Scenario B: versions only on real changes, stable issue ids, acknowledgements, snooze, mark handled,
rollover/weekend/holiday, precompute, fallback, pins and the delta view (tests B-01 … B-18)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.core.errors import NotFound
from app.modules.briefings import service
from app.modules.briefings.models import Briefing, BriefingVersion
from app.modules.briefings.schemas import ItemActionRequest
from app.modules.tasks import issue_keys
from app.modules.tasks import service as tasks
from app.modules.tasks.errors import ActionNotAllowed, NotComplete, SnoozeBeyondDeadline
from app.modules.tasks.models import ChangeLog, Issue, Task
from app.platform.audit.models import AuditLog
from app.platform.events.models import DomainEvent
from app.seed.world import keys
from tests.integration.briefings.world import FakeWorld, MessageRec, d0, ist

pytestmark = pytest.mark.db


def today(world: FakeWorld, person: str, **kw: object):  # type: ignore[no-untyped-def]
    with world.uow(person) as uow:
        return service.get_today(uow, **kw)  # type: ignore[arg-type]


def act(world: FakeWorld, person: str, issue_id: uuid.UUID, **body: object):  # type: ignore[no-untyped-def]
    with world.uow(person) as uow:
        return service.run_item_action(uow, issue_id, ItemActionRequest(**body))  # type: ignore[arg-type]


def issue(world: FakeWorld, issue_key: str) -> uuid.UUID:
    return issue_keys.issue_id(world.company_id, issue_key, 1)


def current_version(world: FakeWorld, briefing_id: uuid.UUID) -> int:
    with world.uow() as uow:
        b = uow.session.get(Briefing, briefing_id)
        assert b is not None
        return b.current_version


def new_message(world: FakeWorld, key: str, party: str, at: datetime) -> MessageRec:
    world.at(at)
    m = MessageRec(uuid.uuid7(), party, keys.CONTACTS["MAISON"][0], keys.USERS.MEERA, at)
    world.messages[key] = m
    world.refs[key] = m.id
    world.emit(keys.USERS.MEERA, "sales.customer_message.received", m.id, {
        "message_id": str(m.id), "party_id": str(world.refs[party]), "contact_id": None, "channel": "email",
        "assignee_user_id": str(world.refs[keys.USERS.MEERA]), "enquiry_id": None, "quote_id": None}, version=1)
    world.drain()
    return m


# ---- B-02 / B-03: no manufactured versions ------------------------------------------------------------------
# ---- B-01: a changed source invalidates the recommendation, keeps the issue id -------------------------------
def test_out_of_order_older_event_changes_nothing(world: FakeWorld) -> None:
    """B-03: quote v3 processed, then a v2 event arrives late: facts stay at v3 and no version is made."""
    v1 = today(world, keys.USERS.MEERA)
    world.at(d0(9, 0))
    world.change_quote(keys.QUOTE_REFS.BERG_EXPIRING, revision_no=2)
    v2_version = world.quotes[keys.QUOTE_REFS.BERG_EXPIRING].version
    world.change_quote(keys.QUOTE_REFS.BERG_EXPIRING, revision_no=3)
    world.emit_quote(keys.USERS.MEERA, "sales.quote.revised", keys.QUOTE_REFS.BERG_EXPIRING, revision_no=3)
    world.drain()
    assert current_version(world, v1.briefing_id) == 2  # type: ignore[arg-type]
    q = world.quotes[keys.QUOTE_REFS.BERG_EXPIRING]
    stale = world.emit(keys.USERS.MEERA, "sales.quote.revised", q.id, {"quote_id": str(q.id), "revision_no": 2}, version=v2_version)
    world.drain()
    assert current_version(world, v1.briefing_id) == 2  # type: ignore[arg-type]
    with world.uow() as uow:
        rows = uow.session.scalars(select(ChangeLog).where(ChangeLog.ref_id == q.id, ChangeLog.event_type == "sales.quote.revised")).all()
    # one row per affected issue (expiry and the Berg message it answers), none from the stale event
    assert {r.after["revision_no"] for r in rows} == {3} and len(rows) == 2  # type: ignore[index]
    assert stale not in {r.event_id for r in rows}


# ---- "N updates" without re-sorting ---------------------------------------------------------------------------
def test_updates_signal_never_resorts_the_visible_version(world: FakeWorld) -> None:
    v1 = today(world, keys.USERS.MEERA)
    new_message(world, "MSG_MAISON_NEW", "MAISON", d0(9, 10))
    shown = today(world, keys.USERS.MEERA, version=1)
    assert [i.issue_id for i in shown.items] == [i.issue_id for i in v1.items]
    assert (shown.version, shown.latest_version, shown.updates_available) == (1, 2, 1)
    with world.uow(keys.USERS.MEERA) as uow:
        assert service.briefing_section(uow)["updates_available"] == 1
    latest = today(world, keys.USERS.MEERA)
    assert latest.version == 2 and latest.updates_available == 0
    new_issue = issue(world, issue_keys.message_key(world.refs["MSG_MAISON_NEW"]))
    assert new_issue in [i.issue_id for i in latest.items]
    assert next(i for i in latest.items if i.issue_id == new_issue).change_kind == "new"
    with world.uow(keys.USERS.MEERA) as uow:
        assert service.briefing_section(uow)["updates_available"] == 0


# ---- acknowledgements --------------------------------------------------------------------------------------
def test_acknowledged_unchanged_items_are_not_realerted(world: FakeWorld) -> None:
    """B-18: after acking v1 only the newly changed issue appears under Changes in v2."""
    v1 = today(world, keys.USERS.MEERA)
    with world.uow(keys.USERS.MEERA) as uow:
        ack = service.acknowledge(uow, v1.briefing_id, version=1)  # type: ignore[arg-type]
    assert ack.accepted
    again = today(world, keys.USERS.MEERA)
    assert "changes_since_last_visit" not in {s.code for s in again.sections} and again.up_to_date
    world.at(d0(9, 20))
    world.change_party_contacts(keys.USERS.PRIYA, "BERG", phone="+46 31 700 00 00")  # real parties.party.updated
    world.drain()
    v2 = today(world, keys.USERS.MEERA)
    changes = [i for i in v2.items if i.section == "changes_since_last_visit"]
    assert v2.version == 2 and [i.issue_id for i in changes] == [issue(world, issue_keys.party_info_key(world.refs["BERG"]))]
    with world.uow(keys.USERS.MEERA) as uow:
        assert service.acknowledge(uow, v1.briefing_id, version=2).accepted  # type: ignore[arg-type]
        older = service.acknowledge(uow, v1.briefing_id, version=1)  # type: ignore[arg-type]
    assert not older.accepted and older.version == 2  # monotonic


# ---- snooze --------------------------------------------------------------------------------------------------
def test_snooze_is_bounded_by_the_deadline_and_woken_by_overdue(world: FakeWorld) -> None:
    """B-08 (and B-07 web part): snooze beyond the hard deadline is 422 with max_until; snoozing keeps the
    task open and the Inbox counts unchanged; the overdue sweep wakes the item into Needs you now."""
    view = today(world, keys.USERS.KABIR)
    item = view.items[0]
    with pytest.raises(SnoozeBeyondDeadline) as too_far:
        act(world, keys.USERS.KABIR, item.issue_id, action="snooze", until=d0(13, 30))
    assert too_far.value.extra["max_until"] == d0(13, 0).astimezone(UTC).isoformat()
    with world.uow(keys.USERS.KABIR) as uow:
        counts_before = tasks.inbox_counts(uow)
    result = act(world, keys.USERS.KABIR, item.issue_id, action="snooze", until=d0(12, 0))
    assert result.outcome == "snoozed"
    snoozed = today(world, keys.USERS.KABIR)
    assert [i.issue_id for i in snoozed.snoozed] == [item.issue_id] and snoozed.items == []
    with world.uow(keys.USERS.KABIR) as uow:
        assert tasks.inbox_counts(uow) == counts_before
        assert uow.session.scalars(select(Task.state).where(Task.issue_id == item.issue_id)).all() == ["open"]
    world.at(d0(14, 5))
    with world.uow() as uow:
        assert tasks.sweep_overdue(uow) >= 1
    world.drain()
    woke = today(world, keys.USERS.KABIR)
    assert woke.version == 2 and woke.snoozed == []
    top = woke.items[0]
    assert (top.issue_id, top.section, top.reason_codes[0]) == (item.issue_id, "needs_you_now", "OVERDUE")
    assert top.due_label == "Overdue since 14:00"


# ---- mark handled ------------------------------------------------------------------------------------------
def test_mark_handled_verifies_the_source_or_needs_an_authorised_reason(world: FakeWorld) -> None:
    """B-09."""
    today(world, keys.USERS.MEERA)
    berg_reply = issue(world, issue_keys.message_key(world.refs[keys.MESSAGES.BERG]))
    with pytest.raises(NotComplete) as incomplete:
        act(world, keys.USERS.MEERA, berg_reply, action="mark_handled")
    assert incomplete.value.extra["remaining"] == ["reply_to_customer"]
    with pytest.raises(NotFound):
        act(world, keys.USERS.KABIR, berg_reply, action="dismiss", reason_code="not_applicable")
    out = act(world, keys.USERS.MEERA, berg_reply, action="mark_handled", reason_code="handled_outside_system", note="Called Erik")
    assert out.outcome == "dismissed"
    with world.uow() as uow:
        assert uow.session.scalar(select(Issue.state).where(Issue.id == berg_reply)) == "open"
        assert uow.session.scalar(select(Task.state).where(Task.issue_id == berg_reply, Task.kind == "reply_needed")) == "dismissed"
        audit = uow.session.scalars(select(AuditLog).where(AuditLog.action == "tasks.task.dismissed")).one()
        assert audit.actor_user_id == world.refs[keys.USERS.MEERA] and audit.reason == "Called Erik"
    sahil = today(world, keys.USERS.SAHIL)
    with pytest.raises(ActionNotAllowed):
        act(world, keys.USERS.SAHIL, sahil.items[0].issue_id, action="mark_handled")


def test_mark_handled_completes_when_the_source_confirms(world: FakeWorld) -> None:
    today(world, keys.USERS.MEERA)
    berg_reply = issue(world, issue_keys.message_key(world.refs[keys.MESSAGES.BERG]))
    world.messages[keys.MESSAGES.BERG].status = "replied"
    world.messages[keys.MESSAGES.BERG].replied_at = d0(8, 54)
    out = act(world, keys.USERS.MEERA, berg_reply, action="mark_handled")
    assert out.outcome == "completed"
    with world.uow() as uow:
        task = uow.session.scalars(select(Task).where(Task.issue_id == berg_reply)).one()
    assert task.state == "done" and task.completion_evidence["reason"] == "message_replied"


def test_validity_extension_completes_the_expiry_task(world: FakeWorld) -> None:
    world.at(d0(9, 30))
    world.change_quote(keys.QUOTE_REFS.BERG_EXPIRING, valid_until=date(2026, 10, 14))
    world.emit_quote(keys.USERS.MEERA, "sales.quote.validity_extended", keys.QUOTE_REFS.BERG_EXPIRING,
                     revision_id=str(uuid.uuid7()), valid_until="2026-10-14")
    world.drain()
    expiry = issue(world, issue_keys.quote_expiry_key(world.refs[keys.QUOTE_REFS.BERG_EXPIRING]))
    with world.uow() as uow:
        rows = uow.session.scalars(select(Task).where(Task.issue_id == expiry).order_by(Task.created_at)).all()
    assert [(t.state, (t.completion_evidence or {}).get("reason")) for t in rows] == [("done", "validity_extended"), ("open", None)]
    assert rows[1].due_at == datetime(2026, 10, 14, 18, 30, tzinfo=UTC)  # end of 2026-10-14 in company time
    view = today(world, keys.USERS.MEERA)
    assert next(i for i in view.items if i.issue_id == expiry).section == "coming_next"


# ---- time boundaries --------------------------------------------------------------------------------------
def test_midnight_rollover(world: FakeWorld) -> None:
    """B-10: 23:50, 00:10 and 03:59:59 return Monday's briefing; 04:00 creates Tuesday's."""
    world.at(ist(2026, 10, 12, 23, 50))
    monday = today(world, keys.USERS.MEERA)
    for at in (ist(2026, 10, 13, 0, 10), ist(2026, 10, 13, 3, 59) + timedelta(seconds=59)):
        world.at(at)
        assert today(world, keys.USERS.MEERA).briefing_id == monday.briefing_id
    world.at(ist(2026, 10, 13, 4, 0))
    tuesday = today(world, keys.USERS.MEERA)
    assert tuesday.briefing_id != monday.briefing_id and tuesday.work_date == date(2026, 10, 13)
    assert monday.work_date == date(2026, 10, 12)
    with world.uow() as uow:
        assert uow.session.get(Briefing, monday.briefing_id) is not None


def test_sunday_is_non_working(world: FakeWorld) -> None:
    """B-12: Sunday shows only overdue/hard items now, Monday's plan under Coming next; SLA due Monday 18:30;
    no precompute on non-working days."""
    world.at(ist(2026, 10, 11, 20, 0))
    view = today(world, keys.USERS.MEERA)
    assert view.day_type == "non_working"
    codes = {s.code for s in view.sections}
    assert "plan_for_today" not in codes and "needs_you_now" not in codes
    berg = next(i for i in view.items if i.issue_id == issue(world, issue_keys.message_key(world.refs[keys.MESSAGES.BERG])))
    assert berg.section == "coming_next" and berg.due_label == "Tomorrow 18:30"
    assert berg.due_at == datetime(2026, 10, 12, 13, 0, tzinfo=UTC)  # received Sunday 17:40 -> Monday 18:30
    from app.modules.briefings.jobs import precompute_company

    world.at(ist(2026, 10, 11, 9, 5))
    with world.uow() as uow:
        assert precompute_company(uow) == 0


def test_holiday_day_type(world: FakeWorld) -> None:
    world.at(ist(2026, 10, 22, 10, 0))
    view = today(world, keys.USERS.MEERA)
    assert view.day_type == "holiday" and "plan_for_today" not in {s.code for s in view.sections}


def test_precompute_then_first_open(world: FakeWorld) -> None:
    """B-14: precompute 30 minutes before the shift creates the briefing unopened; the open reuses it."""
    from app.modules.briefings.jobs import precompute_company

    world.at(ist(2026, 10, 13, 8, 0))
    with world.uow() as uow:
        assert precompute_company(uow) == 0  # too early
    world.at(ist(2026, 10, 13, 9, 5))
    with world.uow() as uow:
        created = precompute_company(uow)
    assert created == 8  # every Slice-1 member with briefing access
    with world.uow() as uow:
        pre = uow.session.scalars(select(Briefing).where(Briefing.user_id == world.refs[keys.USERS.MEERA],
                                                         Briefing.work_date == date(2026, 10, 13))).one()
        assert (pre.trigger, pre.first_opened_at, pre.current_version) == ("precompute", None, 1)
        assert precompute_company(uow) == 0  # idempotent
    world.at(ist(2026, 10, 13, 9, 40))
    opened = today(world, keys.USERS.MEERA)
    assert opened.briefing_id == pre.id and opened.first_opened_at == ist(2026, 10, 13, 9, 40) and opened.trigger == "precompute"


# ---- fallback ----------------------------------------------------------------------------------------------
def test_engine_failure_falls_back_to_tasks_and_last_successful(world: FakeWorld, monkeypatch: pytest.MonkeyPatch) -> None:
    """B-16: a permission-filtered task list (no Neha items) plus the last successful briefing, re-filtered."""
    from app.modules.briefings.engine import collect

    v1 = today(world, keys.USERS.MEERA)
    world.override(keys.USERS.MEERA, {"sales.customer_message.read": None})

    def broken(self, cutoff):  # type: ignore[no-untyped-def]
        raise RuntimeError("engine fault")

    monkeypatch.setattr(collect.Collector, "collect", broken)
    view = today(world, keys.USERS.MEERA)
    assert view.status == "fallback" and view.fallback and view.fallback_detail is not None
    titles = [t.title for t in view.fallback_detail.tasks]
    assert any(keys.QUOTES.BERG_EXPIRING in t for t in titles)
    assert not any(t.startswith("Reply to") for t in titles)  # messages are no longer visible
    neha = str(world.refs[keys.USERS.NEHA])
    assert neha not in view.model_dump_json() and keys.QUOTES.THORNBURY_EXPIRING not in view.model_dump_json()
    last = view.fallback_detail.last_successful
    assert last is not None and last.briefing_id == v1.briefing_id and last.version == 1
    assert last.generated_at == v1.generated_at and last.overview is None  # permissions changed since
    assert not any(i.kind == "reply_needed" for i in last.items)
    with world.uow() as uow:
        failed = uow.session.scalars(select(DomainEvent).where(DomainEvent.event_type == "briefings.briefing.generation_failed")).all()
        assert [e.payload["briefing_id"] for e in failed] == [str(v1.briefing_id)]
        assert uow.session.scalar(select(func.count()).select_from(BriefingVersion).where(BriefingVersion.briefing_id == v1.briefing_id)) == 1


# ---- pins --------------------------------------------------------------------------------------------------------
# ---- delta and isolation ----------------------------------------------------------------------------------------
def test_delta_since_yesterday_is_source_linked_and_filtered(world: FakeWorld) -> None:
    with world.uow(keys.USERS.MEERA) as uow:
        delta = service.get_delta(uow, since="yesterday")
    assert delta.since_instant == ist(2026, 10, 11, 4, 0)
    maison = issue(world, issue_keys.party_info_key(world.refs[keys.PARTY_REFS.MAISON]))
    group = next(g for g in delta.groups if g.issue_id == maison)
    change = group.changes[0]
    assert change.after == {"changed_fields": ["addresses.shipping"]} and change.actor is not None and change.actor.name == "Priya Nair"
    # the source label is the real parties reader's "P-NNNNN · name"
    assert change.source is not None and change.source.label == f"{keys.PARTIES.MAISON} · {keys.PARTY_NAMES['MAISON']}"
    with world.uow(keys.USERS.KABIR) as uow:
        assert service.get_delta(uow, since="last_ack").groups == []


def test_other_users_briefing_resources_are_not_found(world: FakeWorld) -> None:
    """A-11: Kabir cannot reach Sahil's briefing, explain or snooze Meera's items, or open Meera's task."""
    sahil = today(world, keys.USERS.SAHIL)
    meera = today(world, keys.USERS.MEERA)
    today(world, keys.USERS.KABIR)
    with world.uow(keys.USERS.KABIR) as uow, pytest.raises(NotFound):
        service.acknowledge(uow, sahil.briefing_id, version=1)  # type: ignore[arg-type]
    with pytest.raises(NotFound):
        act(world, keys.USERS.KABIR, sahil.items[0].issue_id, action="explain")
    with pytest.raises(NotFound):
        act(world, keys.USERS.KABIR, meera.items[0].issue_id, action="snooze", until=d0(10, 0))
    with world.uow() as uow:
        task_id = uow.session.scalar(select(Task.id).where(Task.issue_id == meera.items[0].issue_id))
    with world.uow(keys.USERS.KABIR) as uow, pytest.raises(NotFound):
        tasks.get_task(uow, task_id)  # type: ignore[arg-type]


def test_explain_returns_rule_text_and_sources(world: FakeWorld) -> None:
    view = today(world, keys.USERS.MEERA)
    out = act(world, keys.USERS.MEERA, view.items[0].issue_id, action="explain")
    assert out.explanation is not None
    assert out.explanation.text.startswith("P1 priority, score 75: Due today (+35); A customer is waiting (+25); Assigned to you (+15).")
    assert out.explanation.sources and out.explanation.rule_version


def test_issue_ids_are_stable_across_regenerations(world: FakeWorld) -> None:
    """A permission change that leaves the visible items unchanged writes no version and signals no update
    (spec review 1); one that changes them writes a permission_change version with the same issue ids."""
    v1 = today(world, keys.USERS.MEERA)
    world.override(keys.USERS.MEERA, {"catalogue.product.read": None})  # irrelevant to every item
    same = today(world, keys.USERS.MEERA)
    assert (same.version, same.latest_version, same.updates_available) == (1, 1, 0)
    assert same.overview is not None and same.overview.sentence == v1.overview.sentence  # type: ignore[union-attr]
    with world.uow(keys.USERS.MEERA) as uow:
        assert service.briefing_section(uow)["updates_available"] == 0
        latest = uow.session.scalars(select(BriefingVersion).where(BriefingVersion.briefing_id == v1.briefing_id)).all()
    assert [v.version for v in latest] == [1]
    world.override(keys.USERS.MEERA, {"catalogue.product.read": None, "parties.party.read": None})  # hides the Maison change
    v2 = today(world, keys.USERS.MEERA)
    assert v2.version == 2
    assert [i.issue_id for i in v2.items] == [i.issue_id for i in v1.items if i.family != "sales.customer_changes"]
    assert v1.items[0].issue_id == issue_keys.issue_id(world.company_id, issue_keys.message_key(world.refs[keys.MESSAGES.BERG]), 1)


def test_night_shift_work_date_and_precompute(world: FakeWorld) -> None:
    """B-11 with a test-local NGT shift (22:00-06:00, rollover 08:00) for Ravi."""
    from app.modules.briefings.jobs import precompute_company
    from app.platform.org.workcal import WorkAssignment, WorkCalendar, WorkShift

    with world.uow() as uow:
        cal = uow.session.scalars(select(WorkCalendar).where(WorkCalendar.company_id == world.company_id)).one()
        shift = WorkShift(calendar_id=cal.id, code="NGT", name="Night", start_local=datetime.strptime("22:00", "%H:%M").time(),
                          end_local=datetime.strptime("06:00", "%H:%M").time(),
                          rollover_local=datetime.strptime("08:00", "%H:%M").time())
        uow.add(shift)
        uow.flush()
        uow.add(WorkAssignment(user_id=world.refs[keys.USERS.RAVI], calendar_id=cal.id, shift_id=shift.id, effective_from=date(2026, 1, 1)))
    world.at(ist(2026, 10, 12, 21, 35))
    with world.uow() as uow:
        precompute_company(uow)
        night = uow.session.scalars(select(Briefing).where(Briefing.user_id == world.refs[keys.USERS.RAVI])).one()
    assert (night.work_date, night.trigger) == (date(2026, 10, 12), "precompute")
    world.at(ist(2026, 10, 13, 2, 0))
    assert today(world, keys.USERS.RAVI).briefing_id == night.id
    world.at(ist(2026, 10, 13, 8, 0))
    assert today(world, keys.USERS.RAVI).work_date == date(2026, 10, 13)


def test_seeds_are_idempotent(world: FakeWorld) -> None:
    from app.modules.tasks.models import Reminder

    with world.uow() as uow:
        before = (uow.session.scalar(select(func.count()).select_from(Task)), uow.session.scalar(select(func.count()).select_from(Reminder)))
    world.run_seeds()
    with world.uow() as uow:
        after = (uow.session.scalar(select(func.count()).select_from(Task)), uow.session.scalar(select(func.count()).select_from(Reminder)))
    assert after == before
