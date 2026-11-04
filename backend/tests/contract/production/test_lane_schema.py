"""Production lane contracts: database CHECKs mirror the StrEnums, every ``production_`` table has forced RLS, the
append-only tables are exactly the flagged ones, the separation-of-duties CHECKs exist, emitted events are in the
frozen catalogue with their handlers registered, and every route declares a catalogued permission."""

from __future__ import annotations

import re
from enum import StrEnum

import pytest
from sqlalchemy import text

from app.core.db.base import Base
from app.modules.production import events as ev
from app.platform.authz.catalogue_data import PERMISSIONS
from app.platform.authz.context import ActorContext
from app.platform.uow import UnitOfWork
from app.registry import get_registry


def _tables() -> dict[str, type]:
    return {m.class_.__tablename__: m.class_ for m in Base.registry.mappers if m.class_.__tablename__.startswith("production_")}


@pytest.mark.db
def test_enum_checks_match_the_strenums(db: None) -> None:
    cols: dict[tuple[str, str], type[StrEnum]] = {
        (t.name, c.name): c.info["enum"]
        for t in Base.metadata.sorted_tables if t.name.startswith("production_") for c in t.columns if c.info.get("enum")
    }
    assert len(cols) == 9
    with UnitOfWork(ActorContext.system(None)) as uow:
        for (table, column), enum in cols.items():
            definition = uow.session.execute(
                text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = CAST(:t AS regclass) AND conname = :n"),
                {"t": table, "n": f"ck_{table}_{column}_values"},
            ).scalar_one()
            assert set(re.findall(r"'([^']*)'", definition)) == {e.value for e in enum}, (table, column)


@pytest.mark.db
def test_tables_force_rls_append_only_and_separation_of_duties(db: None) -> None:
    tables = _tables()
    assert len(tables) == 12
    with UnitOfWork(ActorContext.system(None)) as uow:
        policies = set(uow.session.execute(text("SELECT tablename FROM pg_policies WHERE policyname = 'tenant_isolation'")).scalars())
        forced = set(uow.session.execute(text("SELECT relname FROM pg_class WHERE relforcerowsecurity")).scalars())
        triggers = set(uow.session.execute(text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal")).scalars())
        checks = set(uow.session.execute(text("SELECT conname FROM pg_constraint WHERE contype = 'c'")).scalars())
    assert set(tables) <= policies and set(tables) <= forced
    for name, model in tables.items():
        assert (f"trg_{name}_append_only" in triggers) is bool(getattr(model, "__append_only__", False)), name
    assert {"trg_production_work_order_immutable", "trg_production_bom_immutable", "trg_production_routing_immutable"} <= triggers
    assert {"ck_production_bom_approver_not_author", "ck_production_routing_approver_not_author"} <= checks


def test_emitted_events_are_in_the_frozen_catalogue_and_handlers_registered() -> None:
    registry = get_registry()
    for name in (*ev.EMITTED_EVENTS, "cutting.plan.released", "inventory.lot.measured"):
        assert name in registry.events, name
    for name in ev.MATERIAL_RETRY_TRIGGERS:
        assert f"{ev.MATERIAL_RETRY}:{name}" in registry.handlers
    for name in ("production.work_order.released", "production.work_order.cancelled"):
        assert f"inventory.shortage_refresh:{name}" in registry.handlers
    from app.modules.tasks.rules.consumer import EVENT_FAMILIES

    for name in (*ev.WORK_ORDER_EVENTS, ev.CAPACITY_OVERLOADED, ev.COST_ROLLUP_COMPUTED):
        assert EVENT_FAMILIES[name] == ("ops.production_dependencies",)


def test_routes_declare_catalogued_permissions() -> None:
    from app.main import create_app

    keys = {p["key"] for p in PERMISSIONS}
    spec = create_app().openapi()
    seen = 0
    for path, item in spec["paths"].items():
        if not path.startswith("/api/v1/production/"):
            continue
        for op in item.values():
            decl = op.get("x-authz") or {}
            assert decl.get("kind") == "permission", (path, decl)
            assert set(decl["permissions"]) <= keys, (path, decl)
            seen += 1
    assert seen >= 35


def test_cost_figures_are_guarded_and_never_model_exposed() -> None:
    from app.modules.production.schemas import CostRollupRead, WorkCenterRead, WorkCenterSummary
    from app.platform.authz.redaction import restricted_field_names

    guarded = restricted_field_names(CostRollupRead)
    assert set(guarded) == {"material_total", "operation_total", "total", "lines"}
    assert all(m.guard == "pricing.cost.read" and m.model_exposure == "deny" for m in guarded.values())
    for model in (WorkCenterSummary, WorkCenterRead):
        meta = restricted_field_names(model)["rate_per_hour"]
        assert meta.guard == "pricing.cost.read" and meta.model_exposure == "deny"
