"""Packing lists (``PK-YYYY-NNNN``): computed server-side from a packaging snapshot (see ``packing.py``).

- create from an order the actor can read (its open stock lines at the remaining quantity, chosen quantities, or a
  linked challan's lines); every line snapshots the product's canonical packaging;
- ``refresh`` re-snapshots a draft and clears the stale flag; an override enters a missing / conflicting CBM or weight
  with a reason; ``finalise`` is blocked while any line is incomplete or the list is stale; a final list never changes;
- the ``logistics.packing_list_staleness`` consumer flags drafts stale when a product's packaging changes
  (``catalogue.product.updated`` with ``packaging``) or the order changes (line / order cancelled) and emits
  ``became_stale`` once per transition.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import func, select

from app.core.errors import Conflict, NotFound
from app.core.http.pagination import Page
from app.modules.catalogue.models import Product, ProductPackaging
from app.modules.logistics import events as ev
from app.modules.logistics.enums import PackingListStatus
from app.modules.logistics.models import PackingList, PackingListLine
from app.modules.logistics.packing import Overrides, PackagingSnapshot, compute_line, totals
from app.modules.logistics.schemas import (
    DocRef,
    LineOverride,
    PackingLineRead,
    PackingListCreate,
    PackingListDetail,
    PackingListSummary,
)
from app.modules.procurement.common import business_date, cap, invalid, plain, require_scope
from app.platform.events.models import DomainEvent
from app.platform.events.service import once
from app.platform.uow import UnitOfWork

S = PackingListStatus
CREATE = "logistics.packing_list.create"
ZERO = Decimal(0)


def path(pl_id: uuid.UUID) -> str:
    return f"/operations/dispatch/packing-lists/{pl_id}"


def lines_of(uow: UnitOfWork, pl_id: uuid.UUID) -> list[PackingListLine]:
    return list(
        uow.session.scalars(
            select(PackingListLine)
            .where(PackingListLine.packing_list_id == pl_id)
            .order_by(PackingListLine.line_no)
        )
    )


def _snapshot(uow: UnitOfWork, product_id: uuid.UUID) -> tuple[PackagingSnapshot, dict[str, object]]:
    pk = uow.session.get(ProductPackaging, product_id)
    if pk is None:
        return PackagingSnapshot(), {"packing_type": None, "packaging_updated_at": None}
    snap = PackagingSnapshot(
        carton_qty=pk.carton_qty,
        inner_qty=pk.inner_qty,
        carton_length_cm=pk.carton_length_cm,
        carton_width_cm=pk.carton_width_cm,
        carton_height_cm=pk.carton_height_cm,
        stated_carton_cbm=pk.cbm,
        unit_weight_kg=(Decimal(pk.unit_weight_g) / 1000) if pk.unit_weight_g is not None else None,
        carton_net_kg=pk.net_weight_kg,
        carton_gross_kg=pk.gross_weight_kg,
        is_fragile=bool((pk.fragile_notes or "").strip()),
    )
    return snap, {"packing_type": pk.packing_type, "packaging_updated_at": pk.updated_at}


def _apply(
    line: PackingListLine, snap: PackagingSnapshot | None = None, extra: dict[str, object] | None = None
) -> None:
    if snap is not None:
        line.carton_qty, line.inner_qty = snap.carton_qty, snap.inner_qty
        line.carton_length_cm, line.carton_width_cm = snap.carton_length_cm, snap.carton_width_cm
        line.carton_height_cm, line.stated_carton_cbm = snap.carton_height_cm, snap.stated_carton_cbm
        line.unit_weight_kg, line.carton_net_kg = snap.unit_weight_kg, snap.carton_net_kg
        line.carton_gross_kg, line.is_fragile = snap.carton_gross_kg, snap.is_fragile
    if extra is not None:
        line.packing_type = extra["packing_type"]  # type: ignore[assignment]
        line.packaging_updated_at = extra["packaging_updated_at"]  # type: ignore[assignment]
    current = PackagingSnapshot(
        carton_qty=line.carton_qty,
        inner_qty=line.inner_qty,
        carton_length_cm=line.carton_length_cm,
        carton_width_cm=line.carton_width_cm,
        carton_height_cm=line.carton_height_cm,
        stated_carton_cbm=line.stated_carton_cbm,
        unit_weight_kg=line.unit_weight_kg,
        carton_net_kg=line.carton_net_kg,
        carton_gross_kg=line.carton_gross_kg,
        is_fragile=line.is_fragile,
    )
    r = compute_line(
        Decimal(line.quantity),
        current,
        Overrides(cbm=line.override_cbm, net_kg=line.override_net_kg, gross_kg=line.override_gross_kg),
    )
    line.full_cartons, line.loose_qty, line.cartons = r.full_cartons, r.loose_qty, r.cartons
    line.inner_packs, line.is_part_carton, line.carton_cbm = r.inner_packs, r.is_part_carton, r.carton_cbm
    line.cbm, line.net_kg, line.gross_kg = r.cbm, r.net_kg, r.gross_kg
    line.is_estimate, line.incomplete_reasons = r.is_estimate, list(r.incomplete_reasons)


def _retotal(uow: UnitOfWork, pl: PackingList, lines: list[PackingListLine]) -> None:
    from app.modules.logistics.packing import LineResult

    t = totals(
        [
            LineResult(
                full_cartons=ln.full_cartons,
                loose_qty=ln.loose_qty,
                cartons=ln.cartons,
                inner_packs=ln.inner_packs,
                is_part_carton=ln.is_part_carton,
                carton_cbm=ln.carton_cbm,
                cbm=ln.cbm,
                net_kg=ln.net_kg,
                gross_kg=ln.gross_kg,
                is_estimate=ln.is_estimate,
                incomplete_reasons=tuple(ln.incomplete_reasons),
            )
            for ln in lines
        ]
    )
    pl.total_cartons, pl.total_cbm, pl.total_net_kg, pl.total_gross_kg = (
        t.cartons,
        t.cbm,
        t.net_kg,
        t.gross_kg,
    )
    pl.totals_partial, pl.has_estimates = t.is_partial, t.has_estimates
    uow.flush()


def _order(uow: UnitOfWork, order_id: uuid.UUID):  # noqa: ANN202
    from app.modules.orders.models import SalesOrder

    return uow.repo(SalesOrder).get(order_id)


def create_packing_list(uow: UnitOfWork, data: PackingListCreate) -> PackingList:
    from app.modules.orders.models import SalesOrderLine

    uow.actor.require(CREATE)
    order = _order(uow, data.sales_order_id)
    if order.status in ("draft", "cancelled"):
        raise Conflict("Pack a confirmed order", code="invalid_status", current_status=order.status)
    order_lines = {
        ln.id: ln
        for ln in uow.session.scalars(
            select(SalesOrderLine).where(SalesOrderLine.order_id == order.id).order_by(SalesOrderLine.line_no)
        )
    }
    wanted: list[
        tuple[uuid.UUID | None, uuid.UUID, str, Decimal, str]
    ] = []  # (order line, product, text, qty, unit)
    challan_id = None
    if data.challan_id is not None:
        from app.modules.challans.models import Challan, ChallanLine

        challan = uow.repo(Challan).get(data.challan_id)
        if challan.sales_order_id != order.id:
            raise invalid("The challan belongs to another order", ["challan_id"], "challan_order_mismatch")
        challan_id = challan.id
        for cl in uow.session.scalars(
            select(ChallanLine).where(ChallanLine.challan_id == challan.id).order_by(ChallanLine.line_no)
        ):
            if cl.product_id is not None and not cl.is_non_stock:
                wanted.append(
                    (cl.sales_order_line_id, cl.product_id, cl.item_name, Decimal(cl.quantity), cl.uom_code)
                )
    elif data.quantities:
        for i, q in enumerate(data.quantities):
            ol = order_lines.get(q.sales_order_line_id)
            if ol is None or ol.product_id is None:
                raise invalid(
                    "The line is not a product line of this order",
                    ["quantities", i, "sales_order_line_id"],
                    "order_line_mismatch",
                )
            wanted.append((ol.id, ol.product_id, ol.description, Decimal(q.quantity), ol.uom_code))
    else:
        for ol in order_lines.values():
            if (
                ol.product_id is not None
                and Decimal(ol.qty_remaining) > 0
                and ol.fulfilment_mode != "non_stock"
            ):
                wanted.append((ol.id, ol.product_id, ol.description, Decimal(ol.qty_remaining), ol.uom_code))
    if not wanted:
        raise Conflict("Nothing to pack on this order", code="nothing_to_pack")
    pl = PackingList(
        id=uuid.uuid7(),
        company_id=uow.actor.company_id,
        packing_list_number="PK",
        status=S.DRAFT.value,
        sales_order_id=order.id,
        challan_id=challan_id,
        party_id=order.party_id,
        party_name=order.party_name,
        owner_user_id=order.owner_user_id,
        branch_id=order.branch_id,
        total_cbm=ZERO,
        total_net_kg=ZERO,
        total_gross_kg=ZERO,
        notes=data.notes,
    )
    pl.packing_list_number = uow.allocate_number(
        "logistics.packing_list",
        document_date=business_date(uow),
        resource_type="logistics.packing_list",
        resource_id=pl.id,
        branch_id=order.branch_id,
    )
    uow.add(pl)
    uow.flush()
    rows = []
    for n, (ol_id, product_id, text, qty, unit) in enumerate(wanted, start=1):
        line = PackingListLine(
            id=uuid.uuid7(),
            company_id=uow.actor.company_id,
            packing_list_id=pl.id,
            line_no=n,
            product_id=product_id,
            sales_order_line_id=ol_id,
            description=text[:300],
            quantity=qty,
            uom_code=unit,
        )
        snap, extra = _snapshot(uow, product_id)
        _apply(line, snap, extra)
        uow.add(line)
        rows.append(line)
    uow.flush()
    _retotal(uow, pl, rows)
    uow.audit(
        "logistics.packing_list.create",
        resource_type="logistics.packing_list",
        resource_id=pl.id,
        resource_label=pl.packing_list_number,
        details={"order_number": order.order_number},
    )
    return pl


def _locked(uow: UnitOfWork, pl_id: uuid.UUID) -> PackingList:
    return uow.repo(PackingList).get(pl_id, for_update=True)


def refresh(uow: UnitOfWork, pl_id: uuid.UUID, expected_version: int) -> PackingList:
    pl = _locked(uow, pl_id)
    uow.repo(PackingList).require_action(pl, "update")
    uow.expect_version(pl, expected_version)
    lines = lines_of(uow, pl.id)
    for ln in lines:
        snap, extra = _snapshot(uow, ln.product_id)
        _apply(ln, snap, extra)
    pl.is_stale, pl.stale_since, pl.stale_reason = False, None, None
    uow.flush()
    _retotal(uow, pl, lines)
    return pl


def override_line(uow: UnitOfWork, pl_id: uuid.UUID, line_id: uuid.UUID, data: LineOverride) -> PackingList:
    pl = _locked(uow, pl_id)
    uow.repo(PackingList).require_action(pl, "update")
    uow.expect_version(pl, data.expected_version)
    lines = lines_of(uow, pl.id)
    line = next((ln for ln in lines if ln.id == line_id), None)
    if line is None:
        raise NotFound(code="not_found", resource_type="logistics.packing_list_line")
    if data.cbm is None and data.net_kg is None and data.gross_kg is None:
        raise invalid("Enter at least one value", ["cbm"], "override_empty")
    line.override_cbm = data.cbm if data.cbm is not None else line.override_cbm
    line.override_net_kg = data.net_kg if data.net_kg is not None else line.override_net_kg
    line.override_gross_kg = data.gross_kg if data.gross_kg is not None else line.override_gross_kg
    line.override_reason = data.reason
    _apply(line)
    pl.updated_at = uow.now()
    uow.flush()
    _retotal(uow, pl, lines)
    return pl


def finalise(uow: UnitOfWork, pl_id: uuid.UUID, expected_version: int) -> PackingList:
    pl = _locked(uow, pl_id)
    require_scope(uow, PackingList, pl.id, "transition")
    uow.expect_version(pl, expected_version)
    if pl.status != S.DRAFT.value:
        raise Conflict("Only a draft is finalised", code="invalid_status", current_status=pl.status)
    if pl.is_stale:
        raise Conflict(
            "Refresh the packaging data first (it changed since this list was made)",
            code="packing_list_stale",
        )
    incomplete = [ln.line_no for ln in lines_of(uow, pl.id) if ln.incomplete_reasons]
    if incomplete:
        raise Conflict(
            "Some lines lack packaging data: enter the values with a reason",
            code="packing_list_incomplete",
            line_nos=incomplete,
        )
    pl.status, pl.finalised_at, pl.finalised_by = S.FINAL.value, uow.now(), uow.actor.user_id
    uow.flush()
    uow.emit(
        ev.PACKING_FINALISED,
        aggregate_id=pl.id,
        aggregate_version=pl.version,
        payload={"packing_list_id": str(pl.id)},
    )
    uow.audit(
        "logistics.packing_list.finalise",
        resource_type="logistics.packing_list",
        resource_id=pl.id,
        resource_label=pl.packing_list_number,
    )
    return pl


def cancel(uow: UnitOfWork, pl_id: uuid.UUID, expected_version: int) -> PackingList:
    pl = _locked(uow, pl_id)
    require_scope(uow, PackingList, pl.id, "transition")
    uow.expect_version(pl, expected_version)
    if pl.status != S.DRAFT.value:
        raise Conflict("Only a draft is cancelled", code="invalid_status", current_status=pl.status)
    pl.status = S.CANCELLED.value
    uow.flush()
    return pl


# ---- staleness consumer ------------------------------------------------------------------------------------------
def _mark_stale(uow: UnitOfWork, rows: list[PackingList], reason: str) -> int:
    n = 0
    for pl in rows:
        if pl.is_stale:
            continue
        pl.is_stale, pl.stale_since, pl.stale_reason = True, uow.now(), reason
        uow.flush()
        uow.emit(
            ev.PACKING_STALE,
            aggregate_id=pl.id,
            aggregate_version=pl.version,
            payload={"packing_list_id": str(pl.id)},
        )
        n += 1
    return n


def handle_staleness(uow: UnitOfWork, event: DomainEvent) -> None:
    if not once(uow, ev.STALENESS, event.id):
        return
    payload = event.payload or {}
    base = (
        select(PackingList)
        .where(PackingList.company_id == uow.actor.company_id, PackingList.status == S.DRAFT.value)
        .with_for_update()
    )
    if event.event_type == "catalogue.product.updated":
        if "packaging" not in (payload.get("changed_groups") or []):
            return
        pid = payload.get("product_id")
        if not pid:
            return
        ids = select(PackingListLine.packing_list_id).where(PackingListLine.product_id == uuid.UUID(str(pid)))
        _mark_stale(uow, list(uow.session.scalars(base.where(PackingList.id.in_(ids)))), "packaging_changed")
    else:
        oid = payload.get("order_id")
        if oid:
            _mark_stale(
                uow,
                list(uow.session.scalars(base.where(PackingList.sales_order_id == uuid.UUID(str(oid))))),
                "order_changed",
            )


# ---- reads ----------------------------------------------------------------------------------------------------------
def _summaries(uow: UnitOfWork, rows: list[PackingList]) -> list[dict]:  # type: ignore[type-arg]
    from app.modules.orders.models import SalesOrder

    orders = (
        {
            r[0]: r
            for r in uow.session.execute(
                select(SalesOrder.id, SalesOrder.order_number, SalesOrder.status).where(
                    SalesOrder.id.in_([p.sales_order_id for p in rows])
                )
            ).all()
        }
        if rows
        else {}
    )
    return [
        {
            "id": p.id,
            "packing_list_number": p.packing_list_number,
            "status": p.status,
            "order": DocRef(
                id=p.sales_order_id,
                number=orders[p.sales_order_id][1],
                status=orders[p.sales_order_id][2],
                path=f"/sales/orders/{p.sales_order_id}",
            ),
            "party_name": p.party_name,
            "total_cartons": p.total_cartons,
            "total_cbm": Decimal(p.total_cbm),
            "total_net_kg": Decimal(p.total_net_kg),
            "total_gross_kg": Decimal(p.total_gross_kg),
            "totals_partial": p.totals_partial,
            "has_estimates": p.has_estimates,
            "is_stale": p.is_stale,
            "created_at": p.created_at,
            "path": path(p.id),
            "version": p.version,
        }
        for p in rows
    ]


def list_packing_lists(
    uow: UnitOfWork,
    *,
    status: list[str] | None = None,
    sales_order_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> Page[PackingListSummary]:
    repo = uow.repo(PackingList)
    filters = []
    if status:
        filters.append(PackingList.status.in_(status))
    if sales_order_id is not None:
        filters.append(PackingList.sales_order_id == sales_order_id)
    page = repo.list(
        *filters, order_by=[PackingList.created_at.desc(), PackingList.id.desc()], limit=limit, offset=offset
    )
    items = [PackingListSummary(**d) for d in _summaries(uow, list(page.items))]
    return Page[PackingListSummary](items=items, total=page.total, limit=page.limit, offset=page.offset)


def _opt(value: Decimal | None) -> Decimal | None:
    return plain(value) if value is not None else None


def detail(uow: UnitOfWork, pl: PackingList) -> PackingListDetail:
    lines = lines_of(uow, pl.id)
    keys = (
        dict(
            uow.session.execute(
                select(Product.id, Product.product_key).where(Product.id.in_([ln.product_id for ln in lines]))
            ).all()
        )
        if lines
        else {}
    )
    challan = None
    if pl.challan_id:
        from app.modules.challans.models import Challan

        c = uow.session.get(Challan, pl.challan_id)
        if c is not None:
            challan = DocRef(
                id=c.id, number=c.challan_number, status=c.status, path=f"/operations/challans/{c.id}"
            )
    repo = uow.repo(PackingList)

    def scoped(action: str) -> bool:
        return (
            uow.session.scalar(select(PackingList.id).where(PackingList.id == pl.id, repo.clause(action)))
            is not None
        )

    draft = pl.status == S.DRAFT.value
    incomplete = any(ln.incomplete_reasons for ln in lines)
    fin_ok = scoped("transition") and draft and not pl.is_stale and not incomplete
    fin_reason = (
        "permission_denied"
        if not scoped("transition")
        else "invalid_status"
        if not draft
        else "packing_list_stale"
        if pl.is_stale
        else "packing_list_incomplete"
    )
    return PackingListDetail(
        **_summaries(uow, [pl])[0],
        challan=challan,
        stale_since=pl.stale_since,
        stale_reason=pl.stale_reason,
        finalised_at=pl.finalised_at,
        notes=pl.notes,
        lines=[
            PackingLineRead(
                id=ln.id,
                line_no=ln.line_no,
                product_id=ln.product_id,
                product_key=keys.get(ln.product_id, ""),
                description=ln.description,
                quantity=plain(ln.quantity),
                unit=ln.uom_code,
                carton_qty=ln.carton_qty,
                inner_qty=ln.inner_qty,
                carton_dimensions_cm=(
                    f"{plain(ln.carton_length_cm)} × {plain(ln.carton_width_cm)} × "
                    f"{plain(ln.carton_height_cm)}"
                )
                if ln.carton_length_cm and ln.carton_width_cm and ln.carton_height_cm
                else None,
                stated_carton_cbm=_opt(ln.stated_carton_cbm),
                unit_weight_kg=_opt(ln.unit_weight_kg),
                carton_net_kg=_opt(ln.carton_net_kg),
                carton_gross_kg=_opt(ln.carton_gross_kg),
                packing_type=ln.packing_type,
                is_fragile=ln.is_fragile,
                full_cartons=ln.full_cartons,
                loose_qty=_opt(ln.loose_qty),
                cartons=ln.cartons,
                inner_packs=ln.inner_packs,
                is_part_carton=ln.is_part_carton,
                carton_cbm=_opt(ln.carton_cbm),
                cbm=ln.cbm,
                net_kg=ln.net_kg,
                gross_kg=ln.gross_kg,
                is_estimate=ln.is_estimate,
                incomplete_reasons=list(ln.incomplete_reasons),
                override_reason=ln.override_reason,
            )
            for ln in lines
        ],
        capabilities={
            "refresh": cap(
                scoped("update") and draft, "invalid_status" if scoped("update") else "permission_denied"
            ),
            "override": cap(
                scoped("update") and draft, "invalid_status" if scoped("update") else "permission_denied"
            ),
            "finalise": cap(fin_ok, fin_reason),
            "cancel": cap(
                scoped("transition") and draft,
                "invalid_status" if scoped("transition") else "permission_denied",
            ),
        },
    )


def get_packing_list(uow: UnitOfWork, pl_id: uuid.UUID) -> PackingListDetail:
    return detail(uow, uow.repo(PackingList).get(pl_id))


def count_for_order(uow: UnitOfWork, order_id: uuid.UUID) -> int:
    return int(
        uow.session.scalar(
            select(func.count()).select_from(PackingList).where(PackingList.sales_order_id == order_id)
        )
        or 0
    )
