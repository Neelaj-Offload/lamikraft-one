"""Private reminders (own only, never counted) and the time-driven jobs: overdue sweep and reminder dispatch."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.errors import NotFound, VersionConflict
from app.modules.briefings import service as briefings
from app.modules.tasks import issue_keys
from app.modules.tasks import service as tasks
from app.modules.tasks.jobs import for_each_company
from app.modules.tasks.models import Task
from app.modules.tasks.schemas import ReminderCreate, ReminderUpdate
from app.platform.events.models import DomainEvent
from app.seed.world import keys
from tests.integration.briefings.world import FakeWorld, d0, ist

pytestmark = pytest.mark.db


def test_reminders_are_private_and_never_counted(world: FakeWorld) -> None:
    rid = world.refs[keys.REMINDERS.MEERA]
    with world.uow(keys.USERS.MEERA) as uow:
        mine = tasks.list_reminders(uow)
        counts = tasks.inbox_counts(uow)
    assert [r.id for r in mine.items] == [rid] and mine.items[0].remind_at == ist(2026, 10, 13, 10, 0)
    assert (counts.tasks, counts.conversations) == (1, 2)  # the reminder is not an obligation
    for other in (keys.USERS.SAHIL, keys.USERS.NEHA, keys.USERS.PRIYA):
        with world.uow(other) as uow, pytest.raises(NotFound):
            tasks.get_reminder(uow, rid)
        with world.uow(other) as uow:
            assert all(not i.is_reminder for i in briefings.get_today(uow).items)
    with world.uow(keys.USERS.MEERA) as uow:
        with pytest.raises(VersionConflict):
            tasks.update_reminder(uow, rid, ReminderUpdate(expected_version=99, text="x"))
        updated = tasks.update_reminder(uow, rid, ReminderUpdate(expected_version=mine.items[0].version, remind_at=ist(2026, 10, 13, 11, 0)))
        assert updated.remind_at == ist(2026, 10, 13, 11, 0)
        created = tasks.create_reminder(uow, ReminderCreate(text="Book the Lyon visit", remind_at=d0(16, 0)))
        assert tasks.cancel_reminder(uow, created.id).state == "cancelled"


def test_own_reminder_changes_refresh_the_current_briefing(world: FakeWorld) -> None:
    """A reminder added or cancelled during the day shows up in a new version (the catalogue has no event for
    reminder edits); the version on screen is never re-sorted and a no-op change writes no version."""
    with world.uow(keys.USERS.MEERA) as uow:
        v1 = briefings.get_today(uow)
    with world.uow(keys.USERS.MEERA) as uow:
        created = tasks.create_reminder(uow, ReminderCreate(text="Book the Lyon visit", remind_at=ist(2026, 10, 13, 12, 0)))
    world.drain()
    reminder_issue = issue_keys.issue_id(world.company_id, issue_keys.reminder_key(created.id), 1)
    with world.uow(keys.USERS.MEERA) as uow:
        shown = briefings.get_today(uow, version=v1.version)
        latest = briefings.get_today(uow)
    assert shown.updates_available == 1 and [i.issue_id for i in shown.items] == [i.issue_id for i in v1.items]
    added = next(i for i in latest.items if i.issue_id == reminder_issue)
    assert latest.version == v1.version + 1 and added.is_reminder and added.section == "coming_next"
    with world.uow(keys.USERS.MEERA) as uow:
        tasks.cancel_reminder(uow, created.id)
    world.drain()
    with world.uow(keys.USERS.MEERA) as uow:
        after = briefings.get_today(uow)
    assert after.version == v1.version + 2 and reminder_issue not in {i.issue_id for i in after.items}
    with world.uow(keys.USERS.MEERA) as uow:
        tasks.cancel_reminder(uow, created.id)  # already cancelled: nothing changes
    world.drain()
    with world.uow(keys.USERS.MEERA) as uow:
        assert briefings.get_today(uow).version == after.version
    with world.uow(keys.USERS.NEHA) as uow:  # nobody else's briefing moves
        assert all(not i.is_reminder for i in briefings.get_today(uow).items)


def test_reminder_dispatch_fires_once(world: FakeWorld) -> None:
    world.at(ist(2026, 10, 13, 10, 1))
    with world.uow() as uow:
        assert tasks.dispatch_reminders(uow) == 1
    with world.uow() as uow:
        assert tasks.dispatch_reminders(uow) == 0
        fired = uow.session.scalars(select(DomainEvent).where(DomainEvent.event_type == "tasks.reminder.fired")).all()
    assert [e.payload["reminder_id"] for e in fired] == [str(world.refs[keys.REMINDERS.MEERA])]
    with world.uow(keys.USERS.MEERA) as uow:
        assert tasks.get_reminder(uow, world.refs[keys.REMINDERS.MEERA]).state == "fired"


def test_overdue_sweep_emits_once_and_lapses_quote_expiry(world: FakeWorld) -> None:
    world.at(d0(14, 1))
    with world.uow() as uow:
        assert tasks.sweep_overdue(uow) == 1  # Kabir's 14:00 count task
        assert tasks.sweep_overdue(uow) == 0
        event = uow.session.scalars(select(DomainEvent).where(DomainEvent.event_type == "tasks.task.became_overdue")).one()
    assert event.payload["task_id"] == str(world.refs[keys.TASKS.KABIR_COUNT])
    world.at(ist(2026, 10, 13, 0, 1))  # validity of the two quotes ended at midnight company time
    with world.uow() as uow:
        tasks.sweep_overdue(uow)
        expiry_states = list(uow.session.scalars(select(Task.state).where(Task.kind == "quote_expiry").order_by(Task.created_at)))
    assert expiry_states == ["expired", "expired"]
    with world.uow() as uow:
        from app.modules.tasks.models import Issue

        issue = uow.session.scalars(select(Issue).where(Issue.issue_key == issue_keys.quote_expiry_key(world.refs["Q_BERG_EXPIRING"]))).one()
        assert (issue.state, issue.resolution) == ("resolved", "source_closed")


def test_scheduled_jobs_iterate_active_companies(world: FakeWorld) -> None:
    class Ctx:  # the scheduler enqueues platform-wide jobs without a company
        def __init__(self, uow) -> None:  # type: ignore[no-untyped-def]
            self.uow = uow

    world.at(d0(14, 1))
    from app.platform.authz.context import ActorContext
    from app.platform.uow import UnitOfWork

    with UnitOfWork(ActorContext.system(None, reason="test")) as uow:
        result = for_each_company(Ctx(uow), "tasks.overdue_sweep", tasks.sweep_overdue)  # type: ignore[arg-type]
    assert result["count"] == 1 and result["companies"] >= 1
