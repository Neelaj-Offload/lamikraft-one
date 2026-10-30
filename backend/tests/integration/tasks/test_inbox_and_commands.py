"""The Inbox (tabs, scopes, keyset pages, counts) and task commands (complete, dismiss, assign, snooze,
manual create) with real permission checks: 404 when not visible, 403 when visible but forbidden."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.core.errors import Forbidden, NotFound, ValidationFailed
from app.modules.briefings import service as briefings
from app.modules.tasks import issue_keys
from app.modules.tasks import service as tasks
from app.modules.tasks.errors import ActionNotAllowed, SnoozeBeyondDeadline
from app.modules.tasks.models import Issue, Task
from app.modules.tasks.schemas import TaskCreate
from app.platform.events.models import DomainEvent
from app.seed.world import keys
from tests.integration.briefings.world import FakeWorld, d0

pytestmark = pytest.mark.db


def task_id(world: FakeWorld, issue_key: str, kind: str | None = None) -> uuid.UUID:
    with world.uow() as uow:
        stmt = select(Task.id).join(Issue, Issue.id == Task.issue_id).where(Issue.issue_key == issue_key, Task.state.in_(("open", "in_progress")))
        if kind:
            stmt = stmt.where(Task.kind == kind)
        value = uow.session.scalars(stmt).one()
        return value


def count_task() -> str:
    return keys.TEXTS.TASK_KABIR_COUNT


def kabir_task(world: FakeWorld) -> uuid.UUID:
    return world.refs[keys.TASKS.KABIR_COUNT]


def test_tabs_and_counts_per_persona(world: FakeWorld) -> None:
    with world.uow(keys.USERS.MEERA) as uow:
        conversations = tasks.inbox(uow, tab="conversations")
        work = tasks.inbox(uow, tab="tasks")
        assert tasks.inbox(uow, tab="approvals").items == []
        counts = tasks.inbox_counts(uow)
    assert [i.title for i in conversations.items] == ["Reply to Berg & Co AB", "Reply to Nordhaus Interiors GmbH"]
    assert [i.blocked for i in conversations.items] == [False, True]
    assert [i.kind for i in work.items] == ["quote_expiry"]
    assert work.items[0].source_refs[0].label.startswith(keys.QUOTES.BERG_EXPIRING)
    assert (counts.conversations, counts.tasks, counts.approvals, counts.exceptions) == (2, 1, 0, 0)
    with world.uow(keys.USERS.SAHIL) as uow:
        approvals = tasks.inbox(uow, tab="approvals")
    assert len(approvals.items) == 3 and all(not i.capabilities["complete"].allowed for i in approvals.items)
    with world.uow(keys.USERS.KABIR) as uow:
        kabir = tasks.inbox(uow, tab="tasks")
    assert [i.title for i in kabir.items] == [count_task()] and kabir.items[0].source_refs == []


def test_keyset_pages_do_not_overlap(world: FakeWorld) -> None:
    with world.uow(keys.USERS.SAHIL) as uow:
        first = tasks.inbox(uow, tab="approvals", limit=2)
        assert first.next_cursor is not None
        second = tasks.inbox(uow, tab="approvals", limit=2, cursor=first.next_cursor)
    assert len(first.items) == 2 and len(second.items) == 1 and second.next_cursor is None
    assert not {i.id for i in first.items} & {i.id for i in second.items}
    with world.uow(keys.USERS.SAHIL) as uow, pytest.raises(ValidationFailed):
        tasks.inbox(uow, tab="approvals", cursor="not-a-cursor")


def test_scopes_are_permission_checked_and_sources_filtered(world: FakeWorld) -> None:
    with world.uow(keys.USERS.KABIR) as uow, pytest.raises(Forbidden):
        tasks.inbox(uow, scope="company")
    with world.uow(keys.USERS.RAVI) as uow:
        branch_tasks = tasks.inbox(uow, tab="tasks", scope="branch")
        branch_conversations = tasks.inbox(uow, tab="conversations", scope="branch")
    titles = [i.title for i in branch_tasks.items]
    assert count_task() in titles and any(keys.QUOTES.BERG_EXPIRING in t for t in titles)  # operations reads quotes
    assert branch_conversations.items == []  # but not customer messages
    with world.uow(keys.USERS.SAHIL) as uow:
        company = tasks.inbox(uow, tab="conversations", scope="company")
    assert len(company.items) == 2


def test_complete_manual_task_closes_issue_and_is_handled_for_the_owner(world: FakeWorld) -> None:
    tid = kabir_task(world)
    with world.uow(keys.USERS.KABIR) as uow:
        detail = tasks.get_task(uow, tid)
        assert [t.action for t in detail.allowed_transitions] == ["start", "complete", "dismiss"]
        done = tasks.transition_task(uow, tid, action="complete", expected_version=detail.version)
    assert done.state == "done" and done.completion_evidence == {"reason": "confirmed", "confirmed_by": str(world.refs[keys.USERS.KABIR])}
    with world.uow() as uow:
        assert uow.session.scalar(select(Issue.state).where(Issue.id == done.issue_id)) == "resolved"
        names = [e.event_type for e in uow.session.scalars(select(DomainEvent).where(DomainEvent.aggregate_id.in_((tid, done.issue_id)))
                 .order_by(DomainEvent.seq))]
    assert names[-2:] == ["tasks.task.completed", "tasks.issue.resolved"]
    world.drain()
    with world.uow(keys.USERS.RAVI) as uow:
        ravi = briefings.get_today(uow)
    assert [(i.section, i.title) for i in ravi.items] == [("handled_for_you", count_task())]
    assert ravi.overview is not None and ravi.overview.sentence == "Nothing needs you right now."


def test_dismiss_needs_a_reason_and_scope(world: FakeWorld) -> None:
    berg = task_id(world, issue_keys.message_key(world.refs[keys.MESSAGES.BERG]))
    with world.uow(keys.USERS.NEHA) as uow, pytest.raises(NotFound):
        tasks.transition_task(uow, berg, action="dismiss", reason_code="not_applicable")
    with world.uow(keys.USERS.MEERA) as uow, pytest.raises(ValidationFailed):
        tasks.transition_task(uow, berg, action="dismiss")
    with world.uow(keys.USERS.SAHIL) as uow:  # management dismisses at company scope (audited)
        out = tasks.transition_task(uow, berg, action="dismiss", reason_code="duplicate", note="Answered in another thread")
    assert out.state == "dismissed" and out.dismissal_reason_code == "duplicate"
    approval = task_id(world, issue_keys.approval_key(world.refs[keys.PROPOSALS.MAISON]))
    with world.uow(keys.USERS.SAHIL) as uow, pytest.raises(ActionNotAllowed):
        tasks.transition_task(uow, approval, action="dismiss", reason_code="not_applicable")
    with world.uow(keys.USERS.SAHIL) as uow, pytest.raises(ActionNotAllowed):
        tasks.transition_task(uow, approval, action="complete")


def test_rule_does_not_recreate_a_dismissed_obligation(world: FakeWorld) -> None:
    berg_issue = issue_keys.message_key(world.refs[keys.MESSAGES.BERG])
    berg = task_id(world, berg_issue)
    with world.uow(keys.USERS.MEERA) as uow:
        tasks.transition_task(uow, berg, action="dismiss", reason_code="handled_outside_system")
    world.at(d0(9, 30))
    m = world.messages[keys.MESSAGES.BERG]
    world.emit(keys.USERS.MEERA, "sales.customer_message.received", m.id, {"message_id": str(m.id), "party_id": str(world.refs["BERG"]),
               "contact_id": None, "channel": "email", "assignee_user_id": str(world.refs[keys.USERS.MEERA]), "enquiry_id": None,
               "quote_id": None}, version=m.version)
    world.drain()
    with world.uow() as uow:
        states = list(uow.session.scalars(select(Task.state).join(Issue, Issue.id == Task.issue_id).where(Issue.issue_key == berg_issue)))
    assert states == ["dismissed"]


def test_assign_checks_scope_and_the_assignees_access(world: FakeWorld) -> None:
    tid = kabir_task(world)
    with world.uow(keys.USERS.ARJUN) as uow, pytest.raises(NotFound):  # not visible: 404
        tasks.assign_task(uow, tid, assignee_user_id=world.refs[keys.USERS.ARJUN])
    world.override(keys.USERS.KABIR, {"tasks.task.assign": None})
    with world.uow(keys.USERS.KABIR) as uow, pytest.raises(Forbidden):  # visible but forbidden: 403
        tasks.assign_task(uow, tid, assignee_user_id=world.refs[keys.USERS.RAVI])
    with world.uow(keys.USERS.RAVI) as uow:
        out = tasks.assign_task(uow, tid, assignee_user_id=world.refs[keys.USERS.RAVI])
    assert out.assignee_user_id == world.refs[keys.USERS.RAVI]
    expiry = task_id(world, issue_keys.quote_expiry_key(world.refs[keys.QUOTE_REFS.BERG_EXPIRING]))
    with world.uow(keys.USERS.MEERA) as uow, pytest.raises(ValidationFailed) as err:
        tasks.assign_task(uow, expiry, assignee_user_id=world.refs[keys.USERS.KABIR])
    assert err.value.code == "assignee_cannot_view"


def test_manual_task_link_must_be_visible_to_creator_and_assignee(world: FakeWorld) -> None:
    quote = world.refs[keys.QUOTE_REFS.BERG_EXPIRING]
    with world.uow(keys.USERS.KABIR) as uow, pytest.raises(NotFound):
        tasks.create_task(uow, TaskCreate(title="Check Berg quote", linked_ref_type="sales.quote", linked_ref_id=quote))
    with world.uow(keys.USERS.RAVI) as uow, pytest.raises(ValidationFailed):
        tasks.create_task(uow, TaskCreate(title="Check Berg quote", assignee_user_id=world.refs[keys.USERS.KABIR],
                                          linked_ref_type="sales.quote", linked_ref_id=quote))
    with world.uow(keys.USERS.MEERA) as uow:
        created = tasks.create_task(uow, TaskCreate(title="Confirm Berg delivery window", due_at=d0(17, 0),
                                                    linked_ref_type="sales.quote", linked_ref_id=quote))
    assert created.source_refs[0].id == quote and created.owner_user_id == world.refs[keys.USERS.MEERA]
    with world.uow(keys.USERS.MEERA) as uow, pytest.raises(Forbidden):
        tasks.create_task(uow, TaskCreate(title="Owner elsewhere", owner_user_id=world.refs[keys.USERS.NEHA]))


def test_inbox_snooze_is_bounded_and_per_user(world: FakeWorld) -> None:
    tid = kabir_task(world)
    with world.uow(keys.USERS.KABIR) as uow, pytest.raises(SnoozeBeyondDeadline):
        tasks.snooze_task(uow, tid, d0(13, 1))
    with world.uow(keys.USERS.KABIR) as uow:
        out = tasks.snooze_task(uow, tid, d0(11, 0))
        assert out.snoozed_until == d0(11, 0)
        assert tasks.inbox(uow, tab="tasks").items[0].snoozed_until == d0(11, 0)
    with world.uow(keys.USERS.RAVI) as uow:  # the owner's view is unaffected
        assert tasks.inbox(uow, tab="tasks").items[0].snoozed_until is None
    with world.uow(keys.USERS.KABIR) as uow:
        assert tasks.unsnooze_task(uow, tid).snoozed_until is None
