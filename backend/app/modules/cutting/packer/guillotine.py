"""Guillotine bin (panel-saw mode) that records its cut tree.

Free space is a set of disjoint rectangles. A piece is placed at the top-left corner of a free rectangle ``f`` and
``f`` is split by the Shorter-Leftover-Axis rule: when the leftover width is smaller than the leftover height the
first cut runs horizontally across the whole of ``f`` and the second one vertically inside the strip that holds the
piece; otherwise vertical first. Every cut is edge-to-edge of the rectangle it divides, so the layout is guillotine
by construction (``checker.is_guillotine`` verifies it independently). Free rectangles are never merged, which keeps
the recorded tree valid.

Cuts are recorded in inflated bin coordinates: ``position`` is the line between the two parts (the kerf occupies
``[position - gap, position)`` in real coordinates), ``start``/``end`` the extent along the other axis.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from app.modules.cutting.packer.geometry import Rect

HORIZONTAL = "horizontal"  # a cut along the board length (constant y)
VERTICAL = "vertical"  # a cut across the board (constant x)


@dataclass(frozen=True, slots=True)
class RawCut:
    stage: int
    orientation: str
    position: int
    start: int
    end: int


class GuillotineBin:
    __slots__ = ("cuts", "depth", "free", "height", "used", "width")

    def __init__(self, width: int, height: int) -> None:
        if width <= 0 or height <= 0:
            raise ValueError("bin dimensions must be positive")
        self.width = width
        self.height = height
        self.free: list[Rect] = [(0, 0, width, height)]
        #: tree depth of each free rectangle (the stage of the cut that created it; 0 for the whole bin)
        self.depth: list[int] = [0]
        self.used: list[Rect] = []
        self.cuts: list[RawCut] = []

    def candidates(self, w: int, h: int) -> Iterator[tuple[int, Rect]]:
        for index, f in enumerate(self.free):
            if w <= f[2] and h <= f[3]:
                yield index, f

    def place(self, index: int, w: int, h: int) -> Rect:
        fx, fy, fw, fh = self.free[index]
        if w > fw or h > fh:
            raise ValueError("piece does not fit the chosen free rectangle")
        d = self.depth[index]
        del self.free[index]
        del self.depth[index]
        placed: Rect = (fx, fy, w, h)
        self.used.append(placed)
        dw, dh = fw - w, fh - h
        new: list[tuple[Rect, int]] = []
        if dw < dh:
            # cut 1: horizontal across the whole of f at the piece's lower edge; cut 2: vertical inside the strip
            if dh > 0:
                self.cuts.append(RawCut(d + 1, HORIZONTAL, fy + h, fx, fx + fw))
                new.append(((fx, fy + h, fw, dh), d + 1))
            if dw > 0:
                self.cuts.append(RawCut(d + 2, VERTICAL, fx + w, fy, fy + h))
                new.append(((fx + w, fy, dw, h), d + 2))
        else:
            # cut 1: vertical across the whole of f at the piece's right edge; cut 2: horizontal inside the strip
            if dw > 0:
                self.cuts.append(RawCut(d + 1, VERTICAL, fx + w, fy, fy + fh))
                new.append(((fx + w, fy, dw, fh), d + 1))
            if dh > 0:
                self.cuts.append(RawCut(d + 2, HORIZONTAL, fy + h, fx, fx + w))
                new.append(((fx, fy + h, w, dh), d + 2))
        for rect, depth in new:
            self.free.append(rect)
            self.depth.append(depth)
        return placed

    def free_rects(self) -> list[Rect]:
        return list(self.free)
