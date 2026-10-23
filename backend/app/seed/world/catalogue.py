"""Fixture catalogue (docs/architecture/fixtures.md §5), created through the catalogue service.

Taxonomy (all active): Serveware (Trays, Trivets, Boards) and Decorative Boards (Veneered panels). The four
Slice-1 products carry the specification and packaging stated in the fixtures; decor numbers are text with their
leading zeros (``0120`` Natural Oak). Media (photos, swatches) arrive with the media tables in Slice 2. Created by
Priya at D-116; re-running finds categories by name and products by ``product_key``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from app.modules.catalogue import service as catalogue
from app.modules.catalogue.schemas import CategoryCreate, PackagingIn, ProductCreate, SpecificationIn, TaxonomyOrigin
from app.seed.context import SeedContext
from app.seed.world import keys
from app.seed.world.parties import CREATOR, as_member, at_ist

BRAND = "Lamikraft"

#: refs keys for taxonomy rows (categories and subcategories are not business documents, so no keys.py constant)
CATEGORIES: dict[str, tuple[str, int, tuple[tuple[str, str], ...]]] = {
    "CAT_SERVEWARE": ("Serveware", 10, (("SUB_TRAYS", "Trays"), ("SUB_TRIVETS", "Trivets"), ("SUB_BOARDS", "Boards"))),
    "CAT_DECORATIVE_BOARDS": ("Decorative Boards", 20, (("SUB_VENEERED_PANELS", "Veneered panels"),)),
}


@dataclass(frozen=True)
class FixtureProduct:
    key: str  # attribute of keys.PRODUCTS (also the SeedContext.refs key)
    name: str
    category: str  # CATEGORIES key
    subcategory: str
    unit: str
    decor_no: str
    decor_name: str
    master: dict[str, Any] = field(default_factory=dict)
    specification: dict[str, Any] = field(default_factory=dict)
    packaging: dict[str, Any] = field(default_factory=dict)
    lots_and_qc: bool = False


SLICE1_PRODUCTS: tuple[FixtureProduct, ...] = (
    FixtureProduct(
        "OAK_TRAY", "Oak serving tray 450", "CAT_SERVEWARE", "SUB_TRAYS", "pcs", keys.DECORS.NATURAL_OAK, "Natural Oak",
        master={"size_mm": "450 x 300", "finish": "Matte lacquer", "shape": "Rectangular", "variant_group": "Oak serving tray"},
        specification={
            "length_mm": "450", "width_mm": "300", "thickness_mm": "12", "finish": "Matte lacquer",
            "material_type": "Oak veneer",
        },
        packaging={
            "carton_qty": 24, "inner_qty": 6, "unit_weight_g": "450", "packing_type": "Poly bag",
            "carton_length_cm": "48", "carton_width_cm": "33", "carton_height_cm": "30", "cbm": "0.047520",
            "net_weight_kg": "10.8", "gross_weight_kg": "11.6",
        },
    ),
    FixtureProduct(
        "MAPLE_TRIVET", "Maple trivet 300", "CAT_SERVEWARE", "SUB_TRIVETS", "pcs", keys.DECORS.HARD_MAPLE, "Hard Maple",
        master={"size_mm": "300 x 300"},
        specification={"length_mm": "300", "width_mm": "300", "thickness_mm": "10"},
        packaging={
            "carton_qty": 48, "unit_weight_g": "280", "packing_type": "Shrink wrap", "carton_length_cm": "62",
            "carton_width_cm": "32", "carton_height_cm": "34", "cbm": "0.067456", "net_weight_kg": "13.44",
            "gross_weight_kg": "14.4",
        },
    ),
    FixtureProduct(
        "ASH_BOARD", "Ash chopping board 400", "CAT_SERVEWARE", "SUB_BOARDS", "pcs", keys.DECORS.WHITE_ASH, "White Ash",
        master={"size_mm": "400 x 250"},
        specification={"length_mm": "400", "width_mm": "250", "thickness_mm": "18"},
        packaging={
            "carton_qty": 20, "unit_weight_g": "900", "packing_type": "Carton sleeve", "carton_length_cm": "42",
            "carton_width_cm": "27", "carton_height_cm": "40", "cbm": "0.045360", "net_weight_kg": "18.0",
            "gross_weight_kg": "19.2",
        },
    ),
    FixtureProduct(
        "WALNUT_BOARD", "Walnut veneered board 18 mm", "CAT_DECORATIVE_BOARDS", "SUB_VENEERED_PANELS", "sheets",
        keys.DECORS.AMERICAN_WALNUT, "American Walnut",
        master={"size_mm": "2440 x 1220"},
        specification={"board_size_mm": "2440 x 1220", "thickness_mm": "18"},
        packaging={"packing_type": "Pallet"},
        lots_and_qc=True,
    ),
)


def _taxonomy(ctx: SeedContext) -> None:
    ctx.at(at_ist(-116, 9, 30))
    with as_member(ctx, CREATOR) as uow:
        for cat_key, (name, order, subs) in CATEGORIES.items():
            category = catalogue.find_category(uow, name)
            if category is None:
                category = catalogue.create_category(
                    uow, CategoryCreate(name=name, display_order=order, origin=TaxonomyOrigin.SEED)
                )
            ctx.refs[cat_key] = category.id
            for position, (sub_key, sub_name) in enumerate(subs, start=1):
                sub = catalogue.find_subcategory(uow, category.id, sub_name)
                if sub is None:
                    sub = catalogue.create_subcategory(
                        uow,
                        category.id,
                        CategoryCreate(name=sub_name, display_order=position * 10, origin=TaxonomyOrigin.SEED),
                    )
                ctx.refs[sub_key] = sub.id


def _product(ctx: SeedContext, spec: FixtureProduct, minute: int) -> uuid.UUID:
    product_key = getattr(keys.PRODUCTS, spec.key)
    ctx.at(at_ist(-116, 10, minute))
    with as_member(ctx, CREATOR) as uow:
        existing = catalogue.find_product_id(uow, product_key)
        if existing is not None:
            return existing
        result = catalogue.create_product(
            uow,
            ProductCreate(
                product_key=product_key,
                display_sku=product_key,
                product_name=spec.name,
                brand=BRAND,
                category_id=ctx.ref(spec.category),
                subcategory_id=ctx.ref(spec.subcategory),
                unit_of_sale=spec.unit,  # type: ignore[arg-type]
                decor_no=spec.decor_no,
                decor_name=spec.decor_name,
                status="active",  # type: ignore[arg-type]
                stock_uom_code=spec.unit,  # type: ignore[arg-type]
                track_lots=spec.lots_and_qc,
                qc_required=spec.lots_and_qc,
                specification=SpecificationIn(**spec.specification),
                packaging=PackagingIn(**spec.packaging),
                origin="seed",  # type: ignore[arg-type]
                **spec.master,
            ),
        )
        return result.product.id


def seed_catalogue(ctx: SeedContext) -> None:
    _taxonomy(ctx)
    for minute, spec in enumerate(SLICE1_PRODUCTS):
        ctx.refs[spec.key] = _product(ctx, spec, minute)
