"""Procurement / quality / logistics lane contracts: database CHECKs mirror the StrEnums, every ``procurement_`` /
``quality_`` / ``logistics_`` table has forced RLS, document numbers are immutable, emitted events are in the frozen
catalogue with their consumers registered, stock is never written outside the inventory posting service, and every
route of the three modules declares a catalogued permission."""

from __future__ import annotations

import re
from enum import StrEnum
from pathlib import Path

import pytest
from sqlalchemy import text

from app.core.db.base import Base
from app.modules.logistics import events as log_ev
from app.modules.procurement import events as pro_ev
from app.modules.quality import events as qc_ev
from app.platform.authz.catalogue_data import PERMISSIONS
from app.platform.authz.context import ActorContext
from app.platform.uow import UnitOfWork
from app.registry import get_registry

PREFIXES = ("procurement_", "quality_", "logistics_")
MODULES = Path(__file__).resolve().parents[3] / "app" / "modules"


def _enum_columns() -> dict[tuple[str, str], type[StrEnum]]:
    out: dict[tuple[str, str], type[StrEnum]] = {}
    for t in Base.metadata.sorted_tables:
        if t.name.startswith(PREFIXES):
            for col in t.columns:
                if col.info.get("enum"):
                    out[(t.name, col.name)] = col.info["enum"]
    return out


@pytest.mark.db
def test_enum_checks_match_the_strenums(db: None) -> None:
    columns = _enum_columns()
    assert ("procurement_purchase_order", "status") in columns and ("logistics_shipment", "status") in columns
    with UnitOfWork(ActorContext.system(None)) as uow:
        for (table, column), enum in columns.items():
            definition = uow.session.execute(
                text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = CAST(:t AS regclass) "
                     "AND conname = :n"),
                {"t": table, "n": f"ck_{table}_{column}_values"},
            ).scalar_one()
            assert set(re.findall(r"'([^']*)'", definition)) == {e.value for e in enum}, (table, column)


@pytest.mark.db
def test_tables_force_rls_and_numbers_are_immutable(db: None) -> None:
    tables = {t.name for t in Base.metadata.sorted_tables if t.name.startswith(PREFIXES)}
    assert len(tables) == 15
    with UnitOfWork(ActorContext.system(None)) as uow:
        policies = set(uow.session.execute(text("SELECT tablename FROM pg_policies WHERE policyname = 'tenant_isolation'")).scalars())
        forced = set(uow.session.execute(text("SELECT relname FROM pg_class WHERE relforcerowsecurity")).scalars())
        triggers = set(uow.session.execute(text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal")).scalars())
    assert tables <= policies and tables <= forced
    for name in ("procurement_requisition", "procurement_purchase_order", "procurement_goods_receipt",
                 "quality_inspection", "logistics_packing_list", "logistics_shipment"):
        assert f"trg_{name}_immutable" in triggers, name


def test_emitted_events_and_consumers_are_registered() -> None:
    registry = get_registry()
    for name in (*pro_ev.EMITTED_EVENTS, *qc_ev.EMITTED_EVENTS, *log_ev.EMITTED_EVENTS):
        assert name in registry.events, name
    for name in pro_ev.SHORTAGE_EVENTS:
        assert f"inventory.shortage_refresh:{name}" in registry.handlers, name
    assert log_ev.SHIPMENT_STATUS in registry.handlers
    for name in log_ev.STALENESS_TRIGGERS:
        assert f"{log_ev.STALENESS}:{name}" in registry.handlers, name
    for name in ("procurement.goods_receipt.posted", "quality.inspection.requested", "logistics.shipment.scheduled",
                 "procurement.purchase_order.became_overdue"):
        assert f"tasks.rules:{name}" in registry.handlers, name


def test_stock_is_written_only_through_the_posting_service() -> None:
    """The lane's modules never touch ledger or projection models directly (they call ``post_movement``)."""
    forbidden = re.compile(r"\b(StockBalance|StockSummary|StockMovement|StockPosting)\s*\(")
    offenders = []
    for module in ("procurement", "quality", "logistics"):
        for path in (MODULES / module).rglob("*.py"):
            if forbidden.search(path.read_text(encoding="utf-8")):
                offenders.append(str(path))
    assert offenders == []


def test_routes_declare_catalogued_permissions() -> None:
    from app.main import create_app

    known = {p["key"] for p in PERMISSIONS}
    app = create_app()
    from app.core.http.authz_decl import api_routes

    seen = 0
    for path, route in api_routes(app):
        if not path.startswith(("/api/v1/procurement", "/api/v1/quality", "/api/v1/logistics")):
            continue
        decl = (route.openapi_extra or {}).get("x-authz") or {}
        assert decl.get("kind") == "permission", path
        assert set(decl["permissions"]) <= known, path
        seen += 1
    assert seen >= 40
