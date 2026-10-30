"""Predicted offcuts are disjoint, inside the usable area and at least the gap away from every piece."""

from __future__ import annotations

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.modules.cutting.packer import checker
from app.modules.cutting.packer.engine import GUILLOTINE, NESTED, ItemSpec, PackSettings, pack
from app.modules.cutting.packer.remnants import predicted_offcuts


@settings(max_examples=40, derandomize=True, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    st.lists(st.tuples(st.integers(1000, 14000), st.integers(800, 9000), st.integers(1, 4)), min_size=1, max_size=5),
    st.sampled_from([NESTED, GUILLOTINE]),
    st.sampled_from([0, 60]),
)
def test_predicted_offcuts_disjoint_and_clear_of_pieces(dims: list[tuple[int, int, int]], mode: str, gap: int) -> None:
    items = [ItemSpec(n, f"S{n}", "D", "18", length, width, qty) for n, (length, width, qty) in enumerate(dims, start=1)]
    s = PackSettings(mode=mode, gap_dmm=gap)
    for board in (b for g in pack(items, s).groups for b in g.boards):
        offcuts = [(o.x, o.y, o.length, o.width) for o in board.offcuts]
        pieces = [(p.x, p.y, p.along_length, p.along_width) for p in board.placements]
        assert checker.no_overlap(offcuts)
        m = board.margin
        for o in offcuts:
            assert o[2] >= s.min_offcut_dmm and o[3] >= s.min_offcut_dmm
            assert o[0] >= m and o[1] >= m and o[0] + o[2] <= board.raw_length - m and o[1] + o[3] <= board.raw_width - m
            for p in pieces:
                assert checker.separated_by_gap(o, p, gap), (o, p)


def test_empty_board_is_one_offcut() -> None:
    assert predicted_offcuts([(0, 0, 24360, 12160)], 60, 3000) == [(0, 0, 24300, 12100)]
    assert predicted_offcuts([(0, 0, 3000, 9000)], 60, 3000) == []
