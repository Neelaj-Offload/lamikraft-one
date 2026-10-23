"""Catalogue tables: taxonomy, product master, specification, packaging, parsed dimensions, lookup reference.

Every legacy field (CURRENT_STATE_SPEC §4.2/4.4/4.5/4.7/4.8) has a column. Canonical numbers live in typed
NUMERIC columns (mm, cm, g, kg, cbm); the original strings are kept in ``*_source`` columns or dimension rows.
Enumerations are varchar + CHECK (created in the migration through ``helpers.enum_check``).
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import (
    ArchivableMixin,
    Base,
    IdMixin,
    TenantEntity,
    TenantMixin,
    TimestampMixin,
    VersionMixin,
)


class Category(TenantEntity, VersionMixin, Base):
    __tablename__ = "catalogue_category"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    name_key: Mapped[str] = mapped_column(String(120), nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_catalog_page_start: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source_catalog_page_end: Mapped[str | None] = mapped_column(String(40), nullable=True)
    legacy_product_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    origin: Mapped[str] = mapped_column(String(30), nullable=False, default="ui")

    __table_args__ = (
        UniqueConstraint("company_id", "name_key", name="uq_catalogue_category_name_key"),
        CheckConstraint("btrim(name) <> ''", name="name_not_blank"),
    )


class Subcategory(TenantEntity, VersionMixin, Base):
    __tablename__ = "catalogue_subcategory"

    category_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("catalogue_category.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    name_key: Mapped[str] = mapped_column(String(120), nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_catalog_page_start: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source_catalog_page_end: Mapped[str | None] = mapped_column(String(40), nullable=True)
    legacy_product_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    origin: Mapped[str] = mapped_column(String(30), nullable=False, default="ui")

    __table_args__ = (
        UniqueConstraint("company_id", "category_id", "name_key", name="uq_catalogue_subcategory_name_key"),
        UniqueConstraint("id", "category_id", name="uq_catalogue_subcategory_id_category"),
        CheckConstraint("btrim(name) <> ''", name="name_not_blank"),
    )


class Product(TenantEntity, VersionMixin, ArchivableMixin, Base):
    __tablename__ = "catalogue_product"

    product_key: Mapped[str] = mapped_column(String(120), nullable=False)
    display_sku: Mapped[str] = mapped_column(String(120), nullable=False)
    product_name: Mapped[str] = mapped_column(String(300), nullable=False)
    brand: Mapped[str | None] = mapped_column(String(40), nullable=True)
    category_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("catalogue_category.id", ondelete="RESTRICT"), nullable=False
    )
    subcategory_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    category_source: Mapped[str | None] = mapped_column(String(200), nullable=True)
    subcategory_source: Mapped[str | None] = mapped_column(String(200), nullable=True)
    product_type: Mapped[str | None] = mapped_column(String(200), nullable=True)
    variant_group: Mapped[str | None] = mapped_column(String(200), nullable=True)
    unit_of_sale: Mapped[str | None] = mapped_column(String(20), nullable=True)
    decor_no: Mapped[str | None] = mapped_column(String(40), nullable=True)
    decor_no_source: Mapped[str | None] = mapped_column(String(80), nullable=True)
    decor_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    decor_primary: Mapped[str | None] = mapped_column(String(40), nullable=True)
    decor_options: Mapped[list[str] | None] = mapped_column(ARRAY(String(40)), nullable=True)
    decor_options_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    finish: Mapped[str | None] = mapped_column(String(200), nullable=True)
    shape: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    internal_remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_design_no: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_shape_no: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_sheet: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_row: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_catalog_page: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_extra: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    origin: Mapped[str] = mapped_column(String(30), nullable=False, default="ui")
    origin_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    #: normalised key, SKU, name, decor, finish, family and taxonomy names for tokenised escaped-ILIKE search
    search_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: effective size (denormalised from the parsed dimension rows) for filtering before pagination
    size_length_mm: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    size_width_mm: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    size_height_mm: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    size_diameter_mm: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    size_basis: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # stock attributes: nullable until inventory goes live (ADR-037)
    hsn_sac: Mapped[str | None] = mapped_column(String(8), nullable=True)
    stock_uom_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    is_stock_tracked: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    track_lots: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    qc_required: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    __table_args__ = (
        UniqueConstraint("company_id", "product_key", name="uq_catalogue_product_key"),
        ForeignKeyConstraint(
            ["subcategory_id", "category_id"],
            ["catalogue_subcategory.id", "catalogue_subcategory.category_id"],
            name="fk_catalogue_product_subcategory_in_category",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "product_key = btrim(product_key) AND length(product_key) BETWEEN 1 AND 120 "
            "AND product_key !~ '[[:cntrl:]]'",
            name="product_key_format",
        ),
        CheckConstraint("btrim(display_sku) <> '' AND btrim(product_name) <> ''", name="names_not_blank"),
        CheckConstraint("hsn_sac IS NULL OR hsn_sac ~ '^[0-9]{4,8}$'", name="hsn_sac_format"),
        CheckConstraint(
            "(size_length_mm IS NULL OR size_length_mm > 0) AND (size_width_mm IS NULL OR size_width_mm > 0) "
            "AND (size_height_mm IS NULL OR size_height_mm > 0) AND (size_diameter_mm IS NULL OR size_diameter_mm > 0)",
            name="size_positive",
        ),
        Index("ix_catalogue_product_display_sku", "company_id", "display_sku"),
        Index("ix_catalogue_product_taxonomy", "company_id", "category_id", "subcategory_id"),
        Index("ix_catalogue_product_decor", "company_id", "decor_no"),
        Index("ix_catalogue_product_brand", "company_id", "brand"),
        Index("ix_catalogue_product_variant_group", "company_id", "variant_group"),
        Index("ix_catalogue_product_finish", "company_id", "finish"),
        Index("ix_catalogue_product_size", "company_id", "size_length_mm", "size_width_mm"),
        Index(
            "ix_catalogue_product_search_trgm",
            "search_text",
            postgresql_using="gin",
            postgresql_ops={"search_text": "gin_trgm_ops"},
        ),
    )


Index("ix_catalogue_product_updated", Product.company_id, Product.updated_at.desc())
Index(
    "ix_catalogue_product_status_live",
    Product.company_id,
    Product.status,
    postgresql_where=Product.archived_at.is_(None),
)


class ProductSpecification(TenantMixin, TimestampMixin, Base):
    """One row per product (legacy ``specifications``)."""

    __tablename__ = "catalogue_product_specification"

    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("catalogue_product.id", ondelete="CASCADE"), primary_key=True
    )
    length_mm: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    length_mm_source: Mapped[str | None] = mapped_column(String(80), nullable=True)
    width_mm: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    width_mm_source: Mapped[str | None] = mapped_column(String(80), nullable=True)
    height_mm: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    height_mm_source: Mapped[str | None] = mapped_column(String(80), nullable=True)
    thickness_mm: Mapped[Decimal | None] = mapped_column(Numeric(8, 3), nullable=True)
    thickness_mm_source: Mapped[str | None] = mapped_column(String(80), nullable=True)
    thickness_text: Mapped[str | None] = mapped_column(String(200), nullable=True)
    size_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    spec_finish: Mapped[str | None] = mapped_column(String(200), nullable=True)
    material_type: Mapped[str | None] = mapped_column(String(200), nullable=True)
    groove_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bowl_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bowl_type: Mapped[str | None] = mapped_column(String(200), nullable=True)
    top_sheet: Mapped[str | None] = mapped_column(String(200), nullable=True)
    stand_material: Mapped[str | None] = mapped_column(String(200), nullable=True)
    spec_type: Mapped[str | None] = mapped_column(String(200), nullable=True)
    no_of_boards: Mapped[int | None] = mapped_column(Integer, nullable=True)
    handle_type: Mapped[str | None] = mapped_column(String(200), nullable=True)
    special_features: Mapped[str | None] = mapped_column(Text, nullable=True)
    care_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    usage_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_extra: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "(length_mm IS NULL OR length_mm > 0) AND (width_mm IS NULL OR width_mm > 0) "
            "AND (height_mm IS NULL OR height_mm > 0) AND (thickness_mm IS NULL OR thickness_mm > 0)",
            name="dimensions_positive",
        ),
        CheckConstraint(
            "(groove_count IS NULL OR groove_count >= 0) AND (bowl_count IS NULL OR bowl_count >= 0) "
            "AND (no_of_boards IS NULL OR no_of_boards >= 0)",
            name="counts_non_negative",
        ),
        Index("ix_catalogue_product_specification_thickness", "company_id", "thickness_mm"),
    )


class ProductPackaging(TenantMixin, TimestampMixin, Base):
    """One row per product (legacy ``packaging``); alias names reconcile to these canonical columns."""

    __tablename__ = "catalogue_product_packaging"

    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("catalogue_product.id", ondelete="CASCADE"), primary_key=True
    )
    carton_qty: Mapped[int | None] = mapped_column(Integer, nullable=True)
    inner_qty: Mapped[int | None] = mapped_column(Integer, nullable=True)
    unit_weight_g: Mapped[Decimal | None] = mapped_column(Numeric(14, 3), nullable=True)
    packing_type: Mapped[str | None] = mapped_column(String(200), nullable=True)
    carton_length_cm: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    carton_width_cm: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    carton_height_cm: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    net_weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    gross_weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    cbm: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    packaging_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    fragile_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    packaging_status: Mapped[str | None] = mapped_column(String(200), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    alias_provenance: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    source_extra: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "(carton_qty IS NULL OR carton_qty > 0) AND (inner_qty IS NULL OR inner_qty > 0)",
            name="quantities_positive",
        ),
        CheckConstraint(
            "(unit_weight_g IS NULL OR unit_weight_g > 0) AND (net_weight_kg IS NULL OR net_weight_kg > 0) "
            "AND (gross_weight_kg IS NULL OR gross_weight_kg > 0) AND (cbm IS NULL OR cbm > 0)",
            name="weights_positive",
        ),
        CheckConstraint(
            "(carton_length_cm IS NULL OR carton_length_cm > 0) AND (carton_width_cm IS NULL OR carton_width_cm > 0) "
            "AND (carton_height_cm IS NULL OR carton_height_cm > 0)",
            name="carton_dimensions_positive",
        ),
    )


class ProductDimension(IdMixin, TenantMixin, TimestampMixin, Base):
    """A legacy size string kept verbatim with its parsed canonical millimetres."""

    __tablename__ = "catalogue_product_dimension"

    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("catalogue_product.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    source_field: Mapped[str] = mapped_column(String(60), nullable=False)
    source_text: Mapped[str] = mapped_column(String(200), nullable=False)
    length_mm: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    width_mm: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    height_mm: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    diameter_mm: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    source_unit: Mapped[str | None] = mapped_column(String(10), nullable=True)
    unit_inferred: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    parse_status: Mapped[str] = mapped_column(String(20), nullable=False)
    parse_warnings: Mapped[list[str]] = mapped_column(ARRAY(String(60)), nullable=False, default=list)

    __table_args__ = (
        UniqueConstraint("product_id", "kind", name="uq_catalogue_product_dimension_kind"),
        Index("ix_catalogue_product_dimension_status", "company_id", "parse_status"),
    )


class LookupReference(IdMixin, TenantMixin, TimestampMixin, Base):
    """Legacy ``lookup_reference`` rows, preserved as reference data (reader/export arrive with imports, Slice 2)."""

    __tablename__ = "catalogue_lookup_reference"

    lookup_type: Mapped[str] = mapped_column(String(80), nullable=False)
    key_1: Mapped[str] = mapped_column(String(200), nullable=False)
    key_2: Mapped[str] = mapped_column(String(200), nullable=False, default="", server_default="")
    value_1: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_2: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_extra: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        UniqueConstraint("company_id", "lookup_type", "key_1", "key_2", name="uq_catalogue_lookup_reference_key"),
    )


__all__ = [
    "Category",
    "LookupReference",
    "Product",
    "ProductDimension",
    "ProductPackaging",
    "ProductSpecification",
    "Subcategory",
]
