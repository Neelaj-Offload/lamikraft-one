"""The variant builder (module 4): one design, its decors and sizes, become one product per decor × size.

A sellable unit at Lamikraft is design × decor × size (CB07 in decor 892, size M). The team has no products
spreadsheet, only the catalogue, so a whole design is entered at once: ``CB07`` with decors 892 and 959 in sizes S, M,
L gives six products ``CB07-892-S`` … ``CB07-959-L``, grouped under the design name (``variant_group``, the catalogue's
"family"). Keys that already exist are reported and skipped, so the builder can be re-run after adding a decor.
Spec: docs/superpowers/specs/2026-11-25-products-stock-design.md
"""

from __future__ import annotations

import re
import uuid
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints
from sqlalchemy import select

from app.core.errors import ValidationFailed
from app.modules.catalogue import service
from app.modules.catalogue.models import Product
from app.modules.catalogue.schemas import ProductCreate, ProductOrigin
from app.platform.uow import UnitOfWork

Upper = BeforeValidator(lambda v: v.strip().upper() if isinstance(v, str) else v)


class VariantDecor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decor_no: Annotated[str, Upper, StringConstraints(pattern=r"^[A-Z0-9]{1,10}$")]
    decor_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)] | None = None


class VariantSize(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: short code used in the product key: S, M, L, XL, 300, 450x300 ...
    code: Annotated[str, Upper, StringConstraints(pattern=r"^[A-Z0-9]{1,8}$")]
    label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]
    length_mm: Decimal | None = Field(default=None, gt=0, le=10000)
    width_mm: Decimal | None = Field(default=None, gt=0, le=10000)


class VariantBuild(BaseModel):
    model_config = ConfigDict(extra="forbid")

    design_no: Annotated[str, Upper, StringConstraints(pattern=r"^[A-Z0-9][A-Z0-9-]{0,19}$")]
    design_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    category_id: uuid.UUID
    subcategory_id: uuid.UUID | None = None
    product_type: Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)] | None = None
    brand: Annotated[str, StringConstraints(strip_whitespace=True, max_length=40)] | None = None
    item_class: Literal["finished", "raw_material", "packaging"] = "finished"
    decors: list[VariantDecor] = Field(min_length=1, max_length=30)
    sizes: list[VariantSize] = Field(min_length=1, max_length=12)
    #: preview only: nothing is written
    dry_run: bool = False


class VariantRow(BaseModel):
    product_key: str
    product_name: str
    decor_no: str
    size_code: str
    product_id: uuid.UUID | None
    exists: bool


class VariantBuildResult(BaseModel):
    design_no: str
    created: int
    skipped: int
    rows: list[VariantRow]


def variant_key(design_no: str, decor_no: str, size_code: str) -> str:
    return re.sub(r"-{2,}", "-", f"{design_no}-{decor_no}-{size_code}".upper())


def _name(data: VariantBuild, decor: VariantDecor, size: VariantSize) -> str:
    decor_text = f"{decor.decor_no} {decor.decor_name}" if decor.decor_name else decor.decor_no
    return f"{data.design_name}, {decor_text}, {size.label}"[:300]


def _size_mm(size: VariantSize) -> str | None:
    if size.length_mm and size.width_mm:
        return f"{format(size.length_mm.normalize(), 'f')}x{format(size.width_mm.normalize(), 'f')}"
    if size.length_mm:
        return format(size.length_mm.normalize(), "f")
    return None


def build_variants(uow: UnitOfWork, data: VariantBuild) -> VariantBuildResult:
    uow.actor.require("catalogue.product.create")
    if len({d.decor_no for d in data.decors}) != len(data.decors) or len({s.code for s in data.sizes}) != len(data.sizes):
        raise ValidationFailed("Each decor and each size may appear once",
                               errors=[{"loc": ["body", "decors"], "msg": "duplicate decor or size", "code": "duplicate"}])
    combos = [(d, s, variant_key(data.design_no, d.decor_no, s.code)) for d in data.decors for s in data.sizes]
    existing = dict(uow.session.execute(
        select(Product.product_key, Product.id).where(
            Product.company_id == uow.actor.company_id, Product.product_key.in_([k for _d, _s, k in combos]))
    ).all())
    rows: list[VariantRow] = []
    created = 0
    for decor, size, key in combos:
        name = _name(data, decor, size)
        if key in existing:
            rows.append(VariantRow(product_key=key, product_name=name, decor_no=decor.decor_no, size_code=size.code,
                                   product_id=existing[key], exists=True))
            continue
        product_id = None
        if not data.dry_run:
            result = service.create_product(uow, ProductCreate(
                product_key=key,
                product_name=name,
                category_id=data.category_id,
                subcategory_id=data.subcategory_id,
                product_type=data.product_type,
                brand=data.brand,
                variant_group=data.design_name,
                design_no=data.design_no,
                item_class=data.item_class,
                decor_no=decor.decor_no,
                decor_name=decor.decor_name,
                size_mm=_size_mm(size),
                unit_of_sale="pcs",
                origin=ProductOrigin.UI,
            ))
            product_id = result.product.id
            created += 1
        rows.append(VariantRow(product_key=key, product_name=name, decor_no=decor.decor_no, size_code=size.code,
                               product_id=product_id, exists=False))
    if not data.dry_run:
        uow.audit("catalogue.product.variants_built", resource_type="catalogue.product", resource_id=None,
                  resource_label=data.design_no, details={"created": created, "skipped": len(rows) - created})
    return VariantBuildResult(design_no=data.design_no, created=created, skipped=sum(1 for r in rows if r.exists), rows=rows)
