"""Catalogue resource policies. The catalogue is company-scoped (``catalogue.product.read`` at company scope);
taxonomy rows are read with the same key and written only with ``catalogue.taxonomy.manage``."""

from __future__ import annotations

from app.modules.catalogue.models import Category, Product, Subcategory
from app.platform.authz.policy import ParentRef, ResourcePolicy

PRODUCT_POLICY = ResourcePolicy(
    resource_type="catalogue.product",
    model=Product,
    permission_prefix="catalogue.product",
    business_key_column="product_key",
    label=lambda p: f"{p.product_key} · {p.product_name}",
    canonical_path=lambda p: f"/products/{p.id}",
)

CATEGORY_POLICY = ResourcePolicy(
    resource_type="catalogue.category",
    model=Category,
    permission_prefix="catalogue.product",
    label=lambda c: c.name,
    archived_column=None,
)

SUBCATEGORY_POLICY = ResourcePolicy(
    resource_type="catalogue.subcategory",
    model=Subcategory,
    permission_prefix="catalogue.product",
    parent=ParentRef("catalogue.category", "category_id"),
    label=lambda s: s.name,
    archived_column=None,
)

POLICIES = [PRODUCT_POLICY, CATEGORY_POLICY, SUBCATEGORY_POLICY]
