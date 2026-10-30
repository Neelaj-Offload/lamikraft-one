"""Cutting lane contracts: database CHECKs mirror the model enumerations, every ``cutting_`` table has forced RLS,
the append-only triggers match the model flags, emitted events and their payloads are in the frozen catalogue, the
routes name only catalogued keys, and the lane's contributions (policies, sequence, job, seed) are registered."""

from __future__ import annotations

import re

import pytest
from pydantic import BaseModel
from sqlalchemy import text

from app.core.db.base import Base
from app.modules.cutting import events as ev
from app.modules.cutting import models
from app.modules.cutting.packer import engine
from app.platform.authz.catalogue_data import PERMISSIONS
from app.platform.authz.context import ActorContext
from app.platform.uow import UnitOfWork
from app.registry import get_registry

ENUM_CHECKS: dict[tuple[str, str], tuple[str, ...]] = {
    ("cutting_settings", "ck_cutting_settings_default_mode_values"): models.MODES,
    ("cutting_machine_profile", "ck_cutting_machine_profile_mode_values"): models.MODES,
    ("cutting_plan", "ck_cutting_plan_status_values"): models.PLAN_STATUSES,
    ("cutting_plan", "ck_cutting_plan_mode_values"): models.MODES,
    ("cutting_plan", "ck_cutting_plan_calc_status_values"): models.CALC_STATUSES,
    ("cutting_plan_item", "ck_cutting_plan_item_grain_rule_values"): models.GRAIN_RULES,
    ("cutting_calculation", "ck_cutting_calculation_origin_values"): models.CALC_ORIGINS,
    ("cutting_calc_board", "ck_cutting_calc_board_source_values"): models.BOARD_SOURCES,
    ("cutting_calc_cut", "ck_cutting_calc_cut_orientation_values"): models.CUT_ORIENTATIONS,
    ("cutting_calc_item_result", "ck_cutting_calc_item_result_unfit_reason_values"): models.UNFIT_REASONS,
}
PAYLOADS: dict[str, type[BaseModel]] = {
    ev.PLAN_SAVED: ev.PlanSavedPayload,
    ev.PLAN_CALCULATED: ev.PlanCalculatedPayload,
    ev.PLAN_VERIFICATION_REQUIRED: ev.PlanRefPayload,
    ev.PLAN_VERIFIED: ev.PlanRefPayload,
    ev.PLAN_ARCHIVED: ev.PlanRefPayload,
}


def _tables() -> dict[str, type]:
    return {m.class_.__tablename__: m.class_ for m in Base.registry.mappers if m.class_.__tablename__.startswith("cutting_")}


def _check_values(uow: UnitOfWork, table: str, name: str) -> set[str]:
    definition = uow.session.execute(
        text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = CAST(:t AS regclass) AND conname = :n"),
        {"t": table, "n": name},
    ).scalar_one()
    return set(re.findall(r"'([^']*)'", definition))


@pytest.mark.db
def test_enum_checks_match_the_model_values(db: None) -> None:
    with UnitOfWork(ActorContext.system(None)) as uow:
        for (table, name), values in ENUM_CHECKS.items():
            assert _check_values(uow, table, name) == set(values), (table, name)
    assert set(models.UNFIT_REASONS) == set(engine.UNFIT_REASONS)
    assert set(models.MODES) == set(engine.MODES)


@pytest.mark.db
def test_cutting_tables_force_rls_and_append_only_matches_model_flags(db: None) -> None:
    tables = _tables()
    assert len(tables) == 12
    with UnitOfWork(ActorContext.system(None)) as uow:
        policies = set(uow.session.execute(text("SELECT tablename FROM pg_policies WHERE policyname = 'tenant_isolation'")).scalars())
        forced = set(uow.session.execute(text("SELECT relname FROM pg_class WHERE relforcerowsecurity")).scalars())
        triggers = set(uow.session.execute(text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal")).scalars())
    assert set(tables) <= policies and set(tables) <= forced
    for name, model in tables.items():
        flagged = bool(getattr(model, "__append_only__", False))
        assert (f"trg_{name}_append_only" in triggers) is flagged, name


def test_emitted_events_and_payloads_are_in_the_frozen_catalogue() -> None:
    registry = get_registry()
    assert set(ev.EMITTED_EVENTS) == set(PAYLOADS)
    for name, payload in PAYLOADS.items():
        event = registry.events[name]
        assert event.fields is not None and set(payload.model_fields) - {"origin"} == set(event.fields), name


def test_routes_name_only_catalogued_cutting_keys() -> None:
    from app.core.http.authz_decl import api_routes
    from app.main import create_app

    keys = {p["key"] for p in PERMISSIONS}
    seen = set()
    for path, route in api_routes(create_app()):
        if not path.startswith("/api/v1/cutting"):
            continue
        decl = (route.openapi_extra or {})["x-authz"]
        assert decl["kind"] in {"permission", "authenticated"}, path
        for key in decl.get("permissions", []):
            assert key in keys, (path, key)
            seen.add(key)
    assert {"cutting.calculation.run", "cutting.plan.read", "cutting.plan.create", "cutting.plan.update",
            "cutting.plan.transition", "cutting.plan.export", "cutting.grain_lock.manage", "cutting.settings.manage"} <= seen


def test_lane_contributions_are_registered() -> None:
    registry = get_registry()
    seq = registry.sequences["cutting.plan"]
    assert (seq.format_template, seq.reset_policy) == ("CUT-{yyyy}-{seq:04}", "yearly")
    assert "cutting.calculate" in registry.jobs
    assert [(s.order, s.name, s.slice_no) for s in registry.seeds if s.name.startswith("cutting")] == [(78, "cutting.world", 2)]
    assert registry.policies["cutting.plan"].owner_columns == ("owner_user_id",)
    for child in ("cutting.plan_item", "cutting.calculation"):
        assert registry.policies[child].parent.resource_type == "cutting.plan", child  # type: ignore[union-attr]
    for child in ("cutting.calc_group", "cutting.calc_board", "cutting.calc_placement", "cutting.calc_item_result",
                  "cutting.calc_offcut", "cutting.calc_cut"):
        assert registry.policies[child].parent.resource_type == "cutting.calculation", child  # type: ignore[union-attr]
