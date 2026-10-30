"""Helpers shared by the product-dependent import types (packaging, specifications, pricing, media)."""

from __future__ import annotations

from sqlalchemy import select

from app.modules.catalogue.models import Product
from app.modules.imports.definitions.base import QUARANTINE, Issue, Plan
from app.platform.uow import UnitOfWork


def find_product(uow: UnitOfWork, product_key: str | None) -> Product | None:
    if not product_key:
        return None
    return uow.session.scalars(
        select(Product).where(Product.company_id == uow.actor.company_id, Product.product_key == product_key)
    ).first()


def orphan(product_key: str | None) -> Plan:
    """A row for a product that does not exist (yet): quarantined, released by a recheck after the products import
    (legacy imported such rows anyway, BUG-12)."""
    return Plan(
        "insert",
        issues=[Issue("ORPHAN_PRODUCT", QUARANTINE, f"No product with key '{product_key}'", "product_key", product_key)],
    )
