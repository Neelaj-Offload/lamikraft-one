"""Fixture price lists (docs/architecture/fixtures.md §6), created through the pricing service.

EXP-EUR-2026, EXP-GBP-2026 and DOM-INR-2026: standard lists valid 2026-01-01 .. 2026-12-31, created and activated by
Priya at D-115. No customer-type or customer-agreement lists exist in the world (tier tests add them locally).
Re-running finds lists by code; an already active list is left untouched.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.modules.pricing import service as pricing
from app.modules.pricing.models import PriceListItem
from app.modules.pricing.schemas import PriceListCreate, PriceListItemCreate, PriceSourceKind
from app.seed.context import SeedContext
from app.seed.world import keys
from app.seed.world.parties import CREATOR, as_member, at_ist

VALID_FROM = date(2026, 1, 1)
VALID_TO = date(2026, 12, 31)


@dataclass(frozen=True)
class FixturePriceList:
    ref: str  # SeedContext.refs key (fixtures.md §6 "Key" column)
    code: str
    name: str
    price_type: str
    currency: str
    unit: str
    items: tuple[tuple[str, str, str], ...]  # (product fixture key, unit, unit price)


SLICE1_PRICE_LISTS: tuple[FixturePriceList, ...] = (
    FixturePriceList(
        keys.PRICE_LIST_REFS.EXP_EUR, keys.PRICE_LISTS.EXP_EUR, keys.PRICE_LIST_NAMES["EXP_EUR"], "export", "EUR", "pcs",
        (
            ("OAK_TRAY", "pcs", keys.PRICES.OAK_TRAY_EUR),
            ("MAPLE_TRIVET", "pcs", keys.PRICES.MAPLE_TRIVET_EUR),
            ("ASH_BOARD", "pcs", keys.PRICES.ASH_BOARD_EUR),
        ),
    ),
    FixturePriceList(
        keys.PRICE_LIST_REFS.EXP_GBP, keys.PRICE_LISTS.EXP_GBP, keys.PRICE_LIST_NAMES["EXP_GBP"], "export", "GBP", "pcs",
        (("OAK_TRAY", "pcs", keys.PRICES.OAK_TRAY_GBP),),
    ),
    FixturePriceList(
        keys.PRICE_LIST_REFS.DOM_INR, keys.PRICE_LISTS.DOM_INR, keys.PRICE_LIST_NAMES["DOM_INR"], "domestic", "INR",
        "sheets",
        (("WALNUT_BOARD", "sheets", keys.PRICES.WALNUT_BOARD_INR),),
    ),
)


def item_ref(list_ref: str, product_key: str) -> str:
    """SeedContext.refs key of a seeded price-list item, e.g. ``PLI_EXP_EUR_OAK_TRAY``."""
    return f"PLI_{list_ref.removeprefix('PL_')}_{product_key}"


def seed_pricing(ctx: SeedContext) -> None:
    for position, spec in enumerate(SLICE1_PRICE_LISTS):
        ctx.at(at_ist(-115, 10, position * 10))
        with as_member(ctx, CREATOR) as uow:
            price_list = pricing.find_price_list(uow, spec.code)
            if price_list is None:
                price_list = pricing.create_price_list(
                    uow,
                    PriceListCreate(
                        code=spec.code,
                        name=spec.name,
                        price_type=spec.price_type,  # type: ignore[arg-type]
                        scope_kind="standard",  # type: ignore[arg-type]
                        currency=spec.currency,  # type: ignore[arg-type]
                        default_unit_code=spec.unit,  # type: ignore[arg-type]
                        valid_from=VALID_FROM,
                        valid_to=VALID_TO,
                        source_kind=PriceSourceKind.SEED,
                    ),
                )
                for product_key, unit, price in spec.items:
                    pricing.add_item(
                        uow,
                        price_list.id,
                        PriceListItemCreate(
                            product_id=ctx.ref(product_key),
                            unit_code=unit,  # type: ignore[arg-type]
                            unit_price=Decimal(price),
                            source_kind=PriceSourceKind.SEED,
                        ),
                    )
                pricing.activate_price_list(uow, price_list.id)
            ctx.refs[spec.ref] = price_list.id
            for product_key, unit, _price in spec.items:
                item_id = uow.session.scalar(
                    select(PriceListItem.id).where(
                        PriceListItem.price_list_id == price_list.id,
                        PriceListItem.product_id == ctx.ref(product_key),
                        PriceListItem.unit_code == unit,
                        PriceListItem.valid_from == VALID_FROM,
                    )
                )
                if item_id is not None:
                    ctx.refs[item_ref(spec.ref, product_key)] = item_id
