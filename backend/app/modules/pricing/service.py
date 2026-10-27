"""Pricing services: price lists, items and history, protected product cost, and deterministic price resolution.

Resolution order (ADR-018): customer agreement -> customer-type list -> standard list, then currency, unit and
effective date. Within one tier several matches are AMBIGUOUS unless exactly one carries the highest explicit
priority; ambiguity never falls through to a less specific tier. A zero price is UNAVAILABLE (no fall-through).
Prices are returned only in their list currency: a EUR figure is never relabelled as USD or INR (FX conversion
is a Slice-2 second pass that needs an approved, dated rate).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from datetime import date, timedelta
from typing import Any

from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.orm import aliased

from app.core.clock import local_date
from app.core.db.base import new_id
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.http.pagination import MAX_LIMIT, Page
from app.core.money import Money, Quantity, quantize_unit_price
from app.core.text import LIKE_ESCAPE, contains_pattern, tokens
from app.modules.catalogue import service as catalogue
from app.modules.parties import service as parties
from app.modules.pricing import events as ev
from app.modules.pricing.models import PriceList, PriceListItem, PriceListItemHistory, ProductCost
from app.modules.pricing.schemas import (
    TIERS,
    Capability,
    DisplayPrice,
    PartyMini,
    PriceCandidate,
    PricedItem,
    PriceHistoryKind,
    PriceItemStatus,
    PriceListCreate,
    PriceListDetail,
    PriceListItemCreate,
    PriceListItemRead,
    PriceListStatus,
    PriceListSummary,
    PriceResolution,
    PriceScope,
    PriceType,
    ProductCostCreate,
    ProductCostRead,
    ProductPriceRead,
    ProductPrices,
    SupersedeItem,
    Tier,
    TierCheck,
    TransitionRead,
)
from app.platform.service import query
from app.platform.uow import UnitOfWork

READ = "pricing.price.read"
MANAGE = "pricing.price_list.manage"
COST_READ = "pricing.cost.read"
L = PriceList
I = PriceListItem  # noqa: E741


def price_list_path(price_list_id: uuid.UUID) -> str:
    return f"/products/price-lists/{price_list_id}"


def business_date(uow: UnitOfWork) -> date:
    """Today in the actor's zone (default Asia/Kolkata), from the injected Clock."""
    return local_date(uow.now(), uow.actor.time_zone)


def _effective(model: Any, on: date) -> ColumnElement[bool]:
    return and_(model.valid_from <= on, or_(model.valid_to.is_(None), model.valid_to >= on))


def visible_lists(uow: UnitOfWork) -> ColumnElement[bool]:
    """Lists the actor may read: company price lists, minus customer agreements of parties outside their scope."""
    return and_(
        uow.repo(PriceList).clause("read"),
        or_(L.party_id.is_(None), L.party_id.in_(parties.visible_party_ids(uow))),
    )


def _snapshot(item: PriceListItem) -> dict[str, Any]:
    return {
        "unit_price": format(item.unit_price, "f"),
        "unit_code": item.unit_code,
        "valid_from": item.valid_from.isoformat(),
        "valid_to": item.valid_to.isoformat() if item.valid_to else None,
        "status": item.status,
        "superseded_by_item_id": str(item.superseded_by_item_id) if item.superseded_by_item_id else None,
        "moq": format(item.moq, "f") if item.moq is not None else None,
    }


def _history(
    uow: UnitOfWork,
    item: PriceListItem,
    kind: PriceHistoryKind,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    reason: str | None = None,
) -> None:
    uow.add(
        PriceListItemHistory(
            id=new_id(),
            company_id=uow.actor.company_id,
            item_id=item.id,
            price_list_id=item.price_list_id,
            change_kind=kind.value,
            before=before,
            after=after,
            reason=reason,
            occurred_at=uow.now(),
            actor_user_id=uow.actor.user_id,
        )
    )


def _errors(*items: tuple[Sequence[str], str, str]) -> ValidationFailed:
    return ValidationFailed(
        "Some pricing values are not valid",
        errors=[{"loc": ["body", *loc], "msg": msg, "code": code} for loc, code, msg in items],
    )


# =====================================================================================================
# commands (seeds, imports and tests; the price-list CRUD API arrives in Slice 2)
# =====================================================================================================
def find_price_list(uow: UnitOfWork, code: str) -> PriceList | None:
    return uow.session.scalars(select(L).where(L.company_id == uow.actor.company_id, L.code == code.strip().upper())).first()


def create_price_list(uow: UnitOfWork, data: PriceListCreate, *, origin: str | None = None) -> PriceList:
    uow.actor.require(MANAGE)
    problems: list[tuple[Sequence[str], str, str]] = []
    if data.scope_kind == PriceScope.CUSTOMER:
        if data.party_id is None:
            problems.append((["party_id"], "party_required", "A customer price list needs a party"))
        else:
            parties.get_party_ref(uow, data.party_id)  # 404 when the party is not visible
        if data.customer_type is not None:
            problems.append((["customer_type"], "not_allowed", "A customer price list has no customer type"))
    elif data.scope_kind == PriceScope.CUSTOMER_TYPE:
        if data.customer_type is None:
            problems.append((["customer_type"], "customer_type_required", "A customer-type list needs a customer type"))
        if data.party_id is not None:
            problems.append((["party_id"], "not_allowed", "Only customer price lists have a party"))
    elif data.party_id is not None or data.customer_type is not None:
        problems.append((["scope_kind"], "standard_has_no_target", "A standard list has no party or customer type"))
    if data.valid_to is not None and data.valid_to < data.valid_from:
        problems.append((["valid_to"], "validity_order", "valid_to is before valid_from"))
    if problems:
        raise _errors(*problems)
    if find_price_list(uow, data.code) is not None:
        raise Conflict("A price list with this code already exists", code="price_list_code_exists")
    row = PriceList(
        id=new_id(),
        company_id=uow.actor.company_id,
        code=data.code,
        name=data.name,
        price_type=data.price_type.value,
        scope_kind=data.scope_kind.value,
        party_id=data.party_id,
        customer_type=data.customer_type,
        currency=data.currency,
        default_unit_code=data.default_unit_code,
        price_basis=data.price_basis,
        valid_from=data.valid_from,
        valid_to=data.valid_to,
        status=PriceListStatus.DRAFT.value,
        priority=data.priority,
        notes=data.notes,
        source_kind=data.source_kind.value,
        source_ref=data.source_ref,
    )
    uow.add(row)
    uow.flush()
    uow.emit(
        ev.PRICE_LIST_CREATED,
        aggregate_id=row.id,
        aggregate_version=row.version,
        payload=ev.payload(ev.PriceListCreatedPayload(price_list_id=row.id, code=row.code, origin=origin)),
    )
    uow.audit("pricing.price_list.created", resource_type="pricing.price_list", resource_id=row.id, resource_label=row.code)
    return row


def _overlapping_items(
    uow: UnitOfWork, price_list_id: uuid.UUID, product_id: uuid.UUID, unit_code: str, valid_from: date,
    valid_to: date | None, exclude_id: uuid.UUID | None = None,
) -> list[PriceListItem]:
    stmt = select(I).where(
        I.price_list_id == price_list_id,
        I.product_id == product_id,
        I.unit_code == unit_code,
        I.status == PriceItemStatus.ACTIVE.value,
        or_(I.valid_to.is_(None), I.valid_to >= valid_from),
    )
    if valid_to is not None:
        stmt = stmt.where(I.valid_from <= valid_to)
    if exclude_id is not None:
        stmt = stmt.where(I.id != exclude_id)
    return list(uow.session.scalars(stmt))


def add_item(uow: UnitOfWork, price_list_id: uuid.UUID, data: PriceListItemCreate) -> PriceListItem:
    """Add an item to a draft list (items of an active list change only through an effective-dated supersede)."""
    uow.actor.require(MANAGE)
    price_list = _locked_list(uow, price_list_id)
    if price_list.status != PriceListStatus.DRAFT.value:
        raise Conflict("Items of an active price list change only by superseding them", code="price_list_not_draft")
    product = catalogue.get_product_ref(uow, product_id=data.product_id)
    valid_from = data.valid_from or price_list.valid_from
    valid_to = data.valid_to
    problems: list[tuple[Sequence[str], str, str]] = []
    if valid_to is not None and valid_to < valid_from:
        problems.append((["valid_to"], "validity_order", "valid_to is before valid_from"))
    if data.final_price is not None and data.final_price != data.unit_price:
        problems.append((["final_price"], "price_ambiguous", "final_price and unit_price disagree"))
    if data.moq_unit_code is not None and data.moq is None:
        problems.append((["moq_unit_code"], "moq_required", "moq_unit_code needs a moq"))
    if problems:
        raise _errors(*problems)
    if _overlapping_items(uow, price_list.id, product.id, data.unit_code, valid_from, valid_to):
        raise Conflict("The product already has an active price for this unit and period", code="price_item_overlap")
    item = PriceListItem(
        id=new_id(),
        company_id=uow.actor.company_id,
        price_list_id=price_list.id,
        product_id=product.id,
        product_key=product.product_key,
        display_sku=product.display_sku,
        unit_code=data.unit_code,
        unit_price=quantize_unit_price(data.unit_price),
        final_price=quantize_unit_price(data.final_price) if data.final_price is not None else None,
        base_price=quantize_unit_price(data.base_price) if data.base_price is not None else None,
        base_price_label=data.base_price_label,
        addon_price=quantize_unit_price(data.addon_price) if data.addon_price is not None else None,
        addon_price_label=data.addon_price_label,
        price_basis=data.price_basis,
        yield_qty_per_board=data.yield_qty_per_board,
        thickness_mm=data.thickness_mm,
        moq=data.moq,
        moq_unit_code=data.moq_unit_code or (data.unit_code if data.moq is not None else None),
        notes=data.notes,
        valid_from=valid_from,
        valid_to=valid_to,
        status=PriceItemStatus.ACTIVE.value,
        source_kind=data.source_kind.value,
        source_ref=data.source_ref,
        source_sheet=data.source_sheet,
        source_row=data.source_row,
    )
    uow.add(item)
    uow.flush()
    _history(uow, item, PriceHistoryKind.CREATED, None, _snapshot(item))
    return item


def _activation_target(pl: PriceList) -> str:
    """The overlap target of a list: company, scope target, price type and currency (one activation at a time)."""
    target = pl.party_id or pl.customer_type or "-"
    return f"{pl.company_id}:{pl.scope_kind}:{target}:{pl.price_type}:{pl.currency}"


def _activation_conflicts(uow: UnitOfWork, pl: PriceList) -> list[dict[str, Any]]:
    """Active items in other active lists with the same scope target, price type and currency that overlap an
    item of ``pl`` for the same product and unit, unless both lists carry different explicit priorities.

    One set-based query (this list's active items joined to the candidate lists' active items on product, unit and
    overlapping validity), whatever the number of items or lists."""
    other_list = aliased(PriceList)
    mine = aliased(PriceListItem)
    theirs = aliased(PriceListItem)
    conds: list[ColumnElement[bool]] = [
        mine.price_list_id == pl.id,
        mine.status == PriceItemStatus.ACTIVE.value,
        other_list.company_id == pl.company_id,
        other_list.id != pl.id,
        other_list.status == PriceListStatus.ACTIVE.value,
        other_list.scope_kind == pl.scope_kind,
        other_list.price_type == pl.price_type,
        other_list.currency == pl.currency,
        other_list.party_id.is_(None) if pl.party_id is None else other_list.party_id == pl.party_id,
        other_list.customer_type.is_(None) if pl.customer_type is None else other_list.customer_type == pl.customer_type,
        or_(other_list.valid_to.is_(None), other_list.valid_to >= pl.valid_from),
        theirs.status == PriceItemStatus.ACTIVE.value,
        or_(theirs.valid_to.is_(None), theirs.valid_to >= mine.valid_from),
        or_(mine.valid_to.is_(None), theirs.valid_from <= mine.valid_to),
    ]
    if pl.valid_to is not None:
        conds.append(other_list.valid_from <= pl.valid_to)
    if pl.priority is not None:  # different explicit priorities on both lists resolve the overlap at read time
        conds.append(or_(other_list.priority.is_(None), other_list.priority == pl.priority))
    rows = uow.session.execute(
        select(mine.product_key, mine.unit_code, other_list.code, theirs.id)
        .select_from(mine)
        .join(theirs, and_(theirs.product_id == mine.product_id, theirs.unit_code == mine.unit_code))
        .join(other_list, other_list.id == theirs.price_list_id)
        .where(*conds)
        .order_by(mine.product_key, mine.unit_code, other_list.code, theirs.id)
    ).all()
    return [
        {"product_key": key, "unit_code": unit, "price_list_code": code, "item_id": str(item_id)}
        for key, unit, code, item_id in rows
    ]


def activate_price_list(uow: UnitOfWork, price_list_id: uuid.UUID, *, origin: str | None = None) -> PriceList:
    uow.actor.require(MANAGE)
    pl = _locked_list(uow, price_list_id)
    if pl.status != PriceListStatus.DRAFT.value:
        raise Conflict(f"The price list is {pl.status}", code="price_list_not_draft")
    # serialise activations of lists with the same overlap target: a concurrent activation cannot see this
    # transaction's uncommitted status change, so the overlap check below would otherwise race (READ COMMITTED)
    uow.advisory_xact_lock("pricing.activation", _activation_target(pl))
    items = list(uow.session.scalars(select(I).where(I.price_list_id == pl.id).order_by(I.product_key, I.id)))
    if not items:
        raise Conflict("A price list needs at least one item before activation", code="price_list_empty")
    conflicts = _activation_conflicts(uow, pl)
    if conflicts:
        raise Conflict(
            "Another active list already prices these products for the same scope, type, currency and period; "
            "give both lists different explicit priorities or adjust validity",
            code="price_list_overlap",
            conflicts=conflicts,
        )
    pl.status = PriceListStatus.ACTIVE.value
    pl.activated_at = uow.now()
    pl.activated_by = uow.actor.user_id
    for item in items:
        _history(uow, item, PriceHistoryKind.LIST_ACTIVATED, None, _snapshot(item))
    uow.flush()
    uow.emit(
        ev.PRICE_LIST_ACTIVATED,
        aggregate_id=pl.id,
        aggregate_version=pl.version,
        payload=ev.payload(
            ev.PriceListActivatedPayload(
                price_list_id=pl.id, code=pl.code, scope_kind=pl.scope_kind, price_type=pl.price_type,
                currency=pl.currency, origin=origin,
            )
        ),
    )
    uow.audit("pricing.price_list.activated", resource_type="pricing.price_list", resource_id=pl.id, resource_label=pl.code)
    return pl


def supersede_item(uow: UnitOfWork, item_id: uuid.UUID, data: SupersedeItem) -> PriceListItemRead:
    """Effective-dated price change: the current item ends the day before ``valid_from`` and a new item starts.

    History rows record both sides; quotes keep the item id they were priced from (snapshot provenance).
    """
    uow.actor.require(MANAGE)
    item = uow.repo(PriceListItem).get(item_id)
    pl = _locked_list(uow, item.price_list_id)
    item = uow.lock(PriceListItem, [item.id])[0]
    problems: list[tuple[Sequence[str], str, str]] = []
    if pl.status != PriceListStatus.ACTIVE.value:
        raise Conflict(
            f"The price list is {pl.status}; only prices of an active list are superseded "
            "(draft items are edited before activation, retired lists are history)",
            code="price_list_not_active",
        )
    if item.status != PriceItemStatus.ACTIVE.value or item.superseded_by_item_id is not None:
        raise Conflict("Only the current active price can be superseded", code="price_item_not_current")
    if data.valid_from <= item.valid_from:
        problems.append((["valid_from"], "valid_from_too_early", "The new price must start after the current one"))
    if item.valid_to is not None and data.valid_from > item.valid_to:
        problems.append((["valid_from"], "valid_from_after_validity", "The current price has already ended"))
    if pl.valid_to is not None and data.valid_from > pl.valid_to:
        problems.append((["valid_from"], "valid_from_after_list", "The price list ends before valid_from"))
    if problems:
        raise _errors(*problems)
    before = _snapshot(item)
    original_end = item.valid_to
    item.valid_to = data.valid_from - timedelta(days=1)
    uow.flush()  # shorten first so the no-overlap exclusion constraint never sees two open prices
    new_item = PriceListItem(
        id=new_id(),
        company_id=uow.actor.company_id,
        price_list_id=item.price_list_id,
        product_id=item.product_id,
        product_key=item.product_key,
        display_sku=item.display_sku,
        unit_code=item.unit_code,
        unit_price=quantize_unit_price(data.unit_price),
        final_price=quantize_unit_price(data.unit_price) if item.final_price is not None else None,
        base_price=None,
        base_price_label=None,
        addon_price=None,
        addon_price_label=None,
        price_basis=item.price_basis,
        yield_qty_per_board=item.yield_qty_per_board,
        thickness_mm=item.thickness_mm,
        moq=item.moq,
        moq_unit_code=item.moq_unit_code,
        notes=item.notes,
        valid_from=data.valid_from,
        valid_to=original_end,
        status=PriceItemStatus.ACTIVE.value,
        source_kind="manual",
        source_ref=f"supersedes:{item.id}",
    )
    uow.add(new_item)
    uow.flush()
    item.superseded_by_item_id = new_item.id
    uow.flush()
    _history(uow, item, PriceHistoryKind.SUPERSEDED, before, _snapshot(item), data.reason)
    _history(uow, new_item, PriceHistoryKind.CREATED, None, _snapshot(new_item), data.reason)
    uow.emit(
        ev.ITEM_SUPERSEDED,
        aggregate_id=item.id,
        aggregate_version=item.version,
        payload=ev.payload(
            ev.ItemSupersededPayload(
                item_id=item.id, superseded_by_item_id=new_item.id, price_list_id=pl.id, product_id=item.product_id
            )
        ),
    )
    uow.audit(
        "pricing.price_list_item.superseded",
        resource_type="pricing.price_list_item",
        resource_id=item.id,
        resource_label=f"{pl.code} · {item.product_key}",
        reason=data.reason,
    )
    return _item_read(new_item, pl)


def record_product_cost(
    uow: UnitOfWork, product_id: uuid.UUID, data: ProductCostCreate, *, origin: str | None = None
) -> ProductCostRead:
    """Append a new cost version (protected; never logged, never sent to a model)."""
    uow.actor.require("pricing.cost.update")
    product = catalogue.get_product_ref(uow, product_id=product_id)
    current = uow.session.scalar(
        select(func.max(ProductCost.cost_version)).where(
            ProductCost.company_id == uow.actor.company_id, ProductCost.product_id == product.id
        )
    )
    row = ProductCost(
        id=new_id(),
        company_id=uow.actor.company_id,
        product_id=product.id,
        cost_version=int(current or 0) + 1,
        unit_cost_amount=quantize_unit_price(data.unit_cost_amount),
        unit_cost_currency=data.unit_cost_currency,
        unit_code=data.unit_code,
        cost_components=[c.model_dump(mode="json") for c in data.cost_components] or None,
        source_kind=data.source_kind.value,
        source_ref=data.source_ref,
        effective_from=data.effective_from,
        notes=data.notes,
    )
    uow.add(row)
    uow.flush()
    uow.emit(
        ev.PRODUCT_COST_RECORDED,
        aggregate_id=product.id,
        aggregate_version=row.cost_version,
        payload=ev.payload(
            ev.ProductCostRecordedPayload(
                product_id=product.id, cost_version=row.cost_version, source_kind=row.source_kind, origin=origin
            )
        ),
    )
    uow.audit(
        "pricing.product_cost.recorded",
        resource_type="pricing.product_cost",
        resource_id=row.id,
        resource_label=product.product_key,
        restricted_fields=["unit_cost_amount", "cost_components"],
    )
    return _cost_read(row)


# =====================================================================================================
# read models
# =====================================================================================================
def _party_minis(uow: UnitOfWork, ids: Iterable[uuid.UUID | None]) -> dict[uuid.UUID, PartyMini]:
    labels = parties.party_labels(uow, list(ids))
    return {pid: PartyMini(id=pid, party_number=number, display_name=name) for pid, (number, name) in labels.items()}


def _money(amount: Any, currency: str) -> Money | None:
    return None if amount is None else Money(amount=amount, currency=currency)  # type: ignore[arg-type]


def _quantity(value: Any, uom: str | None) -> Quantity | None:
    return None if value is None or uom is None else Quantity(value=value, uom=uom)


def _item_read(item: PriceListItem, pl: PriceList) -> PriceListItemRead:
    return PriceListItemRead(
        id=item.id,
        price_list_id=pl.id,
        price_list_code=pl.code,
        product_id=item.product_id,
        product_key=item.product_key,
        display_sku=item.display_sku,
        unit_code=item.unit_code,
        unit_price=Money(amount=item.unit_price, currency=pl.currency),  # type: ignore[arg-type]
        final_price=_money(item.final_price, pl.currency),
        base_price=_money(item.base_price, pl.currency),
        base_price_label=item.base_price_label,
        addon_price=_money(item.addon_price, pl.currency),
        addon_price_label=item.addon_price_label,
        price_basis=item.price_basis,
        yield_qty_per_board=item.yield_qty_per_board,
        thickness_mm=item.thickness_mm,
        source_kind=item.source_kind,
        source_ref=item.source_ref,
        source_sheet=item.source_sheet,
        source_row=item.source_row,
        moq=_quantity(item.moq, item.moq_unit_code or item.unit_code),
        notes=item.notes,
        valid_from=item.valid_from,
        valid_to=item.valid_to,
        status=item.status,  # type: ignore[arg-type]
        superseded_by_item_id=item.superseded_by_item_id,
        version=item.version,
    )


def _cost_read(row: ProductCost) -> ProductCostRead:
    return ProductCostRead(
        id=row.id,
        product_id=row.product_id,
        cost_version=row.cost_version,
        unit_cost=Money(amount=row.unit_cost_amount, currency=row.unit_cost_currency),  # type: ignore[arg-type]
        unit_code=row.unit_code,
        cost_components=row.cost_components,
        source_kind=row.source_kind,  # type: ignore[arg-type]
        effective_from=row.effective_from,
        recorded_at=row.created_at,
    )


def _list_summary_fields(pl: PriceList, minis: dict[uuid.UUID, PartyMini], item_count: int) -> dict[str, Any]:
    return {
        "id": pl.id,
        "code": pl.code,
        "name": pl.name,
        "price_type": pl.price_type,
        "scope_kind": pl.scope_kind,
        "party": minis.get(pl.party_id) if pl.party_id else None,
        "customer_type": pl.customer_type,
        "currency": pl.currency,
        "default_unit_code": pl.default_unit_code,
        "valid_from": pl.valid_from,
        "valid_to": pl.valid_to,
        "status": pl.status,
        "priority": pl.priority,
        "item_count": item_count,
        "path": price_list_path(pl.id),
    }


def _item_counts(uow: UnitOfWork, list_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not list_ids:
        return {}
    return dict(
        uow.session.execute(
            select(I.price_list_id, func.count(I.id))
            .where(I.price_list_id.in_(list_ids), I.status == PriceItemStatus.ACTIVE.value, I.superseded_by_item_id.is_(None))
            .group_by(I.price_list_id)
        ).all()
    )


@query(READ)
def list_price_lists(
    uow: UnitOfWork,
    *,
    status: Sequence[PriceListStatus] | None = None,
    scope_kind: PriceScope | None = None,
    price_type: PriceType | None = None,
    currency: str | None = None,
    party_id: uuid.UUID | None = None,
    q: str | None = None,
    on_date: date | None = None,
    limit: int = 50,
    offset: int = 0,
) -> Page[PriceListSummary]:
    conds: list[ColumnElement[bool]] = [visible_lists(uow)]
    if status:
        conds.append(L.status.in_([s.value for s in status]))
    if scope_kind:
        conds.append(L.scope_kind == scope_kind.value)
    if price_type:
        conds.append(L.price_type == price_type.value)
    if currency:
        conds.append(L.currency == currency.upper())
    if party_id:
        conds.append(L.party_id == party_id)
    if on_date:
        conds.append(_effective(L, on_date))
    for tok in tokens(q or ""):
        conds.append(or_(L.code.ilike(contains_pattern(tok), escape=LIKE_ESCAPE), L.name.ilike(contains_pattern(tok), escape=LIKE_ESCAPE)))
    total = uow.session.scalar(select(func.count(L.id)).where(*conds)) or 0
    limit = max(1, min(limit, MAX_LIMIT))
    rows = list(uow.session.scalars(select(L).where(*conds).order_by(L.code, L.id).limit(limit).offset(max(0, offset))))
    minis = _party_minis(uow, [r.party_id for r in rows])
    counts = _item_counts(uow, [r.id for r in rows])
    return Page[PriceListSummary](
        items=[PriceListSummary(**_list_summary_fields(r, minis, int(counts.get(r.id, 0)))) for r in rows],
        total=int(total),
        limit=limit,
        offset=max(0, offset),
    )


def _visible_list(uow: UnitOfWork, price_list_id: uuid.UUID, *, for_update: bool = False) -> PriceList:
    stmt = select(L).where(L.id == price_list_id, visible_lists(uow))
    pl = uow.session.scalars(stmt.with_for_update(of=L) if for_update else stmt).first()
    if pl is None:
        raise NotFound(code="not_found", resource_type="pricing.price_list")
    return pl


def _locked_list(uow: UnitOfWork, price_list_id: uuid.UUID) -> PriceList:
    return _visible_list(uow, price_list_id, for_update=True)


def _list_capabilities(uow: UnitOfWork, pl: PriceList) -> tuple[dict[str, Capability], list[TransitionRead]]:
    """Mirrors the guards of ``add_item``, ``supersede_item`` and ``activate_price_list``."""
    if not uow.actor.can(MANAGE):
        denied = Capability(allowed=False, reason_code="permission_denied")
        return {"add_item": denied, "supersede_item": denied}, []
    is_draft = pl.status == PriceListStatus.DRAFT.value
    is_active = pl.status == PriceListStatus.ACTIVE.value
    capabilities = {
        "add_item": Capability(allowed=is_draft, reason_code=None if is_draft else "price_list_not_draft"),
        "supersede_item": Capability(allowed=is_active, reason_code=None if is_active else "price_list_not_active"),
    }
    transitions = (
        [TransitionRead(action="activate", to_status=PriceListStatus.ACTIVE.value, requires_reason=False)]
        if is_draft
        else []
    )
    return capabilities, transitions


@query(READ)
def get_price_list(uow: UnitOfWork, price_list_id: uuid.UUID) -> PriceListDetail:
    pl = _visible_list(uow, price_list_id)
    minis = _party_minis(uow, [pl.party_id])
    counts = _item_counts(uow, [pl.id])
    capabilities, transitions = _list_capabilities(uow, pl)
    return PriceListDetail(
        **_list_summary_fields(pl, minis, int(counts.get(pl.id, 0))),
        price_basis=pl.price_basis,
        notes=pl.notes,
        source_kind=pl.source_kind,
        source_ref=pl.source_ref,
        activated_at=pl.activated_at,
        retired_at=pl.retired_at,
        version=pl.version,
        capabilities=capabilities,
        allowed_transitions=transitions,
    )


@query(READ)
def list_price_list_items(
    uow: UnitOfWork,
    price_list_id: uuid.UUID,
    *,
    product_id: uuid.UUID | None = None,
    q: str | None = None,
    on_date: date | None = None,
    include_history: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> Page[PriceListItemRead]:
    """Items of a visible list (child rows authorised through the list). By default the current prices only;
    ``on_date`` selects the prices effective on that date; ``include_history`` adds superseded and retired rows."""
    pl = _visible_list(uow, price_list_id)
    conds: list[ColumnElement[bool]] = [I.price_list_id == pl.id, uow.repo(PriceListItem).clause("read")]
    if product_id:
        conds.append(I.product_id == product_id)
    for tok in tokens(q or ""):
        conds.append(or_(I.product_key.ilike(contains_pattern(tok), escape=LIKE_ESCAPE),
                         I.display_sku.ilike(contains_pattern(tok), escape=LIKE_ESCAPE)))
    if on_date is not None:
        conds += [I.status == PriceItemStatus.ACTIVE.value, _effective(I, on_date)]
    elif not include_history:
        conds += [I.status == PriceItemStatus.ACTIVE.value, I.superseded_by_item_id.is_(None)]
    total = uow.session.scalar(select(func.count(I.id)).where(*conds)) or 0
    limit = max(1, min(limit, MAX_LIMIT))
    rows = uow.session.scalars(
        select(I).where(*conds).order_by(I.product_key, I.unit_code, I.valid_from, I.id).limit(limit).offset(max(0, offset))
    )
    return Page[PriceListItemRead](
        items=[_item_read(r, pl) for r in rows], total=int(total), limit=limit, offset=max(0, offset)
    )


@query(READ)
def product_prices(uow: UnitOfWork, product_id: uuid.UUID, *, on_date: date | None = None) -> ProductPrices:
    """Active prices of one product on a date across visible lists; the cost of record only for cost readers."""
    product = catalogue.get_product_ref(uow, product_id=product_id)
    day = on_date or business_date(uow)
    rows = uow.session.execute(
        select(I, L)
        .join(L, L.id == I.price_list_id)
        .where(
            I.product_id == product.id,
            visible_lists(uow),
            L.status == PriceListStatus.ACTIVE.value,
            I.status == PriceItemStatus.ACTIVE.value,
            _effective(L, day),
            _effective(I, day),
        )
        .order_by(L.scope_kind, L.price_type, L.currency, L.code, I.unit_code)
    ).all()
    minis = _party_minis(uow, [pl.party_id for _i, pl in rows])
    prices = [
        ProductPriceRead(
            **_item_read(item, pl).model_dump(exclude={"redacted_fields"}),
            price_list_name=pl.name,
            price_type=pl.price_type,  # type: ignore[arg-type]
            scope_kind=pl.scope_kind,  # type: ignore[arg-type]
            party=minis.get(pl.party_id) if pl.party_id else None,
            customer_type=pl.customer_type,
        )
        for item, pl in rows
    ]
    current_cost = None
    redacted: list[str] = []
    if not uow.actor.can(COST_READ):
        redacted.append("current_cost")  # never loaded for this actor; the field name is listed, no value
    else:
        cost = uow.session.scalars(
            select(ProductCost)
            .where(ProductCost.company_id == uow.actor.company_id, ProductCost.product_id == product.id,
                   ProductCost.effective_from <= day)
            .order_by(ProductCost.effective_from.desc(), ProductCost.cost_version.desc())
        ).first()
        if cost is not None:
            current_cost = _cost_read(cost)
            _audit_cost_read(uow, product, [cost.cost_version])
    return ProductPrices(
        product_id=product.id,
        product_key=product.product_key,
        on_date=day,
        prices=prices,
        current_cost=current_cost,
        redacted_fields=redacted,
    )


def _audit_cost_read(uow: UnitOfWork, product: catalogue.ProductRef, versions: Sequence[int]) -> None:
    """Record that restricted cost values were returned (field names and versions only, never the values)."""
    uow.audit(
        "pricing.product_cost.read",
        resource_type="catalogue.product",
        resource_id=product.id,
        resource_label=product.product_key,
        restricted_fields=["unit_cost", "cost_components"],
        details={"cost_versions": list(versions)},
    )


@query(COST_READ)
def list_product_costs(uow: UnitOfWork, product_id: uuid.UUID, *, limit: int = 50, offset: int = 0) -> Page[ProductCostRead]:
    """Cost history of a product, newest first (``pricing.cost.read``; 403 without it, 404 for unknown products).

    Every read that returns cost rows is audited (``pricing.cost.read`` is sensitive)."""
    product = catalogue.get_product_ref(uow, product_id=product_id)
    conds = [uow.repo(ProductCost).clause("read"), ProductCost.product_id == product.id]
    total = uow.session.scalar(select(func.count(ProductCost.id)).where(*conds)) or 0
    limit = max(1, min(limit, MAX_LIMIT))
    offset = max(0, offset)
    rows = list(
        uow.session.scalars(
            select(ProductCost).where(*conds).order_by(ProductCost.cost_version.desc()).limit(limit).offset(offset)
        )
    )
    if rows:
        _audit_cost_read(uow, product, [r.cost_version for r in rows])
    return Page[ProductCostRead](items=[_cost_read(r) for r in rows], total=int(total), limit=limit, offset=offset)


def priced_items(uow: UnitOfWork, item_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, PricedItem]:
    """Visible price-list items by id, for calculations over resolved lines (requires ``pricing.price.read``)."""
    ids = list(set(item_ids))
    uow.actor.require(READ)
    if not ids:
        return {}
    rows = uow.session.execute(
        select(I, L).join(L, L.id == I.price_list_id).where(I.id.in_(ids), visible_lists(uow))
    ).all()
    return {
        item.id: PricedItem(
            item_id=item.id,
            price_list_id=pl.id,
            price_list_code=pl.code,
            product_id=item.product_id,
            product_key=item.product_key,
            unit_code=item.unit_code,
            unit_price=item.unit_price,
            currency=pl.currency,
            moq=item.moq,
            moq_unit_code=item.moq_unit_code,
            valid_from=item.valid_from,
            valid_to=item.valid_to,
            status=item.status,  # type: ignore[arg-type]
            list_status=pl.status,  # type: ignore[arg-type]
            list_valid_from=pl.valid_from,
            list_valid_to=pl.valid_to,
        )
        for item, pl in rows
    }


# =====================================================================================================
# resolution
# =====================================================================================================
def _choose(matches: Sequence[tuple[PriceListItem, PriceList]]) -> tuple[PriceListItem, PriceList] | None:
    """One match, or the unique highest explicit priority when every match carries one; otherwise None (AMBIGUOUS:
    overlapping prices are never guessed between and never fall through to a less specific tier)."""
    if len(matches) == 1:
        return matches[0]
    priorities = [pl.priority for _i, pl in matches]
    if matches and all(p is not None for p in priorities):
        top = max(p for p in priorities if p is not None)
        winners = [m for m in matches if m[1].priority == top]
        if len(winners) == 1:
            return winners[0]
    return None


def _tier_condition(tier: Tier, party: parties.PartyRef | None) -> ColumnElement[bool] | None:
    if tier == "customer":
        return None if party is None else and_(L.scope_kind == PriceScope.CUSTOMER.value, L.party_id == party.id)
    if tier == "customer_type":
        if party is None or party.customer_type is None:
            return None
        return and_(L.scope_kind == PriceScope.CUSTOMER_TYPE.value, L.customer_type == party.customer_type)
    return L.scope_kind == PriceScope.STANDARD.value


def _candidate(tier: Tier, item: PriceListItem, pl: PriceList) -> PriceCandidate:
    return PriceCandidate(
        tier=tier,
        price_list_id=pl.id,
        price_list_code=pl.code,
        item_id=item.id,
        priority=pl.priority,
        unit_price=Money(amount=item.unit_price, currency=pl.currency),  # type: ignore[arg-type]
        unit_code=item.unit_code,
        valid_from=item.valid_from,
        valid_to=item.valid_to,
    )


@query(READ)
def resolve_price(
    uow: UnitOfWork,
    *,
    currency: str,
    uom: str,
    product_id: uuid.UUID | None = None,
    product_key: str | None = None,
    party_id: uuid.UUID | None = None,
    on_date: date | None = None,
    price_type: PriceType | None = None,
) -> PriceResolution:
    if (product_id is None) == (product_key is None):
        raise _errors((["product_id"], "one_of", "Give exactly one of product_id or product_key"))
    product = catalogue.get_product_ref(uow, product_id=product_id, product_key=product_key)
    party = parties.get_party_ref(uow, party_id) if party_id is not None else None
    day = on_date or business_date(uow)
    currency = currency.upper()
    common: dict[str, Any] = {
        "product_id": product.id,
        "product_key": product.product_key,
        "party_id": party.id if party else None,
        "customer_type": party.customer_type if party else None,
        "requested_currency": currency,
        "requested_uom": uom,
        "on_date": day,
        "price_type": price_type,
    }
    base: list[ColumnElement[bool]] = [visible_lists(uow), L.status == PriceListStatus.ACTIVE.value]
    if price_type is not None:
        base.append(L.price_type == price_type.value)
    checks: list[TierCheck] = []
    seen_currencies: dict[str, set[str]] = {}
    seen_units: set[str] = set()
    seen_not_effective = False
    for tier in TIERS:
        tier_cond = _tier_condition(tier, party)
        if tier_cond is None:
            checks.append(TierCheck(tier=tier, outcome="skipped",
                                    detail="no party" if party is None else "the party has no customer type"))
            continue
        lists_exist = uow.session.scalar(select(func.count(L.id)).where(*base, tier_cond, _effective(L, day))) or 0
        rows = uow.session.execute(
            select(I, L)
            .join(L, L.id == I.price_list_id)
            .where(*base, tier_cond, I.product_id == product.id, I.status == PriceItemStatus.ACTIVE.value)
            .order_by(L.code, I.valid_from)
        ).all()
        effective = [(i, pl) for i, pl in rows if pl.valid_from <= day and (pl.valid_to is None or pl.valid_to >= day)
                     and i.valid_from <= day and (i.valid_to is None or i.valid_to >= day)]
        if rows and not effective:
            seen_not_effective = True
        for i, pl in effective:
            seen_currencies.setdefault(pl.currency, set()).add(pl.code)
            if pl.currency == currency:
                seen_units.add(i.unit_code)
        matches = [(i, pl) for i, pl in effective if pl.currency == currency and i.unit_code == uom]
        if not matches:
            if not lists_exist:
                outcome, detail = "no_list", f"no active {tier.replace('_', ' ')} price list on {day.isoformat()}"
            elif not rows:
                outcome, detail = "no_item", f"{product.product_key} is not on an active {tier.replace('_', ' ')} list"
            elif not effective:
                outcome, detail = "not_effective", f"no {tier.replace('_', ' ')} price is effective on {day.isoformat()}"
            elif any(pl.currency == currency for _i, pl in effective):
                outcome, detail = "unit_mismatch", f"{tier.replace('_', ' ')} prices exist in {currency} for another unit"
            else:
                outcome, detail = "currency_mismatch", f"{tier.replace('_', ' ')} prices exist only in other currencies"
            checks.append(TierCheck(tier=tier, outcome=outcome, detail=detail))  # type: ignore[arg-type]
            continue
        chosen = _choose(matches)
        if chosen is None:
            checks.append(TierCheck(tier=tier, outcome="ambiguous",
                                    detail=f"{len(matches)} overlapping {tier.replace('_', ' ')} prices without a unique explicit priority"))
            return PriceResolution(
                status="ambiguous",
                reason_code="PRICE_AMBIGUOUS",
                explanation=(
                    f"{len(matches)} {tier.replace('_', ' ')} price lists price {product.product_key} in {currency} per "
                    f"{uom} on {day.isoformat()} without a unique explicit priority; choose one (no lower tier is used)."
                ),
                candidates=[_candidate(tier, i, pl) for i, pl in matches],
                checks=checks,
                **common,
            )
        item, pl = chosen
        if item.unit_price == 0:
            checks.append(TierCheck(tier=tier, outcome="zero_price", detail=f"{pl.code} lists a zero price"))
            return PriceResolution(
                status="unavailable",
                reason_code="ZERO_PRICE",
                explanation=f"{pl.code} lists {product.product_key} at zero; a zero price is not used (no lower tier is used).",
                tier=tier,
                price_list_id=pl.id,
                price_list_code=pl.code,
                item_id=item.id,
                currency=pl.currency,
                unit_code=item.unit_code,
                checks=checks,
                **common,
            )
        checks.append(TierCheck(tier=tier, outcome="matched", detail=f"{pl.code} item {item.id}"))
        return PriceResolution(
            status="found",
            reason_code=None,
            explanation=(
                f"{pl.currency} {format(item.unit_price, 'f')} per {item.unit_code} from {pl.code} "
                f"({tier.replace('_', ' ')} tier), effective {item.valid_from.isoformat()}"
                + (f" to {item.valid_to.isoformat()}" if item.valid_to else "")
            ),
            unit_price=Money(amount=item.unit_price, currency=pl.currency),  # type: ignore[arg-type]
            currency=pl.currency,
            unit_code=item.unit_code,
            tier=tier,
            price_list_id=pl.id,
            price_list_code=pl.code,
            item_id=item.id,
            price_basis=item.price_basis,
            product_moq=_quantity(item.moq, item.moq_unit_code or item.unit_code),
            valid_to=item.valid_to,
            checks=checks,
            **common,
        )
    hints: list[str] = []
    for cur, codes in sorted(seen_currencies.items()):
        if cur != currency:
            hints.append(f"priced in {cur} on {', '.join(sorted(codes))} (not converted: no relabelling, FX needs an approved rate)")
    if seen_units:
        hints.append(f"priced in {currency} per {', '.join(sorted(seen_units))} (prices are not converted between units)")
    if any(cur != currency for cur in seen_currencies):
        reason = "NO_PRICE_IN_CURRENCY"
    elif seen_units:
        reason = "NO_PRICE_FOR_UNIT"
    elif seen_not_effective:
        reason = "NOT_EFFECTIVE"
    else:
        reason = "NO_PRICE"
    return PriceResolution(
        status="not_found",
        reason_code=reason,
        explanation=f"No {currency} price per {uom} for {product.product_key} on {day.isoformat()} in any tier checked.",
        checks=checks,
        hints=hints,
        **common,
    )



# =====================================================================================================
# display prices (product list and overview columns; one batch query, never per product)
# =====================================================================================================
def display_prices(
    uow: UnitOfWork,
    product_ids: Iterable[uuid.UUID],
    *,
    currencies: Sequence[str],
    price_type: PriceType | None = None,
    on_date: date | None = None,
) -> dict[uuid.UUID, dict[str, DisplayPrice]]:
    """Standard-tier prices of many products in the given currencies, from one query (``pricing.price.read``).

    Per (product, currency): active standard lists visible to the actor and effective on the date, in that currency,
    per the product's unit of sale (any unit when the product has none). One match is ``found``; several without a
    unique explicit priority are ``ambiguous`` (never guessed); a zero price is ``unavailable``; nothing is
    ``not_found``. Prices stay in their list currency (no relabelling, no conversion).
    """
    uow.actor.require(READ)
    ids = list(dict.fromkeys(product_ids))
    wanted = [c.upper() for c in dict.fromkeys(currencies)]
    if not ids or not wanted:
        return {}
    day = on_date or business_date(uow)
    refs = catalogue.product_refs(uow, ids)
    conds: list[ColumnElement[bool]] = [
        visible_lists(uow),
        L.status == PriceListStatus.ACTIVE.value,
        L.scope_kind == PriceScope.STANDARD.value,
        L.currency.in_(wanted),
        _effective(L, day),
        I.status == PriceItemStatus.ACTIVE.value,
        _effective(I, day),
        I.product_id.in_(list(refs)),
    ]
    if price_type is not None:
        conds.append(L.price_type == price_type.value)
    rows = uow.session.execute(
        select(I, L).join(L, L.id == I.price_list_id).where(*conds).order_by(L.code, I.unit_code, I.id)
    ).all() if refs else []
    grouped: dict[tuple[uuid.UUID, str], list[tuple[PriceListItem, PriceList]]] = {}
    for item, pl in rows:
        unit = refs[item.product_id].unit_of_sale
        if unit is None or item.unit_code == unit:
            grouped.setdefault((item.product_id, pl.currency), []).append((item, pl))
    out: dict[uuid.UUID, dict[str, DisplayPrice]] = {}
    for product_id in refs:
        per_currency: dict[str, DisplayPrice] = {}
        for cur in wanted:
            matches = grouped.get((product_id, cur), [])
            chosen = _choose(matches) if matches else None
            if not matches:
                per_currency[cur] = DisplayPrice(product_id=product_id, currency=cur, status="not_found")  # type: ignore[arg-type]
            elif chosen is None:
                per_currency[cur] = DisplayPrice(
                    product_id=product_id, currency=cur, status="ambiguous", candidate_count=len(matches),  # type: ignore[arg-type]
                )
            else:
                item, pl = chosen
                per_currency[cur] = DisplayPrice(
                    product_id=product_id,
                    currency=cur,  # type: ignore[arg-type]
                    status="unavailable" if item.unit_price == 0 else "found",
                    unit_price=None if item.unit_price == 0 else Money(amount=item.unit_price, currency=pl.currency),  # type: ignore[arg-type]
                    unit_code=item.unit_code,
                    price_list_code=pl.code,
                    item_id=item.id,
                    product_moq=_quantity(item.moq, item.moq_unit_code or item.unit_code),
                    candidate_count=len(matches),
                )
        out[product_id] = per_currency
    return out
