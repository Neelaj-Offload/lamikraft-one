"""Reference data: global currencies and the per-company unit-of-measure master with exact conversions."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.errors import NotFound, ValidationFailed
from app.platform.authz.context import ActorContext
from app.platform.org import reference
from app.platform.org.reference import DEFAULT_UOMS
from app.platform.uow import UnitOfWork
from app.seed.world import keys
from tests.integration.org.platform_lane import ApiClient, member, problem

pytestmark = pytest.mark.db


@pytest.fixture
def uoms(company):  # type: ignore[no-untyped-def]
    company_id, _ = company
    with UnitOfWork(ActorContext.system(company_id, reason="test-setup")) as uow:
        reference.ensure_default_uoms(uow)
    return company_id


@pytest.fixture
def employee(uoms):  # type: ignore[no-untyped-def]
    return member(uoms, keys.PEOPLE["MEERA"].name, "employee").actor()


def test_currencies_are_the_enabled_set_with_exponent_2(api: ApiClient, employee) -> None:  # type: ignore[no-untyped-def]
    r = api.as_(employee).get("/api/v1/org/currencies")
    assert r.status_code == 200
    rows = r.json()
    assert tuple(c["code"] for c in rows) == keys.CURRENCIES
    assert {c["exponent"] for c in rows} == {2}
    assert {c["code"]: c["symbol"] for c in rows}["EUR"] == "€"


def test_currency_reference_is_read_only_for_the_runtime_role(employee) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(DBAPIError, match="permission denied"):
        with UnitOfWork(employee) as uow:
            uow.session.execute(text("UPDATE currency SET exponent = 3 WHERE code = 'EUR'"))


def test_uom_master_lists_the_seeded_codes(api: ApiClient, employee) -> None:  # type: ignore[no-untyped-def]
    r = api.as_(employee).get("/api/v1/org/uoms")
    assert r.status_code == 200
    rows = {u["code"]: u for u in r.json()}
    assert set(rows) == {
        "pcs", "nos", "sheets", "kg", "g", "m", "mm", "cm", "sqm", "sqft", "box", "set", "roll", "bundle", "carton",
    }
    integer_units = {"pcs", "nos", "sheets", "box", "set", "roll", "bundle", "carton"}
    assert {c for c, u in rows.items() if u["is_integer"]} == integer_units
    assert rows["pcs"]["max_decimal_places"] == 0 and rows["kg"]["max_decimal_places"] == 4
    assert "piece" in rows["pcs"]["aliases"] and "sq ft" in rows["sqft"]["aliases"]
    kg = {(c["to_code"], c["factor"]) for c in rows["kg"]["conversions"]}
    assert ("g", "1000") in kg
    assert {(c["to_code"], c["factor"]) for c in rows["sqft"]["conversions"]} == {("sqm", "0.09290304")}


def test_ensure_default_uoms_is_idempotent(uoms) -> None:  # type: ignore[no-untyped-def]
    with UnitOfWork(ActorContext.system(uoms, reason="test")) as uow:
        assert reference.ensure_default_uoms(uow) == 0
        count = uow.session.execute(text("SELECT count(*) FROM uom")).scalar()
    assert count == len(DEFAULT_UOMS)


@pytest.mark.parametrize(
    ("qty", "from_uom", "to_uom", "expected"),
    [
        ("2.5", "kg", "g", "2500.000000"),
        ("750", "g", "kg", "0.750000"),
        ("1.2", "m", "mm", "1200.000000"),
        ("35", "mm", "cm", "3.500000"),
        ("100", "sqft", "sqm", "9.290304"),
        ("9.290304", "sqm", "sqft", "100.000000"),
        ("12", "pcs", "nos", "12.000000"),
        ("3", "Kgs", " GMS ", "3000.000000"),  # aliases, case and spacing
        ("7", "pcs", "pcs", "7.000000"),
    ],
)
def test_convert_uses_exact_conversions(uoms, qty, from_uom, to_uom, expected) -> None:  # type: ignore[no-untyped-def]
    with UnitOfWork(ActorContext.system(uoms)) as uow:
        assert reference.convert(uow, Decimal(qty), from_uom, to_uom) == Decimal(expected)


@pytest.mark.parametrize(("from_uom", "to_uom"), [("pcs", "box"), ("kg", "m"), ("carton", "pcs"), ("sqm", "kg")])
def test_missing_conversion_is_422_never_guessed(uoms, from_uom, to_uom) -> None:  # type: ignore[no-untyped-def]
    with UnitOfWork(ActorContext.system(uoms)) as uow:
        with pytest.raises(ValidationFailed) as exc:
            reference.convert(uow, Decimal("1"), from_uom, to_uom)
    assert exc.value.status == 422 and exc.value.code == "uom_conversion_missing"
    assert exc.value.extra["from_uom"] == from_uom and exc.value.extra["to_uom"] == to_uom


def test_unknown_unit_is_reported_as_missing_conversion(uoms) -> None:  # type: ignore[no-untyped-def]
    with UnitOfWork(ActorContext.system(uoms)) as uow:
        with pytest.raises(ValidationFailed) as exc:
            reference.convert(uow, Decimal("1"), "furlong", "m")
    assert exc.value.code == "uom_conversion_missing" and exc.value.extra["unknown_uoms"] == ["furlong"]


def test_product_specific_conversion_wins_over_generic(uoms) -> None:  # type: ignore[no-untyped-def]
    product_a, product_b = uuid.uuid7(), uuid.uuid7()
    with UnitOfWork(ActorContext.system(uoms)) as uow:
        reference.define_conversion(uow, "carton", "pcs", Decimal("24"), product_id=product_a)
        reference.define_conversion(uow, "carton", "pcs", Decimal("12"))
        assert reference.convert(uow, Decimal("2"), "carton", "pcs", product_id=product_a) == Decimal("48")
        assert reference.convert(uow, Decimal("2"), "carton", "pcs", product_id=product_b) == Decimal("24")
        assert reference.convert(uow, Decimal("48"), "pcs", "carton", product_id=product_a) == Decimal("2")
        assert reference.convert(uow, Decimal("2"), "carton", "pcs") == Decimal("24")


def test_floats_are_rejected(uoms) -> None:  # type: ignore[no-untyped-def]
    with UnitOfWork(ActorContext.system(uoms)) as uow:
        with pytest.raises(TypeError):
            reference.convert(uow, 1.5, "kg", "g")  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            reference.define_conversion(uow, "box", "pcs", 10.0)  # type: ignore[arg-type]


def test_defining_conversions_needs_the_uom_permission(uoms) -> None:  # type: ignore[no-untyped-def]
    emp = member(uoms, "Clerk", "employee").actor()
    from app.core.errors import Forbidden

    with pytest.raises(Forbidden):
        reference.define_conversion(emp, "box", "pcs", Decimal("10"))
    steward = member(uoms, "Steward", "catalogue").actor()
    out = reference.define_conversion(steward, "box", "pcs", Decimal("10"))
    assert out.factor == Decimal("10")
    with pytest.raises(NotFound):
        reference.define_conversion(steward, "box", "furlong", Decimal("10"))
    with pytest.raises(ValidationFailed):
        reference.define_conversion(steward, "box", "box", Decimal("1"))


@pytest.mark.parametrize(
    ("value", "uom", "code"),
    [("2.5", "pcs", "not_integer"), ("1.12345", "kg", "too_many_decimals"), ("0", "kg", "not_positive"),
     ("-1", "m", "not_positive"), ("1", "furlong", "uom_unknown")],
)
def test_entry_rules_per_unit(uoms, value, uom, code) -> None:  # type: ignore[no-untyped-def]
    with UnitOfWork(ActorContext.system(uoms)) as uow:
        with pytest.raises(ValidationFailed) as exc:
            reference.validate_quantity(uow, Decimal(value), uom)
    assert exc.value.extra["errors"][0]["code"] == code


def test_valid_entries_resolve_aliases(uoms) -> None:  # type: ignore[no-untyped-def]
    with UnitOfWork(ActorContext.system(uoms)) as uow:
        assert reference.validate_quantity(uow, Decimal("240"), "Pieces") == (Decimal("240"), "pcs")
        assert reference.validate_quantity(uow, Decimal("240.000"), "pcs") == (Decimal("240.000"), "pcs")
        assert reference.validate_quantity(uow, Decimal("1.2345"), "sq m") == (Decimal("1.2345"), "sqm")


def test_uom_rows_are_tenant_isolated(company) -> None:  # type: ignore[no-untyped-def]
    a, _ = company
    from tests.support import create_company

    b, _ = create_company()
    with UnitOfWork(ActorContext.system(a)) as uow:
        reference.ensure_default_uoms(uow)
    with UnitOfWork(ActorContext.system(b)) as uow:
        assert reference.list_uoms(uow) == []
        with pytest.raises(ValidationFailed):
            reference.convert(uow, Decimal("1"), "kg", "g")


def test_list_uoms_needs_a_signed_in_actor(api: ApiClient) -> None:
    r = api.as_(None).get("/api/v1/org/uoms")
    assert r.status_code == 401 and problem(r)["code"] == "unauthenticated"


@settings(max_examples=60, deadline=None, derandomize=True, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    qty=st.decimals(min_value=Decimal("0.0001"), max_value=Decimal("100000"), places=4),
    pair=st.sampled_from([("kg", "g"), ("m", "mm"), ("m", "cm"), ("cm", "mm"), ("pcs", "nos")]),
)
def test_round_trip_through_exact_factors_is_lossless(uoms, qty, pair) -> None:  # type: ignore[no-untyped-def]
    a, b = pair
    with UnitOfWork(ActorContext.system(uoms)) as uow:
        there = reference.convert(uow, qty, a, b)
        back = reference.convert(uow, there, b, a)
    assert back == qty.quantize(Decimal("0.000001"))
    assert isinstance(there, Decimal)
