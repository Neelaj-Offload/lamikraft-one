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
