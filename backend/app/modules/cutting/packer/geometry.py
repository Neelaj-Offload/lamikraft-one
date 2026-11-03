"""Integer rectangle geometry for the packer (deci-millimetres, no floats, no I/O).

A rectangle is the tuple ``(x, y, w, h)``: origin at the top-left, x along the board length (the grain), y along its
width, growing downwards. Rectangles are half-open (``[x, x + w) x [y, y + h)``), so two rectangles that only share
an edge do not overlap.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

Rect = tuple[int, int, int, int]

#: deci-millimetres per millimetre
DMM_PER_MM = 10


class GeometryError(ValueError):
    """An input dimension that the packer cannot represent exactly."""


def mm_to_dmm(value: Decimal | int | str) -> int:
    """Millimetres with at most one decimal place as integer deci-millimetres (``"2440"`` -> 24400, ``"0.5"`` -> 5).

    More than one decimal place, a non-finite or a float input is rejected: the packer never rounds a dimension.
    """
    if isinstance(value, float | bool):
        raise GeometryError("dimensions must be Decimal or text, never float")
    try:
        number = Decimal(value) if not isinstance(value, Decimal) else value
    except (InvalidOperation, ValueError) as exc:
        raise GeometryError(f"not a number: {value!r}") from exc
    if not number.is_finite():
        raise GeometryError("dimension must be finite")
    scaled = number * DMM_PER_MM
    if scaled != scaled.to_integral_value():
        raise GeometryError("dimensions allow at most one decimal place in millimetres")
    return int(scaled)


def dmm_to_mm(value: int) -> Decimal:
    """Integer deci-millimetres as an exact millimetre Decimal with one place (24400 -> Decimal('2440.0'))."""
    return (Decimal(value) / DMM_PER_MM).quantize(Decimal("0.1"))


def area_mm2(value_dmm2: int) -> Decimal:
    """An area in dmm² as exact mm² with two places (1 mm² = 100 dmm²)."""
    return (Decimal(value_dmm2) / 100).quantize(Decimal("0.01"))


def percent(part: int, whole: int) -> Decimal:
    """``part / whole`` in percent, two places, half-up; 0.00 when ``whole`` is zero."""
    if whole <= 0:
        return Decimal("0.00")
    return (Decimal(part) * 100 / Decimal(whole)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def area(r: Rect) -> int:
    return r[2] * r[3]


def intersects(a: Rect, b: Rect) -> bool:
    return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]


def contains(outer: Rect, inner: Rect) -> bool:
    return (
        outer[0] <= inner[0]
        and outer[1] <= inner[1]
        and inner[0] + inner[2] <= outer[0] + outer[2]
        and inner[1] + inner[3] <= outer[1] + outer[3]
    )


def subtract(r: Rect, cut: Rect) -> list[Rect]:
    """``r`` minus ``cut`` as up to four disjoint rectangles (left and right full height, top and bottom between)."""
    if not intersects(r, cut):
        return [r]
    x, y, w, h = r
    cx, cy, cw, ch = cut
    out: list[Rect] = []
    left_end = max(x, cx)
    right_start = min(x + w, cx + cw)
    if cx > x:
        out.append((x, y, cx - x, h))
    if cx + cw < x + w:
        out.append((cx + cw, y, x + w - (cx + cw), h))
    if cy > y:
        out.append((left_end, y, right_start - left_end, cy - y))
    if cy + ch < y + h:
        out.append((left_end, cy + ch, right_start - left_end, y + h - (cy + ch)))
    return [o for o in out if o[2] > 0 and o[3] > 0]
