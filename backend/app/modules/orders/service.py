"""Sales order commands and reads (operations.md §2) — the module's public service.

Public functions used by other modules (documented in docs/lanes/orders-inventory-s4.md):
- ``convert_quote(uow, quote_id) -> (SalesOrder, created)``: idempotent; one order per accepted quote.
- ``lock_lines(uow, line_ids)``: lock order headers then lines (lock order) before a fulfilment posting.
- ``record_delivery`` / ``reverse_delivery`` / ``record_return``: called by the challan movement policy in the
  challan's transaction; refuse over-delivery and over-return (409) and keep ``fulfilment_state`` and completion.
- ``open_demand(uow, product_id, warehouse_id)``: the shortage-state demand provider (registered on load).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import ColumnElement, and_, exists, or_, select

from app.core.clock import local_date
from app.core.errors import Conflict, Forbidden, InvalidTransition, NotFound, ValidationFailed
from app.core.http.capabilities import Capability, TransitionRead
from app.core.http.pagination import Page
from app.core.money import Money
from app.core.text import LIKE_ESCAPE, contains_pattern, tokens
from app.modules.catalogue.models import Product
from app.modules.inventory import service as inventory
from app.modules.inventory.models import Reservation, Warehouse
from app.modules.inventory.policies import require_warehouse, require_warehouse_for
from app.modules.orders import events as ev
from app.modules.orders.enums import FulfilmentMode, FulfilmentState, LineKind, OrderAction, OrderStatus
from app.modules.orders.models import SalesOrder, SalesOrderLine, SalesOrderStatusHistory
from app.modules.orders.policies import ORDER_RESERVE_POLICY
from app.modules.orders.schemas import (
    ChallanFromOrder,
    ConversionResult,
    ImpactLine,
    ImpactPreview,
    LineCancel,
    LineReserveOutcome,
    OrderDocumentRef,
    OrderFilters,
    OrderHistoryRead,
    OrderLineRead,
    OrderPartyRef,
    OrderQuoteRef,
    OrderReservationRead,
    OrderTransition,
    OrderUpdate,
    OrderUserRef,
    ReleaseRequest,
    ReserveRequest,
    ReserveResponse,
    SalesOrderDetail,
    SalesOrderSummary,
    WarehouseRef,
)
from app.platform.authz.policy import scope_clause
from app.platform.identity.models import AppUser
from app.platform.org.models import Company
from app.platform.org.reference import convert
from app.platform.service import query
from app.platform.uow import UnitOfWork

READ, CREATE, UPDATE, TRANSITION = (
    "orders.sales_order.read",
    "orders.sales_order.create",
    "orders.sales_order.update",
    "orders.sales_order.transition",
)
RESOURCE = "orders.sales_order"
ZERO = Decimal(0)
S = OrderStatus
OPEN = frozenset({S.DRAFT.value, S.CONFIRMED.value, S.ON_HOLD.value})
#: (from status, action) -> to status (table-driven; anything else is 409 invalid_transition)
TRANSITIONS: dict[tuple[str, str], str] = {
    (S.DRAFT.value, "confirm"): S.CONFIRMED.value,
    (S.CONFIRMED.value, "hold"): S.ON_HOLD.value,
    (S.ON_HOLD.value, "release_hold"): S.CONFIRMED.value,
    (S.DRAFT.value, "cancel"): S.CANCELLED.value,
    (S.CONFIRMED.value, "cancel"): S.CANCELLED.value,
    (S.ON_HOLD.value, "cancel"): S.CANCELLED.value,
}
REASON_REQUIRED = frozenset({"hold", "cancel"})
TRANSITION_EVENTS = {
    "confirm": ev.ORDER_CONFIRMED,
    "hold": ev.ORDER_ON_HOLD,
    "release_hold": ev.ORDER_CONFIRMED,
    "cancel": ev.ORDER_CANCELLED,
}


def order_path(order_id: uuid.UUID) -> str:
    return f"/sales/orders/{order_id}"


def _zone(uow: UnitOfWork) -> str:
    return (
        uow.session.scalar(select(Company.default_time_zone).where(Company.id == uow.actor.company_id))
        or "Asia/Kolkata"
    )


def _today(uow: UnitOfWork) -> date:
    return local_date(uow.now(), _zone(uow))


def _users(uow: UnitOfWork, ids: Sequence[uuid.UUID | None]) -> dict[uuid.UUID, OrderUserRef]:
    wanted = {i for i in ids if i}
    if not wanted:
        return {}
    rows = uow.session.execute(select(AppUser.id, AppUser.display_name).where(AppUser.id.in_(wanted))).all()
    return {r[0]: OrderUserRef(id=r[0], display_name=r[1]) for r in rows}


def _money(amount: Decimal | None, currency: str) -> Money | None:
    return None if amount is None else Money(amount=Decimal(amount), currency=currency)  # type: ignore[arg-type]


def _hash(data: Any) -> str:
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _history(
    uow: UnitOfWork,
    order: SalesOrder,
    action: str,
    from_status: str,
    to_status: str,
    *,
    line_id: uuid.UUID | None = None,
    reason_code: str | None = None,
    reason: str | None = None,
    reference: str | None = None,
) -> None:
    uow.add(
        SalesOrderStatusHistory(
            company_id=uow.actor.company_id,
            order_id=order.id,
            line_id=line_id,
            action=action,
            from_status=from_status,
            to_status=to_status,
            actor_user_id=uow.actor.user_id,
            reason_code=reason_code,
            reason=reason,
            reference=reference,
            occurred_at=uow.now(),
            order_version=order.version,
        )
    )


def _emit_order(uow: UnitOfWork, name: str, order: SalesOrder, reason_code: str | None = None) -> None:
    uow.emit(
        name,
        aggregate_id=order.id,
        aggregate_version=order.version,
        payload={"order_id": str(order.id), "reason_code": reason_code},
    )


def lines_of(uow: UnitOfWork, order: SalesOrder) -> list[SalesOrderLine]:
    return list(
        uow.session.scalars(
            select(SalesOrderLine).where(SalesOrderLine.order_id == order.id).order_by(SalesOrderLine.line_no)
        )
    )


# =====================================================================================================
# conversion (idempotent: UNIQUE(company_id, source_quote_id) + the quote row lock)
# =====================================================================================================
def _existing_for_quote(uow: UnitOfWork, quote_id: uuid.UUID) -> SalesOrder | None:
    return uow.session.scalars(
        select(SalesOrder).where(
            SalesOrder.company_id == uow.actor.company_id, SalesOrder.source_quote_id == quote_id
        )
    ).first()


def _line_kind(line_type: str) -> LineKind:
    return {"catalog": LineKind.CATALOG, "custom": LineKind.CUSTOM}.get(line_type, LineKind.MANUAL)


def convert_quote(uow: UnitOfWork, quote_id: uuid.UUID) -> tuple[SalesOrder, bool]:
    """Create the order of a won quote's accepted revision, or return the one that exists (``created=False``)."""
    from app.modules.sales.models import Quote, QuoteRevision

    uow.actor.require(CREATE)
    if uow.actor.user_id is None:
        raise Forbidden("An order needs a user as its owner", code="permission_denied", permission=CREATE)
    quote = uow.repo(Quote).get(quote_id, for_update=True)  # 404 outside the actor's quote scope; serialises
    existing = _existing_for_quote(uow, quote.id)
    if existing is not None:
        return existing, False
    if quote.status != "won" or quote.accepted_revision_id is None:
        raise Conflict(
            "Only a won quote with an accepted revision becomes an order",
            code="quote_not_won",
            current_status=quote.status,
        )
    revision = uow.session.get(QuoteRevision, quote.accepted_revision_id)
    assert revision is not None
    snap = revision.snapshot
    totals = snap.get("totals") or {}
    currency = totals.get("currency") or quote.currency
    lines = sorted(snap.get("lines") or [], key=lambda ln: ln["line_no"])
    errors: list[dict[str, Any]] = []
    for i, ln in enumerate(lines):
        if ln.get("unit_price") is None or ln.get("line_total") is None:
            errors.append(
                {
                    "loc": ["lines", i],
                    "msg": f"line {ln['line_no']} has no price",
                    "code": "price_unavailable",
                }
            )
    if errors:
        raise ValidationFailed("Every line needs a price before the quote becomes an order", errors=errors)
    line_sum = sum((Decimal(str(ln["line_total"])) for ln in lines), ZERO)
    if line_sum != Decimal(str(totals.get("net_subtotal", "0"))):
        raise Conflict(
            "The accepted revision's lines do not add up to its subtotal", code="snapshot_inconsistent"
        )
    product_ids = {uuid.UUID(ln["product_id"]) for ln in lines if ln.get("product_id")}
    products = (
        {
            p.id: p
            for p in uow.session.scalars(
                select(Product).where(Product.company_id == uow.actor.company_id, Product.id.in_(product_ids))
            )
        }
        if product_ids
        else {}
    )
    default_wh = inventory.default_warehouse(uow)
    header = snap.get("header") or {}
    order = SalesOrder(
        id=uuid.uuid7(),
        company_id=uow.actor.company_id,
        order_number="SO-0000-0000",
        order_date=_today(uow),
        party_id=quote.party_id,
        party_name=quote.party_name,
        source_quote_id=quote.id,
        source_quote_revision_id=revision.id,
        quote_number=quote.quote_number,
        quote_revision_no=revision.revision_no,
        status=S.DRAFT.value,
        fulfilment_state=FulfilmentState.NONE.value,
        currency=currency,
        terms_snapshot={
            "incoterm": header.get("incoterm"),
            "incoterm_place": header.get("incoterm_place"),
            "payment_terms": header.get("payment_terms"),
            "validity_days": header.get("validity_days"),
            "valid_until": header.get("valid_until"),
            "brand": header.get("brand"),
            "price_type": header.get("price_type"),
            "customer": snap.get("party"),
            "totals": totals,
            "content_hash": snap.get("content_hash"),
        },
        snapshot_hash=_hash(snap),
        subtotal_amount=Decimal(str(totals.get("net_subtotal", "0"))),
        surcharge_amount=Decimal(str(totals.get("surcharge") or "0")),
        total_amount=Decimal(str(totals["grand_total"])) if totals.get("grand_total") is not None else None,
        default_warehouse_id=default_wh.id if default_wh else None,
        customer_reference=header.get("customer_reference"),
        owner_user_id=quote.owner_user_id,
        branch_id=quote.branch_id,
        origin="agent" if uow.actor.actor_type == "agent" else "user",
        search_text=" ".join(x for x in (quote.quote_number, quote.party_name) if x).lower(),
    )
    order.order_number = uow.allocate_number(
        "orders.sales_order",
        document_date=order.order_date,
        resource_type=RESOURCE,
        resource_id=order.id,
        branch_id=order.branch_id,
    )
    order.search_text = f"{order.order_number.lower()} {order.search_text}"
    uow.add(order)
    uow.flush()
    no = 0
    for ln in lines:
        no += 1
        product = products.get(uuid.UUID(ln["product_id"])) if ln.get("product_id") else None
        kind = _line_kind(ln["line_type"])
        mode = (
            FulfilmentMode.STOCK
            if product is not None and product.is_stock_tracked
            else FulfilmentMode.MAKE_TO_ORDER
            if kind == LineKind.CUSTOM
            else FulfilmentMode.NON_STOCK
        )
        uow.add(
            SalesOrderLine(
                id=uuid.uuid7(),
                company_id=uow.actor.company_id,
                order_id=order.id,
                line_no=no,
                source_line_key=str(ln["line_key"]),
                line_kind=kind.value,
                fulfilment_mode=mode.value,
                product_id=product.id if product else None,
                product_key=ln.get("product_key"),
                description=ln["description"],
                description_snapshot={
                    k: ln.get(k)
                    for k in (
                        "display_sku",
                        "decor_no",
                        "decor_name",
                        "size_text",
                        "finish",
                        "packaging_summary",
                        "remarks",
                    )
                },
                uom_code=ln["unit_code"],
                unit_price=Decimal(str(ln["unit_price"])),
                currency=currency,
                line_total_amount=Decimal(str(ln["line_total"])),
                qty_ordered=Decimal(str(ln["quantity"])),
            )
        )
    if Decimal(str(totals.get("surcharge") or "0")) > 0 and totals.get("surcharge_applied"):
        no += 1
        uow.add(
            SalesOrderLine(
                id=uuid.uuid7(),
                company_id=uow.actor.company_id,
                order_id=order.id,
                line_no=no,
                source_line_key="surcharge",
                line_kind=LineKind.CHARGE.value,
                fulfilment_mode=FulfilmentMode.NON_STOCK.value,
                description=str(totals.get("surcharge_label") or "Shipping surcharge"),
                description_snapshot={},
                uom_code="nos",
                unit_price=Decimal(str(totals["surcharge"])),
                currency=currency,
                line_total_amount=Decimal(str(totals["surcharge"])),
                qty_ordered=Decimal(1),
            )
        )
    order.line_count = no
    uow.flush()
    _history(uow, order, OrderAction.CREATE.value, "new", S.DRAFT.value, reference=quote.quote_number)
    uow.emit(
        ev.ORDER_CREATED,
        aggregate_id=order.id,
        aggregate_version=order.version,
        payload={
            "order_id": str(order.id),
            "order_number": order.order_number,
            "source_quote_id": str(quote.id),
        },
    )
    uow.audit(
        "orders.sales_order.create",
        resource_type=RESOURCE,
        resource_id=order.id,
        resource_label=order.order_number,
        details={"source_quote": quote.quote_number, "revision_no": revision.revision_no},
    )
    return order, True


def convert_quote_command(uow: UnitOfWork, quote_id: uuid.UUID) -> ConversionResult:
    order, created = convert_quote(uow, quote_id)
    uow.flush()
    return ConversionResult(created=created, order=detail(uow, order))


# =====================================================================================================
# reads
# =====================================================================================================
def _warehouses(uow: UnitOfWork, ids: Sequence[uuid.UUID | None]) -> dict[uuid.UUID, WarehouseRef]:
    wanted = {i for i in ids if i}
    if not wanted:
        return {}
    rows = uow.session.scalars(
        select(Warehouse).where(Warehouse.company_id == uow.actor.company_id, Warehouse.id.in_(wanted))
    )
    return {w.id: WarehouseRef(id=w.id, code=w.code, name=w.name) for w in rows}


def _party_refs(uow: UnitOfWork, orders: Sequence[SalesOrder]) -> dict[uuid.UUID, OrderPartyRef]:
    from app.modules.parties.models import Party

    ids = {o.party_id for o in orders}
    rows = (
        uow.session.execute(
            select(Party.id, Party.party_number, Party.display_name).where(Party.id.in_(ids))
        ).all()
        if ids
        else []
    )
    names = {o.party_id: o.party_name for o in orders}
    out = {r[0]: OrderPartyRef(id=r[0], party_number=r[1], display_name=r[2]) for r in rows}
    for pid, name in names.items():
        out.setdefault(pid, OrderPartyRef(id=pid, party_number=None, display_name=name))
    return out


def _summary(
    o: SalesOrder, parties: dict[uuid.UUID, OrderPartyRef], users: dict[uuid.UUID, OrderUserRef]
) -> SalesOrderSummary:
    return SalesOrderSummary(
        id=o.id,
        order_number=o.order_number,
        order_date=o.order_date,
        party=parties[o.party_id],
        quote=OrderQuoteRef(
            id=o.source_quote_id, quote_number=o.quote_number, revision_no=o.quote_revision_no
        ),
        status=S(o.status),
        fulfilment_state=FulfilmentState(o.fulfilment_state),
        total=_money(o.total_amount, o.currency),
        line_count=o.line_count,
        requested_delivery_date=o.requested_delivery_date,
        promised_date=o.promised_date,
        owner=users.get(o.owner_user_id) or OrderUserRef(id=o.owner_user_id, display_name=None),
        branch_id=o.branch_id,
        created_at=o.created_at,
        updated_at=o.updated_at,
        version=o.version,
        path=order_path(o.id),
    )


def _conditions(uow: UnitOfWork, f: OrderFilters) -> list[ColumnElement[bool]]:

    conds: list[ColumnElement[bool]] = []
    for tok in tokens(f.q or ""):
        conds.append(SalesOrder.search_text.ilike(contains_pattern(tok), escape=LIKE_ESCAPE))
    if f.status:
        conds.append(SalesOrder.status.in_([s.value for s in f.status]))
    if f.fulfilment_state:
        conds.append(SalesOrder.fulfilment_state.in_([s.value for s in f.fulfilment_state]))
    if f.party_id:
        conds.append(SalesOrder.party_id == f.party_id)
    if f.source_quote_id:
        conds.append(SalesOrder.source_quote_id == f.source_quote_id)
    if f.scope == "mine" and uow.actor.user_id:
        conds.append(SalesOrder.owner_user_id == uow.actor.user_id)
    return conds


@query(READ)
def list_orders(
    uow: UnitOfWork, filters: OrderFilters, *, limit: int = 50, offset: int = 0
) -> Page[SalesOrderSummary]:
    page = uow.repo(SalesOrder).list(
        *_conditions(uow, filters),
        order_by=[SalesOrder.order_date.desc(), SalesOrder.order_number.desc()],
        limit=limit,
        offset=offset,
    )
    parties = _party_refs(uow, page.items)
    users = _users(uow, [o.owner_user_id for o in page.items])
    return Page[SalesOrderSummary](
        items=[_summary(o, parties, users) for o in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


def _stock_unit(uow: UnitOfWork, line: SalesOrderLine, qty: Decimal) -> Decimal:
    base, _ = inventory.stock_quantity(uow, line.product_id, qty, line.uom_code)  # type: ignore[arg-type]
    return base


def _line_unit(uow: UnitOfWork, line: SalesOrderLine, stock_qty: Decimal, stock_uom: str) -> Decimal:
    if stock_uom == line.uom_code:
        return stock_qty
    return convert(uow, stock_qty, stock_uom, line.uom_code, line.product_id)


def _reserved_line_units(uow: UnitOfWork, lines: Sequence[SalesOrderLine]) -> dict[uuid.UUID, Decimal]:
    stock = [ln for ln in lines if ln.fulfilment_mode == FulfilmentMode.STOCK.value]
    if not stock:
        return {}
    rows = list(
        uow.session.scalars(
            select(Reservation).where(
                Reservation.company_id == uow.actor.company_id,
                Reservation.demand_type == "so_line",
                Reservation.demand_id.in_([ln.id for ln in stock]),
                Reservation.status == "active",
            )
        )
    )
    by_line: dict[uuid.UUID, Decimal] = {}
    lines_by_id = {ln.id: ln for ln in stock}
    for r in rows:
        ln = lines_by_id[r.demand_id]
        by_line[ln.id] = by_line.get(ln.id, ZERO) + _line_unit(uow, ln, inventory.remaining(r), r.uom_code)
    return by_line


def _line_read(ln: SalesOrderLine, reserved: Decimal) -> OrderLineRead:
    remaining = Decimal(ln.qty_ordered) - Decimal(ln.qty_cancelled) - Decimal(ln.qty_delivered)
    return OrderLineRead(
        id=ln.id,
        line_no=ln.line_no,
        line_kind=LineKind(ln.line_kind),
        fulfilment_mode=FulfilmentMode(ln.fulfilment_mode),
        product_id=ln.product_id,
        product_key=ln.product_key,
        description=ln.description,
        unit=ln.uom_code,
        unit_price=_money(ln.unit_price, ln.currency),
        line_total=_money(ln.line_total_amount, ln.currency),
        qty_ordered=Decimal(ln.qty_ordered),
        qty_reserved=reserved,
        qty_delivered=Decimal(ln.qty_delivered),
        qty_returned=Decimal(ln.qty_returned),
        qty_cancelled=Decimal(ln.qty_cancelled),
        qty_remaining=remaining,
        qty_unreserved=max(remaining - reserved, ZERO)
        if ln.fulfilment_mode == FulfilmentMode.STOCK.value
        else ZERO,
        cancel_reason_code=ln.cancel_reason_code,
        version=ln.version,
    )


def _documents(uow: UnitOfWork, order: SalesOrder) -> list[OrderDocumentRef]:
    from app.modules.challans.models import Challan
    from app.modules.inventory.models import PickList

    out: list[OrderDocumentRef] = []
    for c in uow.session.scalars(
        select(Challan)
        .where(
            Challan.company_id == uow.actor.company_id,
            Challan.sales_order_id == order.id,
            Challan.deleted_at.is_(None),
        )
        .order_by(Challan.challan_number)
    ):
        out.append(
            OrderDocumentRef(
                kind="challan",
                id=c.id,
                number=c.challan_number,
                status=c.status,
                path=f"/operations/challans/{c.id}",
            )
        )
    for p in uow.session.scalars(
        select(PickList)
        .where(PickList.company_id == uow.actor.company_id, PickList.order_id == order.id)
        .order_by(PickList.number)
    ):
        out.append(
            OrderDocumentRef(
                kind="pick_list",
                id=p.id,
                number=p.number,
                status=p.status,
                path=f"/operations/inventory/pick-lists/{p.id}",
            )
        )
    return out


def can_reserve(uow: UnitOfWork, order: SalesOrder) -> bool:
    return bool(
        uow.session.scalar(
            select(
                exists().where(
                    and_(SalesOrder.id == order.id, scope_clause(uow.actor, ORDER_RESERVE_POLICY, "reserve"))
                )
            )
        )
    )


def detail(uow: UnitOfWork, order: SalesOrder) -> SalesOrderDetail:
    repo = uow.repo(SalesOrder)
    lines = lines_of(uow, order)
    reserved = _reserved_line_units(uow, lines)
    parties = _party_refs(uow, [order])
    hist = list(
        uow.session.scalars(
            select(SalesOrderStatusHistory)
            .where(SalesOrderStatusHistory.order_id == order.id)
            .order_by(SalesOrderStatusHistory.occurred_at, SalesOrderStatusHistory.id)
        )
    )
    users = _users(uow, [order.owner_user_id, *[h.actor_user_id for h in hist]])
    res_rows = list(
        uow.session.scalars(
            select(Reservation)
            .where(
                Reservation.company_id == uow.actor.company_id,
                Reservation.demand_type == "so_line",
                Reservation.demand_parent_id == order.id,
            )
            .order_by(Reservation.created_at, Reservation.id)
        )
    )
    whs = _warehouses(uow, [order.default_warehouse_id, *[r.warehouse_id for r in res_rows]])
    caps_raw = repo.capabilities(order, ["update", "transition"])
    is_open = order.status in OPEN
    has_stock = any(ln.fulfilment_mode == FulfilmentMode.STOCK.value for ln in lines)
    reservable = order.status == S.CONFIRMED.value and has_stock
    may_reserve = can_reserve(uow, order)
    caps: dict[str, Capability] = {k: Capability(**v) for k, v in caps_raw.items()}
    caps["reserve"] = Capability(
        allowed=reservable and may_reserve,
        reason_code=None
        if reservable and may_reserve
        else ("permission_denied" if not may_reserve else "order_not_confirmed"),
    )
    caps["release_reservations"] = Capability(
        allowed=may_reserve and bool(reserved),
        reason_code=None if may_reserve and reserved else "nothing_reserved",
    )
    challan_ok = uow.actor.can("challans.challan.create") and order.status == S.CONFIRMED.value
    caps["create_challan"] = Capability(
        allowed=challan_ok,
        reason_code=None
        if challan_ok
        else "permission_denied"
        if not uow.actor.can("challans.challan.create")
        else "order_not_confirmed",
    )
    pick_ok = (
        order.status == S.CONFIRMED.value
        and bool(reserved)
        and order.default_warehouse_id is not None
        and inventory_can(uow, order.default_warehouse_id, "inventory.pick_list.create")
    )
    caps["create_pick_list"] = Capability(
        allowed=pick_ok, reason_code=None if pick_ok else "nothing_reserved"
    )
    caps["cancel_line"] = Capability(
        allowed=caps["transition"].allowed and is_open,
        reason_code=None if caps["transition"].allowed and is_open else "order_closed",
    )
    allowed = []
    if caps["transition"].allowed:
        for (frm, action), to in TRANSITIONS.items():
            if frm == order.status and not (
                action == "cancel" and any(Decimal(ln.qty_delivered) > 0 for ln in lines)
            ):
                allowed.append(
                    TransitionRead(action=action, to_status=to, requires_reason=action in REASON_REQUIRED)
                )
    base = _summary(order, parties, users)
    lines_by_id = {ln.id: ln for ln in lines}
    return SalesOrderDetail(
        **base.model_dump(),
        currency=order.currency,
        subtotal=Money(amount=Decimal(order.subtotal_amount), currency=order.currency),  # type: ignore[arg-type]
        surcharge=Money(amount=Decimal(order.surcharge_amount), currency=order.currency),  # type: ignore[arg-type]
        terms=dict(order.terms_snapshot),
        snapshot_hash=order.snapshot_hash,
        default_warehouse=whs.get(order.default_warehouse_id) if order.default_warehouse_id else None,
        ship_to=order.ship_to,
        customer_reference=order.customer_reference,
        confirmed_at=order.confirmed_at,
        hold_reason_code=order.hold_reason_code,
        hold_reason=order.hold_reason,
        cancelled_at=order.cancelled_at,
        cancel_reason_code=order.cancel_reason_code,
        cancel_reason=order.cancel_reason,
        completed_at=order.completed_at,
        lines=[_line_read(ln, reserved.get(ln.id, ZERO)) for ln in lines],
        reservations=[
            OrderReservationRead(
                id=r.id,
                line_id=r.demand_id,
                warehouse=whs[r.warehouse_id],
                quantity=_line_unit(uow, lines_by_id[r.demand_id], Decimal(r.quantity), r.uom_code),
                remaining=_line_unit(uow, lines_by_id[r.demand_id], inventory.remaining(r), r.uom_code),
                unit=lines_by_id[r.demand_id].uom_code,
                status=r.status,
                created_at=r.created_at,
            )
            for r in res_rows
            if r.demand_id in lines_by_id
        ],
        documents=_documents(uow, order),
        history=[
            OrderHistoryRead(
                action=h.action,
                from_status=h.from_status,
                to_status=h.to_status,
                line_id=h.line_id,
                actor=users.get(h.actor_user_id) if h.actor_user_id else None,
                reason_code=h.reason_code,
                reason=h.reason,
                reference=h.reference,
                occurred_at=h.occurred_at,
            )
            for h in hist
        ],
        capabilities=caps,
        allowed_transitions=allowed,
    )


def inventory_can(uow: UnitOfWork, warehouse_id: uuid.UUID, key: str) -> bool:
    from app.modules.inventory.policies import can_on_warehouse

    return can_on_warehouse(uow, warehouse_id, key)


@query(READ)
def get_order(uow: UnitOfWork, order_id: uuid.UUID) -> SalesOrderDetail:
    return detail(uow, uow.repo(SalesOrder).get(order_id))


@query(READ)
def get_order_by_number(uow: UnitOfWork, order_number: str) -> SalesOrderDetail:
    return detail(uow, uow.repo(SalesOrder).get_by_key(order_number.strip().upper()))


def order_for_quote(uow: UnitOfWork, quote_id: uuid.UUID) -> SalesOrder | None:
    """The order converted from ``quote_id`` when the actor may read it (quote workspace link)."""
    o = _existing_for_quote(uow, quote_id)
    return o if o is not None and uow.repo(SalesOrder).can(o, "read") else None


# =====================================================================================================
# commands
# =====================================================================================================
def _locked(uow: UnitOfWork, order_id: uuid.UUID, action: str = "update") -> SalesOrder:
    return uow.repo(SalesOrder).get(order_id, action, for_update=True)


def update_order(uow: UnitOfWork, order_id: uuid.UUID, data: OrderUpdate) -> SalesOrder:
    order = _locked(uow, order_id, "update")
    uow.expect_version(order, data.expected_version)
    sent = data.model_fields_set - {"expected_version"}
    if "default_warehouse_id" in sent and data.default_warehouse_id is not None:
        wh = inventory.resolve_warehouse(uow, data.default_warehouse_id)
        require_warehouse(uow, wh.id)  # IDOR: only a warehouse the actor can see (404 otherwise)
    changed = []
    for name in ("requested_delivery_date", "promised_date", "default_warehouse_id", "ship_to"):
        if name in sent and getattr(order, name) != getattr(data, name):
            setattr(order, name, getattr(data, name))
            changed.append(name)
    if changed:
        uow.flush()
        uow.audit(
            "orders.sales_order.update",
            resource_type=RESOURCE,
            resource_id=order.id,
            resource_label=order.order_number,
            details={"changed_fields": changed},
        )
    return order


def transition_order(uow: UnitOfWork, order_id: uuid.UUID, data: OrderTransition) -> SalesOrder:
    order = _locked(uow, order_id, "transition")
    to = TRANSITIONS.get((order.status, data.action))
    if to is None:
        raise InvalidTransition(
            f"{data.action} is not allowed while the order is {order.status}",
            allowed_transitions=[t.model_dump() for t in detail(uow, order).allowed_transitions],
            current_status=order.status,
        )
    uow.expect_version(order, data.expected_version)
    if data.action in REASON_REQUIRED and not data.reason_code:
        raise ValidationFailed(
            f"{data.action} needs a reason",
            errors=[
                {
                    "loc": ["body", "reason_code"],
                    "msg": "a reason code is required",
                    "code": "reason_required",
                }
            ],
        )
    lines = lines_of(uow, order)
    frm = order.status
    if data.action == "confirm":
        order.confirmed_at = uow.now()
        order.confirmed_by = uow.actor.user_id
        if order.default_warehouse_id is None:
            wh = inventory.default_warehouse(uow)
            order.default_warehouse_id = wh.id if wh else None
    elif data.action == "hold":
        order.hold_reason_code, order.hold_reason = data.reason_code, data.reason
    elif data.action == "release_hold":
        order.hold_reason_code, order.hold_reason = None, None
    elif data.action == "cancel":
        if any(Decimal(ln.qty_delivered) > 0 for ln in lines):
            raise Conflict(
                "Delivered quantities cannot be cancelled: cancel the remaining lines instead",
                code="has_deliveries",
            )
        locked = uow.lock(SalesOrderLine, [ln.id for ln in lines])
        for ln in locked:
            inventory.release_for_demand(uow, "so_line", ln.id, reason_code="order_cancelled")
            ln.qty_cancelled = Decimal(ln.qty_ordered) - Decimal(ln.qty_delivered)
            ln.cancel_reason_code = data.reason_code
        order.cancelled_at, order.cancelled_by = uow.now(), uow.actor.user_id
        order.cancel_reason_code, order.cancel_reason = data.reason_code, data.reason
    order.status = to
    uow.flush()
    _history(
        uow,
        order,
        {"release_hold": OrderAction.RELEASE_HOLD.value}.get(data.action, data.action),
        frm,
        to,
        reason_code=data.reason_code,
        reason=data.reason,
    )
    _emit_order(uow, TRANSITION_EVENTS[data.action], order, data.reason_code)
    uow.audit(
        f"orders.sales_order.{data.action}",
        resource_type=RESOURCE,
        resource_id=order.id,
        resource_label=order.order_number,
        reason=data.reason,
        details={"from_status": frm, "to_status": to, "reason_code": data.reason_code},
    )
    return order


def _line_locked(uow: UnitOfWork, order: SalesOrder, line_id: uuid.UUID) -> SalesOrderLine:
    rows = uow.lock(SalesOrderLine, [line_id])
    if not rows or rows[0].order_id != order.id:
        raise NotFound(code="not_found", resource_type="orders.sales_order_line")
    uow.session.refresh(rows[0])
    return rows[0]


def _refresh_fulfilment(uow: UnitOfWork, order: SalesOrder) -> None:
    lines = lines_of(uow, order)
    deliverable = [ln for ln in lines if ln.line_kind != LineKind.CHARGE.value]
    delivered = any(Decimal(ln.qty_delivered) > 0 for ln in deliverable)
    open_qty = any(
        Decimal(ln.qty_ordered) - Decimal(ln.qty_cancelled) - Decimal(ln.qty_delivered) > 0
        for ln in deliverable
    )
    order.fulfilment_state = (
        FulfilmentState.COMPLETE
        if delivered and not open_qty
        else FulfilmentState.PARTIAL
        if delivered
        else FulfilmentState.NONE
    ).value
    if order.status in (S.CONFIRMED.value, S.ON_HOLD.value) and delivered and not open_qty:
        frm = order.status
        order.status = S.COMPLETED.value
        order.completed_at = uow.now()
        uow.flush()
        _history(uow, order, OrderAction.COMPLETE.value, frm, order.status)
        _emit_order(uow, ev.ORDER_COMPLETED, order, "fulfilled")
    elif order.status == S.COMPLETED.value and open_qty:
        order.status = S.CONFIRMED.value
        order.completed_at = None
        uow.flush()
        _history(uow, order, OrderAction.REVERSE_DELIVERY.value, S.COMPLETED.value, order.status)
        _emit_order(uow, ev.ORDER_CONFIRMED, order, "delivery_reversed")
    else:
        uow.flush()


def cancel_line(uow: UnitOfWork, order_id: uuid.UUID, line_id: uuid.UUID, data: LineCancel) -> SalesOrder:
    """Cancel (part of) a line's remaining quantity under the line lock; releases what is no longer needed."""
    order = _locked(uow, order_id, "transition")
    if order.status not in OPEN:
        raise Conflict("The order is closed", code="order_closed")
    line = _line_locked(uow, order, line_id)
    uow.expect_version(line, data.expected_version)
    remaining = Decimal(line.qty_ordered) - Decimal(line.qty_cancelled) - Decimal(line.qty_delivered)
    qty = remaining if data.quantity is None else Decimal(data.quantity)
    if qty <= 0 or qty > remaining:
        raise ValidationFailed(
            "Only the remaining quantity can be cancelled (delivered goods go through returns)",
            errors=[
                {
                    "loc": ["body", "quantity"],
                    "msg": f"at most {format(remaining.normalize(), 'f')}",
                    "code": "exceeds_remaining",
                }
            ],
        )
    line.qty_cancelled = Decimal(line.qty_cancelled) + qty
    line.cancel_reason_code = data.reason_code.value
    uow.flush()
    if line.fulfilment_mode == FulfilmentMode.STOCK.value:
        _trim_reservations(uow, line, remaining - qty)
    _history(
        uow,
        order,
        OrderAction.CANCEL_LINE.value,
        order.status,
        order.status,
        line_id=line.id,
        reason_code=data.reason_code.value,
        reason=data.reason,
    )
    uow.emit(
        ev.LINE_CANCELLED,
        aggregate_id=order.id,
        aggregate_version=order.version,
        payload={"order_id": str(order.id), "line_id": str(line.id)},
    )
    uow.audit(
        "orders.sales_order_line.cancel",
        resource_type=RESOURCE,
        resource_id=order.id,
        resource_label=order.order_number,
        reason=data.reason,
        details={"line_no": line.line_no, "reason_code": data.reason_code.value},
    )
    _refresh_fulfilment(uow, order)
    if (
        order.status in OPEN
        and all(
            Decimal(ln.qty_ordered) - Decimal(ln.qty_cancelled) - Decimal(ln.qty_delivered) <= 0
            for ln in lines_of(uow, order)
            if ln.line_kind != LineKind.CHARGE.value
        )
        and not any(Decimal(ln.qty_delivered) > 0 for ln in lines_of(uow, order))
    ):
        frm = order.status
        order.status = S.CANCELLED.value
        order.cancelled_at, order.cancelled_by = uow.now(), uow.actor.user_id
        order.cancel_reason_code, order.cancel_reason = data.reason_code.value, data.reason
        uow.flush()
        _history(uow, order, OrderAction.CANCEL.value, frm, order.status, reason_code=data.reason_code.value)
        _emit_order(uow, ev.ORDER_CANCELLED, order, data.reason_code.value)
    return order


def _trim_reservations(uow: UnitOfWork, line: SalesOrderLine, still_needed_line_units: Decimal) -> None:
    """Release reservations beyond what the line still needs (newest first)."""
    needed = _stock_unit(uow, line, still_needed_line_units) if still_needed_line_units > 0 else ZERO
    active = inventory.active_for_demand(uow, "so_line", line.id)
    held = sum((inventory.remaining(r) for r in active), ZERO)
    excess = held - needed
    for r in reversed(active):
        if excess <= 0:
            break
        take = min(excess, inventory.remaining(r))
        inventory.release(uow, r.id, reason_code="line_cancelled", quantity=take)
        excess -= take


def _require_reserve(uow: UnitOfWork, order: SalesOrder) -> None:
    if not can_reserve(uow, order):
        raise Forbidden(code="permission_denied", permission="inventory.stock.reserve")


def reserve_order(uow: UnitOfWork, order_id: uuid.UUID, data: ReserveRequest) -> ReserveResponse:
    """Reserve the unreserved remainder of the order's stock lines (lock order: header -> lines -> summaries)."""
    order = uow.repo(SalesOrder).get(order_id, for_update=True)
    _require_reserve(uow, order)
    if order.status != S.CONFIRMED.value:
        raise Conflict(
            "Only a confirmed order reserves stock", code="order_not_confirmed", current_status=order.status
        )
    warehouse = inventory.resolve_warehouse(uow, data.warehouse_id or order.default_warehouse_id)
    require_warehouse_for(uow, warehouse.id, "inventory.stock.reserve")  # IDOR: the actor's warehouses only
    lines = [ln for ln in lines_of(uow, order) if ln.fulfilment_mode == FulfilmentMode.STOCK.value]
    if data.line_ids is not None:
        wanted = set(data.line_ids)
        unknown = wanted - {ln.id for ln in lines}
        if unknown:
            raise ValidationFailed(
                "Only stock lines of this order can be reserved",
                errors=[
                    {
                        "loc": ["body", "line_ids"],
                        "msg": "not a stock line of this order",
                        "code": "not_stock_line",
                    }
                ],
            )
        lines = [ln for ln in lines if ln.id in wanted]
    locked = uow.lock(SalesOrderLine, [ln.id for ln in lines])
    outcomes: list[LineReserveOutcome] = []
    for ln in sorted(locked, key=lambda x: x.line_no):
        uow.session.refresh(ln)
        remaining = Decimal(ln.qty_ordered) - Decimal(ln.qty_cancelled) - Decimal(ln.qty_delivered)
        if remaining <= 0:
            continue
        need = _stock_unit(uow, ln, remaining) - inventory.reserved_by_demand(uow, "so_line", [ln.id]).get(
            ln.id, ZERO
        )
        if need <= 0:
            continue
        result = inventory.reserve(
            uow,
            demand_type="so_line",
            demand_id=ln.id,
            demand_parent_id=order.id,
            demand_label=f"{order.order_number} · line {ln.line_no}",
            product_id=ln.product_id,  # type: ignore[arg-type]
            warehouse_id=warehouse.id,
            quantity=need,
            policy=data.policy,
        )
        outcomes.append(
            LineReserveOutcome(
                line_id=ln.id,
                requested=_line_unit(uow, ln, result.requested, result.uom_code),
                granted=_line_unit(uow, ln, result.granted, result.uom_code),
                shortfall=_line_unit(uow, ln, result.shortfall, result.uom_code),
                unit=ln.uom_code,
            )
        )
    uow.flush()
    uow.audit(
        "inventory.stock.reserve",
        resource_type=RESOURCE,
        resource_id=order.id,
        resource_label=order.order_number,
        details={"lines": len(outcomes), "policy": data.policy.value, "warehouse": warehouse.code},
    )
    return ReserveResponse(order=detail(uow, order), outcomes=outcomes)


def release_order_reservations(uow: UnitOfWork, order_id: uuid.UUID, data: ReleaseRequest) -> SalesOrder:
    order = uow.repo(SalesOrder).get(order_id, for_update=True)
    _require_reserve(uow, order)
    lines = lines_of(uow, order)
    ids = set(data.line_ids) if data.line_ids is not None else {ln.id for ln in lines}
    for ln in uow.lock(SalesOrderLine, sorted(ids & {x.id for x in lines})):
        inventory.release_for_demand(uow, "so_line", ln.id, reason_code=data.reason_code)
    uow.flush()
    return order


# ---- fulfilment (called by the challan movement policy, inside the challan's transaction) --------------------------
def lock_lines(uow: UnitOfWork, line_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, SalesOrderLine]:
    """Lock the orders (sorted) then the lines (sorted): taken before any summary lock of a fulfilment posting."""
    if not line_ids:
        return {}
    lines = list(
        uow.session.scalars(
            select(SalesOrderLine).where(
                SalesOrderLine.company_id == uow.actor.company_id, SalesOrderLine.id.in_(set(line_ids))
            )
        )
    )
    uow.lock(SalesOrder, [ln.order_id for ln in lines])
    locked = uow.lock(SalesOrderLine, [ln.id for ln in lines])
    for ln in locked:
        uow.session.refresh(ln)
    return {ln.id: ln for ln in locked}


def _fulfilment_line(
    uow: UnitOfWork, line_id: uuid.UUID, qty: Decimal, uom: str
) -> tuple[SalesOrder, SalesOrderLine, Decimal]:
    line = lock_lines(uow, [line_id]).get(line_id)
    if line is None:
        raise NotFound(code="not_found", resource_type="orders.sales_order_line")
    order = uow.session.get(SalesOrder, line.order_id)
    assert order is not None
    if uom != line.uom_code:
        qty = convert(uow, Decimal(qty), uom, line.uom_code, line.product_id)
    return order, line, Decimal(qty)


def record_delivery(
    uow: UnitOfWork,
    line_id: uuid.UUID,
    qty: Decimal,
    uom: str,
    *,
    challan_id: uuid.UUID,
    reference: str | None,
) -> None:
    order, line, q = _fulfilment_line(uow, line_id, qty, uom)
    if order.status not in (S.CONFIRMED.value, S.ON_HOLD.value) and order.status != S.COMPLETED.value:
        raise Conflict(
            f"Order {order.order_number} is {order.status}: confirm it before delivering",
            code="order_not_confirmed",
        )
    if order.status == S.ON_HOLD.value:
        raise Conflict(f"Order {order.order_number} is on hold", code="order_on_hold")
    remaining = Decimal(line.qty_ordered) - Decimal(line.qty_cancelled) - Decimal(line.qty_delivered)
    if q > remaining:
        raise Conflict(
            f"Line {line.line_no} of {order.order_number} has only {format(remaining.normalize(), 'f')} {line.uom_code} left to deliver",
            code="over_delivery",
            line_id=str(line.id),
        )
    line.qty_delivered = Decimal(line.qty_delivered) + q
    uow.flush()
    _history(
        uow,
        order,
        OrderAction.DELIVER.value,
        order.status,
        order.status,
        line_id=line.id,
        reference=reference,
    )
    uow.emit(
        ev.LINE_DELIVERED,
        aggregate_id=order.id,
        aggregate_version=order.version,
        payload={"order_id": str(order.id), "line_id": str(line.id), "challan_id": str(challan_id)},
    )
    _refresh_fulfilment(uow, order)


def reverse_delivery(
    uow: UnitOfWork,
    line_id: uuid.UUID,
    qty: Decimal,
    uom: str,
    *,
    challan_id: uuid.UUID,
    reference: str | None,
) -> None:
    order, line, q = _fulfilment_line(uow, line_id, qty, uom)
    if q > Decimal(line.qty_delivered) - Decimal(line.qty_returned):
        raise Conflict(
            "More would be un-delivered than was delivered net of returns", code="reversal_exceeds_delivered"
        )
    line.qty_delivered = Decimal(line.qty_delivered) - q
    uow.flush()
    _history(
        uow,
        order,
        OrderAction.REVERSE_DELIVERY.value,
        order.status,
        order.status,
        line_id=line.id,
        reference=reference,
    )
    _refresh_fulfilment(uow, order)


def record_return(
    uow: UnitOfWork,
    line_id: uuid.UUID,
    qty: Decimal,
    uom: str,
    *,
    challan_id: uuid.UUID,
    reference: str | None,
    reverse: bool = False,
) -> None:
    order, line, q = _fulfilment_line(uow, line_id, qty, uom)
    new = Decimal(line.qty_returned) + (-q if reverse else q)
    if new < 0 or new > Decimal(line.qty_delivered):
        raise Conflict(
            "The return exceeds what was delivered on the order line",
            code="excess_return",
            line_id=str(line.id),
        )
    line.qty_returned = new
    uow.flush()
    _history(
        uow,
        order,
        OrderAction.RETURN.value,
        order.status,
        order.status,
        line_id=line.id,
        reference=reference,
        reason_code="return_cancelled" if reverse else None,
    )


# ---- documents from the order --------------------------------------------------------------------------------------
def create_challan_for_order(uow: UnitOfWork, order_id: uuid.UUID, data: ChallanFromOrder) -> uuid.UUID:
    """A draft Outward challan to the order's party with one line per stock line (reserved quantity, else remaining)."""
    from app.modules.challans import movement
    from app.modules.challans import service as challans
    from app.modules.challans.schemas import (
        ChallanCreate,
        ChallanLineCreate,
        ChallanType,
        DestinationType,
        LineType,
    )

    order = uow.repo(SalesOrder).get(order_id)
    if order.status != S.CONFIRMED.value:
        raise Conflict(
            "Only a confirmed order is delivered", code="order_not_confirmed", current_status=order.status
        )
    lines = lines_of(uow, order)
    reserved = _reserved_line_units(uow, lines)
    wanted: list[tuple[SalesOrderLine, Decimal]] = []
    for ln in lines:
        if ln.line_kind == LineKind.CHARGE.value:
            continue
        remaining = Decimal(ln.qty_ordered) - Decimal(ln.qty_cancelled) - Decimal(ln.qty_delivered)
        if data.quantities is not None:
            if ln.id not in data.quantities:
                continue
            q = Decimal(data.quantities[ln.id])
        else:
            q = reserved.get(ln.id, ZERO) if ln.fulfilment_mode == FulfilmentMode.STOCK.value else remaining
        if q <= 0:
            continue
        if q > remaining:
            raise ValidationFailed(
                "A challan cannot deliver more than remains on the order",
                errors=[
                    {
                        "loc": ["body", "quantities", str(ln.id)],
                        "msg": "exceeds remaining",
                        "code": "exceeds_remaining",
                    }
                ],
            )
        wanted.append((ln, q))
    if not wanted:
        raise Conflict(
            "Nothing to deliver: reserve stock or choose quantities first", code="nothing_to_deliver"
        )
    if data.warehouse_id is not None:
        chosen = inventory.resolve_warehouse(uow, data.warehouse_id)
        require_warehouse(uow, chosen.id)  # IDOR: only a warehouse the actor can see (404 otherwise)
    body = ChallanCreate(
        challan_type=ChallanType.OUTWARD,
        destination_type=DestinationType.CUSTOMER,
        party_id=order.party_id,
        source_warehouse_id=data.warehouse_id or order.default_warehouse_id,
        reference_no=order.order_number,
        lines=[
            ChallanLineCreate(
                line_type=LineType.CATALOG, product_id=ln.product_id, quantity=q, unit=ln.uom_code
            )
            if ln.product_id
            else ChallanLineCreate(
                line_type=LineType.MANUAL, item_name=ln.description[:500], quantity=q, unit=ln.uom_code
            )
            for ln, q in wanted
        ],
    )
    challan = challans.create_challan(uow, body)
    uow.flush()
    created = challans.lines_of(uow, challan)
    movement.link_order(
        uow, challan.id, order.id, {cl.id: ln.id for cl, (ln, _q) in zip(created, wanted, strict=True)}
    )
    return challan.id


def impact_preview(uow: UnitOfWork, order_id: uuid.UUID) -> ImpactPreview:
    order = uow.repo(SalesOrder).get(order_id)
    lines = lines_of(uow, order)
    reserved = _reserved_line_units(uow, lines)
    wh = None
    try:
        wh = inventory.resolve_warehouse(uow, order.default_warehouse_id)
    except ValidationFailed:
        wh = None
    out: list[ImpactLine] = []
    for ln in lines:
        remaining = Decimal(ln.qty_ordered) - Decimal(ln.qty_cancelled) - Decimal(ln.qty_delivered)
        res = reserved.get(ln.id, ZERO)
        if ln.fulfilment_mode != FulfilmentMode.STOCK.value or wh is None:
            out.append(
                ImpactLine(
                    line_id=ln.id,
                    product_key=ln.product_key,
                    unit=ln.uom_code,
                    remaining=remaining,
                    reserved=res,
                    available_now=None,
                    outcome="not_stock",
                    shortfall=ZERO,
                )
            )
            continue
        s = inventory.summary_of(uow, ln.product_id, wh.id)  # type: ignore[arg-type]
        free_stock = max(Decimal(s.available_on_hand) - Decimal(s.reserved), ZERO) if s else ZERO
        stock_uom = inventory.stock_quantity(uow, ln.product_id, Decimal(1), ln.uom_code)[1]  # type: ignore[arg-type]
        free = _line_unit(uow, ln, free_stock, stock_uom)
        need = max(remaining - res, ZERO)
        short = max(need - free, ZERO)
        outcome = "covered" if short == 0 else ("partial" if free > 0 else "short")
        out.append(
            ImpactLine(
                line_id=ln.id,
                product_key=ln.product_key,
                unit=ln.uom_code,
                remaining=remaining,
                reserved=res,
                available_now=free,
                outcome=outcome,
                shortfall=short,
            )
        )  # type: ignore[arg-type]
    return ImpactPreview(
        order_id=order.id,
        warehouse=WarehouseRef(id=wh.id, code=wh.code, name=wh.name) if wh else None,
        lines=out,
    )


# ---- shortage demand provider and pair resolver (registered on load) ------------------------------------------------
def open_demand(uow: UnitOfWork, product_id: uuid.UUID, warehouse_id: uuid.UUID) -> list[inventory.Demand]:
    """Confirmed (or held) orders' stock lines for ``product_id`` delivered from ``warehouse_id``: unreserved remainder."""
    rows = list(
        uow.session.execute(
            select(SalesOrderLine, SalesOrder.default_warehouse_id)
            .join(SalesOrder, SalesOrder.id == SalesOrderLine.order_id)
            .where(
                SalesOrderLine.company_id == uow.actor.company_id,
                SalesOrderLine.product_id == product_id,
                SalesOrderLine.fulfilment_mode == FulfilmentMode.STOCK.value,
                SalesOrder.status.in_([S.CONFIRMED.value, S.ON_HOLD.value]),
                or_(
                    SalesOrder.default_warehouse_id == warehouse_id, SalesOrder.default_warehouse_id.is_(None)
                ),
                SalesOrderLine.qty_remaining > 0,
            )
            .order_by(SalesOrderLine.id)
        ).all()
    )
    if not rows:
        return []
    default = None
    if any(w is None for _ln, w in rows):
        wh = inventory.default_warehouse(uow)
        default = wh.id if wh else None
    lines = [ln for ln, w in rows if (w or default) == warehouse_id]
    reserved = inventory.reserved_by_demand(uow, "so_line", [ln.id for ln in lines])
    out = []
    for ln in lines:
        need = _stock_unit(uow, ln, Decimal(ln.qty_remaining)) - reserved.get(ln.id, ZERO)
        if need > 0:
            out.append(inventory.Demand("orders.sales_order_line", ln.id, need))
    return out


def pairs_for_order_event(uow: UnitOfWork, event: Any) -> set[tuple[uuid.UUID, uuid.UUID]]:
    payload = event.payload or {}
    raw = payload.get("order_id")
    if not raw:
        return set()
    order = uow.session.get(SalesOrder, uuid.UUID(str(raw)))
    if order is None:
        return set()
    wh_id = order.default_warehouse_id
    if wh_id is None:
        wh = inventory.default_warehouse(uow)
        wh_id = wh.id if wh else None
    if wh_id is None:
        return set()
    pairs = {
        (ln.product_id, wh_id)
        for ln in lines_of(uow, order)
        if ln.product_id and ln.fulfilment_mode == FulfilmentMode.STOCK.value
    }
    for r in uow.session.scalars(
        select(Reservation).where(
            Reservation.company_id == uow.actor.company_id, Reservation.demand_parent_id == order.id
        )
    ):
        pairs.add((r.product_id, r.warehouse_id))
    return pairs  # type: ignore[return-value]


__all__ = [
    "can_reserve",
    "cancel_line",
    "convert_quote",
    "convert_quote_command",
    "create_challan_for_order",
    "detail",
    "get_order",
    "get_order_by_number",
    "impact_preview",
    "list_orders",
    "lock_lines",
    "open_demand",
    "order_for_quote",
    "pairs_for_order_event",
    "record_delivery",
    "record_return",
    "release_order_reservations",
    "reserve_order",
    "reverse_delivery",
    "transition_order",
    "update_order",
]
