"""Pure normalisation for catalogue values (no I/O, exhaustively unit-tested).

- Identifiers (decor numbers, codes) are text: leading zeros are never touched; ``"0120"`` and ``"120"`` are
  different identifiers. The legacy float artefact ``"120.0"`` becomes ``"120"`` with a warning when the
  per-field rule is on (legacy bug §10.1 #5 used ``rstrip('.0')`` and corrupted ``"120.0"`` into ``"12"``).
- Thickness is a canonical millimetre Decimal, so ``0.8`` and ``0.80`` are the same value.
- Dimension strings are parsed into canonical millimetres while the original text is kept as provenance.
- Packaging alias pairs (``carton_qty``/``master_carton_qty`` ...) resolve to one canonical value; a
  disagreement is a conflict, never a guess (legacy bug §10.1 #9).

Fixed patterns are applied to user text; user text never becomes a regular expression.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

# ---- warning / error codes ------------------------------------------------------------------------
DECOR_FLOAT_ARTEFACT_NORMALISED = "DECOR_FLOAT_ARTEFACT_NORMALISED"
DECIMAL_COMMA = "DECIMAL_COMMA"
SINGLE_VALUE_AMBIGUOUS = "SINGLE_VALUE_AMBIGUOUS"
RANGE_NOT_SUPPORTED = "RANGE_NOT_SUPPORTED"
UNRECOGNISED_FORMAT = "UNRECOGNISED_FORMAT"
UNIT_INFERRED = "UNIT_INFERRED"
NOT_INTEGER = "NOT_INTEGER"
NOT_A_NUMBER = "NOT_A_NUMBER"
NOT_POSITIVE = "NOT_POSITIVE"
ALIAS_CONFLICT = "ALIAS_CONFLICT"
CBM_MISMATCH = "CBM_MISMATCH"
GROSS_BELOW_NET = "GROSS_BELOW_NET"
INNER_EXCEEDS_CARTON = "INNER_EXCEEDS_CARTON"

MM_PLACES = Decimal("0.001")
GRAM_PLACES = Decimal("0.001")
_FLOAT_ARTEFACT = re.compile(r"^(\d+)\.0+$")
#: millimetres per unit (exact Decimal factors)
UNIT_FACTORS: dict[str, Decimal] = {
    "mm": Decimal(1),
    "cm": Decimal(10),
    "m": Decimal(1000),
    "in": Decimal("25.4"),
    "ft": Decimal("304.8"),
}
_UNIT_ALIASES = {
    "mm": "mm", "millimetre": "mm", "millimetres": "mm", "millimeter": "mm", "millimeters": "mm",
    "cm": "cm", "centimetre": "cm", "centimetres": "cm", "centimeter": "cm", "centimeters": "cm",
    "m": "m", "metre": "m", "metres": "m", "meter": "m", "meters": "m",
    "in": "in", "inch": "in", "inches": "in", '"': "in",
    "ft": "ft", "foot": "ft", "feet": "ft", "'": "ft",
}
_NUM = r"(\d+(?:,\d+)*(?:\.\d+)?)"
_UNIT = r"(mm|millimetres?|millimeters?|cm|centimetres?|centimeters?|metres?|meters?|m|inches|inch|in|feet|foot|ft|\"|')?"
_PART = re.compile(rf"^{_NUM}\s*{_UNIT}$")
_DIAMETER_PREFIX = re.compile(rf"^(?:ø|⌀|dia(?:meter)?\.?)\s*{_NUM}\s*{_UNIT}$")
_DIAMETER_SUFFIX = re.compile(rf"^{_NUM}\s*{_UNIT}\s*(?:ø|⌀|dia(?:meter)?\.?)$")
_RANGE = re.compile(r"\d\s*(?:-|–|—|to)\s*\d")


# ---- identifiers -------------------------------------------------------------------------------------
@dataclass(frozen=True)
class IdentifierResult:
    value: str | None
    source: str | None  # the original text when normalisation changed it
    warnings: tuple[str, ...] = ()


def normalise_identifier(
    value: Any, *, float_artefact_rule: bool = False, zero_pad_width: int | None = None
) -> IdentifierResult:
    """Normalise a text identifier (decor number, code) without ever corrupting it.

    Strings keep leading zeros and are only trimmed. Integral numbers (spreadsheet numeric cells) become integer
    strings. ``float_artefact_rule`` strips a pure ``.0+`` suffix (``"120.0"`` -> ``"120"``) with a warning;
    ``"12.50"`` is unchanged. ``zero_pad_width`` is an explicit admin choice (never inferred).
    """
    if value is None:
        return IdentifierResult(None, None)
    if isinstance(value, bool):
        raise TypeError("booleans are not identifiers")
    warnings: list[str] = []
    original: str
    if isinstance(value, int):
        original = str(value)
        text = original
    elif isinstance(value, (Decimal, float)):
        number = Decimal(str(value)) if isinstance(value, float) else value
        if not number.is_finite():
            raise ValueError("identifier must be finite")
        original = str(value)
        text = str(int(number)) if number == number.to_integral_value() else format(number.normalize(), "f")
    elif isinstance(value, str):
        original = value
        text = value.strip()
    else:
        raise TypeError(f"unsupported identifier type {type(value).__name__}")
    if not text:
        return IdentifierResult(None, None)
    if float_artefact_rule:
        match = _FLOAT_ARTEFACT.match(text)
        if match:
            text = match.group(1)
            warnings.append(DECOR_FLOAT_ARTEFACT_NORMALISED)
    if zero_pad_width is not None and text.isdigit():
        text = text.zfill(zero_pad_width)
    source = original if original != text else None
    return IdentifierResult(text, source, tuple(warnings))


# ---- numbers -----------------------------------------------------------------------------------------
def _clean(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text).strip().lower()
    for ch in ("×", "✕", "✖", "*"):
        folded = folded.replace(ch, "x")
    return re.sub(r"\s+", " ", folded)


def _number(token: str, warnings: list[str]) -> Decimal | None:
    """Parse a number token with commas: groups of exactly 3 digits are thousands separators, a single comma
    followed by 1-2 digits is a decimal comma (warning); anything else is not recognised."""
    if "," in token:
        head, *groups = token.split(",")
        last = groups[-1]
        if all(len(g.split(".")[0]) == 3 for g in groups) and (len(groups) > 1 or "." in last or len(last) == 3):
            token = head + "".join(groups)
        elif len(groups) == 1 and 1 <= len(last) <= 2 and "." not in last and "." not in head:
            token = f"{head}.{last}"
            warnings.append(DECIMAL_COMMA)
        else:
            return None
    try:
        return Decimal(token)
    except InvalidOperation:
        return None


def _to_mm(number: Decimal, unit: str) -> Decimal:
    return (number * UNIT_FACTORS[unit]).quantize(MM_PLACES, rounding=ROUND_HALF_UP)


def _unit(token: str | None) -> str | None:
    return _UNIT_ALIASES.get(token) if token else None


@dataclass(frozen=True)
class ParsedDimension:
    status: str  # parsed | ambiguous | unparsed
    source_text: str
    length_mm: Decimal | None = None
    width_mm: Decimal | None = None
    height_mm: Decimal | None = None
    diameter_mm: Decimal | None = None
    source_unit: str | None = None
    unit_inferred: bool = False
    warnings: tuple[str, ...] = ()


def parse_dimension(text: str | None, default_unit: str = "mm") -> ParsedDimension | None:
    """Parse ``"450 x 300 mm"``, ``"30 x 20 cm"``, ``'12" x 8"'``, ``"2440*1220*18"``, ``"Ø 300"`` ...

    A single number is ambiguous for a size field; ranges (``"300-350"``) are unparsed. L and W order is
    preserved. Returns None for blank input.
    """
    if text is None:
        return None
    source = text.strip()
    if not source:
        return None
    if default_unit not in UNIT_FACTORS:
        raise ValueError(f"unknown default unit {default_unit}")
    t = _clean(source)
    warnings: list[str] = []
    if _RANGE.search(t):
        return ParsedDimension("unparsed", source, warnings=(RANGE_NOT_SUPPORTED,))

    for pattern in (_DIAMETER_PREFIX, _DIAMETER_SUFFIX):
        m = pattern.match(t)
        if m:
            number = _number(m.group(1), warnings)
            if number is None:
                return ParsedDimension("unparsed", source, warnings=(UNRECOGNISED_FORMAT,))
            unit = _unit(m.group(2))
            inferred = unit is None
            unit = unit or default_unit
            if inferred:
                warnings.append(UNIT_INFERRED)
            return ParsedDimension(
                "parsed", source, diameter_mm=_to_mm(number, unit), source_unit=unit,
                unit_inferred=inferred, warnings=tuple(warnings),
            )

    parts = [p.strip() for p in t.split("x")]
    if not 1 <= len(parts) <= 3 or any(not p for p in parts):
        return ParsedDimension("unparsed", source, warnings=(UNRECOGNISED_FORMAT,))
    parsed: list[tuple[Decimal, str | None]] = []
    for part in parts:
        m = _PART.match(part)
        if not m:
            return ParsedDimension("unparsed", source, warnings=(UNRECOGNISED_FORMAT,))
        number = _number(m.group(1), warnings)
        if number is None:
            return ParsedDimension("unparsed", source, warnings=(UNRECOGNISED_FORMAT,))
        parsed.append((number, _unit(m.group(2))))
    trailing = parsed[-1][1]
    explicit = [u for _, u in parsed if u]
    inferred = not explicit
    if inferred:
        warnings.append(UNIT_INFERRED)
    values = [_to_mm(n, u or trailing or default_unit) for n, u in parsed]
    unit_label = explicit[0] if explicit else default_unit
    if any(v <= 0 for v in values):
        return ParsedDimension("unparsed", source, warnings=(NOT_POSITIVE,))
    if len(values) == 1:
        return ParsedDimension(
            "ambiguous", source, length_mm=values[0], source_unit=unit_label, unit_inferred=inferred,
            warnings=(*warnings, SINGLE_VALUE_AMBIGUOUS),
        )
    return ParsedDimension(
        "parsed", source,
        length_mm=values[0], width_mm=values[1], height_mm=values[2] if len(values) == 3 else None,
        source_unit=unit_label, unit_inferred=inferred, warnings=tuple(warnings),
    )


def parse_length(value: Any, default_unit: str = "mm") -> tuple[Decimal, str]:
    """A single positive length in canonical mm plus the original text (``"450"``, ``"45 cm"``, ``Decimal(18)``)."""
    if isinstance(value, bool) or isinstance(value, float):
        raise TypeError("lengths are decimal strings, never floats")
    if isinstance(value, (int, Decimal)):
        number, unit, source = Decimal(value), default_unit, format(Decimal(value), "f")
        warnings: list[str] = []
    elif isinstance(value, str):
        source = value.strip()
        m = _PART.match(_clean(source))
        if not m:
            raise ValueError(NOT_A_NUMBER)
        warnings = []
        parsed = _number(m.group(1), warnings)
        if parsed is None:
            raise ValueError(NOT_A_NUMBER)
        number, unit = parsed, _unit(m.group(2)) or default_unit
    else:
        raise TypeError(f"unsupported length type {type(value).__name__}")
    if not number.is_finite() or number <= 0:
        raise ValueError(NOT_POSITIVE)
    return _to_mm(number, unit), source


def normalise_thickness(value: Any) -> Decimal | None:
    """Canonical thickness in mm (NUMERIC(8,3) scale): ``"0.8"``, ``"0.80"`` and ``Decimal("0.800")`` are equal."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    mm, _source = parse_length(value)
    return mm


def plain_decimal(value: Decimal) -> str:
    """Decimal as plain text without trailing zeros or exponent (``12.000`` -> ``"12"``, ``0.800`` -> ``"0.8"``)."""
    if value == value.to_integral_value():
        return format(value.quantize(Decimal(1)), "f")
    return format(value.normalize(), "f")


# ---- packaging aliases --------------------------------------------------------------------------------
@dataclass(frozen=True)
class AliasConflict:
    field: str
    values: dict[str, str]


@dataclass(frozen=True)
class PackagingResolution:
    values: dict[str, Any]
    provenance: dict[str, dict[str, str]] = field(default_factory=dict)
    conflicts: tuple[AliasConflict, ...] = ()
    errors: tuple[tuple[str, str], ...] = ()  # (field, code)


_ALIAS_PAIRS: tuple[tuple[str, str, str], ...] = (
    # canonical, alias, kind
    ("carton_qty", "master_carton_qty", "int"),
    ("inner_qty", "inner_pack_qty", "int"),
    ("packing_type", "unit_packing_type", "text"),
    ("unit_weight_g", "unit_weight_kg", "weight"),
)


def _as_text(value: Any) -> str:
    return value if isinstance(value, str) else format(value, "f") if isinstance(value, Decimal) else str(value)


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _as_int(value: Any) -> int:
    if isinstance(value, bool) or isinstance(value, float):
        raise TypeError("quantities are decimal strings or integers, never floats")
    try:
        number = Decimal(value.strip()) if isinstance(value, str) else Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(NOT_A_NUMBER) from exc
    if not number.is_finite() or number != number.to_integral_value():
        raise ValueError(NOT_INTEGER)
    if number <= 0:
        raise ValueError(NOT_POSITIVE)
    return int(number)


def _as_grams(value: Any, *, kilograms: bool) -> Decimal:
    if isinstance(value, bool) or isinstance(value, float):
        raise TypeError("weights are decimal strings, never floats")
    try:
        number = Decimal(value.strip()) if isinstance(value, str) else Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(NOT_A_NUMBER) from exc
    if not number.is_finite() or number <= 0:
        raise ValueError(NOT_POSITIVE)
    grams = number * 1000 if kilograms else number
    return grams.quantize(GRAM_PLACES, rounding=ROUND_HALF_UP)


def resolve_packaging_aliases(raw: Mapping[str, Any]) -> PackagingResolution:
    """Resolve each alias pair to its canonical field.

    One side present: used. Both present and equal after exact conversion (kg x 1000 = g at 0.001 g; integers
    "24" = "24.0"; packing types compared case- and whitespace-insensitively): accepted. Both present and
    different: an ``ALIAS_CONFLICT`` listing both raw values; nothing is guessed.
    """
    values: dict[str, Any] = {}
    provenance: dict[str, dict[str, str]] = {}
    conflicts: list[AliasConflict] = []
    errors: list[tuple[str, str]] = []
    for canonical, alias, kind in _ALIAS_PAIRS:
        raw_c, raw_a = raw.get(canonical), raw.get(alias)
        present = {k: v for k, v in ((canonical, raw_c), (alias, raw_a)) if not _blank(v)}
        if not present:
            continue
        converted: dict[str, Any] = {}
        for name, value in present.items():
            try:
                if kind == "int":
                    converted[name] = _as_int(value)
                elif kind == "weight":
                    converted[name] = _as_grams(value, kilograms=name == "unit_weight_kg")
                else:
                    converted[name] = " ".join(str(value).split())
            except ValueError as exc:
                errors.append((name, str(exc)))
        if len(converted) != len(present):
            continue
        distinct = {v.casefold() if isinstance(v, str) else v for v in converted.values()}
        if len(distinct) > 1:
            conflicts.append(AliasConflict(canonical, {k: _as_text(v) for k, v in present.items()}))
            continue
        winner = canonical if canonical in converted else alias
        values[canonical] = converted[winner]
        if alias in present:
            provenance[canonical] = {k: _as_text(v) for k, v in present.items()}
    return PackagingResolution(values, provenance, tuple(conflicts), tuple(errors))


def packaging_cross_checks(
    *,
    carton_qty: int | None,
    inner_qty: int | None,
    carton_length_cm: Decimal | None,
    carton_width_cm: Decimal | None,
    carton_height_cm: Decimal | None,
    cbm: Decimal | None,
    net_weight_kg: Decimal | None,
    gross_weight_kg: Decimal | None,
) -> list[str]:
    """Warnings only: CBM more than 2 % away from L x W x H / 1e6, gross below net, inner above carton."""
    warnings: list[str] = []
    if cbm is not None and carton_length_cm and carton_width_cm and carton_height_cm:
        computed = carton_length_cm * carton_width_cm * carton_height_cm / Decimal(1_000_000)
        if computed > 0 and abs(cbm - computed) / computed > Decimal("0.02"):
            warnings.append(CBM_MISMATCH)
    if net_weight_kg is not None and gross_weight_kg is not None and gross_weight_kg < net_weight_kg:
        warnings.append(GROSS_BELOW_NET)
    if inner_qty is not None and carton_qty is not None and inner_qty > carton_qty:
        warnings.append(INNER_EXCEEDS_CARTON)
    return warnings
