"""Permission catalogue, legacy alias table and system role templates synced idempotently from code."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.platform.authz.permissions import Scope
from app.platform.identity import roles
from app.platform.identity.models import LegacyPermissionAlias, Permission, Role, RolePermission
from app.platform.org.models import Company
from app.platform.uow import UnitOfWork
from app.registry import get_registry
from tests.integration.identity.fixtures import Tenant, make_member, system

pytestmark = pytest.mark.db


def _db_grants(company_id, role_key: str) -> dict[str, Scope]:  # type: ignore[no-untyped-def]
    with UnitOfWork(system(company_id)) as uow:
        rows = uow.session.execute(
            select(RolePermission.permission_key, RolePermission.scope)
            .join(Role, Role.id == RolePermission.role_id)
            .where(Role.role_key == role_key)
        ).all()
    return {k: Scope.parse(s) for k, s in rows}


def test_permission_catalogue_matches_registry(tenant: Tenant) -> None:
    registry = get_registry()
    with UnitOfWork(system(None)) as uow:
        rows = {p.key: p for p in uow.session.scalars(select(Permission))}
    assert set(rows) == set(registry.permissions)
    for key, perm in registry.permissions.items():
        row = rows[key]
        assert row.allowed_scopes == [s.label for s in sorted(perm.scopes)]
        assert (row.requires_mfa, row.requires_recent_auth, row.delegable, row.field_guard) == (
            perm.requires_mfa,
            perm.requires_recent_auth,
            perm.delegable,
            perm.field_guard,
        )
        assert row.deprecated_at is None


def test_alias_table_rows_match_the_registry(tenant: Tenant) -> None:
    with UnitOfWork(system(None)) as uow:
        rows = list(uow.session.scalars(select(LegacyPermissionAlias)))
    mapping: dict[str, list[str]] = {}
    for row in rows:
        mapping.setdefault(row.legacy_key, []).append(row.permission_key)
    assert {k: sorted(v) for k, v in mapping.items()} == get_registry().legacy_alias_map()
    assert len(mapping) == 14


def test_system_templates_equal_template_grants(tenant: Tenant) -> None:
    registry = get_registry()
    for template, grants in registry.template_grants.items():
        assert _db_grants(tenant.company_id, template) == grants, template
    admin = _db_grants(tenant.company_id, "admin")
    assert admin == {k: p.max_scope for k, p in registry.permissions.items()}
    with UnitOfWork(system(tenant.company_id)) as uow:
        kinds = {r.role_key: (r.kind, r.is_assignable) for r in uow.session.scalars(select(Role))}
    assert kinds["employee"] == ("system_template", False)
    assert kinds["sales"] == ("system_template", True)


def test_resync_is_idempotent_and_keeps_the_epoch(tenant: Tenant) -> None:
    make_member(tenant, ["sales"])
    with UnitOfWork(system(tenant.company_id)) as uow:
        epoch = uow.session.scalar(select(Company.authz_epoch).where(Company.id == tenant.company_id))
    with UnitOfWork(system(None)) as uow:
        roles.sync_permission_catalogue(uow)
    with UnitOfWork(system(tenant.company_id)) as uow:
        roles.ensure_system_roles(uow, tenant.company_id)
        assert uow.session.scalar(select(Company.authz_epoch).where(Company.id == tenant.company_id)) == epoch


def test_template_drift_is_repaired_and_bumps_the_epoch(tenant: Tenant) -> None:
    member = make_member(tenant, ["sales"])
    with UnitOfWork(system(tenant.company_id)) as uow:
        sales = uow.session.scalars(select(Role).where(Role.role_key == "sales")).one()
        row = uow.session.get(RolePermission, (sales.id, "sales.quote.read"))
        assert row is not None
        row.scope = "company"  # simulate a stale or tampered template row
        epoch = uow.session.scalar(select(Company.authz_epoch).where(Company.id == tenant.company_id))
    with UnitOfWork(system(tenant.company_id)) as uow:
        roles.ensure_system_roles(uow, tenant.company_id)
        new_epoch = uow.session.scalar(select(Company.authz_epoch).where(Company.id == tenant.company_id))
    assert new_epoch == epoch + 1
    assert _db_grants(tenant.company_id, "sales")["sales.quote.read"] == Scope.OWN
    from app.platform.events.models import DomainEvent

    with UnitOfWork(system(tenant.company_id)) as uow:
        changed = list(
            uow.session.scalars(
                select(DomainEvent).where(
                    DomainEvent.event_type == "identity.membership.access_changed",
                    DomainEvent.aggregate_id == member.membership_id,
                    DomainEvent.payload["authz_epoch"].as_integer() == new_epoch,
                )
            )
        )
    assert len(changed) == 1 and changed[0].payload["change_kinds"] == ["roles"]


def test_api_startup_repairs_template_drift_without_the_cli(tenant: Tenant) -> None:
    """platform.md §5: the catalogue and system templates sync when the API starts (review finding: only the CLI
    and the seed did). A deleted catalogue row and a stale template row are both repaired; no user is created."""
    from sqlalchemy import func

    from app.platform.identity import startup
    from app.platform.identity.models import AppUser, Permission

    with UnitOfWork(system(tenant.company_id)) as uow:
        sales = uow.session.scalars(select(Role).where(Role.role_key == "sales")).one()
        row = uow.session.get(RolePermission, (sales.id, "sales.quote.read"))
        assert row is not None
        row.scope = "company"
        users = uow.session.scalar(select(func.count()).select_from(AppUser))
    assert startup.run_startup_sync() is None  # skipped in the test environment unless forced
    assert _db_grants(tenant.company_id, "sales")["sales.quote.read"] == Scope.COMPANY
    result = startup.run_startup_sync(force=True)
    assert result is not None and result["companies"] >= 1
    assert result["permissions"] == len(get_registry().permissions)
    assert _db_grants(tenant.company_id, "sales")["sales.quote.read"] == Scope.OWN
    with UnitOfWork(system(None)) as uow:
        assert uow.session.scalar(select(func.count()).select_from(AppUser)) == users
        assert uow.session.scalar(select(func.count()).select_from(Permission)) == len(get_registry().permissions)


def test_the_identity_router_lifespan_runs_the_sync_when_the_app_starts(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.platform.identity import startup

    calls: list[bool] = []
    monkeypatch.setattr(startup, "run_startup_sync", lambda **kw: calls.append(True))
    with TestClient(create_app()):
        pass
    assert calls == [True]


def test_a_failing_sync_does_not_stop_the_api(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.platform.identity import roles, startup

    def broken(**_kw: object) -> dict[str, int]:
        raise RuntimeError("database not reachable")

    monkeypatch.setattr(roles, "sync_access_all", broken)
    assert startup.run_startup_sync(force=True) is None
