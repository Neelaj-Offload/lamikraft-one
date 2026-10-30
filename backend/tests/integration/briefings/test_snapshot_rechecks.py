"""Review-fix regressions for briefings: older snapshots are re-checked against current permissions
(?version=, pins, Explain), linked quote numbers follow quote visibility, undated obligations are never
absent, the delta is clamped and paged, mark-handled is offered only when it can verify, and a dead-lettered
rule delivery marks its family partial."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.errors import NotFound
from app.modules.briefings import service
from app.modules.briefings.models import Briefing, BriefingVersion
from app.modules.briefings.schemas import ItemActionRequest, PinCreate
from app.modules.tasks import issue_keys, responsibility
from app.modules.tasks import service as tasks
from app.modules.tasks.schemas import TaskCreate
from app.modules.tasks.visibility import SourceCache, can_view_source
from app.platform import sources
from app.platform.events.models import DomainEvent
from app.seed.world import keys
from tests.integration.briefings.world import FakeWorld, d0

pytestmark = pytest.mark.db

REVOKED = {"sales.customer_message.read": None, "sales.quote.read": None, "parties.party.read": None}


def today(world: FakeWorld, person: str, **kw: object):  # type: ignore[no-untyped-def]
    with world.uow(person) as uow:
        return service.get_today(uow, **kw)  # type: ignore[arg-type]


def issue(world: FakeWorld, issue_key: str) -> uuid.UUID:
    return issue_keys.issue_id(world.company_id, issue_key, 1)


def test_older_version_is_rechecked_after_a_revoke(world: FakeWorld) -> None:
    """Review blocker 1: ?version=1 after a revoke shows only what Meera may still open, no overview counts."""
    v1 = today(world, keys.USERS.MEERA)
    assert any(i.title.startswith("Reply to") for i in v1.items) and any(i.money for i in v1.items)
    world.overrides[keys.USERS.MEERA] = dict(REVOKED)
    v2 = today(world, keys.USERS.MEERA)
    assert v2.version == 2
    old = today(world, keys.USERS.MEERA, version=1)
    assert old.version == 1 and old.overview is None
    payload = old.model_dump_json()
    for secret in (keys.PARTY_NAMES["BERG"], keys.PARTY_NAMES["NORDHAUS"], keys.PARTY_NAMES["MAISON"],
                   keys.QUOTES.BERG_EXPIRING, keys.QUOTES.NORDHAUS_DRAFT, "5700.00", "5760.00"):
        assert secret not in payload
    with world.uow(keys.USERS.MEERA) as uow:
        cache = SourceCache()
        for item in old.items + old.snoozed:
            for ref in item.source_refs:
                assert can_view_source(uow, ref.type, ref.id, cache=cache)
    berg = issue(world, issue_keys.message_key(world.refs[keys.MESSAGES.BERG]))
    with world.uow(keys.USERS.MEERA) as uow, pytest.raises(NotFound):  # Explain on a row she can no longer see
        service.run_item_action(uow, berg, ItemActionRequest(action="explain"))


def test_permission_change_version_ends_the_live_pin(world: FakeWorld) -> None:
    v1 = today(world, keys.USERS.MEERA)
    with world.uow(keys.USERS.MEERA) as uow:
        pin = service.create_pin(uow, v1.briefing_id, PinCreate(kind="voice"))  # type: ignore[arg-type]
    world.overrides[keys.USERS.MEERA] = dict(REVOKED)
    after = today(world, keys.USERS.MEERA)
    assert after.pin is None and after.version == 2
    with world.uow(keys.USERS.MEERA) as uow:
        ended = uow.session.scalars(select(DomainEvent).where(DomainEvent.event_type == "briefings.pin.ended",
                                                              DomainEvent.aggregate_id == pin.id)).all()
    assert len(ended) == 1


def test_reply_title_hides_numbers_of_quotes_the_viewer_cannot_open(world: FakeWorld) -> None:
    """Review major 6: the linked draft now belongs to Neha; Meera's reply item names no quote number."""
    world.quotes[keys.QUOTE_REFS.NORDHAUS_DRAFT].owner = keys.USERS.NEHA
    with world.uow(keys.USERS.MEERA) as uow:
        assert not can_view_source(uow, "sales.quote", world.refs[keys.QUOTE_REFS.NORDHAUS_DRAFT])
    view = today(world, keys.USERS.MEERA)
    nordhaus = next(i for i in view.items if i.issue_id == issue(world, issue_keys.message_key(world.refs[keys.MESSAGES.NORDHAUS])))
    # (the blocker keeps its own title: Meera may still open the review she requested, approvals.proposal.read)
    text = nordhaus.model_dump_json(include={"title", "summary", "facts", "recommendation", "source_refs", "members"})
    assert keys.QUOTES.NORDHAUS_DRAFT not in text
    assert nordhaus.facts.get("quote_numbers") == []
    assert nordhaus.title == f"Reply to {keys.PARTY_NAMES['NORDHAUS']} — waiting for a review"
    assert nordhaus.recommendation is not None and keys.QUOTES.NORDHAUS_DRAFT not in nordhaus.recommendation.label + nordhaus.recommendation.reason


def test_undated_obligation_is_in_plan_for_today(world: FakeWorld) -> None:
    """Review minor 8: a self-assigned task without a due date (P3) is never absent from Today."""
    world.at(d0(9, 0))
    with world.uow(keys.USERS.MEERA) as uow:
        created = tasks.create_task(uow, TaskCreate(title="Collect Lyon samples"))
    view = today(world, keys.USERS.MEERA)
    item = next(i for i in view.items if i.issue_id == created.issue_id)
    assert item.section == "plan_for_today" and item.band in ("P3", "P4")


def test_delta_is_clamped_to_the_change_window_and_paged(world: FakeWorld) -> None:
    """Review minors 15/12: since=1970 is clamped to seven days before today's window; keyset pages."""
    with world.uow(keys.USERS.MEERA) as uow:
        cal = responsibility.user_calendar(uow, world.refs[keys.USERS.MEERA])
        floor = cal.window(cal.work_date(uow.now()))[0] - service.CHANGE_WINDOW
        full = service.get_delta(uow, since="1970-01-01T00:00:00+00:00")
        assert full.since_instant == floor and full.next_cursor is None
        total = sum(len(g.changes) for g in full.groups)
        assert total >= 1
        first = service.get_delta(uow, since="1970-01-01T00:00:00+00:00", limit=1)
        assert sum(len(g.changes) for g in first.groups) == 1
        if total > 1:
            assert first.next_cursor is not None
            second = service.get_delta(uow, since="1970-01-01T00:00:00+00:00", limit=1, cursor=first.next_cursor)
            assert second.groups[0].changes[0].fact_at >= first.groups[0].changes[0].fact_at
            assert second.groups[0].changes[0] != first.groups[0].changes[0]
        else:
            assert first.next_cursor is None


def test_mark_handled_is_not_offered_when_the_check_cannot_verify(world: FakeWorld) -> None:
    """Spec major 2: without the identity/ui/search readers the onboarding steps offer no mark-handled."""
    steps = [i for i in today(world, keys.USERS.ARJUN).items if i.kind == "onboarding_step"]
    assert steps and all("mark_handled" in {a.action for a in i.allowed_actions} for i in steps)
    for source_type in ("identity.user_preference", "ui.recent_record", "search.recent"):
        sources._READERS.pop(source_type, None)  # world.uninstall restores them
    steps = [i for i in today(world, keys.USERS.ARJUN).items if i.kind == "onboarding_step"]
    assert steps and all("mark_handled" not in {a.action for a in i.allowed_actions} for i in steps)


def test_dead_lettered_rule_delivery_marks_the_family_partial(world: FakeWorld) -> None:
    """Spec minor 6: a dead-lettered tasks.rules delivery opens an admin obligation and flags the family."""
    before = today(world, keys.USERS.MEERA)
    world.at(d0(9, 5))
    job_id = uuid.uuid7()
    world.emit(None, "system.job.dead_lettered", job_id, {"job_id": str(job_id), "kind": "event.handle",
                                                          "handler_key": "tasks.rules:sales.customer_message.received"})
    world.drain()
    with world.uow() as uow:
        admin = tasks.issues_by_id(uow, [issue(world, issue_keys.failed_job_key(job_id))])
    assert admin and next(iter(admin.values())).family == "admin.failed_jobs"
    with world.uow(keys.USERS.MEERA) as uow:
        service.refresh_member(uow, world.refs[keys.USERS.MEERA], cause="event_update", cause_event_ids=[])
    after = today(world, keys.USERS.MEERA, version=before.version + 1)
    replies = [i for i in after.items if i.family == "sales.customer_replies"]
    assert replies and all("PARTIAL_RULES" in i.uncertainty_flags for i in replies)
    assert all("PARTIAL_RULES" not in i.uncertainty_flags for i in after.items if i.family != "sales.customer_replies")
    with world.uow() as uow:
        version = uow.session.scalars(select(BriefingVersion).where(BriefingVersion.briefing_id == before.briefing_id,
                                                                     BriefingVersion.version == before.version + 1)).one()
    assert [p["family"] for p in version.partial_families] == ["sales.customer_replies"]


def test_repeated_generation_failures_open_one_admin_obligation(world: FakeWorld, monkeypatch: pytest.MonkeyPatch) -> None:
    """Spec minor 6: the third consecutive failure of a member's briefing opens an admin obligation."""
    def boom(*_a: object, **_k: object) -> None:
        raise RuntimeError("engine down")

    monkeypatch.setattr(service, "build", boom)
    for minute in (1, 2, 3):
        world.at(d0(9, minute))
        assert today(world, keys.USERS.KABIR).fallback
        world.drain()
    with world.uow() as uow:
        briefing = uow.session.scalars(select(Briefing).where(Briefing.user_id == world.refs[keys.USERS.KABIR])).one()
        assert briefing.consecutive_failures == 3
        found = tasks.issues_by_id(uow, [issue(world, issue_keys.briefing_failure_key(briefing.id))])
    assert len(found) == 1
    monkeypatch.undo()
    world.at(d0(9, 10) + timedelta(minutes=1))
    assert not today(world, keys.USERS.KABIR).fallback
    with world.uow() as uow:
        assert uow.session.get(Briefing, briefing.id).consecutive_failures == 0  # type: ignore[union-attr]
