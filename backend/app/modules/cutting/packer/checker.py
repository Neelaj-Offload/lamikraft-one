"""Independent layout checks (used by property tests and as a guard after every calculation).

They share nothing with the packers except the rectangle tuple: ``no_overlap`` and ``within`` are brute force,
``is_guillotine`` searches for an edge-to-edge cut recursively, and ``cuts_partition`` replays a recorded cut tree.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.modules.cutting.packer.geometry import Rect, intersects


def no_overlap(rects: Sequence[Rect]) -> bool:
    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            if intersects(rects[i], rects[j]):
                return False
    return True


def within(rects: Sequence[Rect], width: int, height: int) -> bool:
    return all(r[0] >= 0 and r[1] >= 0 and r[0] + r[2] <= width and r[1] + r[3] <= height for r in rects)


def separated_by_gap(a: Rect, b: Rect, gap: int) -> bool:
    """Real pieces ``a`` and ``b`` are at least ``gap`` apart along some axis."""
    return (
        a[0] + a[2] + gap <= b[0]
        or b[0] + b[2] + gap <= a[0]
        or a[1] + a[3] + gap <= b[1]
        or b[1] + b[3] + gap <= a[1]
    )


def is_guillotine(rects: Sequence[Rect], region: Rect) -> bool:
    """Whether ``rects`` (disjoint, inside ``region``) can be separated by recursive edge-to-edge cuts."""
    items = [r for r in rects]
    if len(items) <= 1:
        return True
    x, y, w, h = region
    # vertical lines: candidate x positions are rectangle edges strictly inside the region
    for pos in sorted({r[0] for r in items} | {r[0] + r[2] for r in items}):
        if not (x < pos < x + w):
            continue
        if any(r[0] < pos < r[0] + r[2] for r in items):
            continue
        left = [r for r in items if r[0] + r[2] <= pos]
        right = [r for r in items if r[0] >= pos]
        if left and right:
            return is_guillotine(left, (x, y, pos - x, h)) and is_guillotine(right, (pos, y, x + w - pos, h))
    for pos in sorted({r[1] for r in items} | {r[1] + r[3] for r in items}):
        if not (y < pos < y + h):
            continue
        if any(r[1] < pos < r[1] + r[3] for r in items):
            continue
        top = [r for r in items if r[1] + r[3] <= pos]
        bottom = [r for r in items if r[1] >= pos]
        if top and bottom:
            return is_guillotine(top, (x, y, w, pos - y)) and is_guillotine(bottom, (x, pos, w, y + h - pos))
    return False


def cuts_partition(
    rects: Sequence[Rect], region: Rect, cuts: Sequence[tuple[int, str, int, int, int]]
) -> bool:
    """Replay ``cuts`` ``(stage, orientation, position, start, end)`` in stage order: each must divide exactly one
    current region edge to edge without crossing a piece, and at the end no region may hold two pieces."""
    regions: list[Rect] = [region]
    for _stage, orientation, pos, start, end in sorted(cuts, key=lambda c: c[0]):
        hit = None
        for index, (rx, ry, rw, rh) in enumerate(regions):
            if orientation == "vertical" and rx < pos < rx + rw and start == ry and end == ry + rh:
                hit = index
                break
            if orientation == "horizontal" and ry < pos < ry + rh and start == rx and end == rx + rw:
                hit = index
                break
        if hit is None:
            return False
        rx, ry, rw, rh = regions.pop(hit)
        if orientation == "vertical":
            if any(r[0] < pos < r[0] + r[2] and r[1] < ry + rh and ry < r[1] + r[3] for r in rects):
                return False
            regions += [(rx, ry, pos - rx, rh), (pos, ry, rx + rw - pos, rh)]
        else:
            if any(r[1] < pos < r[1] + r[3] and r[0] < rx + rw and rx < r[0] + r[2] for r in rects):
                return False
            regions += [(rx, ry, rw, pos - ry), (rx, pos, rw, ry + rh - pos)]
    for reg in regions:
        inside = [r for r in rects if intersects(r, reg)]
        if len(inside) > 1:
            return False
        if inside and not (
            reg[0] <= inside[0][0]
            and reg[1] <= inside[0][1]
            and inside[0][0] + inside[0][2] <= reg[0] + reg[2]
            and inside[0][1] + inside[0][3] <= reg[1] + reg[3]
        ):
            return False
    return True
