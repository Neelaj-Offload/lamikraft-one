"""The lead pipeline on real PostgreSQL: sources, stage rules, filters, activities, follow-up tasks and the summary.

Spec: docs/superpowers/specs/2026-11-25-leads-module-design.md
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.core.clock import local_date
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.modules.parties import activities, lead_sources, leads
from app.modules.parties import service as parties
from app.modules.parties.schemas import (
    ActivityCreate,
    LeadSourceCreate,
    LeadSourceUpdate,
    LeadStageChange,
    PartyCreate,
    PartyDetail,
    PartyFilters,
    PartyUpdate,
)
from app.modules.tasks.models import Task
from app.platform.events.models import DomainEvent
from app.platform.uow import UnitOfWork
from app.seed.world import keys
from tests.integration.catalogue.world import World
from tests.support import drain

pytestmark = pytest.mark.db

PRIYA, SAHIL, MEERA, NEHA = keys.USERS.PRIYA, keys.USERS.SAHIL, keys.USERS.MEERA, keys.USERS.NEHA


def _today(world: World) -> date:
    with UnitOfWork(world.actor(MEERA)) as uow:
        return local_date(uow.now(), uow.actor.time_zone)


def _lead(world: World, user: str = MEERA, name: str = "Harbour Kitchen Supply", **extra: object) -> PartyDetail:
    body = {"legal_name": name, "country_code": "US", "default_currency": "USD", "roles": ["customer"],
            "status": "prospect", **extra}
    with UnitOfWork(world.actor(user)) as uow:
        return parties.create_party(uow, PartyCreate.model_validate(body))


def _stage(world: World, party: PartyDetail, stage: str, reason: str | None = None, user: str = MEERA) -> PartyDetail:
    with UnitOfWork(world.actor(user)) as uow:
        return leads.change_lead_stage(
            uow, party.id, LeadStageChange(expected_version=party.version, stage=stage, lost_reason=reason)  # type: ignore[arg-type]
        )


def _log(world: World, party_id: uuid.UUID, user: str = MEERA, **body: object) -> None:
    with UnitOfWork(world.actor(user)) as uow:
        activities.log_activity(uow, party_id, ActivityCreate.model_validate({"kind": "call", "outcome": "Spoke", **body}))


def _open_follow_ups(world: World, party_id: uuid.UUID) -> list[Task]:
    with UnitOfWork(world.actor(PRIYA)) as uow:
        rows = list(
            uow.session.scalars(
                select(Task).where(
                    Task.kind == "lead_follow_up", Task.primary_ref_id == party_id, Task.state.in_(("open", "in_progress"))
                )
            )
        )
        for r in rows:
            uow.session.expunge(r)
        return rows


# ---- lead sources -----------------------------------------------------------------------------------------------
def test_system_sources_listed_and_new_source_assignable(world: World) -> None:
    rows = lead_sources.list_lead_sources(world.actor(SAHIL))
    assert [r.code for r in rows] == ["website", "visiting_card", "trade_show", "referral", "other"]
    assert rows[0].capabilities["update"].allowed is True  # management holds parties.lead_source.manage
    assert lead_sources.list_lead_sources(world.actor(MEERA))[0].capabilities["update"].allowed is False
    with UnitOfWork(world.actor(SAHIL)) as uow:
        created = lead_sources.create_lead_source(uow, LeadSourceCreate(code="nra_chicago_2026", label="NRA Chicago 2026"))
    with pytest.raises(Conflict):
        with UnitOfWork(world.actor(SAHIL)) as uow:
            lead_sources.create_lead_source(uow, LeadSourceCreate(code="nra_chicago_2026", label="Again"))
    with pytest.raises(Forbidden):
        with UnitOfWork(world.actor(MEERA)) as uow:
            lead_sources.create_lead_source(uow, LeadSourceCreate(code="ambiente_2026", label="Ambiente 2026"))
    lead = _lead(world, lead_source="nra_chicago_2026")
    assert lead.lead_source is not None and lead.lead_source.label == "NRA Chicago 2026"
    counted = {r.code: r.lead_count for r in lead_sources.list_lead_sources(world.actor(SAHIL))}
    assert counted["nra_chicago_2026"] == 1 and created.lead_count == 0


def test_inactive_source_kept_but_not_newly_assigned(world: World) -> None:
    lead = _lead(world, lead_source="referral")
    source = next(r for r in lead_sources.list_lead_sources(world.actor(SAHIL)) if r.code == "referral")
    with UnitOfWork(world.actor(SAHIL)) as uow:
        lead_sources.update_lead_source(uow, source.id, LeadSourceUpdate(expected_version=source.version, is_active=False))
    with pytest.raises(ValidationFailed):
        _lead(world, name="Second Lead Co", lead_source="referral")
    with UnitOfWork(world.actor(MEERA)) as uow:  # the existing lead keeps it through an unrelated edit
        same = parties.update_party(uow, lead.id, PartyUpdate(expected_version=lead.version, lead_source="referral",
                                                             website="harbour.example"))
    assert same.lead_source is not None and same.lead_source.code == "referral" and same.website == "harbour.example"


def test_slug_code_makes_valid_codes() -> None:
    assert lead_sources.slug_code("NRA Chicago 2026") == "nra_chicago_2026"
    assert lead_sources.slug_code("VISITING CARD & HOST MILANO 2025") == "visiting_card_host_m"
    assert lead_sources.slug_code("2026 Expo") == "s_2026_expo"


# ---- lead fields and stage ----------------------------------------------------------------------------------------
def test_new_lead_gets_pipeline_defaults_and_vendor_gets_none(world: World) -> None:
    lead = _lead(world, interests=["table_top", "lamikraft"], requirement="Chopping boards, platters",
                 website="harbour.example")
    assert (lead.lead_stage, lead.priority, lead.temperature) == ("new", "B", "cold")
    assert lead.interests == ["lamikraft", "table_top"] and lead.first_contact_on == _today(world)
    assert lead.capabilities["change_stage"].allowed and lead.capabilities["log_activity"].allowed
    with UnitOfWork(world.actor(SAHIL)) as uow:
        vendor = parties.create_party(uow, PartyCreate.model_validate(
            {"legal_name": "Board Mill Pvt", "country_code": "IN", "default_currency": "INR", "roles": ["vendor"]}))
    assert vendor.lead_stage is None and vendor.priority is None
    assert vendor.capabilities["change_stage"].reason_code == "not_a_lead"


def test_lost_needs_a_reason_and_reopen_clears_it(world: World) -> None:
    lead = _lead(world)
    with pytest.raises(ValidationFailed):
        _stage(world, lead, "lost")
    lost = _stage(world, lead, "lost", "Chose a local supplier")
    assert lost.lead_stage == "lost" and lost.lost_reason == "Chose a local supplier"
    reopened = _stage(world, lost, "qualified")
    assert reopened.lead_stage == "qualified" and reopened.lost_reason is None
    with UnitOfWork(world.actor(PRIYA)) as uow:
        events = uow.session.scalars(
            select(DomainEvent).where(DomainEvent.event_type == "parties.lead.stage_changed", DomainEvent.aggregate_id == lead.id)
            .order_by(DomainEvent.seq)
        ).all()
        assert [(e.payload["from_stage"], e.payload["to_stage"]) for e in events] == [("new", "lost"), ("lost", "qualified")]


def test_lost_reason_enforced_by_database(world: World) -> None:
    lead = _lead(world)
    with pytest.raises(DBAPIError):
        with UnitOfWork(world.actor(PRIYA)) as uow:
            uow.session.execute(text("UPDATE parties_party SET lead_stage = 'lost' WHERE id = :id"), {"id": lead.id})
            uow.session.flush()


def test_won_makes_a_customer_and_is_final(world: World) -> None:
    lead = _lead(world)
    won = _stage(world, lead, "won")
    assert won.lead_stage == "won" and won.status == "active"
    assert won.capabilities["change_stage"].reason_code == "lead_won"
    with pytest.raises(Conflict):
        _stage(world, won, "negotiating")


def test_stage_change_outside_scope_is_not_found(world: World) -> None:
    lead = _lead(world, user=MEERA)
    with pytest.raises(NotFound):
        _stage(world, lead, "qualified", user=NEHA)


def test_filters_narrow_the_list(world: World) -> None:
    a = _lead(world, name="Alpha Hospitality", interests=["table_top"], priority="A", temperature="hot",
              lead_source="website")
    b = _lead(world, name="Bravo Hotels", priority="C")
    _stage(world, b, "qualified")
    actor = world.actor(MEERA)

    def ids(**f: object) -> set[uuid.UUID]:
        return {p.id for p in parties.list_parties(actor, PartyFilters.model_validate(f), limit=200).items}

    assert a.id in ids(lead_stage=["new"]) and b.id not in ids(lead_stage=["new"])
    assert ids(lead_stage=["qualified"]) >= {b.id}
    assert a.id in ids(interest="table_top") and b.id not in ids(interest="table_top")
    assert a.id in ids(priority="A") and b.id not in ids(priority="A")
    assert a.id in ids(temperature="hot") and b.id not in ids(temperature="hot")
    assert a.id in ids(lead_source="website") and b.id not in ids(lead_source="website")
    with UnitOfWork(world.actor(NEHA)) as uow:  # own scope: Neha never sees Meera's leads
        assert a.id not in {p.id for p in parties.list_parties(uow.actor, PartyFilters(), limit=200).items}


# ---- activities and follow-ups ------------------------------------------------------------------------------------
def test_activity_moves_new_to_contacted_and_opens_one_follow_up(world: World) -> None:
    lead = _lead(world)
    due = _today(world) + timedelta(days=3)
    _log(world, lead.id, next_follow_up_on=due.isoformat(), notes="Asked for the riser catalogue")
    drain()
    detail = parties.get_party(world.actor(MEERA), lead.id)
    assert detail.lead_stage == "contacted" and detail.next_follow_up_on == due
    page = activities.list_activities(world.actor(MEERA), lead.id)
    assert [a.notes for a in page.items] == ["Asked for the riser catalogue"]
    tasks = _open_follow_ups(world, lead.id)
    assert len(tasks) == 1
    assert tasks[0].assignee_user_id == world.user_id(MEERA)
    assert tasks[0].title == f"Follow up with {lead.display_name}"
    assert tasks[0].due_at is not None and tasks[0].facts["due_on"] == due.isoformat()

    later = due + timedelta(days=4)
    _log(world, lead.id, kind="email", outcome="Sent prices", next_follow_up_on=later.isoformat())
    drain()
    tasks = _open_follow_ups(world, lead.id)
    assert len(tasks) == 1 and tasks[0].facts["due_on"] == later.isoformat()

    _log(world, lead.id, kind="note", outcome="Waiting for their buyer")
    drain()
    assert _open_follow_ups(world, lead.id) == []


def test_won_lost_and_archive_close_the_follow_up(world: World) -> None:
    due = (_today(world) + timedelta(days=1)).isoformat()
    for closing in ("won", "lost", "archive"):
        lead = _lead(world, name=f"Closing {closing} Ltd")
        _log(world, lead.id, next_follow_up_on=due)
        drain()
        assert len(_open_follow_ups(world, lead.id)) == 1
        current = parties.get_party(world.actor(MEERA), lead.id)
        if closing == "archive":
            with UnitOfWork(world.actor(SAHIL)) as uow:
                parties.set_party_archived(uow, lead.id, archived=True, expected_version=current.version)
        else:
            _stage(world, current, closing, "No budget" if closing == "lost" else None)
        drain()
        assert _open_follow_ups(world, lead.id) == [], closing


def test_activity_rules(world: World) -> None:
    lead = _lead(world)
    with pytest.raises(ValidationFailed):  # nothing to record
        with UnitOfWork(world.actor(MEERA)) as uow:
            activities.log_activity(uow, lead.id, ActivityCreate(kind="call"))  # type: ignore[arg-type]
    with pytest.raises(ValidationFailed):  # follow-up in the past
        _log(world, lead.id, next_follow_up_on=(_today(world) - timedelta(days=1)).isoformat())
    with pytest.raises(NotFound):  # outside Neha's scope
        _log(world, lead.id, user=NEHA)
    _log(world, lead.id)
    with pytest.raises(DBAPIError):  # append-only
        with UnitOfWork(world.actor(PRIYA)) as uow:
            uow.session.execute(text("UPDATE parties_activity SET outcome = 'x' WHERE party_id = :id"), {"id": lead.id})
            uow.session.flush()


def test_activity_pages_newest_first(world: World) -> None:
    lead = _lead(world)
    for i in range(5):
        _log(world, lead.id, outcome=f"Call {i}")
    first = activities.list_activities(world.actor(MEERA), lead.id, limit=2)
    assert len(first.items) == 2 and first.next_cursor
    rest = activities.list_activities(world.actor(MEERA), lead.id, cursor=first.next_cursor, limit=10)
    assert len(rest.items) == 3 and rest.next_cursor is None
    seen = [a.outcome for a in first.items + rest.items]
    assert sorted(seen) == [f"Call {i}" for i in range(5)] and len(set(seen)) == 5


# ---- summary ------------------------------------------------------------------------------------------------------
def test_summary_counts_within_scope(world: World) -> None:
    before = leads.lead_summary(world.actor(NEHA))
    mine = [_lead(world, user=NEHA, name=f"Neha Lead {i}") for i in range(3)]
    _stage(world, mine[0], "won", user=NEHA)
    _stage(world, mine[1], "lost", "Price", user=NEHA)
    _log(world, mine[2].id, user=NEHA, next_follow_up_on=_today(world).isoformat())
    _lead(world, user=MEERA, name="Meera Only Lead")
    after = leads.lead_summary(world.actor(NEHA))
    assert after.won - before.won == 1 and after.lost - before.lost == 1 and after.open - before.open == 1
    assert after.follow_ups_today - before.follow_ups_today == 1
    assert after.won_this_month - before.won_this_month == 1
    assert {r.key for r in after.by_owner} <= {str(world.user_id(NEHA))}
    total = after.open + after.won + after.lost
    assert after.conversion_rate == str(round(after.won * 100 / total, 1)) if total else "0.0"
