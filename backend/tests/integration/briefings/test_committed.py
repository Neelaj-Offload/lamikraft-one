"""Committed-mode tests: concurrent first opens produce one briefing (advisory lock per member), and the
work tables are isolated per tenant by forced RLS."""

from __future__ import annotations

import threading
import uuid

import pytest
from sqlalchemy import create_engine, func, select, text

from app.core.config import get_settings
from app.modules.briefings import service
from app.modules.briefings.models import Briefing, BriefingVersion
from app.modules.tasks import service as tasks
from app.modules.tasks.schemas import TaskCreate
from app.platform.uow import UnitOfWork
from app.seed.world import keys
from tests.integration.briefings.world import FakeWorld, d0
from tests.support import create_company

pytestmark = [pytest.mark.db, pytest.mark.committed]


def test_concurrent_first_opens_create_one_briefing(committed_db: str, bare_world: FakeWorld) -> None:
    with UnitOfWork(bare_world.actor(keys.USERS.MEERA)) as uow:
        tasks.create_task(uow, TaskCreate(title="Prepare the Lyon visit", due_at=d0(17, 0)))
    barrier = threading.Barrier(4)
    results: list[uuid.UUID] = []
    errors: list[BaseException] = []
    lock = threading.Lock()

    def open_today() -> None:
        try:
            barrier.wait(timeout=30)
            with UnitOfWork(bare_world.actor(keys.USERS.MEERA)) as uow:
                view = service.get_today(uow)
            with lock:
                results.append(view.briefing_id)  # type: ignore[arg-type]
        except BaseException as exc:  # noqa: BLE001 - surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=open_today) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert not errors, errors
    assert len(set(results)) == 1
    with UnitOfWork(bare_world.actor(keys.USERS.MEERA)) as uow:
        assert uow.session.scalar(select(func.count()).select_from(Briefing)) == 1
        assert uow.session.scalar(select(func.count()).select_from(BriefingVersion)) == 1


def test_work_tables_are_tenant_isolated(committed_db: str, bare_world: FakeWorld) -> None:
    with UnitOfWork(bare_world.actor(keys.USERS.MEERA)) as uow:
        tasks.create_task(uow, TaskCreate(title="Prepare the Lyon visit", due_at=d0(17, 0)))
    other, _ = create_company()
    engine = create_engine(get_settings().app_database_url)
    with engine.connect() as conn:
        for table in ("tasks_task", "tasks_issue", "tasks_task_history"):
            assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar() == 0  # fails closed without a tenant
            conn.execute(text("SELECT set_config('app.company_id', :c, false)"), {"c": str(other)})
            assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar() == 0
            conn.execute(text("SELECT set_config('app.company_id', :c, false)"), {"c": str(bare_world.company_id)})
            assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar() >= 1
            conn.execute(text("SELECT set_config('app.company_id', '', false)"))
    engine.dispose()


def test_refresh_rereads_the_briefing_under_the_lock(committed_db: str, bare_world: FakeWorld, monkeypatch: pytest.MonkeyPatch) -> None:
    """Review major 5: another worker writes version 2 between this refresh's first read and its lock; the
    refresh re-reads, writes no duplicate number and reports no generation failure."""
    from app.modules.briefings.models import BriefingVersion as Version
    from app.platform.authz.context import ActorContext
    from app.platform.events.models import DomainEvent

    meera = bare_world.refs[keys.USERS.MEERA]
    with UnitOfWork(bare_world.actor(keys.USERS.MEERA)) as uow:
        tasks.create_task(uow, TaskCreate(title="Prepare the Lyon visit", due_at=d0(17, 0)))
        service.get_today(uow)
    original = service._lock
    state = {"first": True}

    def other_worker_first(uow: UnitOfWork, user_id: uuid.UUID) -> None:
        if state.pop("first", False):
            def run() -> None:
                with UnitOfWork(bare_world.actor(keys.USERS.MEERA)) as other:
                    tasks.create_task(other, TaskCreate(title="Book the Lyon hotel", due_at=d0(16, 0)))
                with UnitOfWork(ActorContext.system(bare_world.company_id, reason="test")) as other:
                    assert service.refresh_member(other, meera, cause="event_update", cause_event_ids=[]) is not None

            worker = threading.Thread(target=run)
            worker.start()
            worker.join(timeout=60)
        original(uow, user_id)

    monkeypatch.setattr(service, "_lock", other_worker_first)
    with UnitOfWork(ActorContext.system(bare_world.company_id, reason="test")) as uow:
        assert service.refresh_member(uow, meera, cause="event_update", cause_event_ids=[]) is None  # nothing new
    with UnitOfWork(ActorContext.system(bare_world.company_id, reason="test")) as uow:
        assert sorted(uow.session.scalars(select(Version.version))) == [1, 2]
        failed = uow.session.scalar(select(func.count()).select_from(DomainEvent).where(
            DomainEvent.event_type == "briefings.briefing.generation_failed"))
    assert failed == 0


def test_task_commands_lock_the_issue_before_the_task(committed_db: str, bare_world: FakeWorld) -> None:
    """Review major 4: one lock order (issue, then task). While another transaction holds the issue row, a
    complete command waits on the issue and has not locked the task row yet."""
    from app.modules.tasks.models import Task

    with UnitOfWork(bare_world.actor(keys.USERS.MEERA)) as uow:
        created = tasks.create_task(uow, TaskCreate(title="Prepare the Lyon visit", due_at=d0(17, 0)))
    engine = create_engine(get_settings().app_database_url)
    holder = engine.connect()
    probe = engine.connect()
    for conn in (holder, probe):
        conn.execute(text("SELECT set_config('app.company_id', :c, false)"), {"c": str(bare_world.company_id)})
    probe.commit()
    holder.commit()
    tx = holder.begin()
    holder.execute(text("SELECT id FROM tasks_issue WHERE id = :i FOR UPDATE"), {"i": created.issue_id})
    errors: list[BaseException] = []

    def complete() -> None:
        try:
            with UnitOfWork(bare_world.actor(keys.USERS.MEERA)) as uow:
                tasks.transition_task(uow, created.id, action="complete", expected_version=created.version)
        except BaseException as exc:  # noqa: BLE001 - surfaced below
            errors.append(exc)

    worker = threading.Thread(target=complete)
    worker.start()
    try:
        waiting = False
        for _ in range(100):  # until the command is blocked on a lock
            waiting = bool(probe.execute(text(
                "SELECT count(*) FROM pg_stat_activity WHERE wait_event_type = 'Lock' AND datname = current_database()")).scalar())
            probe.commit()  # a new statistics snapshot on every poll
            if waiting:
                break
            threading.Event().wait(0.05)
        assert waiting
        locked = probe.execute(text("SELECT id FROM tasks_task WHERE id = :t FOR UPDATE NOWAIT"), {"t": created.id}).all()
        assert len(locked) == 1  # the task row is free: the command waits on the issue first
        probe.rollback()
    finally:
        tx.rollback()
        worker.join(timeout=60)
        holder.close()
        probe.close()
        engine.dispose()
    assert not errors, errors
    with UnitOfWork(bare_world.actor(keys.USERS.MEERA)) as uow:
        assert uow.session.get(Task, created.id).state == "done"  # type: ignore[union-attr]
