"""Predicted offcuts: reusable remnants a board is expected to leave (they become stock only when measured, S4/S5).

1. Choose disjoint free rectangles greedily, largest first, subtracting each choice from the rest.
2. Convert from inflated to real coordinates: shrink the right and bottom edges by the gap. A right/bottom edge is
   either the inflated left/top edge of a piece (which needs the kerf) or the inflated bin edge (``usable + gap``,
   which clips to the usable area), so the shrink is exact in both cases.
3. Keep those at least ``min_size`` x ``min_size``.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.modules.cutting.packer.geometry import Rect, area, subtract

#: hard cap per board (keeps the greedy loop bounded on fragmented boards)
MAX_OFFCUTS_PER_BOARD = 24


def predicted_offcuts(free: Sequence[Rect], gap: int, min_size: int) -> list[Rect]:
    """Disjoint real-coordinate offcuts (usable-area origin), largest first, ties by position."""

    def qualifies(r: Rect) -> bool:
        return r[2] - gap >= min_size and r[3] - gap >= min_size

    def order(r: Rect) -> tuple[int, int, int, int, int]:
        return (-area(r), r[1], r[0], r[2], r[3])

    pool = sorted((r for r in free if qualifies(r)), key=order)
    chosen: list[Rect] = []
    while pool and len(chosen) < MAX_OFFCUTS_PER_BOARD:
        best = pool.pop(0)
        chosen.append(best)
        rest: list[Rect] = []
        for r in pool:
            rest.extend(p for p in subtract(r, best) if qualifies(p))
        pool = sorted(set(rest), key=order)
    return [(x, y, w - gap, h - gap) for x, y, w, h in chosen]
