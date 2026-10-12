"""Unit tests for pure kernel pieces: money, CSV safety, LIKE escaping, numbering, permissions, scope SQL."""

from __future__ import annotations

import csv
import io
import uuid
from datetime import date
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import BaseModel, ValidationError
from sqlalchemy.dialects import postgresql

from app.core.csv_safe import escape_cell, strip_guard, write_csv
from app.core.money import DecimalStr, Money, quantize_money
from app.core.text import contains_pattern, escape_like
from app.platform.authz.context import ActorContext
from app.platform.authz.permissions import PermissionDef, Scope
from app.platform.numbering.service import period_key, render


class _M(BaseModel):
    amount: DecimalStr


def test_decimal_str_rejects_float_and_serialises_as_string() -> None:
    with pytest.raises(ValidationError):
        _M(amount=24.0)  # type: ignore[arg-type]
    m = _M(amount="5760.00")
    assert m.model_dump(mode="json") == {"amount": "5760.00"}
    assert _M.model_json_schema()["properties"]["amount"]["type"] == "string"


def test_money_arithmetic_is_decimal_and_currency_safe() -> None:
    a = Money(amount="24.0000", currency="EUR").times(Decimal(240))
    assert a.rounded().amount == Decimal("5760.00")
    with pytest.raises(ValueError):
        _ = Money(amount="1", currency="EUR") + Money(amount="1", currency="USD")


@given(st.decimals(min_value=Decimal("-1e9"), max_value=Decimal("1e9"), allow_nan=False, allow_infinity=False, places=6))
def test_quantize_money_two_places(value: Decimal) -> None:
    q = quantize_money(value, "INR")
    assert q.as_tuple().exponent == -2


@pytest.mark.parametrize("raw", ["=SUM(A1:A2)", "+1", "-2+3", "@cmd", "\tx", " =1", "＝HYPERLINK()"])
def test_csv_escapes_formula_like_text(raw: str) -> None:
    out = escape_cell(raw)
    assert out.startswith("'")
    assert strip_guard(out) == raw


def test_csv_keeps_numbers_numeric_and_writes_bom_crlf() -> None:
    data = write_csv(["Name", "Total"], [["Crown ₹ €", Decimal("-5.50")], ["=evil()", 3]])
    assert data.startswith("﻿".encode())
    text = data.decode("utf-8-sig")
    assert "\r\n" in text
    rows = list(csv.reader(io.StringIO(text)))
    assert rows[1] == ["Crown ₹ €", "-5.50"]
    assert rows[2] == ["'=evil()", "3"]


def test_escape_like_neutralises_wildcards() -> None:
    assert escape_like("50%_off\\") == "50\\%\\_off\\\\"
    assert contains_pattern("a%") == "%a\\%%"


def test_period_keys_and_rendering() -> None:
    d = date(2026, 10, 12)
    assert period_key("never", d) == "all"
    assert period_key("yearly", d) == "2026"
    assert period_key("financial_year", d) == "2026-27"
    assert period_key("financial_year", date(2027, 3, 31)) == "2026-27"
    assert render("{brand}-QT-{yyyy}-{seq:04}", seq=7, document_date=d, period="2026", tokens={"brand": "LK"}) == "LK-QT-2026-0007"
    assert render("DC-{yyyy}-{seq:04}", seq=12, document_date=d, period="2026", tokens={}) == "DC-2026-0012"
    assert render("CP-{seq:04}", seq=1, document_date=d, period="all", tokens={}) == "CP-0001"
    with pytest.raises(ValueError):
        render("{brand}-{seq:04}", seq=1, document_date=d, period="all", tokens={"brand": "lk; drop"})


def test_permission_def_validates_grammar_and_verbs() -> None:
    PermissionDef("sales.quote.read", "Read quotes", scopes=(Scope.OWN, Scope.COMPANY))
    with pytest.raises(ValueError):
        PermissionDef("sales.read", "bad grammar")
    with pytest.raises(ValueError):
        PermissionDef("sales.quote.frobnicate", "bad verb")


def test_actor_context_scope_and_system() -> None:
    uid = uuid.uuid7()
    ctx = ActorContext(actor_type="user", company_id=uuid.uuid7(), user_id=uid, permissions={"sales.quote.read": Scope.OWN})
    assert ctx.can("sales.quote.read")
    assert not ctx.can("sales.quote.read", Scope.COMPANY)
    assert not ctx.can("sales.quote.delete")
    sys_ctx = ActorContext.system(uuid.uuid7())
    assert sys_ctx.can("anything.at.all", Scope.COMPANY)


def test_scope_clause_compiles_own_scope_to_owner_filter() -> None:
    from sqlalchemy import Column, MetaData, Table, Uuid
    from sqlalchemy.orm import registry

    md = MetaData()
    table = Table("t_doc", md, Column("id", Uuid, primary_key=True), Column("company_id", Uuid), Column("owner_user_id", Uuid))
    reg = registry()

    class Doc:  # minimal mapped class for the clause builder
        pass

    reg.map_imperatively(Doc, table)
    from app.platform.authz.policy import ResourcePolicy, scope_clause

    policy = ResourcePolicy(resource_type="test.doc", model=Doc, permission_prefix="test.doc", owner_columns=("owner_user_id",))
    uid = uuid.uuid7()
    own = ActorContext(actor_type="user", company_id=uuid.uuid7(), user_id=uid, permissions={"test.doc.read": Scope.OWN})
    sql = str(scope_clause(own, policy).compile(dialect=postgresql.dialect()))
    assert "owner_user_id" in sql and "company_id" in sql
    none = ActorContext(actor_type="user", company_id=uuid.uuid7(), user_id=uid, permissions={})
    sql_none = str(scope_clause(none, policy).compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "false" in sql_none.lower()
    company = ActorContext(actor_type="user", company_id=uuid.uuid7(), user_id=uid, permissions={"test.doc.read": Scope.COMPANY})
    sql_company = str(scope_clause(company, policy).compile(dialect=postgresql.dialect()))
    assert "owner_user_id" not in sql_company
