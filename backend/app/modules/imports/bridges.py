"""Read-only bridges the imports module installs into the catalogue (which must not import pricing itself).

``price_presence``: the SELECT of product ids with a current active price in a list the actor may read. It feeds the
catalogue's ``has_price`` filter, the ``no_active_price`` completeness rule and the stats' "without pricing" count.
The pricing lane owns a future ``active_price_exists`` query; until it exists this reads the pricing tables through
the pricing module's own visibility rule (``visible_lists``).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Select, and_, or_, select

from app.platform.uow import UnitOfWork


def price_presence(uow: UnitOfWork) -> Select[Any]:
    from app.modules.pricing.models import PriceList, PriceListItem
    from app.modules.pricing.service import business_date, visible_lists

    today = business_date(uow)
    return (
        select(PriceListItem.product_id)
        .join(PriceList, PriceList.id == PriceListItem.price_list_id)
        .where(
            visible_lists(uow),
            PriceList.status == "active",
            PriceListItem.status == "active",
            PriceListItem.unit_price > 0,
            and_(PriceList.valid_from <= today, or_(PriceList.valid_to.is_(None), PriceList.valid_to >= today)),
            and_(PriceListItem.valid_from <= today, or_(PriceListItem.valid_to.is_(None), PriceListItem.valid_to >= today)),
        )
    )
