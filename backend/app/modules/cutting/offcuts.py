"""Offcut reuse (Slice 5): a cut plan may cut from measured offcut lots before it opens standard sheets.

- **Candidates** are the offcut lots on hand (``inventory.offcut_lots``: measured, positive balance in an internal
  location of a warehouse the actor may read). Each carries the decor of its product and the thickness the optimiser
  groups on (the lot's measured thickness, else the product's), and whether a group of the plan matches it.
- **Selection** (``PUT /cutting/plans/{id}/offcuts``) is a plan input like the items: it needs ``update`` on the plan
  and every lot must be a candidate right now (``422 offcut_not_available`` otherwise: consumed, unmeasured, in an
  invisible warehouse or unknown are one answer). The measured size is pinned with the grain along the length (a lot
  measured with its grain across the width is stored turned). Changing it marks a calculated plan stale.
- **Calculation** passes the selection to the packer as stock boards (``StockBoard(ref=<lot id>)``); boards cut from
  an offcut are stored with ``source='offcut'`` and ``lot_id``.
- **Release**: ``planned_offcuts`` names the lots the plan's current calculation cuts from; production issues them to
  the work order's WIP when the plan is released for it (a lot no longer on hand there is a 409 then).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal

from sqlalchemy import select

from app.core.errors import ValidationFailed
from app.modules.cutting.canonical import canonical_decor, thickness_key
from app.modules.cutting.config import plain
from app.modules.cutting.models import CalcBoard, Plan, PlanItem, PlanOffcut
from app.modules.cutting.packer.engine import StockBoard
from app.modules.cutting.packer.geometry import mm_to_dmm
from app.modules.cutting.schemas import OffcutCandidate, OffcutCandidates, PlanOffcutRead, PlanOffcutsUpdate
from app.modules.inventory import service as inventory
from app.platform.uow import UnitOfWork

MAX_SELECTED = 50


@dataclass(frozen=True)
class _Lot:
    lot: inventory.OffcutLot
    decor_key: str
    thickness_key: str
    product_key: str | None
    product_name: str | None


def _decors(uow: UnitOfWork, product_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, tuple[str | None, str, str, Decimal | None]]:
    """(decor, product key, name, thickness) of visible catalogue products (the catalogue's own read scope)."""
    from app.modules.catalogue import service as catalogue
    from app.modules.catalogue.models import Product

    ids = list(set(product_ids))
    if not ids or not uow.actor.can("catalogue.product.read"):
        return {}
    refs = catalogue.product_refs(uow, ids)
    decors = dict(uow.session.execute(
        select(Product.id, Product.decor_no).where(uow.repo(Product).clause("read"), Product.id.in_(ids))
    ).all())
    return {pid: (decors.get(pid), ref.product_key, ref.product_name, ref.thickness_mm) for pid, ref in refs.items()}


def _lots(uow: UnitOfWork, *, lot_ids: Sequence[uuid.UUID] | None = None) -> list[_Lot]:
    lots = inventory.offcut_lots(uow, lot_ids=lot_ids)
    info = _decors(uow, [lt.product_id for lt in lots])
    out: list[_Lot] = []
    seen: set[uuid.UUID] = set()
    for lt in lots:
        if lt.lot_id in seen:  # one row per lot (a lot sits in one bin; guard against a split balance)
            continue
        seen.add(lt.lot_id)
        decor, key, name, product_thickness = info.get(lt.product_id, (None, None, None, None))
        decor_key, _w = canonical_decor(decor)
        out.append(_Lot(lt, decor_key, thickness_key(lt.thickness_mm or product_thickness), key, name))
    return out


def _groups(uow: UnitOfWork, plan: Plan) -> set[tuple[str, str]]:
    items = uow.session.scalars(uow.repo(PlanItem).select().where(PlanItem.plan_id == plan.id))
    return {(i.decor_key, thickness_key(i.thickness_mm)) for i in items}


def plan_offcuts(uow: UnitOfWork, plan: Plan) -> list[PlanOffcut]:
    return list(uow.session.scalars(
        uow.repo(PlanOffcut).select().where(PlanOffcut.plan_id == plan.id).order_by(PlanOffcut.seq)
    ))


def stock_boards(rows: Sequence[PlanOffcut]) -> list[StockBoard]:
    return [
        StockBoard(ref=str(r.lot_id), decor_key=r.decor_key, thickness_key=r.thickness_key,
                   length_dmm=mm_to_dmm(plain(Decimal(r.length_mm))),  # type: ignore[arg-type]
                   width_dmm=mm_to_dmm(plain(Decimal(r.width_mm))))  # type: ignore[arg-type]
        for r in rows
    ]


def snapshot(rows: Sequence[PlanOffcut]) -> list[dict[str, str | int | None]]:
    return [
        {"seq": r.seq, "lot_id": str(r.lot_id), "lot_code": r.lot_code, "decor_key": r.decor_key,
         "thickness": r.thickness_key, "length_mm": format(plain(Decimal(r.length_mm)), "f"),
         "width_mm": format(plain(Decimal(r.width_mm)), "f"), "grain_axis": r.grain_axis}
        for r in rows
    ]


def _used_lot_ids(uow: UnitOfWork, calculation_id: uuid.UUID | None) -> set[uuid.UUID]:
    if calculation_id is None:
        return set()
    return {lid for lid in uow.session.scalars(
        select(CalcBoard.lot_id).where(CalcBoard.calculation_id == calculation_id, CalcBoard.source == "offcut")
    ) if lid is not None}


def reads(uow: UnitOfWork, plan: Plan) -> list[PlanOffcutRead]:
    rows = plan_offcuts(uow, plan)
    if not rows:
        return []
    stock = uow.actor.can("inventory.stock.read")
    on_hand = {lt.lot_id for lt in inventory.offcut_lots(uow, lot_ids=[r.lot_id for r in rows])} if stock else set()
    used = _used_lot_ids(uow, plan.latest_calculation_id)
    groups = _groups(uow, plan)
    return [
        PlanOffcutRead(
            seq=r.seq, lot_id=r.lot_id, lot_code=r.lot_code, product_id=r.product_id, decor_key=r.decor_key,
            thickness_mm=r.thickness_key, length_mm=plain(r.length_mm), width_mm=plain(r.width_mm),  # type: ignore[arg-type]
            grain_axis=r.grain_axis,  # type: ignore[arg-type]
            on_hand=(r.lot_id in on_hand) if stock else None, used=r.lot_id in used,
            matches_group=(r.decor_key, r.thickness_key) in groups,
        )
        for r in rows
    ]


def candidates(uow: UnitOfWork, plan_id: uuid.UUID) -> OffcutCandidates:
    plan = uow.repo(Plan).get(plan_id)  # 404 for an invisible plan
    if not uow.actor.can("inventory.stock.read"):
        return OffcutCandidates(items=[], stock_visible=False)
    groups = _groups(uow, plan)
    selected = {r.lot_id for r in plan_offcuts(uow, plan)}
    lots = _lots(uow)
    others: dict[uuid.UUID, list[str]] = {}
    if lots:
        rows = uow.session.execute(
            select(PlanOffcut.lot_id, Plan.plan_number)
            .join(Plan, Plan.id == PlanOffcut.plan_id)
            .where(uow.repo(Plan).clause("read"), PlanOffcut.lot_id.in_([x.lot.lot_id for x in lots]),
                   Plan.id != plan.id, Plan.status.in_(("draft", "calculated", "released")))
            .order_by(Plan.plan_number)
        ).all()
        for lot_id, number in rows:
            others.setdefault(lot_id, []).append(number)
    items = [
        OffcutCandidate(
            lot_id=x.lot.lot_id, lot_code=x.lot.lot_code, product_id=x.lot.product_id, product_key=x.product_key,
            product_name=x.product_name, warehouse_id=x.lot.warehouse_id, warehouse_code=x.lot.warehouse_code,
            location_code=x.lot.location_code, length_mm=plain(x.lot.length_mm), width_mm=plain(x.lot.width_mm),  # type: ignore[arg-type]
            thickness_mm=plain(x.lot.thickness_mm) if x.lot.thickness_mm is not None else None,  # type: ignore[arg-type]
            grain_axis=x.lot.grain_axis,  # type: ignore[arg-type]
            decor_key=x.decor_key, thickness_key=x.thickness_key,
            matches_group=(x.decor_key, x.thickness_key) in groups, selected=x.lot.lot_id in selected,
            other_plans=others.get(x.lot.lot_id, []),
        )
        for x in lots
    ]
    items.sort(key=lambda c: (not c.matches_group, not c.selected, c.lot_code))
    return OffcutCandidates(items=items, stock_visible=True)


def _pinned(x: _Lot) -> tuple[Decimal, Decimal]:
    """Measured size with the grain along the length (a lot measured with its grain across the width turns), mm."""
    length, width = x.lot.length_mm, x.lot.width_mm
    if x.lot.grain_axis == "width":
        length, width = width, length
    # the optimiser works in tenths of a millimetre: a finer measurement is rounded down (never assume more board)
    tenth = Decimal("0.1")
    return length.quantize(tenth, rounding=ROUND_FLOOR), width.quantize(tenth, rounding=ROUND_FLOOR)


def replace_selection(uow: UnitOfWork, plan_id: uuid.UUID, data: PlanOffcutsUpdate) -> tuple[Plan, bool]:
    """Replace the plan's offcut selection; returns (plan, changed). Unknown or no-longer-available lots are one
    422 (never confirming a lot of an invisible warehouse); a calculated plan whose selection changed is stale."""
    plan = uow.repo(Plan).get(plan_id, "update", for_update=True)
    uow.expect_version(plan, data.expected_version)
    if len(set(data.lot_ids)) != len(data.lot_ids):
        raise ValidationFailed("A lot is listed twice", errors=[
            {"loc": ["body", "lot_ids"], "msg": "each lot once", "code": "duplicate_lot"}])
    if data.lot_ids and not uow.actor.can("inventory.stock.read"):
        from app.core.errors import Forbidden

        raise Forbidden(code="permission_denied", permission="inventory.stock.read")
    found = {x.lot.lot_id: x for x in _lots(uow, lot_ids=data.lot_ids)} if data.lot_ids else {}
    errors = []
    for i, lot_id in enumerate(data.lot_ids):
        x = found.get(lot_id)
        if x is None:
            errors.append({"loc": ["body", "lot_ids", i], "msg": "not an offcut lot on hand with a measured size",
                           "code": "offcut_not_available"})
        elif not x.thickness_key:
            errors.append({"loc": ["body", "lot_ids", i], "msg": "the lot and its product record no thickness",
                           "code": "offcut_thickness_unknown"})
    if errors:
        raise ValidationFailed("Some offcut lots cannot be used", errors=errors)
    current = plan_offcuts(uow, plan)
    if [r.lot_id for r in current] == list(data.lot_ids):
        return plan, False
    for old in current:
        uow.session.delete(old)
    uow.flush()
    for seq, lot_id in enumerate(data.lot_ids, start=1):
        x = found[lot_id]
        length, width = _pinned(x)
        uow.add(PlanOffcut(
            plan_id=plan.id, seq=seq, lot_id=lot_id, lot_code=x.lot.lot_code, product_id=x.lot.product_id,
            decor_key=x.decor_key, thickness_key=x.thickness_key, length_mm=length, width_mm=width,
            grain_axis=x.lot.grain_axis,
        ))
    if plan.latest_calculation_id is not None:
        plan.inputs_changed_since_calc = True
    plan.updated_at = uow.now()
    uow.flush()
    uow.audit("cutting.plan.offcuts_changed", resource_type="cutting.plan", resource_id=plan.id,
              resource_label=plan.plan_number,
              details={"added": sorted(found[i].lot.lot_code for i in data.lot_ids if i not in {r.lot_id for r in current}),
                       "removed": sorted(r.lot_code for r in current if r.lot_id not in set(data.lot_ids))})
    return plan, True


def copy_selection(uow: UnitOfWork, source: Plan, target: Plan) -> None:
    for r in plan_offcuts(uow, source):
        uow.add(PlanOffcut(
            plan_id=target.id, seq=r.seq, lot_id=r.lot_id, lot_code=r.lot_code, product_id=r.product_id,
            decor_key=r.decor_key, thickness_key=r.thickness_key, length_mm=r.length_mm, width_mm=r.width_mm,
            grain_axis=r.grain_axis,
        ))


@dataclass(frozen=True)
class PlannedOffcut:
    lot_id: uuid.UUID
    lot_code: str
    product_id: uuid.UUID
    group_no: int
    board_no: int


def planned_offcuts(uow: UnitOfWork, plan: Plan) -> list[PlannedOffcut]:
    """The offcut lots the plan's current calculation cuts from (company-scoped; for production's release)."""
    if plan.latest_calculation_id is None:
        return []
    rows = uow.session.execute(
        select(CalcBoard.lot_id, CalcBoard.group_no, CalcBoard.board_no, PlanOffcut.lot_code, PlanOffcut.product_id)
        .join(PlanOffcut, (PlanOffcut.plan_id == plan.id) & (PlanOffcut.lot_id == CalcBoard.lot_id))
        .where(CalcBoard.company_id == uow.actor.company_id, CalcBoard.calculation_id == plan.latest_calculation_id,
               CalcBoard.source == "offcut")
        .order_by(CalcBoard.group_no, CalcBoard.board_no)
    ).all()
    return [PlannedOffcut(lot_id=r[0], lot_code=r[3], product_id=r[4], group_no=r[1], board_no=r[2]) for r in rows]

