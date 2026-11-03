"""Challans lane contracts: database CHECKs mirror the StrEnums, every ``challans_`` table has forced RLS, the
append-only triggers match the model flags, the number is immutable, emitted events and their payloads are in the
frozen catalogue, the state table uses catalogued keys, the tool carries no identity fields, and every contribution
(policies, sequence, setting, tool, reader, job, schedule, seed, routes) is registered."""

from __future__ import annotations

import re
from enum import StrEnum

import pytest
from pydantic import BaseModel
from sqlalchemy import text

from app.core.db.base import Base
from app.modules.challans import events as ev
from app.modules.challans.schemas import (
    ChallanOrigin,
    ChallanStatus,
    ChallanType,
    DestinationType,
    InventoryEffect,
    LineType,
    ReturnLinkKind,
    ReturnType,
    TransitionAction,
)
from app.modules.challans.state import TRANSITIONS
from app.platform import sources
from app.platform.authz.catalogue_data import PERMISSIONS
from app.platform.authz.context import ActorContext
from app.platform.tools import FORBIDDEN_INPUT_FIELDS
from app.platform.uow import UnitOfWork
from app.registry import get_registry

ENUM_COLUMNS: dict[tuple[str, str], type[StrEnum]] = {
    ("challans_challan", "challan_type"): ChallanType,
    ("challans_challan", "return_type"): ReturnType,
    ("challans_challan", "destination_type"): DestinationType,
    ("challans_challan", "status"): ChallanStatus,
    ("challans_challan", "inventory_effect"): InventoryEffect,
    ("challans_challan", "origin"): ChallanOrigin,
    ("challans_challan_line", "line_type"): LineType,
    ("challans_return_link", "kind"): ReturnLinkKind,
    ("challans_challan_status_history", "action"): TransitionAction,
}
PAYLOADS: dict[str, type[BaseModel]] = {
    ev.CHALLAN_ISSUED: ev.ChallanIssuedPayload,
    ev.CHALLAN_CLOSED: ev.ChallanClosedPayload,
    ev.CHALLAN_CANCELLED: ev.ChallanCancelledPayload,
    ev.RETURN_RECEIVED: ev.ReturnReceivedPayload,
    ev.RETURNABLE_DUE: ev.ReturnableDuePayload,
    ev.RETURNABLE_OVERDUE: ev.ReturnableDuePayload,
}
TABLES = {"challans_challan", "challans_challan_line", "challans_return_link", "challans_challan_revision", "challans_challan_status_history"}


def _tables() -> dict[str, type]:
    return {m.class_.__tablename__: m.class_ for m in Base.registry.mappers if m.class_.__tablename__.startswith("challans_")}


def _check_values(uow: UnitOfWork, table: str, name: str) -> set[str]:
    definition = uow.session.execute(
        text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = CAST(:t AS regclass) AND conname = :n"),
        {"t": table, "n": name},
    ).scalar_one()
    return set(re.findall(r"'([^']*)'", definition))


@pytest.mark.db
def test_enum_checks_match_the_strenums(db: None) -> None:
    with UnitOfWork(ActorContext.system(None)) as uow:
        for (table, column), enum in ENUM_COLUMNS.items():
            assert _check_values(uow, table, f"ck_{table}_{column}_values") == {e.value for e in enum}, (table, column)


@pytest.mark.db
def test_tables_force_rls_append_only_matches_flags_and_number_is_immutable(db: None) -> None:
    tables = _tables()
    assert set(tables) == TABLES
    with UnitOfWork(ActorContext.system(None)) as uow:
        policies = set(uow.session.execute(text("SELECT tablename FROM pg_policies WHERE policyname = 'tenant_isolation'")).scalars())
        forced = set(uow.session.execute(text("SELECT relname FROM pg_class WHERE relforcerowsecurity")).scalars())
        triggers = set(uow.session.execute(text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal")).scalars())
        deferrable = uow.session.execute(text(
            "SELECT condeferrable FROM pg_constraint WHERE conrelid = CAST('challans_challan_line' AS regclass) AND contype = 'u'"
        )).scalars().all()
    assert set(tables) <= policies and set(tables) <= forced
    for name, model in tables.items():
        flagged = bool(getattr(model, "__append_only__", False))
        assert (f"trg_{name}_append_only" in triggers) is flagged, name
    assert "trg_challans_challan_immutable" in triggers
    assert True in deferrable  # (challan_id, line_no) is deferrable so lines renumber in one transaction


def test_emitted_events_and_payloads_are_in_the_frozen_catalogue() -> None:
    registry = get_registry()
    assert set(ev.EMITTED_EVENTS) == set(PAYLOADS)
    for name, payload in PAYLOADS.items():
        event = registry.events[name]
        assert event.fields is not None and set(payload.model_fields) == set(event.fields), name


def test_state_table_uses_catalogued_keys_and_events() -> None:
    registry = get_registry()
    keys = {p["key"] for p in PERMISSIONS}
    for t in TRANSITIONS.values():
        assert f"challans.challan.{t.permission_action}" in keys, t
        assert t.event in registry.events, t
        assert t.action in {a.value for a in TransitionAction}
    assert {t.permission_action for t in TRANSITIONS.values()} == {"issue", "transition", "reverse"}


def test_lane_contributions_are_registered() -> None:
    registry = get_registry()
    tools = {t.name: t for t in registry.tools}
    draft = tools["draft_challan"]
    assert (draft.effect, draft.permission, draft.requires_idempotency) == ("draft", "challans.challan.create", True)
    assert not FORBIDDEN_INPUT_FIELDS & set(draft.input_model.model_fields)
    assert sources.has_reader("challans.challan")
    seq = registry.sequences["challans.challan"]
    assert (seq.format_template, seq.reset_policy) == ("DC-{yyyy}-{seq:04}", "yearly")
    assert [(s.order, s.name, s.slice_no) for s in registry.seeds if s.name.startswith("challans")] == [(52, "challans.world", 2)]
    assert "challans.returnables_sweep" in registry.jobs and "challans.returnables_sweep" in registry.schedules
    assert any(getattr(s, "key", None) == "challan_defaults" for s in registry.settings)
    for resource in ("challans.challan",):
        assert resource in registry.policies and registry.policies[resource].archived_column == "deleted_at"
    for child in ("challans.challan_line", "challans.challan_revision", "challans.challan_status_history", "challans.return_link"):
        assert registry.policies[child].parent is not None, child  # authorised only through the challan
    perms = {p["key"]: p for p in PERMISSIONS if p["key"].startswith("challans.challan.")}
    assert set(perms) == {f"challans.challan.{v}" for v in ("read", "create", "update", "issue", "transition", "reverse", "delete", "export")}
    assert perms["challans.challan.delete"]["grants"] == {}  # admin template only (holds every key)


def test_routes_declare_their_permissions() -> None:
    from app.main import create_app

    spec = create_app().openapi()
    paths = {p: item for p, item in spec["paths"].items() if p.startswith("/api/v1/challans/")}
    assert {
        "/api/v1/challans/challans", "/api/v1/challans/challans/summary", "/api/v1/challans/challans/export.csv",
        "/api/v1/challans/challans/lookup", "/api/v1/challans/challans/{challan_id}", "/api/v1/challans/challans/{challan_id}/lines",
        "/api/v1/challans/challans/{challan_id}/lines/{line_id}", "/api/v1/challans/challans/{challan_id}/transitions",
        "/api/v1/challans/challans/{challan_id}/duplicate", "/api/v1/challans/challans/{challan_id}/revisions",
        "/api/v1/challans/challans/{challan_id}/revisions/{revision_no}", "/api/v1/challans/challans/{challan_id}/print",
        "/api/v1/challans/challans/{challan_id}/document.pdf", "/api/v1/challans/challans/{challan_id}/revisions/{revision_no}/document.pdf",
    } == set(paths)
    for path, item in paths.items():
        for method, op in item.items():
            assert op.get("x-authz", {}).get("permissions"), (method, path)
    assert spec["paths"]["/api/v1/challans/challans/{challan_id}"]["delete"]["x-authz"]["permissions"] == ["challans.challan.delete"]
