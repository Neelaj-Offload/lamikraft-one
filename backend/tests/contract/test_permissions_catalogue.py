"""The permission vocabulary matches docs/architecture/permissions.md and reproduces legacy spec §3.2."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.platform.authz.permissions import Scope
from app.registry import build_registry

DOCS = Path(__file__).resolve().parents[3] / "docs" / "architecture"

LEGACY = [
    "view_all_quotes", "view_own_quotes", "create_quotes", "edit_all_quotes", "edit_own_quotes", "delete_quotes",
    "override_price", "export_quotes", "view_products", "edit_products", "manage_users", "import_data",
    "view_costing", "manage_categories",
]
EXPECTED = {
    "admin": set(LEGACY) - {"view_own_quotes", "edit_own_quotes"},
    "management": {"view_all_quotes", "create_quotes", "edit_all_quotes", "override_price", "export_quotes", "view_products", "view_costing"},
    "sales": {"view_own_quotes", "create_quotes", "edit_own_quotes", "override_price", "export_quotes", "view_products"},
    "operations": {"view_all_quotes", "view_products"},
}
EDIT = ("sales.quote.update", "sales.quote.transition", "sales.quote.issue", "sales.quote.archive")


def _holds(grants: dict[str, Scope], legacy: str) -> bool:
    has = grants.__contains__
    match legacy:
        case "view_all_quotes":
            return grants.get("sales.quote.read") == Scope.COMPANY
        case "view_own_quotes":
            return grants.get("sales.quote.read") == Scope.OWN
        case "create_quotes":
            return has("sales.quote.create")
        case "edit_all_quotes":
            return all(grants.get(k) == Scope.COMPANY for k in EDIT)
        case "edit_own_quotes":
            return all(grants.get(k) == Scope.OWN for k in EDIT)
        case "delete_quotes":
            return has("sales.quote.delete")
        case "override_price":
            return has("sales.quote_price.override")
        case "export_quotes":
            return has("sales.quote.export")
        case "view_products":
            return has("catalogue.product.read") and has("pricing.price.read")
        case "edit_products":
            return all(has(k) for k in ("catalogue.product.create", "catalogue.product.update", "catalogue.product.archive", "catalogue.media.manage", "pricing.price_list.manage"))
        case "manage_users":
            return all(has(k) for k in ("identity.user.read", "identity.user.manage", "identity.role.read", "identity.role.manage", "identity.permission.manage"))
        case "import_data":
            return has("imports.job.read") and has("imports.job.run")
        case "view_costing":
            return has("pricing.cost.read") and has("pricing.price_list.read")
        case "manage_categories":
            return has("catalogue.taxonomy.manage")
    raise AssertionError(legacy)


@pytest.mark.parametrize("template", sorted(EXPECTED))
def test_legacy_templates_reproduce_spec_3_2(template: str) -> None:
    grants = build_registry().template_grants[template]
    held = {legacy for legacy in LEGACY if _holds(grants, legacy)}
    assert held == EXPECTED[template]


def test_management_has_no_destructive_or_identity_keys() -> None:
    grants = build_registry().template_grants["management"]
    bad = [
        k for k in grants
        if k.endswith(".delete") or k.startswith(("identity.", "imports."))
        or k in {"catalogue.product.create", "catalogue.product.update", "catalogue.product.archive", "catalogue.media.manage",
                 "catalogue.taxonomy.manage", "pricing.price_list.manage"}
    ]
    assert bad == []


def test_registry_matches_catalogue_docs() -> None:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
    from gen_catalogues import parse_events, parse_permissions

    doc_perms = {r["key"] for r in parse_permissions((DOCS / "permissions.md").read_text(encoding="utf-8"))}
    doc_events = {r["name"] for r in parse_events((DOCS / "events.md").read_text(encoding="utf-8"))}
    reg = build_registry()
    assert set(reg.permissions) == doc_perms
    assert doc_events <= set(reg.events)


def test_alias_table_covers_all_fourteen_legacy_permissions() -> None:
    assert set(build_registry().legacy_alias_map()) == set(LEGACY)


def test_briefing_read_is_own_scope_only() -> None:
    assert build_registry().permissions["briefings.briefing.read"].scopes == (Scope.OWN,)
