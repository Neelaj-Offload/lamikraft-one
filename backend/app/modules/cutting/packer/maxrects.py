"""MaxRects bin (nested mode): a list of maximal free rectangles with splitting and pruning.

Placing rectangle ``r`` replaces every free rectangle that intersects it by up to four maximal sub-rectangles (left,
right, top, bottom) and then prunes every free rectangle contained in another (for exact duplicates the first in
deterministic order is kept). Invariant: every free rectangle is disjoint from every placed rectangle.

This fixes legacy bug §10.1 #11 (BUG-11): the old "MaxRects" split guillotine-style and never pruned.
"""

from __future__ import annotations

from collections.abc import Iterator

from app.modules.cutting.packer.geometry import Rect, contains, intersects


class MaxRectsBin:
    __slots__ = ("free", "height", "used", "width")

    def __init__(self, width: int, height: int) -> None:
        if width <= 0 or height <= 0:
            raise ValueError("bin dimensions must be positive")
        self.width = width
        self.height = height
        self.free: list[Rect] = [(0, 0, width, height)]
        self.used: list[Rect] = []

    def candidates(self, w: int, h: int) -> Iterator[tuple[int, Rect]]:
        """``(index, free rectangle)`` for every free rectangle that can hold a ``w`` x ``h`` piece at its corner."""
        for index, f in enumerate(self.free):
            if w <= f[2] and h <= f[3]:
                yield index, f

    def place(self, index: int, w: int, h: int) -> Rect:
        """Place a ``w`` x ``h`` piece at the top-left corner of free rectangle ``index``."""
        fx, fy, fw, fh = self.free[index]
        if w > fw or h > fh:
            raise ValueError("piece does not fit the chosen free rectangle")
        placed: Rect = (fx, fy, w, h)
        self.used.append(placed)
        split: list[Rect] = []
        for f in self.free:
            if not intersects(f, placed):
                split.append(f)
                continue
            split.extend(_split(f, placed))
        self.free = _prune(split)
        return placed

    def free_rects(self) -> list[Rect]:
        return list(self.free)


def _split(f: Rect, r: Rect) -> list[Rect]:
    """The maximal parts of ``f`` outside ``r`` (each spans ``f`` fully along one axis)."""
    fx, fy, fw, fh = f
    rx, ry, rw, rh = r
    out: list[Rect] = []
    if rx > fx:
        out.append((fx, fy, rx - fx, fh))
    if rx + rw < fx + fw:
        out.append((rx + rw, fy, fx + fw - (rx + rw), fh))
    if ry > fy:
        out.append((fx, fy, fw, ry - fy))
    if ry + rh < fy + fh:
        out.append((fx, ry + rh, fw, fy + fh - (ry + rh)))
    return out


def _prune(rects: list[Rect]) -> list[Rect]:
    """Drop every rectangle contained in another; of exact duplicates keep the first (stable order)."""
    keep: list[Rect] = []
    n = len(rects)
    for i in range(n):
        a = rects[i]
        redundant = False
        for j in range(n):
            if i == j:
                continue
            b = rects[j]
            if contains(b, a) and (a != b or j < i):
                redundant = True
                break
        if not redundant:
            keep.append(a)
    return keep
