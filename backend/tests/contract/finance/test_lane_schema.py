"""Finance lane contracts: database CHECKs mirror the StrEnums, every ``finance_`` table has forced RLS and the
append-only flags match the triggers, emitted events are in the frozen catalogue with id/code/date payloads only (no
amounts, quantities, margins or bank details), sequences follow the April financial year, every finance route
declares a catalogued permission, and the issue-gate blocker codes are stable."""

from __future__ import annotations

import re
from enum import StrEnum

import pytest
from sqlalchemy import text

from app.core.db.base import Base
from app.modules.finance import events as ev
from app.modules.finance.enums import Blocker
from app.platform.authz.catalogue_data import PERMISSIONS
from app.platform.authz.context import ActorContext
from app.platform.events.catalogue_data import EVENTS
from app.platform.uow import UnitOfWork

FORBIDDEN_PAYLOAD = re.compile(r"amount|total|quantity|qty|margin|cost|price|bank|account_number|iban|notes|reason$")


def _tables() -> dict[str, type]:
    return {m.class_.__tablename__: m.class_ for m in Base.registry.mappers if m.class_.__tablename__.startswith("finance_")}


def _enum_columns() -> dict[tuple[str, str], type[StrEnum]]:
    out: dict[tuple[str, str], type[StrEnum]] = {}
    for t in Base.metadata.sorted_tables:
        if t.name.startswith("finance_"):
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
def test_tables_force_rls_append_only_and_issued_frozen(db: None) -> None:
    tables = _tables()
    assert len(tables) == 10
    with UnitOfWork(ActorContext.system(None)) as uow:
        policies = set(uow.session.execute(text("SELECT tablename FROM pg_policies WHERE policyname = 'tenant_isolation'")).scalars())
        forced = set(uow.session.execute(text("SELECT relname FROM pg_class WHERE relforcerowsecurity")).scalars())
        triggers = set(uow.session.execute(text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal")).scalars())
    assert set(tables) <= policies and set(tables) <= forced
    for name, model in tables.items():
        assert (f"trg_{name}_append_only" in triggers) is bool(getattr(model, "__append_only__", False)), name
    assert {"trg_finance_invoice_issued_frozen", "trg_finance_invoice_line_issued_frozen",
            "trg_finance_invoice_immutable", "trg_finance_receipt_immutable"} <= triggers


def test_events_are_catalogued_with_ids_only() -> None:
    catalogue = {e["name"]: e for e in EVENTS}
    for name in ev.EMITTED_EVENTS:
        assert name in catalogue, name
        assert catalogue[name]["slice"] == 5
        leaking = [f for f in catalogue[name]["fields"] if FORBIDDEN_PAYLOAD.search(f)]
        assert leaking == [], (name, leaking)
    assert catalogue[ev.MARGIN_BELOW_THRESHOLD]["fields"] == ["quote_id", "exception_id", "revision_no"]


def test_sequences_follow_the_april_financial_year() -> None:
    by_key = {s.key: s for s in ev.SEQUENCES}
    assert by_key["finance.invoice"].format_template == "INV-{fy}-{seq:04}"
    assert by_key["finance.credit_note"].format_template == "CN-{fy}-{seq:04}"
    assert by_key["finance.receipt"].format_template == "RCPT-{fy}-{seq:04}"
    for key in ("finance.invoice", "finance.credit_note", "finance.receipt", "finance.accounting_export"):
        assert by_key[key].reset_policy == "financial_year"
    assert by_key["finance.draft"].reset_policy == "never"  # drafts never consume an invoice number


def test_every_finance_route_declares_a_catalogued_permission() -> None:
    from app.main import create_app

    known = {p["key"] for p in PERMISSIONS}
    paths = create_app().openapi()["paths"]
    finance = {p: ops for p, ops in paths.items() if p.startswith("/api/v1/finance")}
    assert len(finance) >= 25
    for path, ops in finance.items():
        for method, op in ops.items():
            decl = op.get("x-authz") or {}
            assert decl.get("kind") == "permission", (method, path)
            assert decl["permissions"] and set(decl["permissions"]) <= known, (method, path)


def test_blocker_codes_are_stable() -> None:
    assert {b.value for b in Blocker} == {
        "not_approved", "approval_stale", "company_identity_incomplete", "party_billing_incomplete",
        "tax_profile_missing", "tax_profile_unverified", "e_invoice_provider_not_verified", "totals_changed",
        "quantity_exceeds_delivered", "quantity_exceeds_creditable", "no_lines", "zero_total",
    }
