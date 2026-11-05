"""Offcut reuse in the packer (Slice 5): measured offcut boards are filled before standard boards are opened.

Examples pin the behaviour (offcuts first, only used offcuts reported, no margin on an offcut, other groups' offcuts
ignored, standard-board selection and lower bound), and hypothesis properties check that layouts on offcut boards keep
the Scenario H invariants (no overlap, gap, bounds, grain locks, counts, exact areas, determinism).
"""

from __future__ import annotations

from decimal import Decimal

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.modules.cutting.packer import checker
from app.modules.cutting.packer.engine import (
    GUILLOTINE,
    NESTED,
    ItemSpec,
    PackSettings,
    StockBoard,
    input_hash,
    pack,
)

PROPS = settings(max_examples=40, derandomize=True, deadline=None, suppress_health_check=[HealthCheck.too_slow])


def _item(line: int, length: int, width: int, qty: int, decor: str = "0457", grain: str = "inherit") -> ItemSpec:
    return ItemSpec(line_no=line, sku=f"P-{line}", decor_key=decor, thickness_key="18", length_dmm=length, width_dmm=width,
                    quantity=qty, grain_rule=grain)


def _offcut(ref: str, length: int, width: int, decor: str = "0457", thickness: str = "18") -> StockBoard:
    return StockBoard(ref=ref, decor_key=decor, thickness_key=thickness, length_dmm=length, width_dmm=width)


def test_offcuts_are_filled_before_a_standard_board_is_opened() -> None:
    items = [_item(1, 7000, 5000, 2)]
    plain = pack(items, PackSettings())
    with_offcut = pack(items, PackSettings(), [_offcut("lot-a", 15000, 6000)])
    assert [b.source for g in plain.groups for b in g.boards] == ["standard"]
    boards = with_offcut.groups[0].boards
    assert [(b.source, b.stock_ref) for b in boards] == [("offcut", "lot-a")]
    board = boards[0]
    assert board.margin == 0 and (board.raw_length, board.raw_width) == (15000, 6000)
    assert (board.usable_length, board.usable_width) == (15000, 6000)
    assert len(board.placements) == 2
    group = with_offcut.groups[0]
    assert group.trim_area == 0 and group.raw_area == group.placed_area + group.scrap_area
    assert group.lower_bound_boards == 0  # the offcut's capacity covers the pieces


def test_unused_offcuts_are_not_reported_and_overflow_opens_a_standard_board() -> None:
    items = [_item(1, 20000, 10000, 1), _item(2, 3000, 2000, 1)]
    result = pack(items, PackSettings(), [_offcut("small", 3500, 2500), _offcut("unused", 1000, 1000)])
    sources = [(b.board_no, b.source, b.stock_ref) for b in result.groups[0].boards]
    assert sources == [(1, "offcut", "small"), (2, "standard", None)]
    assert result.board_count == 2
    assert result.groups[0].items[0].placed_required == 1 and result.groups[0].items[1].placed_required == 1


def test_offcuts_of_another_decor_or_thickness_are_ignored() -> None:
    items = [_item(1, 3000, 2000, 1)]
    result = pack(items, PackSettings(), [_offcut("oak", 5000, 5000, decor="0120"), _offcut("thin", 5000, 5000, thickness="9")])
    assert [b.source for b in result.groups[0].boards] == ["standard"]


def test_grain_locked_pieces_keep_their_orientation_on_an_offcut() -> None:
    # 4000 x 2000 locked: fits the 4500 x 2500 offcut straight, never turned onto the 2500 x 4500 one
    items = [_item(1, 4000, 2000, 1, grain="locked")]
    turned = pack(items, PackSettings(), [_offcut("turned", 2500, 4500)])
    assert [b.source for b in turned.groups[0].boards] == ["standard"]
    straight = pack(items, PackSettings(), [_offcut("straight", 4500, 2500)])
    placement = straight.groups[0].boards[0].placements[0]
    assert straight.groups[0].boards[0].source == "offcut" and not placement.rotated


def test_stock_changes_the_hashes_and_oversize_never_applies_to_offcuts() -> None:
    items = [_item(1, 3000, 2000, 2)]
    ps = PackSettings(oversize_enabled=True)
    stock = [_offcut("lot-a", 8000, 3000)]
    a, b = pack(items, ps), pack(items, ps, stock)
    assert a.result_hash != b.result_hash
    assert input_hash(items, ps) != input_hash(items, ps, stock)
    assert a.requires_physical_verification is True
    assert b.requires_physical_verification is False  # only measured offcuts were used
    assert pack(items, ps, stock) == b


def test_duplicate_stock_references_are_rejected() -> None:
    try:
        pack([_item(1, 1000, 1000, 1)], PackSettings(), [_offcut("x", 2000, 2000), _offcut("x", 3000, 3000)])
    except ValueError as exc:
        assert "unique" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("duplicate stock refs accepted")


@st.composite
def cases(draw: st.DrawFn) -> tuple[list[ItemSpec], PackSettings, list[StockBoard]]:
    n = draw(st.integers(min_value=1, max_value=5))
    items = [
        ItemSpec(line_no=i, sku=f"S-{i}", decor_key=draw(st.sampled_from(["0457", "0120"])), thickness_key="18",
                 length_dmm=draw(st.integers(min_value=300, max_value=12000)),
                 width_dmm=draw(st.integers(min_value=300, max_value=6000)),
                 quantity=draw(st.integers(min_value=1, max_value=5)),
                 grain_rule=draw(st.sampled_from(["inherit", "locked", "free"])))
        for i in range(1, n + 1)
    ]
    stock = [
        StockBoard(ref=f"lot-{i}", decor_key=draw(st.sampled_from(["0457", "0120"])), thickness_key="18",
                   length_dmm=draw(st.integers(min_value=500, max_value=15000)),
                   width_dmm=draw(st.integers(min_value=500, max_value=8000)))
        for i in range(draw(st.integers(min_value=0, max_value=4)))
    ]
    ps = PackSettings(
        mode=draw(st.sampled_from([NESTED, GUILLOTINE])),
        gap_dmm=draw(st.sampled_from([0, 30, 60])),
        margin_dmm=draw(st.sampled_from([0, 50])),
        overproduction_enabled=draw(st.booleans()),
        max_extra_qty=2,
        max_extra_pct=Decimal("100"),
        grain_locked_decors=frozenset(draw(st.sets(st.sampled_from(["0457", "0120"]), max_size=1))),
    )
    return items, ps, stock


@PROPS
@given(cases())
def test_layouts_on_offcuts_keep_the_invariants(case: tuple[list[ItemSpec], PackSettings, list[StockBoard]]) -> None:
    items, ps, stock = case
    result = pack(items, ps, stock)
    by_ref = {sb.ref: sb for sb in stock}
    by_line = {i.line_no: i for i in items}
    for group in result.groups:
        assert group.raw_area == group.placed_area + group.scrap_area + group.trim_area
        standard = [b for b in group.boards if b.source == "standard"]
        assert group.lower_bound_boards <= len(standard)
        seen_refs = [b.stock_ref for b in group.boards if b.source == "offcut"]
        assert len(seen_refs) == len(set(seen_refs))
        for board in group.boards:
            rects = [(p.x, p.y, p.along_length, p.along_width) for p in board.placements]
            assert checker.no_overlap(rects)
            for i in range(len(rects)):
                for j in range(i + 1, len(rects)):
                    assert checker.separated_by_gap(rects[i], rects[j], ps.gap_dmm)
            m = board.margin
            for x, y, length, width in rects:
                assert m <= x and m <= y and x + length <= board.raw_length - m and y + width <= board.raw_width - m
            if board.source == "offcut":
                sb = by_ref[board.stock_ref]  # type: ignore[index]
                assert (sb.decor_key, sb.thickness_key) == (group.decor_key, group.thickness_key)
                assert (board.raw_length, board.raw_width, m) == (sb.length_dmm, sb.width_dmm, 0)
                assert board.placements  # unused offcuts are never reported
            for p in board.placements:
                item = by_line[p.line_no]
                if item.grain_rule == "locked" or item.decor_key in ps.grain_locked_decors:
                    assert not p.rotated
        for out in group.items:
            assert out.required == out.placed_required + out.unfit
    assert pack(items, ps, list(stock)).result_hash == result.result_hash
