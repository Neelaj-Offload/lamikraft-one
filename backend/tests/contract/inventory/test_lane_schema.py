"""Orders/inventory lane contracts: database CHECKs mirror the StrEnums, every ``inventory_``/``orders_`` table has
forced RLS, the ledger tables are append-only exactly as flagged, emitted events are in the frozen catalogue, only
``posting.py`` and ``reservations.py`` write the projections, and every route declares a catalogued permission."""

from __future__ import annotations

import re
from enum import StrEnum
from pathlib import Path

import pytest
from sqlalchemy import text

from app.core.db.base import Base
from app.modules.inventory import events as inv_ev
from app.modules.orders import events as ord_ev
from app.platform.authz.catalogue_data import PERMISSIONS
from app.platform.authz.context import ActorContext
from app.platform.uow import UnitOfWork
from app.registry import get_registry

MODULES = Path(__file__).resolve().parents[3] / "app" / "modules"


def _tables() -> dict[str, type]:
    return {m.class_.__tablename__: m.class_ for m in Base.registry.mappers if m.class_.__tablename__.startswith(("inventory_", "orders_"))}


def _enum_columns() -> dict[tuple[str, str], type[StrEnum]]:
    out: dict[tuple[str, str], type[StrEnum]] = {}
    for t in Base.metadata.sorted_tables:
        if t.name.startswith(("inventory_", "orders_")):
            for col in t.columns:
                if col.info.get("enum"):
                    out[(t.name, col.name)] = col.info["enum"]
    return out


@pytest.mark.db
def test_enum_checks_match_the_strenums(db: None) -> None:
    with UnitOfWork(ActorContext.system(None)) as uow:
        for (table, column), enum in _enum_columns().items():
            definition = uow.session.execute(
                text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = CAST(:t AS regclass) AND conname = :n"),
                {"t": table, "n": f"ck_{table}_{column}_values"},
            ).scalar_one()
            assert set(re.findall(r"'([^']*)'", definition)) == {e.value for e in enum}, (table, column)


@pytest.mark.db
def test_tables_force_rls_and_append_only_matches_flags(db: None) -> None:
    tables = _tables()
    assert {"inventory_stock_posting", "inventory_stock_movement", "orders_sales_order"} <= set(tables)
    with UnitOfWork(ActorContext.system(None)) as uow:
        policies = set(uow.session.execute(text("SELECT tablename FROM pg_policies WHERE policyname = 'tenant_isolation'")).scalars())
        forced = set(uow.session.execute(text("SELECT relname FROM pg_class WHERE relforcerowsecurity")).scalars())
        triggers = set(uow.session.execute(text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal")).scalars())
    assert set(tables) <= policies and set(tables) <= forced
    for name, model in tables.items():
        assert (f"trg_{name}_append_only" in triggers) is bool(getattr(model, "__append_only__", False)), name
    assert {"trg_orders_sales_order_immutable", "trg_inventory_warehouse_immutable"} <= triggers


def test_emitted_events_are_in_the_frozen_catalogue() -> None:
    registry = get_registry()
    for name in (*inv_ev.EMITTED_EVENTS, *ord_ev.EMITTED_EVENTS):
        assert name in registry.events, name
    for name in inv_ev.SHORTAGE_TRIGGERS:
        assert f"{inv_ev.SHORTAGE_REFRESH}:{name}" in registry.handlers


def test_only_the_posting_engine_writes_the_projections() -> None:
    """Code review rule (operations.md risks): balances and summaries are written only by posting.py and reservations.py."""
    writers = re.compile(r"\b(StockBalance|StockSummary)\b.*(\.quantity\s*=|\.available_on_hand\s*=|\.reserved\s*=|insert\()|"
                         r"\.(available_on_hand|reserved)\s*=(?!=)")
    offenders = []
    for path in MODULES.rglob("*.py"):
        if path.name in {"posting.py", "reservations.py", "models.py"} and path.parent.name == "inventory":
            continue
        source = path.read_text(encoding="utf-8")
        for i, line in enumerate(source.splitlines(), start=1):
            if writers.search(line) or ("pg_insert(StockBalance" in line or "pg_insert(StockSummary" in line):
                offenders.append(f"{path.relative_to(MODULES)}:{i}")
    assert offenders == []


def test_routes_declare_catalogued_permissions() -> None:
    from app.main import create_app

    keys = {p["key"] for p in PERMISSIONS}
    spec = create_app().openapi()
    seen = 0
    for path, item in spec["paths"].items():
        if not path.startswith(("/api/v1/inventory/", "/api/v1/orders/")):
            continue
        for op in item.values():
            decl = op.get("x-authz") or {}
            assert decl.get("kind") == "permission", (path, decl)
            assert set(decl["permissions"]) <= keys, (path, decl)
            seen += 1
    assert seen >= 40
