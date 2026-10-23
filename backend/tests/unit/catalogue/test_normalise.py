"""Catalogue normalisation: text identifiers, canonical millimetres and packaging aliases (pure functions)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.catalogue.normalise import (
    ALIAS_CONFLICT,
    CBM_MISMATCH,
    DECOR_FLOAT_ARTEFACT_NORMALISED,
    GROSS_BELOW_NET,
    INNER_EXCEEDS_CARTON,
    normalise_identifier,
    normalise_thickness,
    packaging_cross_checks,
    parse_dimension,
    parse_length,
    plain_decimal,
    resolve_packaging_aliases,
)
from app.seed.world import keys


# ---- identifiers (legacy bug §10.1 #5: "120.0".rstrip(".0") corrupted the decor into "12") -----------------
@pytest.mark.parametrize(
    ("raw", "expected", "warned"),
    [
        (keys.DECORS.NATURAL_OAK, "0120", False),  # leading zeros are kept
        ("0120", "0120", False),
        ("120", "120", False),
        ("120.0", "120", True),  # float artefact -> "120" with a warning, never "12"
        ("120.000", "120", True),
        ("12.50", "12.50", False),  # not an artefact; unchanged
        ("  0457 ", "0457", False),  # only outer whitespace is trimmed
        (120, "120", False),  # numeric spreadsheet cell
        (Decimal("120.0"), "120", False),
    ],
)
def test_decor_identifiers(raw: object, expected: str, warned: bool) -> None:
    result = normalise_identifier(raw, float_artefact_rule=True)
    assert result.value == expected
    assert (DECOR_FLOAT_ARTEFACT_NORMALISED in result.warnings) is warned


def test_leading_zero_identifier_is_distinct_from_the_number() -> None:
    a = normalise_identifier("0120", float_artefact_rule=True).value
    b = normalise_identifier("120", float_artefact_rule=True).value
    c = normalise_identifier("120.0", float_artefact_rule=True).value
    assert a == "0120" and b == c == "120" and a != b


def test_artefact_rule_is_a_toggle_and_keeps_the_source() -> None:
    off = normalise_identifier("120.0")
    assert off.value == "120.0" and off.warnings == () and off.source is None
    on = normalise_identifier("120.0", float_artefact_rule=True)
    assert on.source == "120.0"
    assert normalise_identifier("120", zero_pad_width=4).value == "0120"  # explicit admin choice only
    assert normalise_identifier("   ").value is None and normalise_identifier(None).value is None
    with pytest.raises(TypeError):
        normalise_identifier(True)


@settings(max_examples=200, derandomize=True)
@given(st.from_regex(r"\A0*[1-9][0-9]{0,5}\Z", fullmatch=True))
def test_text_identifiers_never_lose_digits(text: str) -> None:
    assert normalise_identifier(text, float_artefact_rule=True).value == text


# ---- thickness and dimensions -------------------------------------------------------------------------
@pytest.mark.parametrize("raw", ["0.8", "0.80", "0.800", Decimal("0.8"), Decimal("0.800"), "0.8 mm", "0.08 cm"])
def test_thickness_point_eight_is_one_value(raw: object) -> None:
    assert normalise_thickness(raw) == Decimal("0.800")
    assert plain_decimal(normalise_thickness(raw)) == "0.8"  # type: ignore[arg-type]


def test_thickness_rejects_floats_and_non_positive() -> None:
    with pytest.raises(TypeError):
        normalise_thickness(0.8)
    with pytest.raises(ValueError):
        normalise_thickness("0")
    with pytest.raises(ValueError):
        normalise_thickness("thick")
    assert normalise_thickness("  ") is None


@pytest.mark.parametrize(
    ("text", "status", "lwh"),
    [
        ("450 x 300", "parsed", ("450.000", "300.000", None)),
        ("450x300 mm", "parsed", ("450.000", "300.000", None)),
        ("30 x 20 cm", "parsed", ("300.000", "200.000", None)),
        ('12" x 8"', "parsed", ("304.800", "203.200", None)),
        ("2440*1220*18", "parsed", ("2440.000", "1220.000", "18.000")),
        ("2,440 x 1,220", "parsed", ("2440.000", "1220.000", None)),
        ("2440 × 1220 mm", "parsed", ("2440.000", "1220.000", None)),
        ("300-350", "unparsed", None),
        ("450", "ambiguous", ("450.000", None, None)),
        ("about a foot", "unparsed", None),
    ],
)
def test_parse_dimension(text: str, status: str, lwh: tuple[str | None, ...] | None) -> None:
    parsed = parse_dimension(text)
    assert parsed is not None and parsed.status == status and parsed.source_text == text
    if lwh is not None:
        got = tuple(None if v is None else format(v, "f") for v in (parsed.length_mm, parsed.width_mm, parsed.height_mm))
        assert got == lwh


def test_diameter_and_decimal_comma() -> None:
    dia = parse_dimension("Ø 300")
    assert dia is not None and dia.diameter_mm == Decimal("300.000")
    comma = parse_dimension("2,5 x 3")
    assert comma is not None and comma.length_mm == Decimal("2.500") and "DECIMAL_COMMA" in comma.warnings
    assert parse_dimension("   ") is None


def test_parse_length_keeps_the_source_text() -> None:
    assert parse_length("45 cm") == (Decimal("450.000"), "45 cm")
    assert parse_length(Decimal("18")) == (Decimal("18.000"), "18")


# ---- packaging aliases (legacy bug §10.1 #9) -----------------------------------------------------------
def test_alias_pairs_resolve_to_canonical_fields() -> None:
    result = resolve_packaging_aliases(
        {"master_carton_qty": "24.0", "inner_pack_qty": 6, "unit_weight_kg": "0.45", "unit_packing_type": "Poly bag"}
    )
    assert result.conflicts == () and result.errors == ()
    assert result.values == {"carton_qty": 24, "inner_qty": 6, "unit_weight_g": Decimal("450.000"), "packing_type": "Poly bag"}


def test_equal_aliases_are_accepted_with_provenance() -> None:
    result = resolve_packaging_aliases({"carton_qty": "24", "master_carton_qty": "24.0", "unit_weight_g": "450",
                                        "unit_weight_kg": "0.450", "packing_type": "poly  BAG", "unit_packing_type": "Poly bag"})
    assert result.conflicts == ()
    assert result.values["carton_qty"] == 24 and result.values["unit_weight_g"] == Decimal("450.000")
    assert result.provenance["carton_qty"] == {"carton_qty": "24", "master_carton_qty": "24.0"}


def test_disagreeing_aliases_are_conflicts_never_guesses() -> None:
    result = resolve_packaging_aliases({"carton_qty": "24", "master_carton_qty": "12", "unit_weight_g": "450",
                                        "unit_weight_kg": "0.5"})
    assert {c.field for c in result.conflicts} == {"carton_qty", "unit_weight_g"}
    assert "carton_qty" not in result.values and "unit_weight_g" not in result.values
    assert ALIAS_CONFLICT == "ALIAS_CONFLICT"
    assert resolve_packaging_aliases({"carton_qty": "24.5"}).errors == (("carton_qty", "NOT_INTEGER"),)


def test_cross_checks_only_warn() -> None:
    ok = packaging_cross_checks(
        carton_qty=24, inner_qty=6, carton_length_cm=Decimal(48), carton_width_cm=Decimal(33),
        carton_height_cm=Decimal(30), cbm=Decimal("0.047520"), net_weight_kg=Decimal("10.8"),
        gross_weight_kg=Decimal("11.6"),
    )
    assert ok == []
    bad = packaging_cross_checks(
        carton_qty=6, inner_qty=24, carton_length_cm=Decimal(48), carton_width_cm=Decimal(33),
        carton_height_cm=Decimal(30), cbm=Decimal("0.06"), net_weight_kg=Decimal("12"), gross_weight_kg=Decimal("11"),
    )
    assert bad == [CBM_MISMATCH, GROSS_BELOW_NET, INNER_EXCEEDS_CARTON]
