"""Rule families on real PostgreSQL: events are triggers, facts are re-read from the sources.

Approvals (eligible approvers, due at shift end, 24 h expiry), quote review grouped under the originating
message, replies (SLA, replied or linked quote sent), enquiries, customer changes, onboarding, responsibility
fallbacks, replay, migration origin and the visibility consistency job.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.modules.approvals import service as approvals
from app.modules.briefings import service as briefings
from app.modules.tasks import issue_keys
from app.modules.tasks.models import ChangeLog, Issue, Task, TaskCandidate, TaskDependency
from app.modules.tasks.rules import consumer
from app.platform.events.models import DomainEvent
from app.platform.identity.models import Membership
from app.platform.search import service as search
from app.seed.world import keys
from tests.integration.briefings.world import FakeWorld, d0, ist

pytestmark = pytest.mark.db


def issue_of(world: FakeWorld, issue_key: str) -> Issue:
    with world.uow() as uow:
        row = uow.session.scalars(select(Issue).where(Issue.issue_key == issue_key)).one()
        uow.session.expunge(row)
        return row


def issue_of_any(world: FakeWorld, issue_id: uuid.UUID) -> Issue:
    with world.uow() as uow:
        row = uow.session.get(Issue, issue_id)
        assert row is not None
        uow.session.expunge(row)
        return row


def tasks_of(world: FakeWorld, issue_id: uuid.UUID) -> list[Task]:
    with world.uow() as uow:
        rows = list(uow.session.scalars(select(Task).where(Task.issue_id == issue_id).order_by(Task.created_at, Task.id)))
        for r in rows:
            uow.session.expunge(r)
        return rows


def candidates(world: FakeWorld, task_id: uuid.UUID) -> set[uuid.UUID]:
    with world.uow() as uow:
        return set(uow.session.scalars(select(TaskCandidate.user_id).where(TaskCandidate.task_id == task_id)))


def test_approval_tasks_go_to_eligible_approvers(world: FakeWorld) -> None:
    for prop in (keys.PROPOSALS.MAISON, keys.PROPOSALS.THORNBURY, keys.PROPOSALS.NORDHAUS):
        issue = issue_of(world, issue_keys.approval_key(world.refs[prop]))
        assert issue.id == issue_keys.issue_id(world.company_id, issue.issue_key, 1)
        (task,) = tasks_of(world, issue.id)
        assert (task.kind, task.state, task.due_kind) == ("approval_decision", "open", "soft")
        assert task.due_at == datetime(2026, 10, 12, 13, 0, tzinfo=UTC)  # shift end of the submission work date
        assert task.owner_user_id is None and task.assignee_user_id is None
        assert candidates(world, task.id) == {world.refs[keys.USERS.SAHIL], world.refs[keys.USERS.PRIYA]}
    with world.uow() as uow:
        p = approvals.get(uow, world.refs[keys.PROPOSALS.MAISON])
        assert p.expires_at == d0(8, 20) + timedelta(hours=24)


def test_draft_review_is_grouped_under_the_originating_message(world: FakeWorld) -> None:
    issue = issue_of(world, issue_keys.message_key(world.refs[keys.MESSAGES.NORDHAUS]))
    reply, review = sorted(tasks_of(world, issue.id), key=lambda t: t.kind)
    assert (reply.kind, reply.state, review.kind, review.state) == ("reply_needed", "open", "review_draft", "done")
    assert review.completion_evidence == {"reason": "quote_left_draft", "status": "internal_review"}
    assert review.closed_by == world.refs[keys.USERS.MEERA]
    approval = issue_of(world, issue_keys.approval_key(world.refs[keys.PROPOSALS.NORDHAUS]))
    with world.uow() as uow:
        deps = list(uow.session.scalars(select(TaskDependency.depends_on_issue_id).where(TaskDependency.task_id == reply.id)))
    assert deps == [approval.id]
    assert reply.due_at == datetime(2026, 10, 12, 13, 0, tzinfo=UTC)  # received Sun 19:20 -> next working day 18:30


def test_reply_closes_when_the_message_is_replied(world: FakeWorld) -> None:
    m = world.mark_replied(keys.USERS.MEERA, keys.MESSAGES.BERG, d0(9, 30))
    issue = issue_of(world, issue_keys.message_key(m.id))
    (task,) = tasks_of(world, issue.id)
    assert task.state == "done" and task.completion_evidence["reason"] == "message_replied"
    assert issue.state == "resolved" and issue.resolution == "completed"


def test_reply_closes_when_a_linked_quote_is_sent_after_the_message(world: FakeWorld) -> None:
    world.at(d0(10, 0))
    sent = world.transition(keys.USERS.MEERA, keys.QUOTE_REFS.NORDHAUS_DRAFT, "mark_sent", dispatch_channel="email")
    assert sent.valid_until is not None and str(sent.valid_until)[:10] == "2026-11-11"
    issue = issue_of(world, issue_keys.message_key(world.refs[keys.MESSAGES.NORDHAUS]))
    reply = next(t for t in tasks_of(world, issue.id) if t.kind == "reply_needed")
    assert reply.state == "done" and reply.completion_evidence["reason"] == "linked_quote_sent"
    assert reply.completion_evidence["quote_number"] == keys.QUOTES.NORDHAUS_DRAFT
    expiry = issue_of(world, issue_keys.quote_expiry_key(world.refs[keys.QUOTE_REFS.NORDHAUS_DRAFT]))
    assert [t.state for t in tasks_of(world, expiry.id)] == ["open"]


def test_decided_approval_closes_and_is_handled_for_the_others(world: FakeWorld) -> None:
    world.at(d0(9, 0))
    pid = world.refs[keys.PROPOSALS.MAISON]
    with world.uow(keys.USERS.SAHIL) as uow:
        p = approvals.get(uow, pid)
        approvals.decide(uow, pid, decision="approve", content_hash_seen=p.content_hash, expected_version=p.version)
    world.drain()
    issue = issue_of(world, issue_keys.approval_key(pid))
    (task,) = tasks_of(world, issue.id)
    assert (task.state, task.closed_by, task.completion_evidence["decision"]) == ("done", world.refs[keys.USERS.SAHIL], "approved")
    assert issue.state == "resolved"
    for person in (keys.USERS.PRIYA, keys.USERS.MEERA):  # the other candidate and the initiator
        with world.uow(person) as uow:
            view = briefings.get_today(uow)
        handled = [i for i in view.items if i.section == "handled_for_you"]
        assert [i.issue_id for i in handled] == [issue.id]
        assert handled[0].summary.startswith("Approved by Sahil")
    with world.uow(keys.USERS.SAHIL) as uow:
        assert "handled_for_you" not in {s.code for s in briefings.get_today(uow).sections}


def test_proposals_expire_after_24_hours(world: FakeWorld) -> None:
    world.at(d0(8, 46) + timedelta(hours=24))  # after the last submission (08:45) plus 24 h
    with world.uow() as uow:
        assert approvals.expire_due(uow) == 3
    world.drain()
    for prop in (keys.PROPOSALS.MAISON, keys.PROPOSALS.THORNBURY, keys.PROPOSALS.NORDHAUS):
        (task,) = tasks_of(world, issue_of(world, issue_keys.approval_key(world.refs[prop])).id)
        assert task.state == "expired"


def test_customer_change_is_an_informational_issue_for_the_owner(world: FakeWorld) -> None:
    issue = issue_of(world, issue_keys.party_info_key(world.refs[keys.PARTY_REFS.MAISON]))
    assert (issue.state, issue.family, issue.scope_owner_id) == ("info", "sales.customer_changes", world.refs[keys.USERS.MEERA])
    with world.uow() as uow:
        (row,) = uow.session.scalars(select(ChangeLog).where(ChangeLog.issue_id == issue.id)).all()
    assert (row.change_code, row.actor_user_id, row.after) == ("party.updated", world.refs[keys.USERS.PRIYA], {"changed_fields": ["addresses.shipping"]})
    assert row.fact_at == ist(2026, 10, 11, 10, 5)


def test_onboarding_steps_and_manager_check_in(world: FakeWorld) -> None:
    arjun = world.refs[keys.USERS.ARJUN]
    with world.uow() as uow:
        rows = list(uow.session.scalars(select(Task).where(Task.family == "common.onboarding").order_by(Task.title)))
    steps = [t for t in rows if t.kind == "onboarding_step"]
    (checkin,) = [t for t in rows if t.kind == "onboarding_checkin"]
    assert len(steps) == 3 and {t.completion_check for t in steps} == {"pref_briefing_saved", "recent_record_exists", "recent_search_exists"}
    assert all(t.owner_user_id == arjun and t.assignee_user_id == arjun and t.due_at == d0(18, 30) and t.due_kind == "soft" for t in steps)
    assert (checkin.owner_user_id, checkin.assignee_user_id) == (world.refs[keys.USERS.SAHIL], None)
    assert checkin.due_at == ist(2026, 10, 14, 18, 30)


def test_onboarding_step_completes_only_when_the_source_confirms(world: FakeWorld) -> None:
    from app.modules.tasks import service as tasks
    from app.modules.tasks.errors import NotComplete

    step = issue_of(world, issue_keys.onboarding_key(world.refs[keys.USERS.ARJUN], "global_search"))
    with world.uow(keys.USERS.ARJUN) as uow, pytest.raises(NotComplete):
        tasks.mark_issue_handled(uow, step.id)
    search.record_recent(world.actor(keys.USERS.ARJUN), "oak tray")  # the real search.recent fact
    with world.uow(keys.USERS.ARJUN) as uow:
        assert tasks.mark_issue_handled(uow, step.id).outcome == "completed"


def test_enquiries_open_and_close(world: FakeWorld) -> None:
    done = issue_of(world, issue_keys.enquiry_key(world.refs[keys.ENQUIRY_REFS.MAISON]))
    assert [t.state for t in tasks_of(world, done.id)] == ["done"]
    enquiry_id = world.create_enquiry("ENQ_NEW", keys.PARTY_REFS.BERG, keys.USERS.MEERA, d0(10, 0))
    (task,) = tasks_of(world, issue_of(world, issue_keys.enquiry_key(enquiry_id)).id)
    assert (task.kind, task.state, task.assignee_user_id) == ("enquiry_reply", "open", world.refs[keys.USERS.MEERA])
    assert task.due_at == ist(2026, 10, 13, 18, 30)  # next working day after receipt


def _message(world: FakeWorld, key: str, assignee: str, at: datetime, *, origin: str | None = None,
             received_by_system: bool = False, drain: bool = True) -> uuid.UUID:
    """A real inbound Berg message; one for an assignee who is being deactivated is recorded by the system."""
    return world.record_message(key, keys.PARTY_REFS.BERG, assignee, at, by_system=received_by_system, origin=origin, drain=drain)


def test_team_lead_fallback_then_queue(world: FakeWorld) -> None:
    """No active named person: the manager takes it; with no active manager the family queue does."""
    # the messages are recorded while the assignee is still a member; the rule runs after the deactivation
    m = _message(world, "MSG_FALLBACK", keys.USERS.MEERA, d0(10, 0), received_by_system=True, drain=False)
    with world.uow() as uow:
        meera = uow.session.scalars(select(Membership).where(Membership.user_id == world.refs[keys.USERS.MEERA])).one()
        meera.status = "deactivated"
    world.drain()
    (task,) = tasks_of(world, issue_of(world, issue_keys.message_key(m)).id)
    assert (task.owner_user_id, task.assignee_user_id, task.queue_code) == (world.refs[keys.USERS.SAHIL],) * 2 + (None,)
    with world.uow() as uow:
        meera = uow.session.scalars(select(Membership).where(Membership.user_id == world.refs[keys.USERS.MEERA])).one()
        meera.status = "active"
    m2 = _message(world, "MSG_QUEUE", keys.USERS.MEERA, d0(10, 5), received_by_system=True, drain=False)
    with world.uow() as uow:
        for person in (keys.USERS.MEERA, keys.USERS.SAHIL):
            member = uow.session.scalars(select(Membership).where(Membership.user_id == world.refs[person])).one()
            member.status = "deactivated"
    world.drain()
    (queued,) = tasks_of(world, issue_of(world, issue_keys.message_key(m2)).id)
    assert (queued.owner_user_id, queued.assignee_user_id, queued.queue_code) == (None, None, "sales")
    # the queue is never silent: a triage obligation for queue managers (admins) until it is empty
    triage_issue = issue_of(world, issue_keys.responsibility_key("sales"))
    (triage,) = tasks_of(world, triage_issue.id)
    assert (triage.kind, triage.title, triage.state) == ("queue_triage", "Assign 1 unassigned sales item", "open")
    assert candidates(world, triage.id) == {world.refs[keys.USERS.PRIYA]}
    from app.modules.tasks import service as tasks

    with world.uow(keys.USERS.PRIYA) as uow:
        tasks.assign_task(uow, queued.id, assignee_user_id=world.refs[keys.USERS.PRIYA])
    (triage,) = tasks_of(world, triage_issue.id)
    assert triage.state == "done" and issue_of_any(world, triage_issue.id).state == "resolved"


def test_replayed_and_migration_events_change_nothing(world: FakeWorld) -> None:
    with world.uow() as uow:
        event = uow.session.scalars(select(DomainEvent).where(DomainEvent.event_type == "parties.party.updated")).one()
        assert consumer.handle(uow, event) == 0  # already consumed: exactly once
    m = _message(world, "MSG_MIGRATED", keys.USERS.MEERA, d0(10, 0), origin="migration")
    with world.uow() as uow:
        assert uow.session.scalars(select(Issue).where(Issue.issue_key == issue_keys.message_key(m))).first() is None


def test_access_change_rechecks_approval_eligibility(world: FakeWorld) -> None:
    """The visibility consistency job: revoking sales.quote_price.approve removes Sahil from override approvals."""
    with world.uow(keys.USERS.SAHIL) as uow:
        before = briefings.get_today(uow)
    world.override(keys.USERS.SAHIL, {"sales.quote_price.approve": None})
    world.at(d0(9, 0))
    membership = world.refs[f"{keys.USERS.SAHIL}_MEMBERSHIP"]
    world.emit(keys.USERS.PRIYA, "identity.permission_override.changed", membership,
               {"membership_id": str(membership), "permission_key": "sales.quote_price.approve", "effect": "revoke", "archived": False})
    world.drain()
    sahil, priya = world.refs[keys.USERS.SAHIL], world.refs[keys.USERS.PRIYA]
    for prop, expected in ((keys.PROPOSALS.MAISON, {priya}), (keys.PROPOSALS.THORNBURY, {priya}), (keys.PROPOSALS.NORDHAUS, {sahil, priya})):
        (task,) = tasks_of(world, issue_of(world, issue_keys.approval_key(world.refs[prop])).id)
        assert candidates(world, task.id) == expected
    with world.uow() as uow:
        version = uow.session.scalars(
            select(briefings.BriefingVersion).where(briefings.BriefingVersion.briefing_id == before.briefing_id)
            .order_by(briefings.BriefingVersion.version.desc())).first()
    assert version is not None and version.version == 2 and version.cause == "permission_change"


def test_dismissed_reply_keeps_the_issue_open_across_rederivation(world: FakeWorld) -> None:
    from app.modules.tasks import service as tasks

    key = issue_keys.message_key(world.refs[keys.MESSAGES.BERG])
    (reply,) = tasks_of(world, issue_of(world, key).id)
    with world.uow(keys.USERS.MEERA) as uow:
        tasks.transition_task(uow, reply.id, action="dismiss", reason_code="handled_outside_system")
    world.at(d0(9, 40))
    world.slice2_quote_change(keys.QUOTE_REFS.BERG_EXPIRING, revision_no=2)
    world.emit_quote(keys.USERS.MEERA, "sales.quote.revised", keys.QUOTE_REFS.BERG_EXPIRING, revision_no=2)  # re-derives msg:M2
    world.drain()
    issue = issue_of(world, key)
    assert issue.state == "open" and [t.state for t in tasks_of(world, issue.id)] == ["dismissed"]


def test_lapsed_quote_is_not_reopened_by_later_events(world: FakeWorld) -> None:
    from app.modules.tasks import service as tasks

    world.at(ist(2026, 10, 13, 0, 5))
    with world.uow() as uow:
        tasks.sweep_overdue(uow)
    world.slice2_quote_change(keys.QUOTE_REFS.BERG_EXPIRING)
    world.emit_quote(keys.USERS.MEERA, "sales.quote.updated", keys.QUOTE_REFS.BERG_EXPIRING, version=world.quote(keys.QUOTE_REFS.BERG_EXPIRING).version,
                     changed_fields=["notes"], line_change_kinds=[])
    world.drain()
    expiry = issue_of_any(world, issue_keys.issue_id(world.company_id, issue_keys.quote_expiry_key(world.refs[keys.QUOTE_REFS.BERG_EXPIRING]), 1))
    assert expiry.state == "resolved" and [t.state for t in tasks_of(world, expiry.id)] == ["expired"]


def test_event_after_lapse_expires_the_obligation_before_the_sweep_runs(world: FakeWorld) -> None:
    """The rule re-reads the quote: an event arriving after validity ended lapses the task, never re-arms it."""
    world.at(ist(2026, 10, 13, 0, 5))  # the sweep has not run yet
    world.slice2_quote_change(keys.QUOTE_REFS.BERG_EXPIRING)
    world.emit_quote(keys.USERS.MEERA, "sales.quote.updated", keys.QUOTE_REFS.BERG_EXPIRING, version=world.quote(keys.QUOTE_REFS.BERG_EXPIRING).version,
                     changed_fields=["notes"], line_change_kinds=[])
    world.drain()
    expiry = issue_of_any(world, issue_keys.issue_id(world.company_id, issue_keys.quote_expiry_key(world.refs[keys.QUOTE_REFS.BERG_EXPIRING]), 1))
    assert (expiry.state, expiry.resolution) == ("resolved", "source_closed")
    (task,) = tasks_of(world, expiry.id)
    assert task.state == "expired" and task.completion_evidence == {"reason": "quote_lapsed"}
