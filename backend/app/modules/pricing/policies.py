"""Pricing resource policies.

Price lists and their items are company-wide reference data read with ``pricing.price.read``; customer price
lists are additionally limited to parties the actor may read (enforced in the service). Product cost is its own
restricted resource read with ``pricing.cost.read``.
"""

from __future__ import annotations

from app.modules.pricing.models import PriceList, PriceListItem, ProductCost
from app.platform.authz.policy import ParentRef, ResourcePolicy

PRICE_LIST_POLICY = ResourcePolicy(
    resource_type="pricing.price_list",
    model=PriceList,
    permission_prefix="pricing.price",
    business_key_column="code",
    label=lambda pl: f"{pl.code} · {pl.name}",
    canonical_path=lambda pl: f"/products/price-lists/{pl.id}",
)

PRICE_LIST_ITEM_POLICY = ResourcePolicy(
    resource_type="pricing.price_list_item",
    model=PriceListItem,
    permission_prefix="pricing.price",
    parent=ParentRef("pricing.price_list", "price_list_id"),
)

PRODUCT_COST_POLICY = ResourcePolicy(
    resource_type="pricing.product_cost",
    model=ProductCost,
    permission_prefix="pricing.cost",
)

POLICIES = [PRICE_LIST_POLICY, PRICE_LIST_ITEM_POLICY, PRODUCT_COST_POLICY]
