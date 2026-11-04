"""The challan movement policy consumer (Slice 4): what an issued challan does to stock (operations.md §4, ADR-021).

Called inside the challan transition's unit of work, after the challan row is locked, so one challan issue is one
posting (source ``('challan', id, 'issue')``, UNIQUE in the ledger) and a replayed or re-delivered issue can never post
again. Before inventory go-live (``inventory_policy.challan_postings_enabled`` false) and for legacy or imported
challans the effect stays ``none`` (documents only, as in Slice 2).

| Type | Return type | Movement on issue (W = the challan's warehouse, default STOCK location) |
|---|---|---|
| Outward | non-returnable | W -> customers (vendor destination: suppliers); consumes the SO line's reservation |
| Outward | returnable | W -> held by the party (stays company-owned) |
| Job Work | returnable | W -> held by the fabricator / vendor (stays company-owned) |
| Sample | returnable | W -> held by the party, or the office location for an Office destination |
| Sample | non-returnable | W -> samples given away |
| Inward | non-returnable | suppliers (vendor) / customers -> W's QC hold (QC-required products) or W; needs ``inventory.stock.receive`` |
| Return | inherits the original | from where the original line's movement put it -> the original warehouse's QC hold or STOCK |
| Transfer | non-returnable | W -> the destination warehouse's STOCK (one posting), or the office location |

Lines without a stock-tracked product are explicitly ``is_non_stock``. SO-linked lines record their delivery (or
return) on the order line in the same transaction. Cancelling an issued challan posts the reversal (source
``('challan', id, 'cancel')``, ``reverses_posting_id`` = the issue posting) and reverses the SO figures.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select

from app.core.errors import ValidationFailed
from app.modules.catalogue.models import Product
from app.modules.challans.models import Challan, ChallanLine
from app.modules.challans.schemas import ChallanType, DestinationType, InventoryEffect, ReturnType
from app.platform.uow import UnitOfWork

LEGACY_ORIGINS = frozenset({"migration", "import"})
ZERO = Decimal(0)


@dataclass(frozen=True)
class _Delivery:
    order_line_id: uuid.UUID
    quantity: Decimal
    uom_code: str
    returned: bool


def _products(uow: UnitOfWork, lines: list[ChallanLine]) -> dict[uuid.UUID, Product]:
    ids = {ln.product_id for ln in lines if ln.product_id}
    if not ids:
        return {}
    return {
        p.id: p
        for p in uow.session.scalars(
            select(Product).where(Product.company_id == uow.actor.company_id, Product.id.in_(ids))
        )
    }


def posts_stock(uow: UnitOfWork, challan: Challan) -> bool:
    from app.modules.inventory import service as inventory

    return challan.origin not in LEGACY_ORIGINS and inventory.challan_postings_enabled(uow)


def _stock_lines(
    uow: UnitOfWork, lines: list[ChallanLine]
) -> tuple[list[ChallanLine], dict[uuid.UUID, Product]]:
    products = _products(uow, lines)
    stock = [
        ln
        for ln in lines
        if ln.product_id and ln.product_id in products and products[ln.product_id].is_stock_tracked
    ]
    return stock, products


def posting_blocker(uow: UnitOfWork, challan: Challan, lines: list[ChallanLine]) -> str | None:
    """A cheap pre-check for ``capabilities.issue`` (the posting itself re-validates everything under lock)."""
    if challan.status != "draft" or not posts_stock(uow, challan):
        return None
    stock, products = _stock_lines(uow, lines)
    if not stock:
        return None
    from app.modules.inventory import service as inventory

    t = ChallanType(challan.challan_type)
    if t != ChallanType.RETURN:
        try:
            inventory.resolve_warehouse(uow, challan.source_warehouse_id)
        except ValidationFailed:
            return "warehouse_required"
    if any(products[ln.product_id].track_lots and ln.lot_id is None for ln in stock if ln.product_id):
        return "lot_required"
    holding = (
        t in (ChallanType.JOB_WORK, ChallanType.OUTWARD, ChallanType.SAMPLE)
        and challan.return_type == ReturnType.RETURNABLE.value
    )
    if holding and challan.destination_type != DestinationType.OFFICE.value and challan.party_id is None:
        return "party_required"
    if (
        t == ChallanType.TRANSFER
        and challan.destination_type == DestinationType.WAREHOUSE.value
        and challan.destination_warehouse_id is None
    ):
        return "destination_warehouse_required"
    if (
        challan.destination_type == DestinationType.OFFICE.value
        and challan.office_branch_id is None
        and t in (ChallanType.TRANSFER, ChallanType.SAMPLE)
    ):
        return "office_required"
    return None


def _target(uow: UnitOfWork, challan: Challan, product: Product, warehouse_id: uuid.UUID) -> uuid.UUID:
    from app.modules.inventory import service as inventory
    from app.modules.inventory.enums import LocationType

    if product.qc_required:
        return inventory.warehouse_location(uow, warehouse_id, LocationType.QC_HOLD).id
    return inventory.default_location(uow, warehouse_id).id


def _outbound_destination(uow: UnitOfWork, challan: Challan) -> uuid.UUID:
    from app.modules.inventory import service as inventory
    from app.modules.inventory.enums import LocationType

    t = ChallanType(challan.challan_type)
    returnable = challan.return_type == ReturnType.RETURNABLE.value
    dest = DestinationType(challan.destination_type)
    if t == ChallanType.TRANSFER:
        if dest == DestinationType.OFFICE:
            assert challan.office_branch_id is not None
            return inventory.office_location(uow, challan.office_branch_id).id
        return inventory.default_location(
            uow, inventory.resolve_warehouse(uow, challan.destination_warehouse_id).id
        ).id
    if t == ChallanType.SAMPLE and not returnable:
        return inventory.company_location(uow, LocationType.SAMPLE_CONSUMPTION).id
    if returnable or t == ChallanType.JOB_WORK:
        if dest == DestinationType.OFFICE and challan.office_branch_id is not None:
            return inventory.office_location(uow, challan.office_branch_id).id
        if challan.party_id is None:
            raise ValidationFailed(
                "Link the receiving party: returnable goods are held at their location",
                errors=[{"loc": ["body", "party_id"], "msg": "party required", "code": "party_required"}],
            )
        return inventory.holding_location(uow, challan.party_id).id
    if dest == DestinationType.VENDOR:
        return inventory.company_location(uow, LocationType.SUPPLIER).id
    return inventory.company_location(uow, LocationType.CUSTOMER).id


def _split_by_reservation(
    uow: UnitOfWork, line: ChallanLine, product: Product, warehouse_id: uuid.UUID
) -> list[tuple[Decimal, str, uuid.UUID | None]]:
    """(quantity, uom, reservation) parts of an SO-linked line: reserved stock is consumed first, the rest is free."""
    from app.modules.inventory import service as inventory

    qty, uom = Decimal(line.quantity), line.uom_code
    if line.sales_order_line_id is None:
        return [(qty, uom, None)]
    base, stock_uom = inventory.stock_quantity(uow, product.id, qty, uom)
    parts: list[tuple[Decimal, str, uuid.UUID | None]] = []
    left = base
    for res in inventory.active_for_demand(uow, "so_line", line.sales_order_line_id):
        if res.warehouse_id != warehouse_id or left <= 0:
            continue
        take = min(left, inventory.remaining(res))
        if take > 0:
            parts.append((take, stock_uom, res.id))
            left -= take
    if left > 0:
        parts.append((left, stock_uom, None))
    return parts


def _order_lines_touched(
    uow: UnitOfWork, challan: Challan, lines: list[ChallanLine]
) -> tuple[list[uuid.UUID], dict[uuid.UUID, ChallanLine]]:
    """The SO lines this issue changes (outward: the lines' own links; return: the original lines' links)."""
    if challan.challan_type == ChallanType.RETURN.value:
        ids = [ln.original_line_id for ln in lines if ln.original_line_id]
        originals = (
            {o.id: o for o in uow.session.scalars(select(ChallanLine).where(ChallanLine.id.in_(ids)))}
            if ids
            else {}
        )
        return sorted({o.sales_order_line_id for o in originals.values() if o.sales_order_line_id}), originals
    return sorted({ln.sales_order_line_id for ln in lines if ln.sales_order_line_id}), {}


def on_issue(uow: UnitOfWork, challan: Challan, lines: list[ChallanLine]) -> uuid.UUID | None:
    """Post the issue movement (once) and record SO deliveries; returns the posting id (None: no stock moved).

    Lock order: the challan (held) -> the SO headers and lines -> the stock summaries / balances / reservations
    (inside ``post_movement``), the same order a reservation takes, so issue and reserve never deadlock."""
    from app.modules.inventory import service as inventory
    from app.modules.inventory.enums import LocationType

    if not posts_stock(uow, challan):
        return None
    stock, products = _stock_lines(uow, lines)
    stock_ids = {ln.id for ln in stock}
    for ln in lines:
        ln.is_non_stock = ln.id not in stock_ids
    so_line_ids, originals = _order_lines_touched(uow, challan, lines)
    if so_line_ids:
        from app.modules.orders import service as orders

        orders.lock_lines(uow, so_line_ids)
    t = ChallanType(challan.challan_type)
    posting_lines: list = []
    deliveries: list[_Delivery] = []
    if t == ChallanType.RETURN:
        posting_lines = _return_lines(uow, challan, stock, products)
        deliveries = [
            _Delivery(
                originals[ln.original_line_id].sales_order_line_id, Decimal(ln.quantity), ln.uom_code, True
            )  # type: ignore[arg-type]
            for ln in lines
            if ln.original_line_id in originals and originals[ln.original_line_id].sales_order_line_id
        ]
    else:
        deliveries = [
            _Delivery(ln.sales_order_line_id, Decimal(ln.quantity), ln.uom_code, False)
            for ln in lines
            if ln.sales_order_line_id
        ]
        if stock:
            wh = inventory.resolve_warehouse(uow, challan.source_warehouse_id)
            # IDOR: a challan posts only from (and to) warehouses its issuer can see (404 otherwise)
            from app.modules.inventory.policies import require_warehouse as _visible

            _visible(uow, wh.id)
            if t == ChallanType.TRANSFER and challan.destination_warehouse_id is not None:
                _visible(uow, challan.destination_warehouse_id)
            if challan.source_warehouse_id is None:
                challan.source_warehouse_id = wh.id
            if t == ChallanType.INWARD:
                from app.modules.inventory.policies import require_warehouse
                from app.platform.authz.stepup import require_step_up

                require_warehouse(uow, wh.id, "inventory.stock.receive")
                require_step_up(uow, "inventory.stock.receive")
                source = inventory.company_location(
                    uow,
                    LocationType.SUPPLIER
                    if challan.destination_type == DestinationType.VENDOR.value
                    else LocationType.CUSTOMER,
                ).id
                for ln in stock:
                    product = products[ln.product_id]  # type: ignore[index]
                    posting_lines.append(
                        inventory.PostingLine(
                            product_id=product.id,
                            quantity=Decimal(ln.quantity),
                            uom_code=ln.uom_code,
                            from_location_id=source,
                            to_location_id=_target(uow, challan, product, wh.id),
                            lot_id=ln.lot_id,
                            counterparty_party_id=challan.party_id,
                            source_line_type="challans.challan_line",
                            source_line_id=ln.id,
                        )
                    )
            else:
                src = inventory.default_location(uow, wh.id).id
                dst = _outbound_destination(uow, challan)
                for ln in stock:
                    product = products[ln.product_id]  # type: ignore[index]
                    for qty, uom, reservation_id in _split_by_reservation(uow, ln, product, wh.id):
                        posting_lines.append(
                            inventory.PostingLine(
                                product_id=product.id,
                                quantity=qty,
                                uom_code=uom,
                                from_location_id=src,
                                to_location_id=dst,
                                lot_id=ln.lot_id,
                                counterparty_party_id=challan.party_id,
                                reservation_id=reservation_id,
                                source_line_type="challans.challan_line",
                                source_line_id=ln.id,
                            )
                        )
    replayed = False
    posting_id: uuid.UUID | None = None
    if posting_lines:
        receipt = inventory.post_movement(
            uow,
            inventory.PostingRequest(
                source_type="challan",
                source_id=challan.id,
                purpose="issue",
                lines=tuple(posting_lines),
                source_label=challan.challan_number,
            ),
        )
        challan.inventory_effect = InventoryEffect.POSTING.value
        challan.issue_posting_id = posting_id = receipt.posting.id
        replayed = receipt.replayed
    if not replayed:
        _apply_deliveries(uow, challan, deliveries)
    return posting_id


def _return_lines(
    uow: UnitOfWork, challan: Challan, stock: list[ChallanLine], products: dict[uuid.UUID, Product]
) -> list:
    """Each return line moves back from where its original line's movement put the goods (same lot and owner)."""
    from app.modules.inventory import service as inventory

    out: list = []
    if challan.original_challan_id is None:
        return out
    original = uow.session.scalars(
        select(Challan).where(
            Challan.company_id == uow.actor.company_id, Challan.id == challan.original_challan_id
        )
    ).first()
    if original is None or original.issue_posting_id is None:
        for ln in stock:
            ln.is_non_stock = True  # the original never moved stock (legacy / pre-go-live): document only
        return out
    originals = {
        o.id: o
        for o in uow.session.scalars(
            select(ChallanLine).where(
                ChallanLine.id.in_([ln.original_line_id for ln in stock if ln.original_line_id])
            )
        )
    }
    moved = inventory.movements_by_source_line(uow, original.issue_posting_id, list(originals))
    for ln in stock:
        orig = originals.get(ln.original_line_id) if ln.original_line_id else None
        movements = moved.get(orig.id, []) if orig else []
        if not movements:
            ln.is_non_stock = True
            continue
        product = products[ln.product_id]  # type: ignore[index]
        first = movements[0]
        warehouse_id = first.from_warehouse_id
        assert warehouse_id is not None
        out.append(
            inventory.PostingLine(
                product_id=product.id,
                quantity=Decimal(ln.quantity),
                uom_code=ln.uom_code,
                from_location_id=first.to_location_id,
                to_location_id=_target(uow, challan, product, warehouse_id),
                lot_id=first.lot_id,
                owner_party_id=first.owner_party_id,
                counterparty_party_id=challan.party_id,
                source_line_type="challans.challan_line",
                source_line_id=ln.id,
            )
        )
    return out


def _apply_deliveries(
    uow: UnitOfWork, challan: Challan, deliveries: list[_Delivery], *, reverse: bool = False
) -> None:
    if not deliveries:
        return
    from app.modules.orders import service as orders

    for d in sorted(deliveries, key=lambda x: str(x.order_line_id)):
        if d.returned:
            orders.record_return(
                uow,
                d.order_line_id,
                d.quantity,
                d.uom_code,
                challan_id=challan.id,
                reference=challan.challan_number,
                reverse=reverse,
            )
        elif reverse:
            orders.reverse_delivery(
                uow,
                d.order_line_id,
                d.quantity,
                d.uom_code,
                challan_id=challan.id,
                reference=challan.challan_number,
            )
        else:
            orders.record_delivery(
                uow,
                d.order_line_id,
                d.quantity,
                d.uom_code,
                challan_id=challan.id,
                reference=challan.challan_number,
            )


def _issued_under_policy(challan: Challan, lines: list[ChallanLine]) -> bool:
    """Whether the issue ran the movement policy (go-live): it posted, or it flagged every line non-stock."""
    return challan.issue_posting_id is not None or (bool(lines) and all(ln.is_non_stock for ln in lines))


def on_cancel_issued(
    uow: UnitOfWork, challan: Challan, lines: list[ChallanLine], *, reason_code: str, reason: str | None
) -> uuid.UUID | None:
    """The auditable correction of an issued challan: a reversal posting and the SO figures restored."""
    if not _issued_under_policy(challan, lines):
        return None
    from app.modules.inventory import service as inventory
    from app.platform.authz.stepup import require_step_up

    so_line_ids, originals = _order_lines_touched(uow, challan, lines)
    if so_line_ids:
        from app.modules.orders import service as orders

        orders.lock_lines(uow, so_line_ids)
    replayed = False
    if challan.issue_posting_id is not None:
        require_step_up(uow, "challans.challan.reverse")
        receipt = inventory.reverse_posting(
            uow,
            challan.issue_posting_id,
            reason_code=reason_code,
            reason=reason,
            source=("challan", challan.id, "cancel"),
            source_label=challan.challan_number,
        )
        challan.reversal_posting_id = receipt.posting.id
        replayed = receipt.replayed
    if not replayed:
        if challan.challan_type == ChallanType.RETURN.value:
            deliveries = [
                _Delivery(
                    originals[ln.original_line_id].sales_order_line_id,
                    Decimal(ln.quantity),
                    ln.uom_code,
                    True,
                )  # type: ignore[arg-type]
                for ln in lines
                if ln.original_line_id in originals and originals[ln.original_line_id].sales_order_line_id
            ]
        else:
            deliveries = [
                _Delivery(ln.sales_order_line_id, Decimal(ln.quantity), ln.uom_code, False)
                for ln in lines
                if ln.sales_order_line_id
            ]
        _apply_deliveries(uow, challan, deliveries, reverse=True)
    return challan.reversal_posting_id


def link_order(
    uow: UnitOfWork, challan_id: uuid.UUID, order_id: uuid.UUID, line_links: dict[uuid.UUID, uuid.UUID]
) -> None:
    """Attach a draft challan (created by orders / picking) to its sales order: ``{challan_line_id: order_line_id}``."""
    challan = uow.session.scalars(
        select(Challan)
        .where(Challan.company_id == uow.actor.company_id, Challan.id == challan_id)
        .with_for_update()
    ).first()
    assert challan is not None and challan.status == "draft"
    challan.sales_order_id = order_id
    for ln in uow.session.scalars(select(ChallanLine).where(ChallanLine.challan_id == challan_id)):
        if ln.id in line_links:
            ln.sales_order_line_id = line_links[ln.id]
    uow.flush()
