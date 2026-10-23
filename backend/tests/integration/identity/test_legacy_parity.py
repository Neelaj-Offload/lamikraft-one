"""Legacy parity through the database (CURRENT_STATE_SPEC §3.2, permissions.md §8 and §12).

For admin, management, sales and operations, each of the 14 legacy permissions is evaluated from the stored
``legacy_permission_alias`` rows against the stored system template grants — and against the effective
permissions of a real member holding that template.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.platform.authz.permissions import Scope
from app.platform.identity import provisioning
from app.platform.identity.access import LegacyAlias, legacy_holds
from app.platform.identity.models import LegacyPermissionAlias, Role, RolePermission
from app.platform.uow import UnitOfWork
from tests.integration.identity.fixtures import Tenant, make_member, system

pytestmark = pytest.mark.db

LEGACY = [
    "view_all_quotes", "view_own_quotes", "create_quotes", "edit_all_quotes", "edit_own_quotes", "delete_quotes",
    "override_price", "export_quotes", "view_products", "edit_products", "manage_users", "import_data",
    "view_costing", "manage_categories",
]
#: CURRENT_STATE_SPEC §3.2, column by column
EXPECTED = {
    "admin": set(LEGACY) - {"view_own_quotes", "edit_own_quotes"},
    "management": {"view_all_quotes", "create_quotes", "edit_all_quotes", "override_price", "export_quotes", "view_products", "view_costing"},
    "sales": {"view_own_quotes", "create_quotes", "edit_own_quotes", "override_price", "export_quotes", "view_products"},
    "operations": {"view_all_quotes", "view_products"},
}


def _aliases_from_db() -> list[LegacyAlias]:
    with UnitOfWork(system(None)) as uow:
        rows = list(uow.session.scalars(select(LegacyPermissionAlias)))
    return [
        LegacyAlias(
            legacy_key=r.legacy_key,
            permission_key=r.permission_key,
            scope=Scope.parse(r.scope) if r.scope else None,
            scope_from_key=r.scope_from_key,
            fallback_scope=Scope.parse(r.fallback_scope) if r.fallback_scope else None,
        )
        for r in rows
    ]


def _template_from_db(tenant: Tenant, role_key: str) -> dict[str, Scope]:
    with UnitOfWork(system(tenant.company_id)) as uow:
        rows = uow.session.execute(
            select(RolePermission.permission_key, RolePermission.scope)
            .join(Role, Role.id == RolePermission.role_id)
            .where(Role.role_key.in_([role_key, "employee"]))
        ).all()
    grants: dict[str, Scope] = {}
    for key, label in rows:
        grants[key] = max(grants.get(key, Scope.parse(label)), Scope.parse(label))
    return grants


@pytest.mark.parametrize("template", sorted(EXPECTED))
def test_legacy_templates_reproduce_spec_3_2_through_alias_table(tenant: Tenant, template: str) -> None:
    aliases = _aliases_from_db()
    assert {a.legacy_key for a in aliases} == set(LEGACY)
    stored = _template_from_db(tenant, template)
    held = {legacy for legacy in LEGACY if legacy_holds(stored, legacy, aliases)}
    assert held == EXPECTED[template]

    member = make_member(tenant, [template])
    with UnitOfWork(system(tenant.company_id)) as uow:
        effective = provisioning.effective_permissions(uow, member.membership_id)
    assert {legacy for legacy in LEGACY if legacy_holds(effective, legacy, aliases)} == EXPECTED[template]


def test_management_has_no_destructive_catalogue_write_or_identity_keys(tenant: Tenant) -> None:
    stored = _template_from_db(tenant, "management")
    forbidden = {
        "catalogue.product.create", "catalogue.product.update", "catalogue.product.archive", "catalogue.media.manage",
        "catalogue.taxonomy.manage", "pricing.price_list.manage",
    }
    bad = [
        k for k in stored
        if k.endswith(".delete") or k.startswith(("identity.", "imports.")) or k in forbidden
    ]
    assert bad == []
