"""Committed-mode tests: tenant isolation of identity tables under RLS and one-time links under concurrency."""

from __future__ import annotations

import threading
import uuid

import pytest
from sqlalchemy import create_engine, text

from app.core.config import get_settings
from app.core.errors import AppError
from app.platform.identity import provisioning, service
from app.platform.identity.provisioning import TeamSeat
from app.platform.identity.sessions import ClientInfo
from app.platform.uow import UnitOfWork
from tests.integration.identity.fixtures import make_member, make_tenant, system

pytestmark = pytest.mark.db

TENANT_TABLES = (
    "role",
    "role_permission",
    "membership_role",
    "membership_branch",
    "user_permission_override",
    "demo_sign_in_token",
    "team",
    "team_member",
)


@pytest.mark.committed
def test_identity_tables_are_tenant_isolated(committed_db: str) -> None:
    a = make_tenant(is_demo=True)
    b = make_tenant(is_demo=True)
    for tenant in (a, b):
        with UnitOfWork(system(tenant.company_id)) as uow:
            team = provisioning.ensure_team(uow, team_key="T-ISO", name="Isolation")
        member = make_member(tenant, ["sales"], teams=[TeamSeat(team)])
        with UnitOfWork(system(tenant.company_id)) as uow:
            provisioning.set_permission_override(
                uow, member.membership_id, permission_key="sales.quote.export", effect="revoke", reason="isolation"
            )
        service.issue_demo_link(company_key=tenant.key, email=member.email)
    engine = create_engine(get_settings().app_database_url)
    try:
        with engine.connect() as conn:
            for table in TENANT_TABLES:
                assert conn.execute(text(f'SELECT count(*) FROM "{table}"')).scalar() == 0, table  # noqa: S608
            conn.execute(text("SELECT set_config('app.company_id', :c, false)"), {"c": str(a.company_id)})
            for table in TENANT_TABLES:
                companies = set(conn.execute(text(f'SELECT DISTINCT company_id FROM "{table}"')).scalars())  # noqa: S608
                assert companies == {a.company_id}, table
    finally:
        engine.dispose()


@pytest.mark.committed
def test_a_demo_link_signs_in_exactly_once_under_concurrency(committed_db: str) -> None:
    tenant = make_tenant(is_demo=True)
    member = make_member(tenant, ["sales"])
    link = service.issue_demo_link(company_key=tenant.key, email=member.email)
    barrier = threading.Barrier(4)
    results: list[str] = []
    lock = threading.Lock()

    def attempt(i: int) -> None:
        barrier.wait()
        try:
            signed = service.demo_sign_in(link.token, ClientInfo(ip=f"10.0.0.{i}"))
            outcome = f"ok:{signed.issued.session_id}"
        except AppError as exc:
            outcome = exc.code
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert len(results) == 4
    assert sum(r.startswith("ok:") for r in results) == 1
    assert sorted(r for r in results if not r.startswith("ok:")) == ["link_invalid_or_used"] * 3


@pytest.mark.committed
def test_concurrent_failures_count_every_attempt(committed_db: str) -> None:
    from app.platform.identity import ratelimit
    from app.platform.identity.auth_models import RateLimitCounter

    barrier = threading.Barrier(6)
    email_key = uuid.uuid4().hex

    def fail() -> None:
        barrier.wait()
        with UnitOfWork(system(None)) as uow:
            ratelimit.record_failure(uow.session, email_key, now=uow.now())

    threads = [threading.Thread(target=fail) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    with UnitOfWork(system(None)) as uow:
        row = uow.session.get(RateLimitCounter, (f"login:lock:{email_key}", ratelimit._LOCK_WINDOW))
        assert row is not None
        # five failures locked the email (count reset to 0); the sixth started counting again
        assert (row.lock_count, row.count) == (1, 1) and row.blocked_until is not None


@pytest.mark.committed
def test_two_admins_demoting_each_other_concurrently_keep_one_admin(committed_db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Review finding: without a company lock both last-admin guards passed under READ COMMITTED and the company
    ended with no role manager. ``provisioning.lock_access`` serialises access changes: the second demotion waits,
    then sees the first and is refused."""
    from sqlalchemy import select

    from app.platform.identity.actors import actor_for
    from app.platform.identity.models import Membership

    tenant = make_tenant()
    first = make_member(tenant, ["admin"])
    second = make_member(tenant, ["admin"])
    barrier = threading.Barrier(2)
    original = provisioning.access_changed

    def paused_access_changed(*args, **kwargs):  # type: ignore[no-untyped-def]
        # both guards have run by now unless the lock made the other thread wait; never wait for more than 2 s
        try:
            barrier.wait(timeout=2)
        except threading.BrokenBarrierError:
            pass
        return original(*args, **kwargs)

    monkeypatch.setattr(provisioning, "access_changed", paused_access_changed)
    results: list[str] = []
    lock = threading.Lock()

    def demote(actor_user: uuid.UUID, target: uuid.UUID) -> None:
        actor = actor_for(tenant.company_id, actor_user, "test")
        assert actor is not None
        try:
            with UnitOfWork(actor) as uow:
                provisioning.assign_roles(uow, target, ["management"])
            outcome = "ok"
        except AppError as exc:
            outcome = exc.code
        with lock:
            results.append(outcome)

    threads = [
        threading.Thread(target=demote, args=(first.user_id, second.membership_id)),
        threading.Thread(target=demote, args=(second.user_id, first.membership_id)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert sorted(results) == ["last_admin", "ok"]
    with UnitOfWork(system(tenant.company_id)) as uow:
        members = list(uow.session.scalars(select(Membership).where(Membership.company_id == tenant.company_id)))
        holders = [m for m in members if provisioning._holds_role_manage(uow, m)]
    assert len(holders) == 1
