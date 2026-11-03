"""The sheet-packing engine: groups, pre-checks, deterministic multi-start, bounded overproduction and metrics.

Pure Python, integer deci-millimetres, no I/O and no clock: identical input gives an identical result (and
``result_hash``). The service layer canonicalises decors and thicknesses and converts millimetres before calling
``pack``.

Kerf/gap model: every piece is inflated to ``(l + g, w + g)`` and the bin to ``(U_L + g, U_W + g)`` where ``U`` is
the usable area ``raw - 2 * margin``. Non-overlapping inflated rectangles therefore keep real pieces at least ``g``
apart and inside the usable area. With oversize enabled a standard board is assumed ``2 * oversize`` larger along
each axis and the result is flagged ``requires_physical_verification`` (business decision #12).

Results say "Heuristic layout, not guaranteed optimal": the area lower bound is reported beside the board count.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from decimal import ROUND_FLOOR, Decimal
from fractions import Fraction
from typing import Any

from app.modules.cutting.packer.geometry import Rect, area_mm2, dmm_to_mm, percent
from app.modules.cutting.packer.guillotine import GuillotineBin
from app.modules.cutting.packer.maxrects import MaxRectsBin
from app.modules.cutting.packer.remnants import predicted_offcuts

ALGORITHM_VERSION = "lk-pack-1.0"
NESTED = "nested"
GUILLOTINE = "guillotine"
MODES = (NESTED, GUILLOTINE)
GRAIN_RULES = ("inherit", "locked", "free")

EXCEEDS_USABLE_BOARD = "exceeds_usable_board"
GRAIN_LOCK_PREVENTS_ROTATION = "grain_lock_prevents_rotation"
BOARD_SUPPLY_EXHAUSTED = "board_supply_exhausted"
MAX_BOARDS_LIMIT = "max_boards_limit"
UNFIT_REASONS = (EXCEEDS_USABLE_BOARD, GRAIN_LOCK_PREVENTS_ROTATION, BOARD_SUPPLY_EXHAUSTED, MAX_BOARDS_LIMIT)

WARN_BLANK_DECOR = "blank_decor_treated_as_locked"
WARN_OVERSIZE = "oversize_requires_physical_verification"

#: piece count per plan above which the multi-start is reduced to its first two runs (still deterministic)
REDUCED_MULTISTART_ABOVE = 300


class PackBudgetExceeded(Exception):
    """The deterministic work budget ran out (too many pieces or boards for one calculation)."""

    def __init__(self, evaluations: int, budget: int) -> None:
        super().__init__(f"packing needed more than {budget} candidate evaluations")
        self.evaluations = evaluations
        self.budget = budget


# ---------------------------------------------------------------------------------------------------------
# inputs
# ---------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class ItemSpec:
    line_no: int
    sku: str
    #: canonical decor (``""`` when blank; treated as grain-locked)
    decor_key: str
    #: normalised thickness text (``"18"``, ``"0.8"``)
    thickness_key: str
    length_dmm: int
    width_dmm: int
    quantity: int
    grain_rule: str = "inherit"

    def __post_init__(self) -> None:
        if self.length_dmm <= 0 or self.width_dmm <= 0:
            raise ValueError(f"line {self.line_no}: length and width must be positive")
        if self.quantity <= 0:
            raise ValueError(f"line {self.line_no}: quantity must be positive")
        if self.grain_rule not in GRAIN_RULES:
            raise ValueError(f"line {self.line_no}: unknown grain rule {self.grain_rule!r}")


@dataclass(frozen=True)
class PackSettings:
    board_length_dmm: int = 24400
    board_width_dmm: int = 12200
    margin_dmm: int = 50
    gap_dmm: int = 60
    oversize_enabled: bool = False
    oversize_dmm: int = 100
    mode: str = NESTED
    overproduction_enabled: bool = False
    max_extra_qty: int = 0
    #: percent of the required quantity (``Decimal("10")`` = 10 %)
    max_extra_pct: Decimal = Decimal("0")
    min_offcut_dmm: int = 3000
    max_boards_per_group: int = 500
    #: deterministic budget of candidate evaluations for the whole calculation
    work_budget: int = 60_000_000
    grain_locked_decors: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise ValueError(f"unknown mode {self.mode!r}")
        if self.margin_dmm < 0 or self.gap_dmm < 0 or self.oversize_dmm < 0:
            raise ValueError("margin, gap and oversize must not be negative")
        if self.usable_length <= 0 or self.usable_width <= 0:
            raise ValueError("the margins leave no usable area on the board")
        if self.max_extra_qty < 0 or self.max_extra_pct < 0:
            raise ValueError("overproduction bounds must not be negative")

    @property
    def raw_length(self) -> int:
        return self.board_length_dmm + (2 * self.oversize_dmm if self.oversize_enabled else 0)

    @property
    def raw_width(self) -> int:
        return self.board_width_dmm + (2 * self.oversize_dmm if self.oversize_enabled else 0)

    @property
    def usable_length(self) -> int:
        return self.raw_length - 2 * self.margin_dmm

    @property
    def usable_width(self) -> int:
        return self.raw_width - 2 * self.margin_dmm


# ---------------------------------------------------------------------------------------------------------
# outputs (integers in dmm / dmm²; the service converts to mm strings)
# ---------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class PlacementOut:
    line_no: int
    sku: str
    piece_no: int
    #: raw-board coordinates of the real piece
    x: int
    y: int
    along_length: int
    along_width: int
    rotated: bool
    is_extra: bool


@dataclass(frozen=True)
class CutOut:
    seq: int
    stage: int
    orientation: str
    #: raw-board coordinate where the kerf starts (the real piece edge)
    kerf_start: int
    extent_start: int
    extent_end: int
    kerf: int


@dataclass(frozen=True)
class OffcutOut:
    x: int
    y: int
    length: int
    width: int


@dataclass(frozen=True)
class BoardOut:
    board_no: int
    source: str
    raw_length: int
    raw_width: int
    margin: int
    usable_length: int
    usable_width: int
    placements: tuple[PlacementOut, ...]
    cuts: tuple[CutOut, ...]
    offcuts: tuple[OffcutOut, ...]
    placed_area: int

    @property
    def raw_area(self) -> int:
        return self.raw_length * self.raw_width

    @property
    def usable_area(self) -> int:
        return self.usable_length * self.usable_width


@dataclass(frozen=True)
class ItemOut:
    line_no: int
    sku: str
    length: int
    width: int
    rotation_allowed: bool
    required: int
    placed_required: int
    extra: int
    produced: int
    unfit: int
    unfit_reason: str | None


@dataclass(frozen=True)
class GroupOut:
    group_no: int
    decor_key: str
    thickness_key: str
    mode: str
    boards: tuple[BoardOut, ...]
    items: tuple[ItemOut, ...]
    raw_area: int
    usable_area: int
    placed_area: int
    trim_area: int
    scrap_area: int
    efficiency_usable_pct: Decimal
    efficiency_raw_pct: Decimal
    scrap_pct: Decimal
    lower_bound_boards: int
    run_index: int
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class PackResult:
    algorithm_version: str
    groups: tuple[GroupOut, ...]
    requires_physical_verification: bool
    evaluations: int
    result_hash: str

    @property
    def board_count(self) -> int:
        return sum(len(g.boards) for g in self.groups)

    def totals(self) -> dict[str, int]:
        keys = ("raw_area", "usable_area", "placed_area", "trim_area", "scrap_area")
        out = {k: sum(getattr(g, k) for g in self.groups) for k in keys}
        out["boards"] = self.board_count
        out["required"] = sum(i.required for g in self.groups for i in g.items)
        out["placed_required"] = sum(i.placed_required for g in self.groups for i in g.items)
        out["extra"] = sum(i.extra for g in self.groups for i in g.items)
        out["produced"] = sum(i.produced for g in self.groups for i in g.items)
        out["unfit"] = sum(i.unfit for g in self.groups for i in g.items)
        out["lower_bound_boards"] = sum(g.lower_bound_boards for g in self.groups)
        return out


# ---------------------------------------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class _Piece:
    line_no: int
    piece_no: int
    sku: str
    length: int
    width: int
    rotation_allowed: bool


_ORDERS: tuple[Callable[[_Piece], tuple[int, ...]], ...] = (
    lambda p: (-(p.length * p.width), -max(p.length, p.width), p.line_no, p.piece_no),  # area desc
    lambda p: (-max(p.length, p.width), -min(p.length, p.width), p.line_no, p.piece_no),  # longest side desc
    lambda p: (-(p.length + p.width), -(p.length * p.width), p.line_no, p.piece_no),  # perimeter desc
    lambda p: (-p.length, -p.width, p.line_no, p.piece_no),  # length desc
)


def _bssf(fw: int, fh: int, w: int, h: int) -> tuple[int, int]:
    dw, dh = fw - w, fh - h
    return (min(dw, dh), max(dw, dh))


def _baf(fw: int, fh: int, w: int, h: int) -> tuple[int, int]:
    dw, dh = fw - w, fh - h
    return (fw * fh - w * h, min(dw, dh))


_SCORES: dict[str, tuple[Callable[[int, int, int, int], tuple[int, int]], ...]] = {
    NESTED: (_bssf, _baf),
    GUILLOTINE: (_baf, _bssf),
}

type _Bin = MaxRectsBin | GuillotineBin


class _Budget:
    __slots__ = ("limit", "used")

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.used = 0

    def spend(self, n: int) -> None:
        self.used += n
        if self.used > self.limit:
            raise PackBudgetExceeded(self.used, self.limit)


@dataclass
class _Run:
    bins: list[_Bin]
    #: per bin: (piece, inflated rect, rotated, is_extra)
    contents: list[list[tuple[_Piece, Rect, bool, bool]]]
    unfit: dict[int, list[tuple[_Piece, str]]]
    index: int


def _orientations(p: _Piece, g: int) -> list[tuple[int, int, bool]]:
    out = [(p.length + g, p.width + g, False)]
    if p.rotation_allowed and p.length != p.width:
        out.append((p.width + g, p.length + g, True))
    return out


def _best_slot(
    bins: Sequence[_Bin], p: _Piece, g: int, score: Callable[[int, int, int, int], tuple[int, int]], budget: _Budget
) -> tuple[int, int, int, int, bool] | None:
    """(bin index, free index, w, h, rotated) of the best candidate, ties by (bin, y, x, orientation)."""
    best_key: tuple[Any, ...] | None = None
    best: tuple[int, int, int, int, bool] | None = None
    orients = _orientations(p, g)
    for b_index, b in enumerate(bins):
        budget.spend(len(b.free) * len(orients))
        for o_index, (w, h, rotated) in enumerate(orients):
            for f_index, f in b.candidates(w, h):
                key = (score(f[2], f[3], w, h), b_index, f[1], f[0], o_index)
                if best_key is None or key < best_key:
                    best_key = key
                    best = (b_index, f_index, w, h, rotated)
    return best


def _new_bin(mode: str, width: int, height: int) -> _Bin:
    return GuillotineBin(width, height) if mode == GUILLOTINE else MaxRectsBin(width, height)


def _run(
    pieces: Sequence[_Piece],
    settings: PackSettings,
    order_index: int,
    score: Callable[[int, int, int, int], tuple[int, int]],
    run_index: int,
    budget: _Budget,
) -> _Run:
    g = settings.gap_dmm
    bw, bh = settings.usable_length + g, settings.usable_width + g
    run = _Run(bins=[], contents=[], unfit={}, index=run_index)
    for p in sorted(pieces, key=_ORDERS[order_index]):
        slot = _best_slot(run.bins, p, g, score, budget)
        if slot is None:
            if len(run.bins) >= settings.max_boards_per_group:
                run.unfit.setdefault(p.line_no, []).append((p, MAX_BOARDS_LIMIT))
                continue
            run.bins.append(_new_bin(settings.mode, bw, bh))
            run.contents.append([])
            slot = _best_slot(run.bins[-1:], p, g, score, budget)
            if slot is None:  # pre-check guarantees a fit on an empty standard board
                raise AssertionError("piece passed the pre-check but does not fit an empty board")
            slot = (len(run.bins) - 1, *slot[1:])
        b_index, f_index, w, h, rotated = slot
        rect = run.bins[b_index].place(f_index, w, h)
        run.contents[b_index].append((p, rect, rotated, False))
    return run


def _selection_key(run: _Run, usable_area: int, g: int) -> tuple[Any, ...]:
    unfit = sum(len(v) for v in run.unfit.values())
    if run.contents:
        last = run.contents[-1]
        used = sum((r[2] - g) * (r[3] - g) for _p, r, _rot, _x in last)
        last_util = Fraction(used, usable_area)
    else:
        last_util = Fraction(0)
    return (unfit, len(run.bins), last_util, run.index)


def _overproduce(
    run: _Run, items: Sequence[ItemSpec], rotation: dict[int, bool], settings: PackSettings, budget: _Budget
) -> dict[int, int]:
    """Round-robin by line_no, one extra piece at a time, into already-open boards only (never opens a board)."""
    extras = {item.line_no: 0 for item in items}
    if not settings.overproduction_enabled or not run.bins:
        return extras
    g = settings.gap_dmm
    score = _SCORES[settings.mode][0]
    caps: dict[int, int] = {}
    for item in items:
        by_pct = int((Decimal(item.quantity) * settings.max_extra_pct / 100).to_integral_value(rounding=ROUND_FLOOR))
        caps[item.line_no] = min(settings.max_extra_qty, by_pct)
    active = [item for item in sorted(items, key=lambda i: i.line_no) if caps[item.line_no] > 0]
    while active:
        still: list[ItemSpec] = []
        for item in active:
            n = extras[item.line_no]
            piece = _Piece(item.line_no, item.quantity + n + 1, item.sku, item.length_dmm, item.width_dmm, rotation[item.line_no])
            slot = _best_slot(run.bins, piece, g, score, budget)
            if slot is None:
                continue
            b_index, f_index, w, h, rotated = slot
            rect = run.bins[b_index].place(f_index, w, h)
            run.contents[b_index].append((piece, rect, rotated, True))
            extras[item.line_no] = n + 1
            if extras[item.line_no] < caps[item.line_no]:
                still.append(item)
        active = still
    return extras


def _board_out(
    board_no: int, b: _Bin, contents: Sequence[tuple[_Piece, Rect, bool, bool]], settings: PackSettings
) -> BoardOut:
    g, m = settings.gap_dmm, settings.margin_dmm
    placements = []
    placed_area = 0
    for p, (x, y, w, h), rotated, is_extra in sorted(contents, key=lambda c: (c[1][1], c[1][0])):
        real_l, real_w = w - g, h - g
        placed_area += real_l * real_w
        placements.append(PlacementOut(p.line_no, p.sku, p.piece_no, x + m, y + m, real_l, real_w, rotated, is_extra))
    cuts: list[CutOut] = []
    if isinstance(b, GuillotineBin):
        for seq, c in enumerate(b.cuts, start=1):
            cuts.append(CutOut(seq, c.stage, c.orientation, c.position - g + m, c.start + m, c.end - g + m, g))
    offcuts = tuple(
        OffcutOut(x + m, y + m, w, h) for x, y, w, h in predicted_offcuts(b.free_rects(), g, settings.min_offcut_dmm)
    )
    return BoardOut(
        board_no=board_no,
        source="standard",
        raw_length=settings.raw_length,
        raw_width=settings.raw_width,
        margin=m,
        usable_length=settings.usable_length,
        usable_width=settings.usable_width,
        placements=tuple(placements),
        cuts=tuple(cuts),
        offcuts=offcuts,
        placed_area=placed_area,
    )


def _precheck(item: ItemSpec, rotation_allowed: bool, settings: PackSettings) -> str | None:
    ul, uw = settings.usable_length, settings.usable_width
    straight = item.length_dmm <= ul and item.width_dmm <= uw
    turned = item.width_dmm <= ul and item.length_dmm <= uw
    if straight or (turned and rotation_allowed):
        return None
    return GRAIN_LOCK_PREVENTS_ROTATION if turned else EXCEEDS_USABLE_BOARD


def _pack_group(
    group_no: int,
    decor_key: str,
    thickness_key: str,
    items: Sequence[ItemSpec],
    settings: PackSettings,
    budget: _Budget,
    reduced: bool,
) -> GroupOut:
    g = settings.gap_dmm
    warnings: list[str] = []
    if decor_key == "":
        warnings.append(WARN_BLANK_DECOR)
    decor_locked = decor_key == "" or decor_key in settings.grain_locked_decors
    rotation = {item.line_no: (not decor_locked and item.grain_rule != "locked") for item in items}
    precheck = {item.line_no: _precheck(item, rotation[item.line_no], settings) for item in items}
    pieces = [
        _Piece(item.line_no, n, item.sku, item.length_dmm, item.width_dmm, rotation[item.line_no])
        for item in items
        if precheck[item.line_no] is None
        for n in range(1, item.quantity + 1)
    ]
    plans = [(o, s) for o in range(len(_ORDERS)) for s in range(len(_SCORES[settings.mode]))]
    if reduced:
        plans = plans[:2]
    usable_area = settings.usable_length * settings.usable_width
    best: _Run | None = None
    best_key: tuple[Any, ...] | None = None
    for run_index, (o, s) in enumerate(plans):
        run = _run(pieces, settings, o, _SCORES[settings.mode][s], run_index, budget)
        key = _selection_key(run, usable_area, g)
        if best_key is None or key < best_key:
            best, best_key = run, key
        if not pieces:
            break
    assert best is not None
    extras = _overproduce(best, items, rotation, settings, budget)

    boards = tuple(_board_out(n, b, c, settings) for n, (b, c) in enumerate(zip(best.bins, best.contents, strict=True), start=1))
    placed_count: dict[int, int] = {}
    for c in best.contents:
        for p, _r, _rot, is_extra in c:
            if not is_extra:
                placed_count[p.line_no] = placed_count.get(p.line_no, 0) + 1
    item_outs = []
    for item in sorted(items, key=lambda i: i.line_no):
        reason = precheck[item.line_no]
        placed = placed_count.get(item.line_no, 0)
        unfit = item.quantity - placed
        if unfit and reason is None:
            reason = best.unfit[item.line_no][0][1] if best.unfit.get(item.line_no) else MAX_BOARDS_LIMIT
        extra = extras.get(item.line_no, 0)
        item_outs.append(
            ItemOut(
                line_no=item.line_no,
                sku=item.sku,
                length=item.length_dmm,
                width=item.width_dmm,
                rotation_allowed=rotation[item.line_no],
                required=item.quantity,
                placed_required=placed,
                extra=extra,
                produced=placed + extra,
                unfit=unfit,
                unfit_reason=reason if unfit else None,
            )
        )
    raw = sum(b.raw_area for b in boards)
    usable = sum(b.usable_area for b in boards)
    placed_area = sum(b.placed_area for b in boards)
    inflated_bin = (settings.usable_length + g) * (settings.usable_width + g)
    inflated_pieces = sum((p.length + g) * (p.width + g) for p in pieces)
    eff_usable = percent(placed_area, usable)
    if settings.oversize_enabled and boards:
        warnings.append(WARN_OVERSIZE)
    return GroupOut(
        group_no=group_no,
        decor_key=decor_key,
        thickness_key=thickness_key,
        mode=settings.mode,
        boards=boards,
        items=tuple(item_outs),
        raw_area=raw,
        usable_area=usable,
        placed_area=placed_area,
        trim_area=raw - usable,
        scrap_area=usable - placed_area,
        efficiency_usable_pct=eff_usable,
        efficiency_raw_pct=percent(placed_area, raw),
        scrap_pct=(Decimal("100.00") - eff_usable) if usable else Decimal("0.00"),
        lower_bound_boards=math.ceil(inflated_pieces / inflated_bin) if inflated_pieces else 0,
        run_index=best.index,
        warnings=tuple(warnings),
    )


def _thickness_sort(key: str) -> tuple[int, Decimal | str]:
    try:
        return (0, Decimal(key))
    except ArithmeticError:
        return (1, key)


def pack(items: Sequence[ItemSpec], settings: PackSettings) -> PackResult:
    """Pack every item, grouped by (canonical decor, normalised thickness); groups in (decor, thickness) order."""
    line_nos = [i.line_no for i in items]
    if len(set(line_nos)) != len(line_nos):
        raise ValueError("line numbers must be unique")
    groups: dict[tuple[str, str], list[ItemSpec]] = {}
    for item in items:
        groups.setdefault((item.decor_key, item.thickness_key), []).append(item)
    budget = _Budget(settings.work_budget)
    reduced = sum(i.quantity for i in items) > REDUCED_MULTISTART_ABOVE
    outs = tuple(
        _pack_group(n, decor, thickness, groups[(decor, thickness)], settings, budget, reduced)
        for n, (decor, thickness) in enumerate(sorted(groups, key=lambda k: (k[0], _thickness_sort(k[1]))), start=1)
    )
    requires_verification = settings.oversize_enabled and any(g.boards for g in outs)
    body = {
        "algorithm_version": ALGORITHM_VERSION,
        "groups": [_jsonable(asdict(g)) for g in outs],
        "requires_physical_verification": requires_verification,
    }
    digest = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return PackResult(ALGORITHM_VERSION, outs, requires_verification, budget.used, digest)


def input_hash(items: Sequence[ItemSpec], settings: PackSettings) -> str:
    """sha256 of the canonical input (items in line order, settings, the relevant grain locks, algorithm version)."""
    decors = {i.decor_key for i in items}
    body = {
        "algorithm_version": ALGORITHM_VERSION,
        "items": [_jsonable(asdict(i)) for i in sorted(items, key=lambda i: i.line_no)],
        "settings": _jsonable(
            {**asdict(settings), "grain_locked_decors": sorted(settings.grain_locked_decors & decors)}
        ),
    }
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, frozenset | set):
        return sorted(_jsonable(v) for v in value)
    if isinstance(value, Decimal):
        return format(value, "f")
    return value


__all__ = [
    "ALGORITHM_VERSION",
    "BOARD_SUPPLY_EXHAUSTED",
    "EXCEEDS_USABLE_BOARD",
    "GRAIN_LOCK_PREVENTS_ROTATION",
    "GUILLOTINE",
    "MAX_BOARDS_LIMIT",
    "MODES",
    "NESTED",
    "UNFIT_REASONS",
    "BoardOut",
    "CutOut",
    "GroupOut",
    "ItemOut",
    "ItemSpec",
    "OffcutOut",
    "PackBudgetExceeded",
    "PackResult",
    "PackSettings",
    "PlacementOut",
    "area_mm2",
    "dmm_to_mm",
    "input_hash",
    "pack",
]
