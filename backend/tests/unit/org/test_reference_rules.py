"""Unit-of-measure seed data and wire formats (no database)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.platform.org.reference import DEFAULT_CONVERSIONS, DEFAULT_UOMS, normalize_unit_text
from app.platform.org.schemas import UomConversionRead

SEEDED = ("pcs", "nos", "sheets", "kg", "g", "m", "mm", "cm", "sqm", "sqft", "box", "set", "roll", "bundle", "carton")
INTEGER_UNITS = {"pcs", "nos", "sheets", "box", "set", "roll", "bundle", "carton"}


def test_seeded_codes_follow_conventions_section_6() -> None:
    assert tuple(u.code for u in DEFAULT_UOMS) == SEEDED
    assert {u.code for u in DEFAULT_UOMS if u.is_integer} == INTEGER_UNITS


def test_aliases_are_normalised_unique_and_never_shadow_a_code() -> None:
    seen: dict[str, str] = {}
    codes = set(SEEDED)
    for unit in DEFAULT_UOMS:
        for alias in unit.aliases:
            text = normalize_unit_text(alias)
            assert text not in codes or text == unit.code
            assert seen.setdefault(text, unit.code) == unit.code, f"alias {alias} maps to two units"


def test_standard_conversions_only_link_compatible_seeded_units() -> None:
    dims = {u.code: u.dimension for u in DEFAULT_UOMS}
    for from_code, to_code, factor in DEFAULT_CONVERSIONS:
        assert dims[from_code] == dims[to_code]
        assert Decimal(factor) > 0
    pack_units = {u.code for u in DEFAULT_UOMS if u.dimension == "pack"}
    assert not any(a in pack_units or b in pack_units for a, b, _ in DEFAULT_CONVERSIONS)  # per product only


def test_normalize_unit_text() -> None:
    assert normalize_unit_text("  Sq.  M ") == "sq. m"
    assert normalize_unit_text("ＫＧ") == "kg"  # full-width input (NFKC)
    assert normalize_unit_text("m²") == "m2"


def test_factors_serialise_exactly_without_trailing_zeros() -> None:
    row = UomConversionRead(from_code="sqft", to_code="sqm", factor=Decimal("0.0929030400"), provenance="standard")
    assert row.model_dump(mode="json")["factor"] == "0.09290304"
    assert UomConversionRead(from_code="kg", to_code="g", factor=Decimal("1000.0000000000"),
                             provenance="standard").model_dump(mode="json")["factor"] == "1000"
    schema = UomConversionRead.model_json_schema()["properties"]["factor"]
    assert schema["type"] == "string"


@pytest.mark.parametrize("bad", [0.5, "0", "-2", "0.00000000001", "abc", True, "", "NaN"])
def test_factors_are_positive_decimals_with_at_most_10_places(bad: object) -> None:
    """Same rules as the kernel RatioStr on main: no floats, positive, NUMERIC(20,10) precision."""
    with pytest.raises(ValidationError):
        UomConversionRead(from_code="kg", to_code="g", factor=bad, provenance="standard")  # type: ignore[arg-type]
    ok = UomConversionRead(from_code="kg", to_code="g", factor="0.0000000001", provenance="standard")
    assert ok.model_dump(mode="json")["factor"] == "0.0000000001"
