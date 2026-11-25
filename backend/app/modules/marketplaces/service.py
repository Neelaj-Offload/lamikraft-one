"""Marketplace channels, listings, order import and the stock sync (module 5).

An imported order moves stock out of the channel warehouse's inventory (STOCK) to the company customer location in
one posting (source ``marketplace_order``), exactly once per external order. An order whose SKU is not mapped, or
whose free stock is short, is kept as ``needs_attention`` with the reason. The sync then pushes the free quantity of
every push-enabled listing; sample and exhibition stock never count as free.
Spec: docs/superpowers/specs/2026-11-25-marketplace-sync-design.md
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import func, select

from app.core.db.base import new_id
from app.core.errors import AppError, Conflict, NotFound, ValidationFailed
from app.core.http.capabilities import Capability
from app.modules.catalogue.models import Product
from app.modules.inventory.enums import LocationType
from app.modules.inventory.locations import company_location, default_location
from app.modules.inventory.models import StockSummary, Warehouse
from app.modules.inventory.posting import PostingLine, PostingRequest, post_movement
from app.modules.marketplaces.adapters import (
    AdapterError,
    ExternalLine,
    ExternalOrder,
    adapter_for,
    amazon_configured,
)
from app.modules.marketplaces.models import MarketplaceChannel, MarketplaceListing, MarketplaceOrder
from app.platform.service import query
from app.platform.uow import UnitOfWork

READ = "marketplaces.channel.read"
MANAGE = "marketplaces.channel.manage"
RUN = "marketplaces.channel.run"
SOURCE = "marketplace_order"
DEFAULT_CHANNELS = (
    ("amazon_in", "Amazon India", "amazon"),
    ("flipkart", "Flipkart", "flipkart"),
    ("pepperfry", "Pepperfry", "pepperfry"),
    ("website", "Website", "website"),
)

Sku = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


# ---- schemas -------------------------------------------------------------------------------------------------
class ChannelUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    mode: Literal["demo", "live"] | None = None
    warehouse_id: uuid.UUID | None = None
    is_active: bool | None = None


class ListingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: uuid.UUID
    channel_sku: Sku
    external_id: Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)] | None = None
    product_type: Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)] | None = None
    push_stock: bool = True


class ListingUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    external_id: Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)] | None = None
    product_type: Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)] | None = None
    push_stock: bool | None = None
    is_active: bool | None = None


class SimulatedOrder(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel_sku: Sku
    quantity: int = Field(ge=1, le=1000)


class ListingRead(BaseModel):
    id: uuid.UUID
    channel_id: uuid.UUID
    product_id: uuid.UUID
    product_key: str
    product_name: str
    channel_sku: str
    external_id: str | None
    product_type: str | None
    push_stock: bool
    is_active: bool
    free_quantity: str
    last_pushed_qty: str | None
    last_pushed_at: datetime | None
    last_push_error: str | None
    version: int


class OrderRead(BaseModel):
    id: uuid.UUID
    channel_id: uuid.UUID
    external_order_id: str
    ordered_at: datetime
    status: Literal["posted", "needs_attention", "cancelled"]
    lines: list[dict[str, Any]]
    attention_reason: str | None
    posting_id: uuid.UUID | None
    is_demo: bool


class ChannelRead(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    kind: str
    mode: Literal["demo", "live"]
    warehouse_id: uuid.UUID
    warehouse_code: str
    is_active: bool
    live_available: bool
    last_synced_at: datetime | None
    last_sync_summary: dict[str, Any] | None
    listing_count: int
    attention_count: int
    version: int
    capabilities: dict[str, Capability]


class ChannelDetail(ChannelRead):
    listings: list[ListingRead]
    orders: list[OrderRead]


class SyncSummary(BaseModel):
    channel_id: uuid.UUID
    mode: str
    orders_fetched: int
    orders_posted: int
    orders_held: int
    listings_pushed: int
    push_errors: list[str]
    error: str | None = None


# ---- helpers -------------------------------------------------------------------------------------------------
def _fmt(value: Decimal | None) -> str:
    return format(value.normalize(), "f") if value else "0"


def _cap(ok: bool, reason: str) -> Capability:
    return Capability(allowed=ok, reason_code=None if ok else reason)


def _live_available(kind: str) -> bool:
    return kind == "amazon" and amazon_configured()


def ensure_default_channels(uow: UnitOfWork) -> None:
    """The four channels exist in Demo mode, shipping from the default warehouse (first use per company)."""
    if uow.session.scalar(select(func.count()).select_from(MarketplaceChannel).where(
            MarketplaceChannel.company_id == uow.actor.company_id)):
        return
    warehouse = uow.session.scalars(
        select(Warehouse).where(Warehouse.company_id == uow.actor.company_id, Warehouse.is_active.is_(True)).order_by(Warehouse.code)
    ).first()
    if warehouse is None:
        return
    for code, name, kind in DEFAULT_CHANNELS:
        uow.add(MarketplaceChannel(id=new_id(), company_id=uow.actor.company_id, code=code, name=name, kind=kind, mode="demo",
                                   warehouse_id=warehouse.id, is_active=True))
    uow.flush()


def _channel(uow: UnitOfWork, channel_id: uuid.UUID, *, lock: bool = False) -> MarketplaceChannel:
    stmt = select(MarketplaceChannel).where(MarketplaceChannel.id == channel_id,
                                            MarketplaceChannel.company_id == uow.actor.company_id)
    row = uow.session.scalars(stmt.with_for_update() if lock else stmt).first()
    if row is None:
        raise NotFound(code="not_found", resource_type="marketplaces.channel")
    return row


def _free(uow: UnitOfWork, product_id: uuid.UUID, warehouse_id: uuid.UUID) -> Decimal:
    value = uow.session.scalar(select(StockSummary.available_on_hand).where(
        StockSummary.company_id == uow.actor.company_id, StockSummary.product_id == product_id,
        StockSummary.warehouse_id == warehouse_id))
    return Decimal(value or 0)


def _channel_read(uow: UnitOfWork, ch: MarketplaceChannel) -> dict[str, Any]:
    wh_code = uow.session.scalar(select(Warehouse.code).where(Warehouse.id == ch.warehouse_id)) or ""
    listings = uow.session.scalar(select(func.count()).select_from(MarketplaceListing).where(
        MarketplaceListing.channel_id == ch.id, MarketplaceListing.is_active.is_(True))) or 0
    attention = uow.session.scalar(select(func.count()).select_from(MarketplaceOrder).where(
        MarketplaceOrder.channel_id == ch.id, MarketplaceOrder.status == "needs_attention")) or 0
    manage, run = uow.actor.can(MANAGE), uow.actor.can(RUN)
    return {
        "id": ch.id, "code": ch.code, "name": ch.name, "kind": ch.kind, "mode": ch.mode, "warehouse_id": ch.warehouse_id,
        "warehouse_code": wh_code, "is_active": ch.is_active, "live_available": _live_available(ch.kind),
        "last_synced_at": ch.last_synced_at, "last_sync_summary": ch.last_sync_summary, "listing_count": int(listings),
        "attention_count": int(attention), "version": ch.version,
        "capabilities": {
            "manage": _cap(manage, "permission_denied"),
            "sync": _cap(run and ch.is_active, "permission_denied" if not run else "inactive"),
            "simulate": _cap(run and ch.mode == "demo" and ch.is_active, "permission_denied" if not run else "live_mode"),
        },
    }


def _listing_read(uow: UnitOfWork, ln: MarketplaceListing, warehouse_id: uuid.UUID, products: dict[uuid.UUID, tuple[str, str]]) -> ListingRead:
    key, name = products.get(ln.product_id, ("", ""))
    return ListingRead(
        id=ln.id, channel_id=ln.channel_id, product_id=ln.product_id, product_key=key, product_name=name,
        channel_sku=ln.channel_sku, external_id=ln.external_id, product_type=ln.product_type, push_stock=ln.push_stock,
        is_active=ln.is_active, free_quantity=_fmt(_free(uow, ln.product_id, warehouse_id)),
        last_pushed_qty=_fmt(ln.last_pushed_qty) if ln.last_pushed_qty is not None else None,
        last_pushed_at=ln.last_pushed_at, last_push_error=ln.last_push_error, version=ln.version,
    )


def _order_read(o: MarketplaceOrder) -> OrderRead:
    return OrderRead(id=o.id, channel_id=o.channel_id, external_order_id=o.external_order_id, ordered_at=o.ordered_at,
                     status=o.status, lines=list(o.lines), attention_reason=o.attention_reason,  # type: ignore[arg-type]
                     posting_id=o.posting_id, is_demo=o.is_demo)


# ---- reads ---------------------------------------------------------------------------------------------------
def list_channels(uow: UnitOfWork) -> list[ChannelRead]:
    uow.actor.require(READ)
    ensure_default_channels(uow)
    rows = uow.session.scalars(select(MarketplaceChannel).where(
        MarketplaceChannel.company_id == uow.actor.company_id).order_by(MarketplaceChannel.code))
    return [ChannelRead(**_channel_read(uow, ch)) for ch in rows]


@query(READ)
def get_channel(uow: UnitOfWork, channel_id: uuid.UUID) -> ChannelDetail:
    ch = _channel(uow, channel_id)
    listings = list(uow.session.scalars(select(MarketplaceListing).where(MarketplaceListing.channel_id == ch.id)
                                        .order_by(MarketplaceListing.channel_sku)))
    products = dict((pid, (k, n)) for pid, k, n in uow.session.execute(
        select(Product.id, Product.product_key, Product.product_name).where(Product.id.in_([ln.product_id for ln in listings]))
    )) if listings else {}
    orders = list(uow.session.scalars(select(MarketplaceOrder).where(MarketplaceOrder.channel_id == ch.id)
                                      .order_by(MarketplaceOrder.ordered_at.desc()).limit(50)))
    return ChannelDetail(
        **_channel_read(uow, ch),
        listings=[_listing_read(uow, ln, ch.warehouse_id, products) for ln in listings],
        orders=[_order_read(o) for o in orders],
    )


# ---- channel and listing writes ----------------------------------------------------------------------------------
def update_channel(uow: UnitOfWork, channel_id: uuid.UUID, data: ChannelUpdate) -> MarketplaceChannel:
    uow.actor.require(MANAGE)
    ch = _channel(uow, channel_id, lock=True)
    uow.expect_version(ch, data.expected_version)
    if data.mode == "live" and not _live_available(ch.kind):
        raise ValidationFailed(
            "Live mode needs the platform's credentials in the server environment",
            errors=[{"loc": ["body", "mode"], "msg": "credentials not configured", "code": "live_not_configured"}],
        )
    if data.warehouse_id is not None:
        if uow.session.scalar(select(Warehouse.id).where(Warehouse.id == data.warehouse_id,
                                                        Warehouse.company_id == uow.actor.company_id)) is None:
            raise NotFound(code="not_found", resource_type="inventory.warehouse")
        ch.warehouse_id = data.warehouse_id
    if data.mode is not None:
        ch.mode = data.mode
    if data.is_active is not None:
        ch.is_active = data.is_active
    ch.updated_at = uow.now()
    uow.flush()
    uow.audit("marketplaces.channel.updated", resource_type="marketplaces.channel", resource_id=ch.id, resource_label=ch.code,
              details=data.model_dump(mode="json", exclude={"expected_version"}, exclude_none=True))
    return ch


def create_listing(uow: UnitOfWork, channel_id: uuid.UUID, data: ListingCreate) -> MarketplaceListing:
    uow.actor.require(MANAGE)
    ch = _channel(uow, channel_id)
    if uow.session.scalar(select(Product.id).where(Product.id == data.product_id, Product.company_id == uow.actor.company_id)) is None:
        raise NotFound(code="not_found", resource_type="catalogue.product")
    if uow.session.scalar(select(MarketplaceListing.id).where(MarketplaceListing.channel_id == ch.id,
                                                             MarketplaceListing.channel_sku == data.channel_sku)):
        raise Conflict("This SKU is already mapped on the channel", code="sku_mapped")
    ln = MarketplaceListing(id=new_id(), company_id=uow.actor.company_id, channel_id=ch.id, product_id=data.product_id,
                            channel_sku=data.channel_sku, external_id=data.external_id, product_type=data.product_type,
                            push_stock=data.push_stock, is_active=True)
    uow.add(ln)
    uow.flush()
    uow.audit("marketplaces.listing.created", resource_type="marketplaces.listing", resource_id=ln.id, resource_label=ln.channel_sku)
    return ln


def update_listing(uow: UnitOfWork, listing_id: uuid.UUID, data: ListingUpdate) -> MarketplaceListing:
    uow.actor.require(MANAGE)
    ln = uow.session.scalars(select(MarketplaceListing).where(
        MarketplaceListing.id == listing_id, MarketplaceListing.company_id == uow.actor.company_id).with_for_update()).first()
    if ln is None:
        raise NotFound(code="not_found", resource_type="marketplaces.listing")
    uow.expect_version(ln, data.expected_version)
    for name, value in data.model_dump(exclude_unset=True, exclude={"expected_version"}).items():
        if name in ("push_stock", "is_active") and value is None:
            continue
        setattr(ln, name, value)
    ln.updated_at = uow.now()
    uow.flush()
    return ln


# ---- order import ------------------------------------------------------------------------------------------------
def import_order(uow: UnitOfWork, ch: MarketplaceChannel, order: ExternalOrder, *, demo: bool = False) -> MarketplaceOrder | None:
    """Store one external order once and post its stock out; returns None when it was already imported."""
    if uow.session.scalar(select(MarketplaceOrder.id).where(MarketplaceOrder.channel_id == ch.id,
                                                            MarketplaceOrder.external_order_id == order.external_order_id)):
        return None
    skus = {ln.channel_sku: ln for ln in uow.session.scalars(select(MarketplaceListing).where(
        MarketplaceListing.channel_id == ch.id, MarketplaceListing.channel_sku.in_([line.sku for line in order.lines])))}
    lines = [{"sku": line.sku, "quantity": _fmt(line.quantity), "title": line.title,
              "product_id": str(skus[line.sku].product_id) if line.sku in skus else None} for line in order.lines]
    row = MarketplaceOrder(id=new_id(), company_id=uow.actor.company_id, channel_id=ch.id,
                           external_order_id=order.external_order_id, ordered_at=order.ordered_at, status="needs_attention",
                           lines=lines, is_demo=demo)
    problems: list[str] = []
    if order.status == "cancelled":
        row.status = "cancelled"
    else:
        unmapped = [line.sku for line in order.lines if line.sku not in skus]
        if unmapped:
            problems.append("SKU not mapped to a product: " + ", ".join(unmapped))
        for line in order.lines:
            if line.sku in skus and _free(uow, skus[line.sku].product_id, ch.warehouse_id) < line.quantity:
                problems.append(f"Not enough free stock for {line.sku} in the channel warehouse")
        if not order.lines:
            problems.append("The order has no items")
    uow.add(row)
    uow.flush()
    if row.status != "cancelled" and not problems:
        source = default_location(uow, ch.warehouse_id)
        customer = company_location(uow, LocationType.CUSTOMER)
        units = dict(uow.session.execute(select(Product.id, func.coalesce(Product.stock_uom_code, Product.unit_of_sale, "pcs"))
                                         .where(Product.id.in_([skus[line.sku].product_id for line in order.lines]))).all())
        try:
            receipt = post_movement(uow, PostingRequest(
                source_type=SOURCE, source_id=row.id, purpose="dispatch",
                source_label=f"{ch.name} {order.external_order_id}",
                lines=tuple(PostingLine(product_id=skus[line.sku].product_id, quantity=line.quantity,
                                        uom_code=units.get(skus[line.sku].product_id) or "pcs",
                                        from_location_id=source.id, to_location_id=customer.id) for line in order.lines),
            ))
            row.posting_id = receipt.posting.id
            row.status = "posted"
        except AppError as exc:
            problems.append(getattr(exc, "detail", None) or str(exc))
    if problems:
        row.attention_reason = "; ".join(problems)[:2000]
    uow.flush()
    uow.emit("marketplaces.order.imported", aggregate_id=row.id, aggregate_version=None,
             payload={"channel_id": str(ch.id), "order_id": str(row.id), "status": row.status})
    return row


def simulate_order(uow: UnitOfWork, channel_id: uuid.UUID, data: SimulatedOrder) -> MarketplaceOrder:
    """Demo only: an order arrives on the channel for one listing (labelled Demo everywhere it shows)."""
    uow.actor.require(RUN)
    ch = _channel(uow, channel_id, lock=True)
    if ch.mode != "demo":
        raise Conflict("Simulated orders exist only in Demo mode", code="live_mode")
    count = uow.session.scalar(select(func.count()).select_from(MarketplaceOrder).where(MarketplaceOrder.channel_id == ch.id)) or 0
    external = f"DEMO-{ch.code.upper()}-{count + 1:05d}"
    row = import_order(uow, ch, ExternalOrder(external, uow.now(), "open", (ExternalLine(data.channel_sku, Decimal(data.quantity)),)),
                       demo=True)
    assert row is not None
    return row


# ---- sync --------------------------------------------------------------------------------------------------------
def sync_channel(uow: UnitOfWork, channel_id: uuid.UUID, *, client: httpx.Client | None = None) -> SyncSummary:
    uow.actor.require(RUN)
    ch = _channel(uow, channel_id, lock=True)
    summary = SyncSummary(channel_id=ch.id, mode=ch.mode, orders_fetched=0, orders_posted=0, orders_held=0,
                          listings_pushed=0, push_errors=[])
    if not ch.is_active:
        raise Conflict("Turn the channel on before syncing it", code="inactive")
    try:
        adapter = adapter_for(ch.kind, ch.mode, client=client)
        started = uow.now()
        for order in adapter.fetch_orders(ch.last_synced_at):
            summary.orders_fetched += 1
            row = import_order(uow, ch, order)
            if row is not None:
                summary.orders_posted += row.status == "posted"
                summary.orders_held += row.status == "needs_attention"
        for ln in uow.session.scalars(select(MarketplaceListing).where(
                MarketplaceListing.channel_id == ch.id, MarketplaceListing.push_stock.is_(True),
                MarketplaceListing.is_active.is_(True))):
            free = _free(uow, ln.product_id, ch.warehouse_id)
            try:
                adapter.push_quantity(ln.channel_sku, int(free), product_type=ln.product_type)
                ln.last_pushed_qty, ln.last_pushed_at, ln.last_push_error = free, uow.now(), None
                summary.listings_pushed += 1
            except AdapterError as exc:
                ln.last_push_error = str(exc)[:500]
                summary.push_errors.append(f"{ln.channel_sku}: {exc}")
        ch.last_synced_at = started
    except AdapterError as exc:
        summary.error = str(exc)
    ch.last_sync_summary = summary.model_dump(mode="json")
    ch.updated_at = uow.now()
    uow.flush()
    uow.emit("marketplaces.sync.completed", aggregate_id=ch.id, aggregate_version=ch.version,
             payload={"channel_id": str(ch.id), "orders_posted": summary.orders_posted, "orders_held": summary.orders_held})
    return summary
