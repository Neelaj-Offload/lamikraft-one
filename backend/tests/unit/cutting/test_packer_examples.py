"""Worked examples of the packer: defaults, oversize, grouping on canonical keys, grain locks, unfit reasons,
bounded overproduction and the deterministic result hash (PARITY LM-72/73/77, BR-11, FG-GRN-01, LP-09.x)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.cutting.canonical import canonical_decor, thickness_key
from app.modules.cutting.packer.engine import (
    EXCEEDS_USABLE_BOARD,
    GRAIN_LOCK_PREVENTS_ROTATION,
    GUILLOTINE,
    MAX_BOARDS_LIMIT,
    WARN_BLANK_DECOR,
    WARN_OVERSIZE,
    ItemSpec,
    PackSettings,
    input_hash,
    pack,
)
from app.modules.cutting.packer.geometry import GeometryError, mm_to_dmm


def item(line: int, length_mm: str, width_mm: str, qty: int = 1, *, decor: str = "W-7", thickness: str = "18",
         rule: str = "inherit") -> ItemSpec:
    key, _w = canonical_decor(decor)
    return ItemSpec(line, f"SKU-{line}", key, thickness_key(thickness), mm_to_dmm(length_mm), mm_to_dmm(width_mm), qty, rule)


def test_defaults_and_oversize_effect() -> None:
    s = PackSettings()
    assert (s.board_length_dmm, s.board_width_dmm, s.margin_dmm, s.gap_dmm, s.oversize_dmm) == (24400, 12200, 50, 60, 100)
    assert (s.usable_length, s.usable_width) == (24300, 12100)
    assert not s.oversize_enabled and not s.overproduction_enabled
    # 2435 x 1215 is unfit with the defaults (usable 2430 x 1210) ...
    plain = pack([item(1, "2435", "1215")], s)
    out = plain.groups[0].items[0]
    assert (out.unfit, out.unfit_reason) == (1, EXCEEDS_USABLE_BOARD)
    assert not plain.requires_physical_verification
    # ... and fits on the oversize board (raw 2460 x 1240, usable 2450 x 1230), which must be verified physically
    big = PackSettings(oversize_enabled=True)
    assert (big.raw_length, big.raw_width, big.usable_length, big.usable_width) == (24600, 12400, 24500, 12300)
    over = pack([item(1, "2435", "1215")], big)
    assert over.groups[0].items[0].placed_required == 1
    assert over.requires_physical_verification
    assert WARN_OVERSIZE in over.groups[0].warnings
    assert over.groups[0].boards[0].raw_length == 24600


def test_oversize_never_flags_an_empty_result() -> None:
    result = pack([item(1, "9000", "100")], PackSettings(oversize_enabled=True))
    assert result.board_count == 0 and not result.requires_physical_verification


def test_grouping_decor_thickness() -> None:
    items = [item(1, "500", "400", decor="0120"), item(2, "500", "400", decor="120"), item(3, "500", "400", decor="120.0"),
             item(4, "500", "400", decor="120", thickness="0.8"), item(5, "500", "400", decor="120", thickness="0.80")]
    result = pack(items, PackSettings())
    groups = {(g.decor_key, g.thickness_key): sorted(i.line_no for i in g.items) for g in result.groups}
    # leading zeros keep '0120' distinct; '120.0' is the float artefact of '120'; 0.8 and 0.80 are one thickness
    assert groups == {("0120", "18"): [1], ("120", "18"): [2, 3], ("120", "0.8"): [4, 5]}
    assert canonical_decor("120.0") == ("120", ("DECOR_FLOAT_ARTEFACT_NORMALISED",))
    assert canonical_decor(" 0120 ") == ("0120", ())


def test_lock_on_120_blocks_rotation_of_120_0() -> None:
    # 1200 x 2400 fits the 2430 x 1210 usable area only when turned
    turned = item(1, "1200", "2400", decor="120.0")
    free = pack([turned], PackSettings())
    assert free.groups[0].boards[0].placements[0].rotated
    locked = pack([turned], PackSettings(grain_locked_decors=frozenset({"120"})))
    out = locked.groups[0].items[0]
    assert (out.unfit, out.unfit_reason, out.rotation_allowed) == (1, GRAIN_LOCK_PREVENTS_ROTATION, False)


def test_unfit_reasons() -> None:
    s = PackSettings()
    result = pack([item(1, "2500", "100"), item(2, "1200", "2400", rule="locked"), item(3, "1200", "2400", decor="")], s)
    reasons = {i.line_no: i.unfit_reason for g in result.groups for i in g.items}
    assert reasons == {1: EXCEEDS_USABLE_BOARD, 2: GRAIN_LOCK_PREVENTS_ROTATION, 3: GRAIN_LOCK_PREVENTS_ROTATION}
    blank = next(g for g in result.groups if g.decor_key == "")
    assert WARN_BLANK_DECOR in blank.warnings
    with pytest.raises(ValueError):
        ItemSpec(1, "Z", "W", "18", 0, 100, 1)
    with pytest.raises(GeometryError):
        mm_to_dmm("12.25")
    with pytest.raises(GeometryError):
        mm_to_dmm(12.5)  # type: ignore[arg-type]


def test_max_boards_limit_reason() -> None:
    result = pack([item(1, "2000", "1000", qty=3)], PackSettings(max_boards_per_group=2))
    out = result.groups[0].items[0]
    assert (out.placed_required, out.unfit, out.unfit_reason) == (2, 1, MAX_BOARDS_LIMIT)
    assert len(result.groups[0].boards) == 2


def test_overproduction_bounded() -> None:
    items = [item(1, "600", "400", qty=10), item(2, "300", "300", qty=7)]
    off = pack(items, PackSettings())
    assert all(i.extra == 0 for g in off.groups for i in g.items)
    on = pack(items, PackSettings(overproduction_enabled=True, max_extra_qty=5, max_extra_pct=Decimal("30")))
    assert on.board_count == off.board_count  # extras only go into boards that were already open
    for out in on.groups[0].items:
        cap = min(5, int(out.required * 30 // 100))
        assert 0 < out.extra <= cap
        assert out.produced == out.placed_required + out.extra
    extras = [p for b in on.groups[0].boards for p in b.placements if p.is_extra]
    assert len(extras) == sum(i.extra for i in on.groups[0].items)
    # enabled with zero bounds means no extras
    zero = pack(items, PackSettings(overproduction_enabled=True, max_extra_qty=0, max_extra_pct=Decimal("50")))
    assert all(i.extra == 0 for g in zero.groups for i in g.items)


def test_deterministic_result_hash() -> None:
    items = [item(n, str(300 + 37 * n), str(200 + 11 * n), qty=n % 4 + 1, decor=["A", "B"][n % 2]) for n in range(1, 12)]
    for mode in ("nested", GUILLOTINE):
        s = PackSettings(mode=mode)
        a, b = pack(items, s), pack(list(reversed(items)), s)
        assert a.result_hash == b.result_hash
        assert input_hash(items, s) == input_hash(list(reversed(items)), s)
    assert input_hash(items, PackSettings()) != input_hash(items, PackSettings(gap_dmm=40))


def test_guillotine_records_cut_tree() -> None:
    result = pack([item(1, "1000", "500", qty=4)], PackSettings(mode=GUILLOTINE))
    board = result.groups[0].boards[0]
    assert board.cuts and min(c.stage for c in board.cuts) == 1
    assert all(c.kerf == 60 for c in board.cuts)


def test_metrics_reported_in_exact_units() -> None:
    result = pack([item(1, "1000", "500", qty=2)], PackSettings())
    g = result.groups[0]
    assert g.placed_area == 2 * 10000 * 5000
    assert g.usable_area == 24300 * 12100 and g.raw_area == 24400 * 12200
    assert g.efficiency_usable_pct == Decimal("34.01")
    assert g.scrap_pct == Decimal("65.99")
    assert g.lower_bound_boards == 1
