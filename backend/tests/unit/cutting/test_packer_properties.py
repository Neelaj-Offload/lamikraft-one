"""Scenario H invariants of the packer, as hypothesis properties (derandomized, both modes, oversize on and off).

Every layout is checked with the independent checker: real pieces never overlap and are at least the gap apart,
lie inside the usable area of their board, grain-locked pieces are never rotated, guillotine layouts are separable
by edge-to-edge cuts and the recorded cut tree reproduces the partition; counts and areas reconcile exactly.
"""

from __future__ import annotations

from decimal import Decimal

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.modules.cutting.packer import checker
from app.modules.cutting.packer.engine import (
    GUILLOTINE,
    NESTED,
    BoardOut,
    ItemSpec,
    PackResult,
    PackSettings,
    pack,
)

PROPS = settings(max_examples=40, derandomize=True, deadline=None, suppress_health_check=[HealthCheck.too_slow])

DECORS = ["120", "0120", "", "W-7", "OAK"]


@st.composite
def item_lists(draw: st.DrawFn) -> list[ItemSpec]:
    n = draw(st.integers(min_value=1, max_value=6))
    items = []
    for line in range(1, n + 1):
        items.append(
            ItemSpec(
                line_no=line,
                sku=f"SKU-{line}",
                decor_key=draw(st.sampled_from(DECORS)),
                thickness_key=draw(st.sampled_from(["18", "0.8"])),
                # some pieces exceed the board on purpose (unfit), most fit
                length_dmm=draw(st.integers(min_value=50, max_value=25000)),
                width_dmm=draw(st.integers(min_value=50, max_value=13000)),
                quantity=draw(st.integers(min_value=1, max_value=6)),
                grain_rule=draw(st.sampled_from(["inherit", "locked", "free"])),
            )
        )
    return items


@st.composite
def pack_settings(draw: st.DrawFn) -> PackSettings:
    return PackSettings(
        mode=draw(st.sampled_from([NESTED, GUILLOTINE])),
        oversize_enabled=draw(st.booleans()),
        gap_dmm=draw(st.sampled_from([0, 30, 60])),
        margin_dmm=draw(st.sampled_from([0, 50, 100])),
        overproduction_enabled=draw(st.booleans()),
        max_extra_qty=draw(st.integers(min_value=0, max_value=3)),
        max_extra_pct=Decimal(draw(st.sampled_from(["0", "25", "50", "100"]))),
        grain_locked_decors=frozenset(draw(st.sets(st.sampled_from(DECORS), max_size=2))),
    )


def _real(board: BoardOut) -> list[tuple[int, int, int, int]]:
    return [(p.x, p.y, p.along_length, p.along_width) for p in board.placements]


def _boards(result: PackResult) -> list[BoardOut]:
    return [b for g in result.groups for b in g.boards]


@PROPS
@given(item_lists(), pack_settings())
def test_no_overlap_with_gap(items: list[ItemSpec], s: PackSettings) -> None:
    result = pack(items, s)
    for board in _boards(result):
        rects = _real(board)
        assert checker.no_overlap(rects)
        for i in range(len(rects)):
            for j in range(i + 1, len(rects)):
                assert checker.separated_by_gap(rects[i], rects[j], s.gap_dmm), (rects[i], rects[j])


@PROPS
@given(item_lists(), pack_settings())
def test_within_usable_bounds(items: list[ItemSpec], s: PackSettings) -> None:
    result = pack(items, s)
    for board in _boards(result):
        m = board.margin
        for x, y, length, width in _real(board):
            assert m <= x and m <= y
            assert x + length <= board.raw_length - m and y + width <= board.raw_width - m
        assert board.raw_length == s.board_length_dmm + (2 * s.oversize_dmm if s.oversize_enabled else 0)


@PROPS
@given(item_lists(), pack_settings())
def test_grain_locked_never_rotated(items: list[ItemSpec], s: PackSettings) -> None:
    result = pack(items, s)
    by_line = {i.line_no: i for i in items}
    for board in _boards(result):
        for p in board.placements:
            item = by_line[p.line_no]
            locked = item.decor_key == "" or item.decor_key in s.grain_locked_decors or item.grain_rule == "locked"
            if locked:
                assert not p.rotated
                assert (p.along_length, p.along_width) == (item.length_dmm, item.width_dmm)
            else:
                expected = (item.width_dmm, item.length_dmm) if p.rotated else (item.length_dmm, item.width_dmm)
                assert (p.along_length, p.along_width) == expected


@PROPS
@given(item_lists(), pack_settings())
def test_guillotine_mode_is_guillotine_separable(items: list[ItemSpec], s: PackSettings) -> None:
    gs = PackSettings(**{**s.__dict__, "mode": GUILLOTINE})
    result = pack(items, gs)
    g, m = gs.gap_dmm, gs.margin_dmm
    for board in _boards(result):
        inflated = [(x - m, y - m, length + g, width + g) for x, y, length, width in _real(board)]
        region = (0, 0, board.usable_length + g, board.usable_width + g)
        assert checker.no_overlap(inflated)
        assert checker.within(inflated, region[2], region[3])
        assert checker.is_guillotine(inflated, region)
        cuts = [(c.stage, c.orientation, c.kerf_start - m + g, c.extent_start - m, c.extent_end - m + g) for c in board.cuts]
        assert checker.cuts_partition(inflated, region, cuts)
        assert all(c.kerf == g for c in board.cuts)


@PROPS
@given(item_lists(), pack_settings())
def test_counts_reconcile(items: list[ItemSpec], s: PackSettings) -> None:
    result = pack(items, s)
    lines = {i.line_no for i in items}
    seen: set[int] = set()
    for group in result.groups:
        for out in group.items:
            seen.add(out.line_no)
            assert out.required == out.placed_required + out.unfit
            assert out.produced == out.placed_required + out.extra
            assert (out.unfit_reason is None) == (out.unfit == 0)
            if not s.overproduction_enabled:
                assert out.extra == 0
            placed = [p for b in group.boards for p in b.placements if p.line_no == out.line_no]
            assert sum(1 for p in placed if not p.is_extra) == out.placed_required
            assert sum(1 for p in placed if p.is_extra) == out.extra
    assert seen == lines
    totals = result.totals()
    assert totals["required"] == sum(i.quantity for i in items)
    assert totals["required"] == totals["placed_required"] + totals["unfit"]
    assert totals["produced"] == totals["placed_required"] + totals["extra"]


@PROPS
@given(item_lists(), pack_settings())
def test_area_identity_exact(items: list[ItemSpec], s: PackSettings) -> None:
    result = pack(items, s)
    for group in result.groups:
        assert group.raw_area == group.placed_area + group.scrap_area + group.trim_area
        assert group.usable_area == group.placed_area + group.scrap_area
        assert group.placed_area == sum(p.along_length * p.along_width for b in group.boards for p in b.placements)
        if group.usable_area:
            assert group.scrap_pct == Decimal("100.00") - group.efficiency_usable_pct
        assert group.lower_bound_boards <= len(group.boards)
    totals = result.totals()
    assert totals["raw_area"] == totals["placed_area"] + totals["scrap_area"] + totals["trim_area"]


@PROPS
@given(item_lists(), pack_settings())
def test_deterministic_for_identical_input(items: list[ItemSpec], s: PackSettings) -> None:
    first, second = pack(items, s), pack(list(items), s)
    assert first == second
    assert first.result_hash == second.result_hash
