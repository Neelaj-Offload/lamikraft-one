"""Every legacy product, specification and packaging field (CURRENT_STATE_SPEC §4.2, §4.4, §4.5) survives a write
through the catalogue service and comes back from the detail read: canonical values next to their source text,
dimension rows for every size field, and packaging alias pairs reconciled with provenance."""

from __future__ import annotations

import uuid

import pytest

from app.modules.catalogue import service as catalogue
from app.modules.catalogue.schemas import (
    PackagingIn,
    ProductCreate,
    ProductOrigin,
    ProductStatus,
    SpecificationIn,
)
from app.platform.uow import UnitOfWork
from app.seed.world import keys
from tests.integration.catalogue.world import World

pytestmark = pytest.mark.db


def _create(world: World, data: ProductCreate) -> tuple[uuid.UUID, list[str]]:
    with UnitOfWork(world.actor(keys.USERS.PRIYA)) as uow:
        result = catalogue.create_product(uow, data)
    return result.product.id, result.warnings


def test_master_decor_provenance_and_stock_fields_round_trip(world: World) -> None:
    product_id, _ = _create(world, ProductCreate(
        product_key="RT-PANEL-0457",
        display_sku=keys.PRODUCTS.WALNUT_BOARD,  # display SKUs are not unique
        product_name="Round-trip walnut panel",
        brand="Lamikraft",
        category_id=world.ref(keys.CATEGORIES.DECORATIVE_BOARDS),
        subcategory_id=world.ref(keys.SUBCATEGORIES.VENEERED_PANELS),
        category_source="DECORATIVE BOARDS",
        subcategory_source="Veneered Panels",
        product_type="Panel",
        variant_group="Walnut panels",
        unit_of_sale="sheets",
        size_mm="2440 x 1220",
        decor_no="0457",
        decor_name="American Walnut",
        decor_primary="0457",
        decor_options=["0457", "0120"],
        decor_options_text="0457 / 0120",
        finish="Natural veneer",
        shape="Rectangular",
        status=ProductStatus.UNDER_DEVELOPMENT,
        description="Veneered panel for furniture fronts",
        internal_remarks="Check grain direction before cutting",
        source_design_no="D-457",
        source_shape_no="S-12",
        source_sheet="Boards",
        source_row="57",
        source_catalog_page="14",
        source_notes="Imported from the 2025 catalogue",
        source_extra={"legacy_column": "kept"},
        hsn_sac="4412",
        stock_uom_code="sheets",
        is_stock_tracked=False,
        track_lots=True,
        qc_required=True,
        origin=ProductOrigin.IMPORT,
        origin_ref="IMP-2026-0001",
    ))
    d = catalogue.get_product(world.actor(keys.USERS.MEERA), product_id)
    assert (d.product_key, d.display_sku, d.product_name, d.brand) == (
        "RT-PANEL-0457", keys.PRODUCTS.WALNUT_BOARD, "Round-trip walnut panel", "Lamikraft"
    )
    assert (d.category.name, d.subcategory.name if d.subcategory else None) == ("Decorative Boards", "Veneered panels")
    assert (d.product_type, d.variant_group, d.unit_of_sale, d.finish, d.shape) == (
        "Panel", "Walnut panels", "sheets", "Natural veneer", "Rectangular"
    )
    assert d.status == ProductStatus.UNDER_DEVELOPMENT
    assert (d.description, d.internal_remarks) == ("Veneered panel for furniture fronts", "Check grain direction before cutting")
    assert d.decor.model_dump() == {
        "decor_no": "0457", "decor_no_source": None, "decor_name": "American Walnut", "decor_primary": "0457",
        "decor_options": ["0457", "0120"], "decor_options_text": "0457 / 0120",
    }
    assert d.provenance.model_dump(mode="json") == {
        "category_source": "DECORATIVE BOARDS", "subcategory_source": "Veneered Panels", "source_design_no": "D-457",
        "source_shape_no": "S-12", "source_sheet": "Boards", "source_row": "57", "source_catalog_page": "14",
        "source_notes": "Imported from the 2025 catalogue", "source_extra": {"legacy_column": "kept"},
        "origin": "import", "origin_ref": "IMP-2026-0001",
    }
    assert d.stock_attributes.model_dump() == {
        "hsn_sac": "4412", "stock_uom_code": "sheets", "is_stock_tracked": False, "track_lots": True, "qc_required": True,
    }
    assert [(r.kind.value, r.source_text, str(r.length_mm), str(r.width_mm)) for r in d.dimensions] == [
        ("master_size", "2440 x 1220", "2440", "1220")
    ]
    assert (str(d.size.length_mm), str(d.size.width_mm), d.size.basis.value if d.size.basis else None) == (
        "2440", "1220", "master_size"
    )


def test_specification_fields_and_dimension_rows_round_trip(world: World) -> None:
    product_id, _ = _create(world, ProductCreate(
        product_key="RT-SPEC-0001",
        product_name="Round-trip specification",
        category_id=world.ref(keys.CATEGORIES.SERVEWARE),
        subcategory_id=world.ref(keys.SUBCATEGORIES.BOARDS),
        unit_of_sale="pcs",
        specification=SpecificationIn(
            length_mm="45 cm", width_mm="300", height_mm="18", thickness_mm="0.80", thickness_text="0.8 mm laminate",
            size_mm="450 x 300", size_label="Large", finish="Matte lacquer", material_type="Oak veneer",
            groove_count=2, bowl_count=1, bowl_type="Round", top_sheet="Oak", stand_material="Steel",
            stand_size_mm="Ø 300", board_size_mm="2440*1220*18", working_size_mm="2400 x 1200", type="Serving board",
            plate1_size_mm="30 x 20 cm", plate2_size_mm='12" x 8"', plate3_size_mm="300-350", no_of_boards=3,
            handle_type="Cut-out", special_features="Juice groove", care_instructions="Hand wash only",
            usage_notes="Not for oven use", source_extra={"legacy_spec": "kept"},
        ),
    ))
    d = catalogue.get_product(world.actor(keys.USERS.MEERA), product_id)
    s = d.specification
    assert s is not None
    assert [(str(getattr(s, f)), getattr(s, f"{f}_source")) for f in ("length_mm", "width_mm", "height_mm", "thickness_mm")] == [
        ("450", "45 cm"), ("300", "300"), ("18", "18"), ("0.8", "0.80"),
    ]
    assert s.model_dump(exclude={
        "length_mm", "length_mm_source", "width_mm", "width_mm_source", "height_mm", "height_mm_source",
        "thickness_mm", "thickness_mm_source",
    }) == {
        "thickness_text": "0.8 mm laminate", "size_label": "Large", "finish": "Matte lacquer",
        "material_type": "Oak veneer", "groove_count": 2, "bowl_count": 1, "bowl_type": "Round", "top_sheet": "Oak",
        "stand_material": "Steel", "type": "Serving board", "no_of_boards": 3, "handle_type": "Cut-out",
        "special_features": "Juice groove", "care_instructions": "Hand wash only", "usage_notes": "Not for oven use",
        "source_extra": {"legacy_spec": "kept"},
    }

    def fmt(value: object) -> str | None:
        return None if value is None else str(value)

    rows = {
        r.kind.value: (r.source_text, fmt(r.length_mm), fmt(r.width_mm), fmt(r.height_mm), fmt(r.diameter_mm), r.parse_status.value)
        for r in d.dimensions
    }
    assert rows == {
        "spec_size": ("450 x 300", "450", "300", None, None, "parsed"),
        "board_size": ("2440*1220*18", "2440", "1220", "18", None, "parsed"),
        "working_size": ("2400 x 1200", "2400", "1200", None, None, "parsed"),
        "stand_size": ("Ø 300", None, None, None, "300", "parsed"),
        "plate_1_size": ("30 x 20 cm", "300", "200", None, None, "parsed"),
        "plate_2_size": ('12" x 8"', "304.8", "203.2", None, None, "parsed"),
        "plate_3_size": ("300-350", None, None, None, None, "unparsed"),  # ranges are never guessed
    }
    assert _rule_codes(d) >= {"unparsed_dimensions"}


def _rule_codes(detail: object) -> set[str]:
    return {m.code.value for m in detail.completeness.missing}  # type: ignore[attr-defined]


def test_packaging_fields_and_legacy_alias_pairs_round_trip(world: World) -> None:
    product_id, warnings = _create(world, ProductCreate(
        product_key="RT-PACK-0001",
        product_name="Round-trip packaging",
        category_id=world.ref(keys.CATEGORIES.SERVEWARE),
        subcategory_id=world.ref(keys.SUBCATEGORIES.TRAYS),
        unit_of_sale="pcs",
        packaging=PackagingIn(
            master_carton_qty="24", inner_qty=6, inner_pack_qty="6.0", unit_weight_kg="0.45",
            unit_packing_type="Poly bag", carton_length_cm="48", carton_width_cm="33", carton_height_cm="30",
            net_weight_kg="10.8", gross_weight_kg="11.6", cbm="0.047520", packaging_notes="Corner protectors",
            fragile_notes="Stack max 6", packaging_status="approved", notes="From the packaging sheet",
            source_extra={"legacy_pack": "kept"},
        ),
    ))
    assert warnings == []  # cbm matches L x W x H and gross >= net
    p = catalogue.get_product(world.actor(keys.USERS.MEERA), product_id).packaging
    assert p is not None
    assert (p.carton_qty, p.inner_qty, str(p.unit_weight_g), p.packing_type) == (24, 6, "450", "Poly bag")
    assert [str(v) for v in (p.carton_length_cm, p.carton_width_cm, p.carton_height_cm, p.net_weight_kg, p.gross_weight_kg)] == [
        "48", "33", "30", "10.8", "11.6",
    ]
    assert str(p.cbm) == "0.047520"
    assert (p.packaging_notes, p.fragile_notes, p.packaging_status, p.notes, p.source_extra) == (
        "Corner protectors", "Stack max 6", "approved", "From the packaging sheet", {"legacy_pack": "kept"},
    )
    assert p.alias_provenance == {
        "carton_qty": {"master_carton_qty": "24"},
        "inner_qty": {"inner_qty": "6", "inner_pack_qty": "6.0"},
        "unit_weight_g": {"unit_weight_kg": "0.45"},
        "packing_type": {"unit_packing_type": "Poly bag"},
    }
