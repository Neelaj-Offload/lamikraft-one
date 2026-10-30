"""Cut plans: save, reopen, duplicate, archive, verify boards, calculate (synchronously for small inputs, as a durable
job for large ones) and the stateless legacy calculation.

Lifecycle (operations.md §7): calculating appends an immutable calculation and points the plan at it; reopening
shows the stored latest calculation without recomputing; editing inputs marks the plan stale; duplicating copies
inputs only. A plan whose calculation assumed the +oversize board must be physically verified (business decision
#12) before it can be released (release and work-order links arrive in Slice 4).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal
from typing import Any

from pydantic import BaseModel
from sqlalchemy import func, insert, or_, select

from app.core.clock import local_date
from app.core.db.base import new_id
from app.core.errors import Conflict, PermanentJobError, ValidationFailed
from app.core.http.pagination import MAX_LIMIT, Page
from app.core.text import LIKE_ESCAPE, contains_pattern, tokens
from app.modules.catalogue import service as catalogue
from app.modules.catalogue.normalise import normalise_thickness
from app.modules.catalogue.schemas import ProductFilters
from app.modules.cutting import config
from app.modules.cutting import events as ev
from app.modules.cutting.canonical import canonical_decor, thickness_key
from app.modules.cutting.config import MAX_PIECES, SYNC_PIECE_LIMIT, plain
from app.modules.cutting.models import (
    CalcBoard,
    CalcCut,
    CalcGroup,
    CalcItemResult,
    CalcOffcut,
    CalcPlacement,
    Calculation,
    Plan,
    PlanItem,
)
from app.modules.cutting.packer.engine import (
    ItemSpec,
    PackBudgetExceeded,
    PackResult,
    PackSettings,
    input_hash,
    pack,
)
from app.modules.cutting.packer.geometry import GeometryError, area_mm2, dmm_to_mm, mm_to_dmm
from app.modules.cutting.schemas import (
    HEURISTIC_NOTE,
    BoardRead,
    CalcStateRead,
    CalculateIn,
    CalculationRead,
    CalculationResult,
    CalculationSummary,
    CalculationTotals,
    Capability,
    CutRead,
    CuttingProduct,
    GroupRead,
    ItemResultRead,
    OffcutRead,
    PlacementRead,
    PlanCommand,
    PlanCreate,
    PlanDetail,
    PlanFilters,
    PlanItemIn,
    PlanItemRead,
    PlanSettingsIn,
    PlanSettingsRead,
    PlanSummary,
    PlanTransition,
    PlanUpdate,
    TransitionRead,
    UserRef,
    VerificationRead,
    VerifyBoards,
)
from app.platform.idempotency.service import run_idempotent
from app.platform.identity.models import AppUser
from app.platform.org.models import Company
from app.platform.uow import UnitOfWork

READ = "cutting.plan.read"
CREATE = "cutting.plan.create"
RUN = "cutting.calculation.run"
CALC_JOB = "cutting.calculate"
API = "/api/v1/cutting"

SETTING_FIELDS = (
    "board_length_mm", "board_width_mm", "margin_mm", "gap_mm", "oversize_enabled", "oversize_mm", "mode",
    "machine_profile_id", "overproduction_enabled", "max_extra_qty", "max_extra_pct", "min_offcut_mm",
    "max_boards_per_group",
)
_PCT = Decimal("0.01")


class Errors:
    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    def add(self, loc: Sequence[str | int], code: str, msg: str) -> None:
        self.items.append({"loc": ["body", *loc], "msg": msg, "code": code})

    def raise_if_any(self, title: str = "Some cut-plan values are not valid") -> None:
        if self.items:
            raise ValidationFailed(title, errors=self.items)


def plan_path(plan_id: uuid.UUID) -> str:
    return f"/operations/cutting/{plan_id}"


def _api_plan(plan_id: uuid.UUID) -> str:
    return f"{API}/plans/{plan_id}"


def idempotent[T: BaseModel](
    uow: UnitOfWork, operation: str, body: BaseModel | dict[str, Any], fn: Callable[[], T], model: type[T], status: int = 200
) -> tuple[T, bool]:
    payload = body.model_dump(mode="json") if isinstance(body, BaseModel) else body
    out, replayed = run_idempotent(
        uow, key=uow.actor.idempotency_key, operation=operation, body=payload,
        fn=lambda: fn().model_dump(mode="json"), status=status,
    )
    return model.model_validate(out), replayed


def _users(uow: UnitOfWork, ids: Sequence[uuid.UUID | None]) -> dict[uuid.UUID, UserRef]:
    wanted = {i for i in ids if i is not None}
    if not wanted:
        return {}
    rows = uow.session.execute(select(AppUser.id, AppUser.display_name).where(AppUser.id.in_(wanted))).all()
    return {r[0]: UserRef(id=r[0], display_name=r[1]) for r in rows}


def _user(uow: UnitOfWork, user_id: uuid.UUID | None) -> UserRef | None:
    if user_id is None:
        return None
    return _users(uow, [user_id]).get(user_id) or UserRef(id=user_id, display_name=None)


def _business_date(uow: UnitOfWork) -> Any:
    zone = uow.session.scalar(select(Company.default_time_zone).where(Company.id == uow.actor.company_id))
    return local_date(uow.now(), zone or "Asia/Kolkata")


# =====================================================================================================
# settings snapshot
# =====================================================================================================
def _company_defaults(uow: UnitOfWork) -> dict[str, Any]:
    s = config.effective_settings(uow)
    values: dict[str, Any] = {
        "board_length_mm": s.board_length_mm, "board_width_mm": s.board_width_mm, "margin_mm": s.margin_mm,
        "gap_mm": s.gap_mm, "oversize_enabled": False, "oversize_mm": s.oversize_mm, "mode": s.default_mode,
        "machine_profile_id": None, "overproduction_enabled": False, "max_extra_qty": s.max_extra_qty,
        "max_extra_pct": s.max_extra_pct, "min_offcut_mm": s.min_offcut_mm, "max_boards_per_group": s.max_boards_per_group,
    }
    if s.default_machine_profile_id is not None:
        profile = config.machine_profile(uow, s.default_machine_profile_id)
        if profile.archived_at is None:
            values["machine_profile_id"] = profile.id
            values["mode"] = profile.mode
            if profile.gap_mm is not None:
                values["gap_mm"] = plain(profile.gap_mm)
    return values


def _plan_values(plan: Plan) -> dict[str, Any]:
    values = {f: getattr(plan, f) for f in SETTING_FIELDS}
    for f in ("board_length_mm", "board_width_mm", "margin_mm", "gap_mm", "oversize_mm", "min_offcut_mm", "max_extra_pct"):
        values[f] = plain(values[f])
    return values


def _apply_settings(uow: UnitOfWork, values: dict[str, Any], data: PlanSettingsIn | None, errors: Errors) -> set[str]:
    """Overlay explicitly sent settings on ``values``; a machine profile brings its mode and kerf unless both are sent."""
    if data is None:
        return set()
    sent = data.model_fields_set
    changed: set[str] = set()
    for f in sent:
        value = getattr(data, f)
        if value is None and f != "machine_profile_id":
            continue
        if values.get(f) != value:
            changed.add(f)
        values[f] = value
    if "machine_profile_id" in sent and data.machine_profile_id is not None:
        profile = config.machine_profile(uow, data.machine_profile_id)
        if profile.archived_at is not None:
            errors.add(["settings", "machine_profile_id"], "machine_profile_archived", "The machine profile is archived")
        if "mode" not in sent and values["mode"] != profile.mode:
            values["mode"] = profile.mode
            changed.add("mode")
        if "gap_mm" not in sent and profile.gap_mm is not None and values["gap_mm"] != plain(profile.gap_mm):
            values["gap_mm"] = plain(profile.gap_mm)
            changed.add("gap_mm")
    if 2 * Decimal(values["margin_mm"]) >= min(Decimal(values["board_length_mm"]), Decimal(values["board_width_mm"])):
        errors.add(["settings", "margin_mm"], "margin_too_large", "The margins leave no usable area on the board")
    return changed


def _pack_settings(values: Mapping[str, Any], locks: frozenset[str], *, max_boards: int | None = None) -> PackSettings:
    return PackSettings(
        board_length_dmm=mm_to_dmm(values["board_length_mm"]),
        board_width_dmm=mm_to_dmm(values["board_width_mm"]),
        margin_dmm=mm_to_dmm(values["margin_mm"]),
        gap_dmm=mm_to_dmm(values["gap_mm"]),
        oversize_enabled=bool(values["oversize_enabled"]),
        oversize_dmm=mm_to_dmm(values["oversize_mm"]),
        mode=values["mode"],
        overproduction_enabled=bool(values["overproduction_enabled"]),
        max_extra_qty=int(values["max_extra_qty"]),
        max_extra_pct=Decimal(values["max_extra_pct"]),
        min_offcut_dmm=mm_to_dmm(values["min_offcut_mm"]),
        max_boards_per_group=max_boards or int(values["max_boards_per_group"]),
        grain_locked_decors=locks,
    )


def _settings_read(values: Mapping[str, Any]) -> PlanSettingsRead:
    over = Decimal(values["oversize_mm"]) * 2 if values["oversize_enabled"] else Decimal(0)
    raw_l = Decimal(values["board_length_mm"]) + over
    raw_w = Decimal(values["board_width_mm"]) + over
    margin = Decimal(values["margin_mm"])
    return PlanSettingsRead(
        board_length_mm=values["board_length_mm"],
        board_width_mm=values["board_width_mm"],
        margin_mm=values["margin_mm"],
        gap_mm=values["gap_mm"],
        oversize_enabled=bool(values["oversize_enabled"]),
        oversize_mm=values["oversize_mm"],
        mode=values["mode"],
        machine_profile_id=values["machine_profile_id"],
        overproduction_enabled=bool(values["overproduction_enabled"]),
        max_extra_qty=int(values["max_extra_qty"]),
        max_extra_pct=values["max_extra_pct"],
        min_offcut_mm=values["min_offcut_mm"],
        max_boards_per_group=int(values["max_boards_per_group"]),
        raw_length_mm=plain(raw_l),  # type: ignore[arg-type]
        raw_width_mm=plain(raw_w),  # type: ignore[arg-type]
        usable_length_mm=plain(raw_l - 2 * margin),  # type: ignore[arg-type]
        usable_width_mm=plain(raw_w - 2 * margin),  # type: ignore[arg-type]
    )


# =====================================================================================================
# items
# =====================================================================================================
def _item_values(uow: UnitOfWork, items: Sequence[PlanItemIn], errors: Errors, warnings: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    product_ids = [i.product_id for i in items if i.product_id is not None]
    visible = catalogue.product_refs(uow, product_ids) if product_ids else {}
    for index, item in enumerate(items):
        decor_key, warns = canonical_decor(item.decor)
        if len(decor_key) > 40:
            errors.add(["items", index, "decor"], "invalid_decor", "decor must be at most 40 characters")
        if warns:
            warnings.append(f"Line {index + 1}: decor {item.decor!s} is {decor_key}")
        try:
            thickness = normalise_thickness(item.thickness_mm)
        except ValueError:
            thickness = None
        if thickness is None or thickness <= 0:
            errors.add(["items", index, "thickness_mm"], "invalid_thickness", "thickness must be a positive length in mm")
        if item.product_id is not None and item.product_id not in visible:
            errors.add(["items", index, "product_id"], "product_not_found", "The product does not exist or is not visible")
        rows.append(
            {
                "line_no": index + 1,
                "product_id": item.product_id,
                "sku": item.sku,
                "decor": item.decor.strip() if item.decor and item.decor.strip() else None,
                "decor_key": decor_key,
                "thickness_mm": thickness,
                "length_mm": item.length_mm,
                "width_mm": item.width_mm,
                "quantity": item.quantity,
                "grain_rule": item.grain_rule,
                "label": item.label or None,
            }
        )
    pieces = sum(i.quantity for i in items)
    if pieces > MAX_PIECES:
        errors.add(["items"], "cutting_input_too_large", f"A plan holds at most {MAX_PIECES} pieces ({pieces} entered)")
    return rows


def _specs(rows: Sequence[Mapping[str, Any]]) -> list[ItemSpec]:
    return [
        ItemSpec(
            line_no=r["line_no"],
            sku=r["sku"],
            decor_key=r["decor_key"],
            thickness_key=thickness_key(r["thickness_mm"]),
            length_dmm=mm_to_dmm(plain(Decimal(r["length_mm"]))),  # type: ignore[arg-type]
            width_dmm=mm_to_dmm(plain(Decimal(r["width_mm"]))),  # type: ignore[arg-type]
            quantity=int(r["quantity"]),
            grain_rule=r["grain_rule"],
        )
        for r in rows
    ]


def _plan_items(uow: UnitOfWork, plan: Plan) -> list[PlanItem]:
    return list(
        uow.session.scalars(uow.repo(PlanItem).select().where(PlanItem.plan_id == plan.id).order_by(PlanItem.line_no))
    )


def _item_dict(i: PlanItem) -> dict[str, Any]:
    return {
        "line_no": i.line_no, "product_id": i.product_id, "sku": i.sku, "decor": i.decor, "decor_key": i.decor_key,
        "thickness_mm": plain(i.thickness_mm), "length_mm": plain(i.length_mm), "width_mm": plain(i.width_mm),
        "quantity": i.quantity, "grain_rule": i.grain_rule, "label": i.label,
    }


def _replace_items(uow: UnitOfWork, plan: Plan, rows: Sequence[Mapping[str, Any]]) -> None:
    for old in _plan_items(uow, plan):
        uow.session.delete(old)
    uow.flush()
    for r in rows:
        uow.add(PlanItem(plan_id=plan.id, **r))


# =====================================================================================================
# results: PackResult -> rows -> reads
# =====================================================================================================
def _mm(v: int) -> Decimal:
    return plain(dmm_to_mm(v))  # type: ignore[return-value]


def _rows_from_result(result: PackResult) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {k: [] for k in ("groups", "boards", "placements", "items", "offcuts", "cuts")}
    for g in result.groups:
        out["groups"].append(
            {
                "group_no": g.group_no, "decor_key": g.decor_key, "thickness_key": g.thickness_key, "mode": g.mode,
                "boards": len(g.boards), "raw_area_mm2": area_mm2(g.raw_area), "usable_area_mm2": area_mm2(g.usable_area),
                "placed_area_mm2": area_mm2(g.placed_area), "trim_area_mm2": area_mm2(g.trim_area),
                "scrap_area_mm2": area_mm2(g.scrap_area), "efficiency_usable_pct": g.efficiency_usable_pct,
                "efficiency_raw_pct": g.efficiency_raw_pct, "scrap_pct": g.scrap_pct,
                "lower_bound_boards": g.lower_bound_boards, "run_index": g.run_index, "warnings": list(g.warnings),
            }
        )
        for it in g.items:
            out["items"].append(
                {
                    "group_no": g.group_no, "line_no": it.line_no, "sku": it.sku, "length_mm": _mm(it.length),
                    "width_mm": _mm(it.width), "rotation_allowed": it.rotation_allowed, "required": it.required,
                    "placed_required": it.placed_required, "extra": it.extra, "produced": it.produced,
                    "unfit": it.unfit, "unfit_reason": it.unfit_reason,
                }
            )
        for b in g.boards:
            out["boards"].append(
                {
                    "group_no": g.group_no, "board_no": b.board_no, "source": b.source, "lot_id": None,
                    "raw_length_mm": _mm(b.raw_length), "raw_width_mm": _mm(b.raw_width), "margin_mm": _mm(b.margin),
                    "usable_length_mm": _mm(b.usable_length), "usable_width_mm": _mm(b.usable_width),
                    "placed_area_mm2": area_mm2(b.placed_area),
                    "efficiency_pct": (Decimal(b.placed_area) * 100 / Decimal(b.usable_area)).quantize(_PCT),
                }
            )
            for seq, p in enumerate(b.placements, start=1):
                out["placements"].append(
                    {
                        "group_no": g.group_no, "board_no": b.board_no, "seq": seq, "line_no": p.line_no, "sku": p.sku,
                        "piece_no": p.piece_no, "x_mm": _mm(p.x), "y_mm": _mm(p.y),
                        "along_length_mm": _mm(p.along_length), "along_width_mm": _mm(p.along_width),
                        "rotated": p.rotated, "is_extra": p.is_extra,
                    }
                )
            for seq, o in enumerate(b.offcuts, start=1):
                out["offcuts"].append(
                    {
                        "group_no": g.group_no, "board_no": b.board_no, "seq": seq, "x_mm": _mm(o.x), "y_mm": _mm(o.y),
                        "length_mm": _mm(o.length), "width_mm": _mm(o.width),
                    }
                )
            for c in b.cuts:
                out["cuts"].append(
                    {
                        "group_no": g.group_no, "board_no": b.board_no, "seq": c.seq, "stage": c.stage,
                        "orientation": c.orientation, "kerf_start_mm": _mm(c.kerf_start),
                        "extent_start_mm": _mm(c.extent_start), "extent_end_mm": _mm(c.extent_end), "kerf_mm": _mm(c.kerf),
                    }
                )
    return out


def _totals_from_result(result: PackResult) -> dict[str, Any]:
    t = result.totals()
    return {
        "boards": t["boards"], "required": t["required"], "placed_required": t["placed_required"], "extra": t["extra"],
        "produced": t["produced"], "unfit": t["unfit"], "lower_bound_boards": t["lower_bound_boards"],
        "raw_area_mm2": area_mm2(t["raw_area"]), "usable_area_mm2": area_mm2(t["usable_area"]),
        "placed_area_mm2": area_mm2(t["placed_area"]), "trim_area_mm2": area_mm2(t["trim_area"]),
        "scrap_area_mm2": area_mm2(t["scrap_area"]),
        "efficiency_usable_pct": _pct_of(t["placed_area"], t["usable_area"]),
        "efficiency_raw_pct": _pct_of(t["placed_area"], t["raw_area"]),
        "scrap_pct": (Decimal("100.00") - _pct_of(t["placed_area"], t["usable_area"])) if t["usable_area"] else Decimal("0.00"),
    }


def _pct_of(part: int, whole: int) -> Decimal:
    from app.modules.cutting.packer.geometry import percent

    return percent(part, whole)


def _area_fields(r: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "raw_area_mm2": Decimal(r["raw_area_mm2"]).quantize(_PCT),
        "usable_area_mm2": Decimal(r["usable_area_mm2"]).quantize(_PCT),
        "placed_area_mm2": Decimal(r["placed_area_mm2"]).quantize(_PCT),
        "trim_area_mm2": Decimal(r["trim_area_mm2"]).quantize(_PCT),
        "scrap_area_mm2": Decimal(r["scrap_area_mm2"]).quantize(_PCT),
        "efficiency_usable_pct": Decimal(r["efficiency_usable_pct"]).quantize(_PCT),
        "efficiency_raw_pct": Decimal(r["efficiency_raw_pct"]).quantize(_PCT),
        "scrap_pct": Decimal(r["scrap_pct"]).quantize(_PCT),
    }


def _p(v: Any) -> Decimal:
    return plain(Decimal(v))  # type: ignore[return-value]


def compose_groups(rows: Mapping[str, Sequence[Mapping[str, Any]]], svg_base: str | None) -> list[GroupRead]:
    """Reads from result rows (fresh from the packer or loaded from the database)."""

    def by_board(kind: str) -> dict[tuple[int, int], list[Mapping[str, Any]]]:
        out: dict[tuple[int, int], list[Mapping[str, Any]]] = {}
        for r in rows[kind]:
            out.setdefault((r["group_no"], r["board_no"]), []).append(r)
        return out

    placements, offcuts, cuts = by_board("placements"), by_board("offcuts"), by_board("cuts")
    items: dict[int, list[Mapping[str, Any]]] = {}
    for r in rows["items"]:
        items.setdefault(r["group_no"], []).append(r)
    boards: dict[int, list[Mapping[str, Any]]] = {}
    for r in rows["boards"]:
        boards.setdefault(r["group_no"], []).append(r)
    groups: list[GroupRead] = []
    index = 0
    for g in sorted(rows["groups"], key=lambda r: r["group_no"]):
        board_reads: list[BoardRead] = []
        for b in sorted(boards.get(g["group_no"], []), key=lambda r: r["board_no"]):
            index += 1
            key = (g["group_no"], b["board_no"])
            board_reads.append(
                BoardRead(
                    index=index,
                    board_no=b["board_no"],
                    source=b["source"],
                    raw_length_mm=_p(b["raw_length_mm"]),
                    raw_width_mm=_p(b["raw_width_mm"]),
                    margin_mm=_p(b["margin_mm"]),
                    usable_length_mm=_p(b["usable_length_mm"]),
                    usable_width_mm=_p(b["usable_width_mm"]),
                    placed_area_mm2=Decimal(b["placed_area_mm2"]).quantize(_PCT),
                    efficiency_pct=Decimal(b["efficiency_pct"]).quantize(_PCT),
                    placements=[
                        PlacementRead(
                            seq=p["seq"], line_no=p["line_no"], sku=p["sku"], piece_no=p["piece_no"], x_mm=_p(p["x_mm"]),
                            y_mm=_p(p["y_mm"]), along_length_mm=_p(p["along_length_mm"]),
                            along_width_mm=_p(p["along_width_mm"]), rotated=p["rotated"], is_extra=p["is_extra"],
                        )
                        for p in sorted(placements.get(key, []), key=lambda r: r["seq"])
                    ],
                    offcuts=[
                        OffcutRead(seq=o["seq"], x_mm=_p(o["x_mm"]), y_mm=_p(o["y_mm"]), length_mm=_p(o["length_mm"]),
                                   width_mm=_p(o["width_mm"]))
                        for o in sorted(offcuts.get(key, []), key=lambda r: r["seq"])
                    ],
                    cuts=[
                        CutRead(seq=c["seq"], stage=c["stage"], orientation=c["orientation"],
                                kerf_start_mm=_p(c["kerf_start_mm"]), extent_start_mm=_p(c["extent_start_mm"]),
                                extent_end_mm=_p(c["extent_end_mm"]), kerf_mm=_p(c["kerf_mm"]))
                        for c in sorted(cuts.get(key, []), key=lambda r: r["seq"])
                    ],
                    svg_path=f"{svg_base}/boards/{index}.svg" if svg_base else None,
                )
            )
        groups.append(
            GroupRead(
                group_no=g["group_no"],
                decor_key=g["decor_key"],
                thickness_mm=g["thickness_key"],
                mode=g["mode"],
                board_count=g["boards"],
                lower_bound_boards=g["lower_bound_boards"],
                warnings=list(g["warnings"] or []),
                items=[
                    ItemResultRead(
                        line_no=i["line_no"], sku=i["sku"], length_mm=_p(i["length_mm"]), width_mm=_p(i["width_mm"]),
                        rotation_allowed=i["rotation_allowed"], required=i["required"],
                        placed_required=i["placed_required"], extra=i["extra"], produced=i["produced"],
                        unfit=i["unfit"], unfit_reason=i["unfit_reason"],
                    )
                    for i in sorted(items.get(g["group_no"], []), key=lambda r: r["line_no"])
                ],
                boards=board_reads,
                **_area_fields(g),
            )
        )
    return groups


def _totals_read(t: Mapping[str, Any]) -> CalculationTotals:
    return CalculationTotals(
        boards=t["boards"], required=t["required"], placed_required=t["placed_required"], extra=t["extra"],
        produced=t["produced"], unfit=t["unfit"], lower_bound_boards=t["lower_bound_boards"], **_area_fields(t),
    )


_RESULT_TABLES: dict[str, type] = {
    "groups": CalcGroup, "boards": CalcBoard, "placements": CalcPlacement, "items": CalcItemResult,
    "offcuts": CalcOffcut, "cuts": CalcCut,
}


def _load_rows(uow: UnitOfWork, calc: Calculation) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for kind, model in _RESULT_TABLES.items():
        cols = [c.key for c in model.__table__.columns]  # type: ignore[attr-defined]
        stmt = uow.repo(model).select().where(model.calculation_id == calc.id)  # type: ignore[attr-defined]
        out[kind] = [{c: getattr(obj, c) for c in cols} for obj in uow.session.scalars(stmt)]
    return out


def _calc_totals(calc: Calculation) -> dict[str, Any]:
    keys = ("boards", "required", "placed_required", "extra", "produced", "unfit", "lower_bound_boards",
            "raw_area_mm2", "usable_area_mm2", "placed_area_mm2", "trim_area_mm2", "scrap_area_mm2",
            "efficiency_usable_pct", "efficiency_raw_pct", "scrap_pct")
    return {k: getattr(calc, k) for k in keys}


def calculation_read(uow: UnitOfWork, calc: Calculation, *, with_svg: bool = True) -> CalculationRead:
    rows = _load_rows(uow, calc)
    svg_base = f"{_api_plan(calc.plan_id)}/calculations/{calc.calc_no}" if with_svg else None
    snapshot = calc.settings_snapshot
    return CalculationRead(
        id=calc.id,
        plan_id=calc.plan_id,
        calc_no=calc.calc_no,
        origin=calc.origin,  # type: ignore[arg-type]
        created_at=calc.created_at,
        created_by=_user(uow, calc.created_by),
        algorithm_version=calc.algorithm_version,
        mode=calc.mode,  # type: ignore[arg-type]
        input_hash=calc.input_hash,
        result_hash=calc.result_hash,
        requires_physical_verification=calc.requires_physical_verification,
        note=HEURISTIC_NOTE,
        totals=_totals_read(_calc_totals(calc)),
        groups=compose_groups(rows, svg_base),
        settings=PlanSettingsRead.model_validate(snapshot["settings"]),
        grain_locked_decors=list(snapshot.get("grain_locked_decors") or []),
    )


# =====================================================================================================
# calculation
# =====================================================================================================
def _run_pack(specs: Sequence[ItemSpec], ps: PackSettings) -> PackResult:
    try:
        return pack(specs, ps)
    except PackBudgetExceeded as exc:
        raise ValidationFailed(
            "This cut list needs more work than one calculation may spend; split it into smaller plans",
            code="cutting_budget_exceeded",
            evaluations=exc.evaluations,
            budget=exc.budget,
        ) from exc
    except (GeometryError, ValueError) as exc:
        raise ValidationFailed(str(exc), code="cutting_invalid_input") from exc


def _persist(
    uow: UnitOfWork, plan: Plan, values: Mapping[str, Any], specs: Sequence[ItemSpec], ps: PackSettings,
    result: PackResult, origin: str, requested_by: uuid.UUID | None,
) -> Calculation:
    totals = _totals_from_result(result)
    decors = {s.decor_key for s in specs}
    settings_json = _settings_read(values).model_dump(mode="json")
    calc = Calculation(
        id=new_id(),
        plan_id=plan.id,
        calc_no=plan.calc_count + 1,
        algorithm_version=result.algorithm_version,
        mode=ps.mode,
        origin=origin,
        settings_snapshot={"settings": settings_json, "grain_locked_decors": sorted(ps.grain_locked_decors & decors)},
        input_snapshot={"items": [_jsonable(_spec_dict(s)) for s in specs]},
        input_hash=input_hash(specs, ps),
        result_hash=result.result_hash,
        requires_physical_verification=result.requires_physical_verification,
        evaluations=result.evaluations,
        created_by=requested_by,
        updated_by=requested_by,
        **totals,
    )
    uow.add(calc)
    uow.flush()
    rows = _rows_from_result(result)
    for kind, model in _RESULT_TABLES.items():
        batch = [{"id": new_id(), "company_id": uow.actor.company_id, "calculation_id": calc.id, **r} for r in rows[kind]]
        for start in range(0, len(batch), 1000):
            uow.session.execute(insert(model), batch[start : start + 1000])
    return calc


def _spec_dict(s: ItemSpec) -> dict[str, Any]:
    return {
        "line_no": s.line_no, "sku": s.sku, "decor_key": s.decor_key, "thickness": s.thickness_key,
        "length_mm": _mm(s.length_dmm), "width_mm": _mm(s.width_dmm), "quantity": s.quantity, "grain_rule": s.grain_rule,
    }


def _jsonable(d: Mapping[str, Any]) -> dict[str, Any]:
    return {k: format(v, "f") if isinstance(v, Decimal) else v for k, v in d.items()}


def _calculate(uow: UnitOfWork, plan: Plan, origin: str, requested_by: uuid.UUID | None) -> Calculation:
    items = _plan_items(uow, plan)
    if not items:
        raise ValidationFailed("Add at least one piece before calculating", code="plan_has_no_items")
    values = _plan_values(plan)
    locks = config.locked_decor_keys(uow)
    specs = _specs([_item_dict(i) for i in items])
    ps = _pack_settings(values, locks)
    result = _run_pack(specs, ps)
    calc = _persist(uow, plan, values, specs, ps, result, origin, requested_by)
    was_verified = plan.verified_at is not None and _verification_matches(plan, values)
    plan.calc_count = calc.calc_no
    plan.latest_calculation_id = calc.id
    plan.status = "calculated" if plan.status == "draft" else plan.status
    plan.inputs_changed_since_calc = False
    plan.requires_physical_verification = result.requires_physical_verification
    if not result.requires_physical_verification or not was_verified:
        plan.verified_at = None
        plan.verified_by = None
        if not result.requires_physical_verification:
            plan.verification = None
    plan.calc_status = "idle"
    plan.calc_job_id = None
    plan.calc_error = None
    plan.updated_at = uow.now()
    uow.flush()
    uow.emit(
        ev.PLAN_CALCULATED,
        aggregate_id=plan.id,
        aggregate_version=plan.version,
        payload=ev.payload(
            ev.PlanCalculatedPayload(
                plan_id=plan.id, calculation_id=calc.id, calc_no=calc.calc_no, input_hash=calc.input_hash,
                requires_physical_verification=calc.requires_physical_verification,
            )
        ),
    )
    if plan.requires_physical_verification and plan.verified_at is None:
        uow.emit(ev.PLAN_VERIFICATION_REQUIRED, aggregate_id=plan.id, aggregate_version=plan.version,
                 payload=ev.payload(ev.PlanRefPayload(plan_id=plan.id)))
    uow.audit("cutting.plan.calculated", resource_type="cutting.plan", resource_id=plan.id,
              resource_label=plan.plan_number, details={"calc_no": calc.calc_no, "origin": origin, "boards": calc.boards})
    return calc


def _verification_matches(plan: Plan, values: Mapping[str, Any]) -> bool:
    v = plan.verification or {}
    read = _settings_read(values)
    try:
        return Decimal(v["measured_length_mm"]) >= read.raw_length_mm and Decimal(v["measured_width_mm"]) >= read.raw_width_mm
    except (KeyError, TypeError, ArithmeticError):
        return False


def calculate_stateless(uow: UnitOfWork, data: CalculateIn) -> CalculationResult:
    """Legacy parity: calculate without saving (up to the synchronous piece limit)."""
    uow.actor.require(RUN)
    errors = Errors()
    warnings: list[str] = []
    values = _company_defaults(uow)
    _apply_settings(uow, values, data.settings, errors)
    rows = _item_values(uow, data.items, errors, warnings)
    pieces = sum(i.quantity for i in data.items)
    if pieces > SYNC_PIECE_LIMIT:
        errors.add(["items"], "cutting_sync_limit_exceeded",
                   f"Calculate at most {SYNC_PIECE_LIMIT} pieces without saving; save a plan to calculate {pieces}")
    errors.raise_if_any()
    locks = config.locked_decor_keys(uow)
    specs = _specs(rows)
    ps = _pack_settings(values, locks)
    result = _run_pack(specs, ps)
    decors = {s.decor_key for s in specs}
    return CalculationResult(
        algorithm_version=result.algorithm_version,
        mode=ps.mode,  # type: ignore[arg-type]
        input_hash=input_hash(specs, ps),
        result_hash=result.result_hash,
        requires_physical_verification=result.requires_physical_verification,
        totals=_totals_read(_totals_from_result(result)),
        groups=compose_groups(_rows_from_result(result), None),
        settings=_settings_read(values),
        grain_locked_decors=sorted(locks & decors),
    )


# =====================================================================================================
# reads
# =====================================================================================================
def _calc_state(plan: Plan, pieces: int) -> CalcStateRead:
    return CalcStateRead(
        status=plan.calc_status,  # type: ignore[arg-type]
        requested_at=plan.calc_requested_at,
        error=plan.calc_error,
        pieces=pieces,
        sync_piece_limit=SYNC_PIECE_LIMIT,
        max_pieces=MAX_PIECES,
    )


def _verification(uow: UnitOfWork, plan: Plan, values: Mapping[str, Any]) -> VerificationRead:
    read = _settings_read(values)
    return VerificationRead(
        required=plan.requires_physical_verification,
        verified=plan.verified_at is not None,
        verified_at=plan.verified_at,
        verified_by=_user(uow, plan.verified_by),
        assumed_length_mm=read.raw_length_mm if plan.requires_physical_verification else None,
        assumed_width_mm=read.raw_width_mm if plan.requires_physical_verification else None,
        measured=plan.verification,
    )


def _capabilities(uow: UnitOfWork, plan: Plan) -> dict[str, Capability]:
    repo = uow.repo(Plan)
    caps = {k: Capability(**v) for k, v in repo.capabilities(plan, ["update", "export", "transition"]).items()}
    can_run = uow.actor.can(RUN)
    caps["calculate"] = Capability(
        allowed=caps["update"].allowed and can_run,
        reason_code=None if caps["update"].allowed and can_run else (caps["update"].reason_code or "permission_denied"),
    )
    can_create = uow.actor.can(CREATE)
    caps["duplicate"] = Capability(allowed=can_create, reason_code=None if can_create else "permission_denied")
    needs = plan.requires_physical_verification and plan.verified_at is None and plan.latest_calculation_id is not None
    verify_ok = caps["transition"].allowed and needs and plan.status in ("draft", "calculated")
    caps["verify"] = Capability(
        allowed=verify_ok,
        reason_code=None if verify_ok else (caps["transition"].reason_code if not caps["transition"].allowed else "verification_not_required"),
    )
    return caps


def _transitions(caps: Mapping[str, Capability]) -> list[TransitionRead]:
    out: list[TransitionRead] = []
    if caps["verify"].allowed:
        out.append(TransitionRead(action="verify_boards", to_status="calculated"))
    if caps["transition"].allowed:
        out.append(TransitionRead(action="archive", to_status="archived"))
    return out


def detail(uow: UnitOfWork, plan: Plan) -> PlanDetail:
    items = _plan_items(uow, plan)
    values = _plan_values(plan)
    caps = _capabilities(uow, plan)
    latest = None
    if plan.latest_calculation_id is not None:
        calc = uow.repo(Calculation).get(plan.latest_calculation_id)
        latest = calculation_read(uow, calc)
    history = list(
        uow.session.scalars(
            uow.repo(Calculation).select().where(Calculation.plan_id == plan.id).order_by(Calculation.calc_no.desc()).limit(20)
        )
    )
    users = _users(uow, [plan.owner_user_id, *(c.created_by for c in history)])
    source = None
    if plan.duplicated_from_id is not None:
        source = uow.session.scalar(
            uow.repo(Plan).select().with_only_columns(Plan.plan_number).where(Plan.id == plan.duplicated_from_id)
        )
    exports: dict[str, str] = {}
    if caps["export"].allowed:
        base = _api_plan(plan.id)
        exports = {"csv": f"{base}/export.csv", "summary_csv": f"{base}/export.csv?kind=summary", "pdf": f"{base}/export.pdf"}
    warnings = [f"Line {i.line_no}: decor {i.decor} is {i.decor_key}" for i in items if i.decor and i.decor != i.decor_key and i.decor_key]
    warnings += [f"Line {i.line_no}: no decor, so the piece is treated as grain-locked" for i in items if not i.decor_key]
    return PlanDetail(
        id=plan.id,
        plan_number=plan.plan_number,
        name=plan.name,
        notes=plan.notes,
        status=plan.status,  # type: ignore[arg-type]
        owner=users.get(plan.owner_user_id) or UserRef(id=plan.owner_user_id, display_name=None),
        branch_id=plan.branch_id,
        created_at=plan.created_at,
        updated_at=plan.updated_at,
        version=plan.version,
        duplicated_from=source,
        items=[
            PlanItemRead(
                id=i.id, line_no=i.line_no, product_id=i.product_id, sku=i.sku, decor=i.decor, decor_key=i.decor_key,
                thickness_mm=plain(i.thickness_mm), length_mm=plain(i.length_mm), width_mm=plain(i.width_mm),  # type: ignore[arg-type]
                quantity=i.quantity, grain_rule=i.grain_rule, label=i.label,  # type: ignore[arg-type]
            )
            for i in items
        ],
        settings=_settings_read(values),
        stale=plan.inputs_changed_since_calc,
        calculation=_calc_state(plan, sum(i.quantity for i in items)),
        verification=_verification(uow, plan, values),
        latest_calculation=latest,
        calculations=[
            CalculationSummary(
                id=c.id, calc_no=c.calc_no, created_at=c.created_at,
                created_by=users.get(c.created_by) if c.created_by else None, origin=c.origin,  # type: ignore[arg-type]
                boards=c.boards, efficiency_usable_pct=Decimal(c.efficiency_usable_pct).quantize(_PCT), unfit=c.unfit,
                requires_physical_verification=c.requires_physical_verification, input_hash=c.input_hash,
                result_hash=c.result_hash,
            )
            for c in history
        ],
        capabilities=caps,
        allowed_transitions=_transitions(caps),
        exports=exports,
        path=plan_path(plan.id),
        warnings=warnings,
    )


def get_plan(uow: UnitOfWork, plan_id: uuid.UUID) -> PlanDetail:
    return detail(uow, uow.repo(Plan).get(plan_id))


def get_calculation(uow: UnitOfWork, plan_id: uuid.UUID, calc_no: int) -> CalculationRead:
    plan = uow.repo(Plan).get(plan_id)
    calc = uow.session.scalars(
        uow.repo(Calculation).select().where(Calculation.plan_id == plan.id, Calculation.calc_no == calc_no)
    ).first()
    if calc is None:
        from app.core.errors import NotFound

        raise NotFound(code="not_found", resource_type="cutting.calculation")
    return calculation_read(uow, calc)


def list_plans(uow: UnitOfWork, filters: PlanFilters, *, limit: int = 25, offset: int = 0) -> Page[PlanSummary]:
    uow.actor.require(READ)
    repo = uow.repo(Plan)
    conds = []
    if filters.q and (parts := tokens(filters.q)):
        for t in parts:
            pattern = contains_pattern(t)
            conds.append(or_(Plan.plan_number.ilike(pattern, escape=LIKE_ESCAPE), Plan.name.ilike(pattern, escape=LIKE_ESCAPE)))
    if filters.status:
        conds.append(Plan.status.in_(filters.status))
    elif not filters.include_archived:
        conds.append(Plan.status != "archived")
    if filters.scope == "mine":
        conds.append(Plan.owner_user_id == uow.actor.user_id)
    page = repo.list(*conds, order_by=[Plan.updated_at.desc(), Plan.id.desc()], limit=min(limit, MAX_LIMIT), offset=offset)
    plans = list(page.items)
    ids = [p.id for p in plans]
    counts = {
        r[0]: (int(r[1]), int(r[2] or 0))
        for r in uow.session.execute(
            select(PlanItem.plan_id, func.count(PlanItem.id), func.sum(PlanItem.quantity))
            .where(uow.repo(PlanItem).clause(), PlanItem.plan_id.in_(ids))
            .group_by(PlanItem.plan_id)
        )
    } if ids else {}
    calc_ids = [p.latest_calculation_id for p in plans if p.latest_calculation_id]
    calcs = {
        r[0]: (r[1], r[2])
        for r in uow.session.execute(
            select(Calculation.id, Calculation.boards, Calculation.efficiency_usable_pct).where(
                uow.repo(Calculation).clause(), Calculation.id.in_(calc_ids)
            )
        )
    } if calc_ids else {}
    users = _users(uow, [p.owner_user_id for p in plans])
    items = []
    for p in plans:
        n_items, n_pieces = counts.get(p.id, (0, 0))
        calc = calcs.get(p.latest_calculation_id) if p.latest_calculation_id else None
        items.append(
            PlanSummary(
                id=p.id, plan_number=p.plan_number, name=p.name, status=p.status,  # type: ignore[arg-type]
                owner=users.get(p.owner_user_id) or UserRef(id=p.owner_user_id, display_name=None),
                item_count=n_items, piece_count=n_pieces, boards=calc[0] if calc else None,
                efficiency_usable_pct=Decimal(calc[1]).quantize(_PCT) if calc else None,
                requires_physical_verification=p.requires_physical_verification, verified=p.verified_at is not None,
                stale=p.inputs_changed_since_calc, calc_status=p.calc_status,  # type: ignore[arg-type]
                updated_at=p.updated_at, version=p.version, path=plan_path(p.id),
            )
        )
    return Page[PlanSummary](items=items, total=page.total, limit=page.limit, offset=page.offset)


# =====================================================================================================
# commands
# =====================================================================================================
def _emit_saved(uow: UnitOfWork, plan: Plan) -> None:
    uow.emit(
        ev.PLAN_SAVED,
        aggregate_id=plan.id,
        aggregate_version=plan.version,
        payload=ev.payload(ev.PlanSavedPayload(plan_id=plan.id, plan_number=plan.plan_number, owner_user_id=plan.owner_user_id)),
    )


def create_plan(uow: UnitOfWork, data: PlanCreate) -> Plan:
    actor = uow.actor
    actor.require(CREATE)
    errors = Errors()
    warnings: list[str] = []
    values = _company_defaults(uow)
    _apply_settings(uow, values, data.settings, errors)
    rows = _item_values(uow, data.items, errors, warnings)
    errors.raise_if_any()
    if actor.user_id is None:
        raise ValidationFailed("A cut plan needs an owning user", code="owner_required")
    plan = Plan(
        id=new_id(),
        name=data.name,
        notes=data.notes or None,
        status="draft",
        owner_user_id=actor.user_id,
        branch_id=sorted(actor.branch_ids)[0] if actor.branch_ids else None,
        calc_status="idle",
        **values,
    )
    plan.plan_number = uow.allocate_number(
        ev.PLAN_SEQUENCE.key, document_date=_business_date(uow), resource_type="cutting.plan", resource_id=plan.id
    )
    uow.add(plan)
    uow.flush()
    for r in rows:
        uow.add(PlanItem(plan_id=plan.id, **r))
    uow.flush()
    _emit_saved(uow, plan)
    uow.audit("cutting.plan.created", resource_type="cutting.plan", resource_id=plan.id,
              resource_label=f"{plan.plan_number} · {plan.name}")
    return plan


def _locked(uow: UnitOfWork, plan_id: uuid.UUID, action: str) -> Plan:
    return uow.repo(Plan).get(plan_id, action, for_update=True)


def update_plan(uow: UnitOfWork, plan_id: uuid.UUID, data: PlanUpdate) -> Plan:
    plan = _locked(uow, plan_id, "update")
    uow.expect_version(plan, data.expected_version)
    errors = Errors()
    warnings: list[str] = []
    changed: set[str] = set()
    if data.name is not None and data.name != plan.name:
        plan.name = data.name
        changed.add("name")
    if "notes" in data.model_fields_set and (data.notes or None) != plan.notes:
        plan.notes = data.notes or None
        changed.add("notes")
    values = _plan_values(plan)
    settings_changed = _apply_settings(uow, values, data.settings, errors)
    rows = _item_values(uow, data.items, errors, warnings) if data.items is not None else None
    errors.raise_if_any()
    for f in settings_changed:
        setattr(plan, f, values[f])
    items_changed = False
    if rows is not None:
        current = [_item_dict(i) for i in _plan_items(uow, plan)]
        normalised = [{**r, "thickness_mm": plain(r["thickness_mm"]), "length_mm": plain(r["length_mm"]),
                       "width_mm": plain(r["width_mm"])} for r in rows]
        if normalised != current:
            _replace_items(uow, plan, rows)
            items_changed = True
    if settings_changed or items_changed:
        changed |= settings_changed | ({"items"} if items_changed else set())
        if plan.latest_calculation_id is not None:
            plan.inputs_changed_since_calc = True
        if plan.calc_status == "failed":
            plan.calc_status, plan.calc_error = "idle", None
    if changed:
        plan.updated_at = uow.now()
        uow.flush()
        _emit_saved(uow, plan)
        uow.audit("cutting.plan.updated", resource_type="cutting.plan", resource_id=plan.id,
                  resource_label=plan.plan_number, details={"changed": sorted(changed)})
    return plan


def duplicate_plan(uow: UnitOfWork, plan_id: uuid.UUID) -> Plan:
    """A new draft with the source's inputs and settings (never its calculations); owned by the actor."""
    source = uow.repo(Plan).get(plan_id)
    uow.actor.require(CREATE)
    items = [_item_dict(i) for i in _plan_items(uow, source)]
    values = _plan_values(source)
    copy = Plan(
        id=new_id(),
        name=f"Copy of {source.name}"[:200],
        notes=source.notes,
        status="draft",
        owner_user_id=uow.actor.user_id,
        branch_id=sorted(uow.actor.branch_ids)[0] if uow.actor.branch_ids else source.branch_id,
        duplicated_from_id=source.id,
        calc_status="idle",
        **values,
    )
    copy.plan_number = uow.allocate_number(
        ev.PLAN_SEQUENCE.key, document_date=_business_date(uow), resource_type="cutting.plan", resource_id=copy.id
    )
    uow.add(copy)
    uow.flush()
    for r in items:
        uow.add(PlanItem(plan_id=copy.id, **r))
    uow.flush()
    _emit_saved(uow, copy)
    uow.audit("cutting.plan.duplicated", resource_type="cutting.plan", resource_id=copy.id,
              resource_label=copy.plan_number, details={"source": source.plan_number})
    return copy


def transition_plan(uow: UnitOfWork, plan_id: uuid.UUID, data: PlanTransition) -> Plan:
    plan = _locked(uow, plan_id, "transition")
    uow.expect_version(plan, data.expected_version)
    if data.action == "archive":
        if plan.calc_status in ("queued", "running"):
            raise Conflict("Wait for the running calculation to finish", code="calculation_in_progress")
        plan.status = "archived"
        plan.archived_at = uow.now()
        plan.archived_by = uow.actor.user_id
        uow.flush()
        uow.emit(ev.PLAN_ARCHIVED, aggregate_id=plan.id, aggregate_version=plan.version,
                 payload=ev.payload(ev.PlanRefPayload(plan_id=plan.id)))
        uow.audit("cutting.plan.archived", resource_type="cutting.plan", resource_id=plan.id,
                  resource_label=plan.plan_number, reason=data.reason)
    return plan


def verify_boards(uow: UnitOfWork, plan_id: uuid.UUID, data: VerifyBoards) -> Plan:
    """Compare measured raw boards with the assumed oversize board: equal or larger verifies the plan; smaller marks
    it stale (recalculate without oversize or with the measured size)."""
    plan = _locked(uow, plan_id, "transition")
    uow.expect_version(plan, data.expected_version)
    if not (plan.requires_physical_verification and plan.latest_calculation_id is not None and plan.verified_at is None):
        raise Conflict("This plan does not need a board verification", code="verification_not_required")
    read = _settings_read(_plan_values(plan))
    ok = data.measured_length_mm >= read.raw_length_mm and data.measured_width_mm >= read.raw_width_mm
    plan.verification = {
        "measured_length_mm": format(data.measured_length_mm, "f"),
        "measured_width_mm": format(data.measured_width_mm, "f"),
        "assumed_length_mm": format(read.raw_length_mm, "f"),
        "assumed_width_mm": format(read.raw_width_mm, "f"),
        "outcome": "verified" if ok else "smaller_than_assumed",
        "note": data.note,
        "measured_by": str(uow.actor.user_id) if uow.actor.user_id else None,
        "measured_at": uow.now().isoformat(),
    }
    if ok:
        plan.verified_at = uow.now()
        plan.verified_by = uow.actor.user_id
    else:
        plan.inputs_changed_since_calc = True
    plan.updated_at = uow.now()
    uow.flush()
    if ok:
        uow.emit(ev.PLAN_VERIFIED, aggregate_id=plan.id, aggregate_version=plan.version,
                 payload=ev.payload(ev.PlanRefPayload(plan_id=plan.id)))
    uow.audit("cutting.plan.boards_verified" if ok else "cutting.plan.boards_too_small", resource_type="cutting.plan",
              resource_id=plan.id, resource_label=plan.plan_number, details=plan.verification)
    return plan


def request_calculation(uow: UnitOfWork, plan_id: uuid.UUID, data: PlanCommand) -> Plan:
    """Calculate now (up to the synchronous piece limit) or queue the durable calculation job (up to the hard cap)."""
    uow.actor.require(RUN)
    plan = _locked(uow, plan_id, "update")
    uow.expect_version(plan, data.expected_version)
    if plan.calc_status in ("queued", "running"):
        return plan
    pieces = sum(i.quantity for i in _plan_items(uow, plan))
    if pieces == 0:
        raise ValidationFailed("Add at least one piece before calculating", code="plan_has_no_items")
    if pieces > MAX_PIECES:
        raise ValidationFailed(f"A plan holds at most {MAX_PIECES} pieces", code="cutting_input_too_large")
    if pieces <= SYNC_PIECE_LIMIT:
        _calculate(uow, plan, "sync", uow.actor.user_id)
        return plan
    plan.calc_status = "queued"
    plan.calc_requested_at = uow.now()
    plan.calc_error = None
    plan.updated_at = uow.now()
    uow.flush()
    plan.calc_job_id = uow.enqueue(
        CALC_JOB,
        {"plan_id": str(plan.id), "requested_by": str(uow.actor.user_id) if uow.actor.user_id else None},
        dedupe_key=f"{CALC_JOB}:{plan.id}:{plan.version}",
        resource_type="cutting.plan",
        resource_id=plan.id,
    )
    uow.flush()
    return plan


def calculation_job(ctx: Any, payload: dict[str, Any]) -> dict[str, Any] | None:
    """``cutting.calculate``: the durable path for large plans (system actor of the plan's company)."""
    uow: UnitOfWork = ctx.uow
    plan_id = uuid.UUID(str(payload["plan_id"]))
    requested_by = uuid.UUID(payload["requested_by"]) if payload.get("requested_by") else None
    plan = uow.session.scalars(
        uow.repo(Plan).select().where(Plan.id == plan_id).with_for_update()
    ).first()
    if plan is None:
        raise PermanentJobError(f"plan {plan_id} not found")
    if plan.calc_status != "queued":
        return {"skipped": True, "status": plan.calc_status}
    try:
        with uow.session.begin_nested():
            calc = _calculate(uow, plan, "job", requested_by)
        return {"calculation_id": str(calc.id), "calc_no": calc.calc_no, "boards": calc.boards}
    except Exception as exc:  # noqa: BLE001 - every failure is reported on the plan, never left queued
        uow.session.refresh(plan)
        code = getattr(exc, "code", None) or "calculation_failed"
        plan.calc_status = "failed"
        plan.calc_error = {"code": code, "detail": str(getattr(exc, "detail", exc))[:500]}
        plan.calc_job_id = None
        plan.updated_at = uow.now()
        uow.flush()
        return {"failed": True, "code": code}


# ---- idempotent command wrappers (routers) ----------------------------------------------------------
def create_plan_command(uow: UnitOfWork, data: PlanCreate) -> tuple[PlanDetail, bool]:
    uow.actor.require(CREATE)
    return idempotent(uow, "cutting.create_plan", data, lambda: detail(uow, create_plan(uow, data)), PlanDetail, status=201)


def update_plan_command(uow: UnitOfWork, plan_id: uuid.UUID, data: PlanUpdate) -> tuple[PlanDetail, bool]:
    uow.repo(Plan).get(plan_id, "update")
    return idempotent(uow, f"cutting.update_plan:{plan_id}", data, lambda: detail(uow, update_plan(uow, plan_id, data)), PlanDetail)


def duplicate_plan_command(uow: UnitOfWork, plan_id: uuid.UUID) -> tuple[PlanDetail, bool]:
    uow.repo(Plan).get(plan_id)
    return idempotent(uow, f"cutting.duplicate_plan:{plan_id}", {}, lambda: detail(uow, duplicate_plan(uow, plan_id)), PlanDetail, status=201)


def calculate_plan_command(uow: UnitOfWork, plan_id: uuid.UUID, data: PlanCommand) -> tuple[PlanDetail, bool]:
    uow.repo(Plan).get(plan_id, "update")
    return idempotent(uow, f"cutting.calculate_plan:{plan_id}", data,
                      lambda: detail(uow, request_calculation(uow, plan_id, data)), PlanDetail)


def transition_plan_command(uow: UnitOfWork, plan_id: uuid.UUID, data: PlanTransition) -> tuple[PlanDetail, bool]:
    uow.repo(Plan).get(plan_id, "transition")
    return idempotent(uow, f"cutting.transition_plan:{plan_id}", data,
                      lambda: detail(uow, transition_plan(uow, plan_id, data)), PlanDetail)


def verify_boards_command(uow: UnitOfWork, plan_id: uuid.UUID, data: VerifyBoards) -> tuple[PlanDetail, bool]:
    uow.repo(Plan).get(plan_id, "transition")
    return idempotent(uow, f"cutting.verify_boards:{plan_id}", data,
                      lambda: detail(uow, verify_boards(uow, plan_id, data)), PlanDetail)


# =====================================================================================================
# catalogue autocomplete
# =====================================================================================================
def search_products(uow: UnitOfWork, search: str, *, limit: int = 10) -> list[CuttingProduct]:
    """Live catalogue products matching ``search`` (the catalogue's own scoped search), with decor, thickness and
    dimensions for the cut list; empty without ``catalogue.product.read``."""
    uow.actor.require(RUN)
    if not search.strip() or not uow.actor.can("catalogue.product.read"):
        return []
    page = catalogue.list_products(uow, ProductFilters(q=search.strip()), sort="relevance", limit=max(1, min(limit, 25)))
    locks = config.locked_decor_keys(uow)
    out: list[CuttingProduct] = []
    for p in page.items:
        decor_key, _w = canonical_decor(p.decor_no)
        out.append(
            CuttingProduct(
                product_id=p.id, product_key=p.product_key, display_sku=p.display_sku, product_name=p.product_name,
                decor=p.decor_no, decor_key=decor_key, decor_name=p.decor_name,
                thickness_mm=p.thickness_mm, length_mm=p.size.length_mm, width_mm=p.size.width_mm,
                grain_locked=bool(decor_key) and decor_key in locks,
            )
        )
    return out
