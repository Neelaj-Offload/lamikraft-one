"""Kernel behaviour on real PostgreSQL: RLS, numbering, outbox, jobs, idempotency, concurrency."""

from __future__ import annotations

import threading
import uuid
from datetime import date
from typing import Any

import pytest
from sqlalchemy import create_engine, select, text

from app.core.config import get_settings
from app.core.db.base import Base
from app.core.errors import IdempotencyKeyReused, VersionConflict
from app.platform.authz.context import ActorContext
from app.platform.events.defs import EventDef, Subscription
from app.platform.events.models import DomainEvent
from app.platform.identity.models import Membership
from app.platform.idempotency.service import run_idempotent
from app.platform.jobs.defs import JobDef
from app.platform.jobs.models import Job
from app.platform.numbering.models import DocumentSequence
from app.platform.org.models import Branch
from app.platform.uow import UnitOfWork
from app.registry import get_registry
from tests.support import create_company, create_user, drain

pytestmark = pytest.mark.db


def _sequence(company_id: uuid.UUID, key: str = "test.doc", template: str = "TD-{yyyy}-{seq:04}", policy: str = "yearly") -> None:
    with UnitOfWork(ActorContext.system(company_id)) as uow:
        uow.add(DocumentSequence(company_id=company_id, sequence_key=key, name=key, format_template=template, reset_policy=policy))


# ---- RLS ---------------------------------------------------------------------------------------
@pytest.mark.committed
def test_rls_fails_closed_without_tenant_guc(committed_db: str) -> None:
    a, _ = create_company()
    b, _ = create_company()
    engine = create_engine(get_settings().app_database_url)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM branch")).scalar() == 0
        conn.execute(text("SELECT set_config('app.company_id', :c, false)"), {"c": str(a)})
        rows = conn.execute(text("SELECT company_id FROM branch")).scalars().all()
        assert rows == [a]
        with pytest.raises(Exception):  # WITH CHECK blocks writing another tenant's row
            conn.execute(
                text("INSERT INTO branch (id, company_id, branch_code, name, is_head_office, created_at, updated_at) "
                     "VALUES (:i, :c, 'X', 'x', false, now(), now())"),
                {"i": uuid.uuid7(), "c": b},
            )
    engine.dispose()


@pytest.mark.committed
def test_app_role_cannot_bypass_rls(committed_db: str) -> None:
    engine = create_engine(get_settings().app_database_url)
    with engine.connect() as conn:
        row = conn.execute(text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")).one()
        assert row == (False, False)
    engine.dispose()


def test_every_tenant_table_has_rls_policy(db: None) -> None:
    with UnitOfWork(ActorContext.system(None)) as uow:
        policies = set(uow.session.execute(text("SELECT tablename FROM pg_policies WHERE policyname = 'tenant_isolation'")).scalars())
        forced = set(uow.session.execute(text("SELECT relname FROM pg_class WHERE relforcerowsecurity")).scalars())
    missing = []
    for table in Base.metadata.sorted_tables:
        model_rls = True
        for mapper in Base.registry.mappers:
            if mapper.local_table is table:
                model_rls = getattr(mapper.class_, "__tenant_rls__", True)
        if "company_id" in table.c and model_rls and (table.name not in policies or table.name not in forced):
            missing.append(table.name)
    assert missing == [], f"tenant tables without forced RLS: {missing}"


def test_cross_tenant_write_is_blocked_by_unit_of_work(db: None) -> None:
    a, _ = create_company()
    b, _ = create_company()
    with pytest.raises(PermissionError):
        with UnitOfWork(ActorContext.system(a)) as uow:
            uow.add(Branch(company_id=b, branch_code="X", name="Other tenant"))


def test_audit_log_is_append_only(db: None) -> None:
    a, _ = create_company()
    with UnitOfWork(ActorContext.system(a)) as uow:
        uow.audit("test.audited", resource_type="test", resource_label="x")
    with pytest.raises(Exception, match="append-only|permission denied"):
        with UnitOfWork(ActorContext.system(a)) as uow:
            uow.session.execute(text("UPDATE audit_log SET action = 'tampered'"))


# ---- optimistic concurrency ---------------------------------------------------------------------
def test_stale_version_raises_version_conflict(db: None) -> None:
    a, _ = create_company()
    user = create_user(a)
    with UnitOfWork(ActorContext.system(a)) as uow:
        m = uow.session.scalars(select(Membership).where(Membership.user_id == user)).one()
        with pytest.raises(VersionConflict):
            uow.expect_version(m, m.version + 1)


# ---- numbering -----------------------------------------------------------------------------------
def test_numbering_formats_and_never_reuses(db: None) -> None:
    a, _ = create_company()
    _sequence(a)
    numbers = []
    for _ in range(3):
        with UnitOfWork(ActorContext.system(a)) as uow:
            numbers.append(uow.allocate_number("test.doc", document_date=date(2026, 10, 12), resource_type="test", resource_id=uuid.uuid7()))
    assert numbers == ["TD-2026-0001", "TD-2026-0002", "TD-2026-0003"]
    with pytest.raises(RuntimeError):
        with UnitOfWork(ActorContext.system(a)) as uow:
            uow.allocate_number("test.doc", document_date=date(2026, 10, 12), resource_type="test", resource_id=uuid.uuid7())
            raise RuntimeError("rolled back")
    with UnitOfWork(ActorContext.system(a)) as uow:
        nxt = uow.allocate_number("test.doc", document_date=date(2027, 1, 2), resource_type="test", resource_id=uuid.uuid7())
    assert nxt == "TD-2027-0001"  # yearly reset; the rolled-back allocation consumed nothing


@pytest.mark.committed
def test_concurrent_numbering_is_unique_and_gapless(committed_db: str) -> None:
    a, _ = create_company()
    _sequence(a, key="test.concurrent", template="LK-QT-{yyyy}-{seq:04}", policy="never")
    results: list[str] = []
    errors: list[BaseException] = []
    barrier = threading.Barrier(40)
    lock = threading.Lock()

    def worker() -> None:
        try:
            barrier.wait(timeout=30)
            with UnitOfWork(ActorContext.system(a)) as uow:
                n = uow.allocate_number("test.concurrent", document_date=date(2026, 10, 12), resource_type="test", resource_id=uuid.uuid7())
            with lock:
                results.append(n)
        except BaseException as exc:  # noqa: BLE001 - surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(40)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert not errors, errors
    assert sorted(results) == [f"LK-QT-2026-{i:04d}" for i in range(1, 41)]


# ---- outbox and jobs -------------------------------------------------------------------------------
@pytest.fixture
def test_registry_entries() -> Any:
    reg = get_registry()
    seen: list[uuid.UUID] = []

    def handler(uow: UnitOfWork, event: DomainEvent) -> None:
        from app.platform.events.service import once

        if once(uow, "test.recorder", event.id):
            seen.append(event.id)

    attempts: list[int] = []

    def flaky(ctx: Any, payload: dict[str, Any]) -> dict[str, Any]:
        attempts.append(ctx.attempt)
        raise RuntimeError("transient failure")

    reg.events["test.thing.happened"] = EventDef("test.thing.happened", "test.thing", "test event")
    sub = Subscription("test.thing.happened", "test.recorder", handler)
    reg.subscriptions["test.thing.happened"] = [sub]
    reg.handlers["test.recorder"] = sub
    reg.jobs["test.flaky"] = JobDef("test.flaky", flaky, max_attempts=2)
    yield seen, attempts
    reg.events.pop("test.thing.happened", None)
    reg.subscriptions.pop("test.thing.happened", None)
    reg.handlers.pop("test.recorder", None)
    reg.jobs.pop("test.flaky", None)


def test_outbox_relay_delivers_each_event_once(db: None, test_registry_entries: Any) -> None:
    seen, _ = test_registry_entries
    a, _ = create_company()
    with UnitOfWork(ActorContext.system(a)) as uow:
        event_id = uow.emit("test.thing.happened", aggregate_id=uuid.uuid7(), payload={"changed": ["status"]})
    drain()
    drain()
    assert seen == [event_id]
    with UnitOfWork(ActorContext.system(None)) as uow:
        jobs = uow.session.scalars(select(Job).where(Job.kind == "event.handle")).all()
        assert [j.status for j in jobs if j.payload["event_id"] == str(event_id)] == ["succeeded"]


def test_rolled_back_command_emits_nothing(db: None, test_registry_entries: Any) -> None:
    seen, _ = test_registry_entries
    a, _ = create_company()
    with pytest.raises(RuntimeError):
        with UnitOfWork(ActorContext.system(a)) as uow:
            uow.emit("test.thing.happened", aggregate_id=uuid.uuid7())
            raise RuntimeError("abort")
    drain()
    assert seen == []


def test_failing_job_backs_off_then_dead_letters(db: None, test_registry_entries: Any, frozen_clock: Any) -> None:
    _, attempts = test_registry_entries
    a, _ = create_company()
    with UnitOfWork(ActorContext.system(a)) as uow:
        job_id = uow.enqueue("test.flaky", {"x": 1})
    drain()
    with UnitOfWork(ActorContext.system(None)) as uow:
        job = uow.session.get(Job, job_id)
        assert job is not None and job.status == "queued" and job.attempts == 1
        uow.session.execute(text("UPDATE job SET run_at = now() WHERE id = :id"), {"id": job_id})
    drain()
    with UnitOfWork(ActorContext.system(None)) as uow:
        job = uow.session.get(Job, job_id)
        assert job is not None and job.status == "dead" and job.attempts == 2
        assert job.last_error and job.last_error["type"] == "RuntimeError"
    assert attempts == [1, 2]


def test_enqueue_dedupe_key_is_idempotent(db: None) -> None:
    a, _ = create_company()
    with UnitOfWork(ActorContext.system(a)) as uow:
        first = uow.enqueue("event.handle", {"event_id": str(uuid.uuid7()), "handler": "none"}, dedupe_key="dedupe:1")
        second = uow.enqueue("event.handle", {"event_id": str(uuid.uuid7()), "handler": "none"}, dedupe_key="dedupe:1")
    assert first is not None and second is None


# ---- idempotency ---------------------------------------------------------------------------------------
def test_idempotent_command_replays_and_rejects_reuse(db: None) -> None:
    a, _ = create_company()
    user = create_user(a)
    actor = ActorContext(actor_type="user", company_id=a, user_id=user)
    calls: list[int] = []

    def op() -> dict[str, Any]:
        calls.append(1)
        return {"ok": True, "n": len(calls)}

    with UnitOfWork(actor) as uow:
        first, replayed = run_idempotent(uow, key="k-1", operation="test.op", body={"a": 1}, fn=op)
    with UnitOfWork(actor) as uow:
        second, replayed2 = run_idempotent(uow, key="k-1", operation="test.op", body={"a": 1}, fn=op)
    assert first == second == {"ok": True, "n": 1} and replayed2 and not replayed
    with pytest.raises(IdempotencyKeyReused):
        with UnitOfWork(actor) as uow:
            run_idempotent(uow, key="k-1", operation="test.op", body={"a": 2}, fn=op)
