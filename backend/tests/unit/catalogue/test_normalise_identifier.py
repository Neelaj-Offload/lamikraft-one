"""Identifier normalisation (BUG-05, FG-PRD-09): decor numbers are text; "120.0" becomes "120" with a warning;
"0120" keeps its leading zero and stays distinct from "120" (legacy bug §10.1 #5: ``"120.0".rstrip(".0")`` -> "12")."""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.catalogue.normalise import DECOR_FLOAT_ARTEFACT_NORMALISED, normalise_identifier
from app.seed.world import keys


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
        (120, "120", False),  # integer spreadsheet cell
        (Decimal("120"), "120", False),
        (Decimal("120.0"), "120", True),  # numeric cells written as 120.0 carry the same warning
        (120.0, "120", True),
        (Decimal("12.5"), "12.5", False),
    ],
)
def test_normalise_identifier(raw: object, expected: str, warned: bool) -> None:
    result = normalise_identifier(raw, float_artefact_rule=True)
    assert result.value == expected
    assert (DECOR_FLOAT_ARTEFACT_NORMALISED in result.warnings) is warned
    assert result.warnings.count(DECOR_FLOAT_ARTEFACT_NORMALISED) <= 1


def test_120_0_becomes_120_and_0120_stays_distinct() -> None:
    a = normalise_identifier("0120", float_artefact_rule=True)
    b = normalise_identifier("120", float_artefact_rule=True)
    c = normalise_identifier("120.0", float_artefact_rule=True)
    assert a.value == "0120" and b.value == c.value == "120" and a.value != b.value
    assert c.warnings == (DECOR_FLOAT_ARTEFACT_NORMALISED,) and c.source == "120.0"
    assert a.warnings == b.warnings == ()
    numeric = normalise_identifier(120.0)  # a numeric cell is normalised (and flagged) even without the text rule
    assert numeric.value == "120" and numeric.warnings == (DECOR_FLOAT_ARTEFACT_NORMALISED,)


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
