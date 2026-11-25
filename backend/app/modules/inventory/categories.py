"""Stock by category (module 4): one pool split into inventory, sample and exhibition stock, plus what is on order.

Every warehouse has an ``inventory`` location tree (STOCK and its bins, available to sell) and the ``SAMPLE`` and
``EXHIB`` locations (stock-bearing, never available to sell). This read sums balances per product and warehouse by
category for finished goods, and adds the quantity still on order from the factory. Purchasing owns purchase orders,
so it registers the on-order provider (``register_on_order_provider``); inventory never imports procurement.
Spec: docs/superpowers/specs/2026-11-25-products-stock-design.md
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints
from sqlalchemy import and_, case, func, or_, select

from app.core.http.pagination import MAX_LIMIT, Page
from app.core.text import LIKE_ESCAPE, contains_pattern, tokens
from app.modules.catalogue.models import Product
from app.modules.inventory.models import Location, StockBalance, Warehouse
from app.platform.service import query
from app.platform.uow import UnitOfWork

READ = "inventory.stock.read"
OnOrder = Callable[[UnitOfWork, Iterable[uuid.UUID]], dict[tuple[uuid.UUID, uuid.UUID | None], Decimal]]
_ON_ORDER: list[OnOrder] = []


def register_on_order_provider(fn: OnOrder) -> None:
    """``fn(uow, product_ids) -> {(product_id, warehouse_id): outstanding quantity}`` (purchasing registers one)."""
    if fn not in _ON_ORDER:
        _ON_ORDER.append(fn)


class CategoryFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    q: Annotated[str, StringConstraints(max_length=200)] | None = None
    warehouse_id: uuid.UUID | None = None
    market: Literal["domestic", "export"] | None = None
    category: Literal["inventory", "sample", "exhibition"] | None = None
    design: Annotated[str, StringConstraints(strip_whitespace=True, max_length=20)] | None = None
    #: finished goods only unless asked (raw materials such as PRM, BRW, IP stay out of this view)
    include_all_classes: bool = False


class CategoryRow(BaseModel):
    product_id: uuid.UUID
    product_key: str
    product_name: str
    design_no: str | None
    decor_no: str | None
    warehouse_id: uuid.UUID
    warehouse_code: str
    warehouse_name: str
    market: Literal["domestic", "export"] | None
    country_code: str | None
    uom: str | None
    inventory: str
    sample: str
    exhibition: str
    total: str
    on_order: str


def _fmt(value: Decimal | None) -> str:
    return format((value or Decimal(0)).normalize(), "f") if value else "0"


@query(READ)
def stock_by_category(uow: UnitOfWork, filters: CategoryFilters, *, limit: int = 50, offset: int = 0) -> Page[CategoryRow]:
    cid = uow.actor.company_id
    P, L, W, B = Product, Location, Warehouse, StockBalance
    qty = lambda cat: func.coalesce(func.sum(case((L.stock_category == cat, B.quantity), else_=0)), 0)  # noqa: E731
    conds = [B.company_id == cid, L.stock_category.is_not(None), B.quantity != 0]
    if not filters.include_all_classes:
        conds.append(P.item_class == "finished")
    if filters.warehouse_id:
        conds.append(W.id == filters.warehouse_id)
    if filters.market:
        conds.append(W.market == filters.market)
    if filters.design:
        conds.append(P.design_no == filters.design.strip().upper())
    if filters.q:
        for tok in tokens(filters.q):
            pattern = contains_pattern(tok)
            conds.append(or_(P.product_key.ilike(pattern, escape=LIKE_ESCAPE), P.product_name.ilike(pattern, escape=LIKE_ESCAPE),
                             P.decor_no.ilike(pattern, escape=LIKE_ESCAPE)))
    base = (
        select(P.id, P.product_key, P.product_name, P.design_no, P.decor_no, P.stock_uom_code, P.unit_of_sale,
               W.id, W.code, W.name, W.market, W.country_code,
               qty("inventory").label("inv"), qty("sample").label("smp"), qty("exhibition").label("exh"))
        .select_from(B)
        .join(L, and_(L.id == B.location_id, L.company_id == B.company_id))
        .join(W, and_(W.id == L.warehouse_id, W.company_id == L.company_id))
        .join(P, and_(P.id == B.product_id, P.company_id == B.company_id))
        .where(*conds)
        .group_by(P.id, P.product_key, P.product_name, P.design_no, P.decor_no, P.stock_uom_code, P.unit_of_sale,
                  W.id, W.code, W.name, W.market, W.country_code)
    )
    if filters.category:
        base = base.having(qty(filters.category) != 0)
    total = uow.session.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = uow.session.execute(
        base.order_by(P.product_key, W.code).limit(max(1, min(limit, MAX_LIMIT))).offset(max(0, offset))
    ).all()
    on_order: dict[tuple[uuid.UUID, uuid.UUID | None], Decimal] = {}
    for provider in _ON_ORDER:
        for key, value in provider(uow, [r[0] for r in rows]).items():
            on_order[key] = on_order.get(key, Decimal(0)) + value
    items = [
        CategoryRow(
            product_id=r[0], product_key=r[1], product_name=r[2], design_no=r[3], decor_no=r[4], uom=r[5] or r[6],
            warehouse_id=r[7], warehouse_code=r[8], warehouse_name=r[9], market=r[10], country_code=r[11],
            inventory=_fmt(r.inv), sample=_fmt(r.smp), exhibition=_fmt(r.exh), total=_fmt(r.inv + r.smp + r.exh),
            on_order=_fmt(on_order.get((r[0], r[7]))),
        )
        for r in rows
    ]
    return Page[CategoryRow](items=items, total=int(total), limit=limit, offset=offset)


@query(READ)
def category_totals(uow: UnitOfWork, filters: CategoryFilters) -> dict[str, str]:
    """Company totals per category for the same filters (the stock screen's tiles), in one aggregate."""
    P, L, W, B = Product, Location, Warehouse, StockBalance
    conds = [B.company_id == uow.actor.company_id, L.stock_category.is_not(None)]
    if not filters.include_all_classes:
        conds.append(P.item_class == "finished")
    if filters.warehouse_id:
        conds.append(W.id == filters.warehouse_id)
    if filters.market:
        conds.append(W.market == filters.market)
    if filters.design:
        conds.append(P.design_no == filters.design.strip().upper())
    rows = uow.session.execute(
        select(L.stock_category, func.coalesce(func.sum(B.quantity), 0))
        .select_from(B)
        .join(L, and_(L.id == B.location_id, L.company_id == B.company_id))
        .join(W, and_(W.id == L.warehouse_id, W.company_id == L.company_id))
        .join(P, and_(P.id == B.product_id, P.company_id == B.company_id))
        .where(*conds)
        .group_by(L.stock_category)
    ).all()
    sums = {"inventory": Decimal(0), "sample": Decimal(0), "exhibition": Decimal(0)}
    for category, value in rows:
        sums[category] = Decimal(value)
    return {k: _fmt(v) for k, v in sums.items()}
