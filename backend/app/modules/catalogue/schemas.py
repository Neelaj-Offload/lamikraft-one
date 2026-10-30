"""Catalogue enumerations, request models and read models (DecimalStr for every measure; floats rejected)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StrictInt, StringConstraints

from app.core.http.capabilities import Capability, TransitionRead
from app.core.money import CurrencyCode, DecimalStr, Money, Quantity
from app.modules.catalogue.normalise import plain_decimal
from app.platform.authz.redaction import Restricted

#: Seeded UOM codes (docs/architecture/conventions.md §6). ``org.uom`` is created by the platform lane in this
#: wave; until the FK to ``uom.code`` is added at merge, columns holding a unit code carry a CHECK on this list.
UOM_CODES: tuple[str, ...] = (
    "pcs", "nos", "sheets", "kg", "g", "m", "mm", "cm", "sqm", "sqft", "box", "set", "roll", "bundle", "carton",
)
UomCode = Literal[
    "pcs", "nos", "sheets", "kg", "g", "m", "mm", "cm", "sqm", "sqft", "box", "set", "roll", "bundle", "carton",
]
#: ``uom.is_integer`` units (conventions §6): quantities in these units are whole numbers; others take <= 4 dp
INTEGER_UOMS: frozenset[str] = frozenset({"pcs", "nos", "sheets", "box", "set", "roll", "bundle", "carton"})
#: the guard of the price columns on catalogue reads (resolved final prices; never the breakdown or cost)
PRICE_COLUMNS_GUARD = Restricted("pricing.price.read", model_exposure="allow")


def quantity_entry_problem(value: Decimal, uom: str) -> tuple[str, str] | None:
    """The conventions §6 entry rule for a quantity in ``uom``: ``(code, message)`` when it is broken, else None."""
    if uom in INTEGER_UOMS:
        if value != value.to_integral_value():
            return "uom_integer_only", f"{uom} quantities are whole numbers"
    elif value.as_tuple().exponent < -4 and value != value.quantize(Decimal("0.0001")):  # type: ignore[operator]
        return "uom_max_decimals", f"{uom} quantities take at most 4 decimal places"
    return None


class ProductStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    UNDER_DEVELOPMENT = "under_development"


class ProductOrigin(StrEnum):
    UI = "ui"
    IMPORT = "import"
    MIGRATION = "migration"
    PROMOTION = "promotion"
    SEED = "seed"


class TaxonomyOrigin(StrEnum):
    SEED = "seed"
    UI = "ui"
    IMPORT = "import"
    MIGRATION = "migration"
    MIGRATION_INFERRED = "migration_inferred"


class DimensionKind(StrEnum):
    MASTER_SIZE = "master_size"
    SPEC_SIZE = "spec_size"
    BOARD_SIZE = "board_size"
    WORKING_SIZE = "working_size"
    STAND_SIZE = "stand_size"
    PLATE_1_SIZE = "plate_1_size"
    PLATE_2_SIZE = "plate_2_size"
    PLATE_3_SIZE = "plate_3_size"


class ParseStatus(StrEnum):
    PARSED = "parsed"
    AMBIGUOUS = "ambiguous"
    UNPARSED = "unparsed"


class SizeBasis(StrEnum):
    MASTER_SIZE = "master_size"
    SPEC_SIZE = "spec_size"
    SPEC_LENGTH_WIDTH = "spec_length_width"


class CompletenessRule(StrEnum):
    NO_DECOR = "no_decor"
    NO_SPECIFICATION = "no_specification"
    NO_THICKNESS = "no_thickness"
    NO_SIZE = "no_size"
    UNPARSED_DIMENSIONS = "unparsed_dimensions"
    NO_PACKAGING = "no_packaging"
    NO_CARTON_QTY = "no_carton_qty"
    NO_UNIT_WEIGHT = "no_unit_weight"
    CATEGORY_INACTIVE = "category_inactive"
    NO_HSN_SAC = "no_hsn_sac"
    SHARED_DISPLAY_SKU = "shared_display_sku"
    NO_IMAGE = "no_image"
    NO_PRIMARY_IMAGE = "no_primary_image"
    MEDIA_INGEST_FAILED = "media_ingest_failed"
    NO_ACTIVE_PRICE = "no_active_price"


#: spec field (legacy name) -> dimension kind; the text is parsed into canonical millimetres
SPEC_DIMENSION_FIELDS: dict[str, DimensionKind] = {
    "size_mm": DimensionKind.SPEC_SIZE,
    "board_size_mm": DimensionKind.BOARD_SIZE,
    "working_size_mm": DimensionKind.WORKING_SIZE,
    "stand_size_mm": DimensionKind.STAND_SIZE,
    "plate1_size_mm": DimensionKind.PLATE_1_SIZE,
    "plate2_size_mm": DimensionKind.PLATE_2_SIZE,
    "plate3_size_mm": DimensionKind.PLATE_3_SIZE,
}


def _plain(value: Decimal) -> Decimal:
    return Decimal(plain_decimal(value))


#: a measure (mm, cm, g, kg) rendered without trailing zeros: thickness 0.800 -> "0.8", 12.000 -> "12"
Measure = Annotated[DecimalStr, AfterValidator(_plain)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000)]


# ---- write models (services; HTTP write endpoints arrive with the Slice-2 forms) ------------------
class SpecificationIn(BaseModel):
    """Specification fields. Lengths are the entered text (unit mm unless stated, e.g. ``"45 cm"``); the text is
    kept as ``*_source`` provenance next to the canonical millimetres."""

    model_config = ConfigDict(extra="forbid")

    length_mm: Text | None = None
    width_mm: Text | None = None
    height_mm: Text | None = None
    thickness_mm: Text | None = None
    thickness_text: Text | None = None
    size_mm: Text | None = None
    size_label: Text | None = None
    finish: Text | None = None
    material_type: Text | None = None
    groove_count: int | None = Field(default=None, ge=0)
    bowl_count: int | None = Field(default=None, ge=0)
    bowl_type: Text | None = None
    top_sheet: Text | None = None
    stand_material: Text | None = None
    stand_size_mm: Text | None = None
    board_size_mm: Text | None = None
    working_size_mm: Text | None = None
    type: Text | None = None
    plate1_size_mm: Text | None = None
    plate2_size_mm: Text | None = None
    plate3_size_mm: Text | None = None
    no_of_boards: int | None = Field(default=None, ge=0)
    handle_type: Text | None = None
    special_features: LongText | None = None
    care_instructions: LongText | None = None
    usage_notes: LongText | None = None
    source_extra: dict[str, Any] | None = None


class PackagingIn(BaseModel):
    """Packaging fields. Legacy alias names are accepted and reconciled to one canonical value each
    (carton_qty/master_carton_qty, inner_qty/inner_pack_qty, unit_weight_g/unit_weight_kg,
    packing_type/unit_packing_type); a disagreement is rejected with ``alias_conflict``."""

    model_config = ConfigDict(extra="forbid")

    carton_qty: StrictInt | DecimalStr | None = None
    master_carton_qty: StrictInt | DecimalStr | None = None
    inner_qty: StrictInt | DecimalStr | None = None
    inner_pack_qty: StrictInt | DecimalStr | None = None
    unit_weight_g: DecimalStr | None = None
    unit_weight_kg: DecimalStr | None = None
    packing_type: Text | None = None
    unit_packing_type: Text | None = None
    carton_length_cm: DecimalStr | None = None
    carton_width_cm: DecimalStr | None = None
    carton_height_cm: DecimalStr | None = None
    net_weight_kg: DecimalStr | None = None
    gross_weight_kg: DecimalStr | None = None
    cbm: DecimalStr | None = None
    packaging_notes: LongText | None = None
    fragile_notes: LongText | None = None
    packaging_status: Text | None = None
    notes: LongText | None = None
    source_extra: dict[str, Any] | None = None


class ProductMasterFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_sku: Text | None = None
    product_name: Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] | None = None
    brand: Annotated[str, StringConstraints(strip_whitespace=True, max_length=40)] | None = None
    category_id: uuid.UUID | None = None
    subcategory_id: uuid.UUID | None = None
    category_source: Text | None = None
    subcategory_source: Text | None = None
    product_type: Text | None = None
    variant_group: Text | None = None
    unit_of_sale: UomCode | None = None
    size_mm: Text | None = None
    decor_no: Annotated[str, StringConstraints(max_length=40)] | None = None
    decor_name: Text | None = None
    decor_primary: Annotated[str, StringConstraints(max_length=40)] | None = None
    decor_options: list[Annotated[str, StringConstraints(max_length=40)]] | None = None
    decor_options_text: LongText | None = None
    finish: Text | None = None
    shape: Text | None = None
    status: ProductStatus | None = None
    description: LongText | None = None
    internal_remarks: LongText | None = None
    source_design_no: Text | None = None
    source_shape_no: Text | None = None
    source_sheet: Text | None = None
    source_row: Text | None = None
    source_catalog_page: Text | None = None
    source_notes: LongText | None = None
    source_extra: dict[str, Any] | None = None
    hsn_sac: Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[0-9]{4,8}$")] | None = None
    stock_uom_code: UomCode | None = None
    is_stock_tracked: bool | None = None
    track_lots: bool | None = None
    qc_required: bool | None = None


class ProductCreate(ProductMasterFields):
    product_key: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    category_id: uuid.UUID  # type: ignore[assignment]
    specification: SpecificationIn | None = None
    packaging: PackagingIn | None = None
    origin: ProductOrigin = ProductOrigin.UI
    origin_ref: Text | None = None


class ProductUpdate(ProductMasterFields):
    """Dirty master fields plus optional full replacement of the specification or packaging section.
    ``product_key`` is immutable and therefore not accepted (``extra="forbid"``)."""

    expected_version: int
    specification: SpecificationIn | None = None
    packaging: PackagingIn | None = None


class CategoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    display_order: int = 0
    is_active: bool = True
    description: LongText | None = None
    source_catalog_page_start: Annotated[str, StringConstraints(max_length=40)] | None = None
    source_catalog_page_end: Annotated[str, StringConstraints(max_length=40)] | None = None
    legacy_product_count: int | None = Field(default=None, ge=0)
    origin: TaxonomyOrigin = TaxonomyOrigin.UI


# ---- read models ----------------------------------------------------------------------------------
class TaxonomyRef(BaseModel):
    id: uuid.UUID
    name: str
    is_active: bool


class ProductSize(BaseModel):
    length_mm: Measure | None = None
    width_mm: Measure | None = None
    height_mm: Measure | None = None
    diameter_mm: Measure | None = None
    basis: SizeBasis | None = None


class OrderValueRecommendationRead(BaseModel):
    """The commercial engine's order-value recommendation for a list price (advisory; not a product MOQ)."""

    status: Literal["AVAILABLE", "UNAVAILABLE", "NOT_EVALUATED", "NOT_APPLICABLE"]
    quantity: Quantity | None
    minimum_order_value: Money | None
    carton_qty: int | None
    explanation: str
    label: str


class ProductPriceColumn(BaseModel):
    """The standard-tier price of a product in one currency, from a real active list (never relabelled or
    converted): ``found``, ``ambiguous`` (several lists without a unique explicit priority; never guessed),
    ``unavailable`` (zero price) or ``not_found``."""

    currency: CurrencyCode
    status: Literal["found", "ambiguous", "not_found", "unavailable"]
    unit_price: Money | None = None
    unit_code: str | None = None
    price_list_code: str | None = None
    item_id: uuid.UUID | None = None
    product_moq: Quantity | None = None
    recommendation: OrderValueRecommendationRead | None = None


class MediaThumb(BaseModel):
    """The primary image of a product (served by ``GET /api/v1/files/{file_id}/content``; originals only until the
    platform's image variants exist)."""

    media_id: uuid.UUID
    file_id: uuid.UUID
    url: str
    alt_text: str | None


class ProductSummary(BaseModel):
    id: uuid.UUID
    product_key: str
    display_sku: str
    product_name: str
    brand: str | None
    category: TaxonomyRef
    subcategory: TaxonomyRef | None
    product_type: str | None
    variant_group: str | None
    unit_of_sale: str | None
    decor_no: str | None
    decor_name: str | None
    finish: str | None
    shape: str | None
    status: ProductStatus
    thickness_mm: Measure | None
    size: ProductSize
    carton_qty: int | None
    primary_image: MediaThumb | None = None
    archived: bool
    updated_at: datetime
    path: str
    #: price and order-value recommendation in the requested currency (UI-35); only with ``pricing.price.read``,
    #: otherwise absent and listed in ``redacted_fields``
    prices: Annotated[list[ProductPriceColumn] | None, PRICE_COLUMNS_GUARD] = None
    redacted_fields: list[str] = Field(default_factory=list)


class DimensionRead(BaseModel):
    kind: DimensionKind
    source_field: str
    source_text: str
    length_mm: Measure | None
    width_mm: Measure | None
    height_mm: Measure | None
    diameter_mm: Measure | None
    source_unit: str | None
    unit_inferred: bool
    parse_status: ParseStatus
    parse_warnings: list[str]


class SpecificationRead(BaseModel):
    length_mm: Measure | None
    length_mm_source: str | None
    width_mm: Measure | None
    width_mm_source: str | None
    height_mm: Measure | None
    height_mm_source: str | None
    thickness_mm: Measure | None
    thickness_mm_source: str | None
    thickness_text: str | None
    size_label: str | None
    finish: str | None
    material_type: str | None
    groove_count: int | None
    bowl_count: int | None
    bowl_type: str | None
    top_sheet: str | None
    stand_material: str | None
    type: str | None
    no_of_boards: int | None
    handle_type: str | None
    special_features: str | None
    care_instructions: str | None
    usage_notes: str | None
    source_extra: dict[str, Any] | None


class PackagingRead(BaseModel):
    carton_qty: int | None
    inner_qty: int | None
    unit_weight_g: Measure | None
    packing_type: str | None
    carton_length_cm: Measure | None
    carton_width_cm: Measure | None
    carton_height_cm: Measure | None
    net_weight_kg: Measure | None
    gross_weight_kg: Measure | None
    cbm: DecimalStr | None
    packaging_notes: str | None
    fragile_notes: str | None
    packaging_status: str | None
    notes: str | None
    alias_provenance: dict[str, dict[str, str]] | None
    source_extra: dict[str, Any] | None
    summary: str | None  # "450g · 24/ctn · Poly bag" (FG-PKG-11 configurator summary, from canonical fields)
    warnings: list[str]


class DecorRead(BaseModel):
    decor_no: str | None
    decor_no_source: str | None
    decor_name: str | None
    decor_primary: str | None
    decor_options: list[str]
    decor_options_text: str | None


class ProvenanceRead(BaseModel):
    category_source: str | None
    subcategory_source: str | None
    source_design_no: str | None
    source_shape_no: str | None
    source_sheet: str | None
    source_row: str | None
    source_catalog_page: str | None
    source_notes: str | None
    source_extra: dict[str, Any] | None
    origin: ProductOrigin
    origin_ref: str | None


class StockAttributesRead(BaseModel):
    hsn_sac: str | None
    stock_uom_code: str | None
    is_stock_tracked: bool | None
    track_lots: bool | None
    qc_required: bool | None


class CompletenessIssue(BaseModel):
    code: CompletenessRule
    severity: Literal["warning", "info"]
    label: str


class NotEvaluated(BaseModel):
    code: str
    reason: str


class CompletenessRead(BaseModel):
    score_pct: int
    checks_evaluated: int
    checks_passed: int
    missing: list[CompletenessIssue]
    not_evaluated: list[NotEvaluated]


class SectionRead(BaseModel):
    key: str
    label: str
    path: str


class ProductDetail(BaseModel):
    id: uuid.UUID
    product_key: str
    display_sku: str
    product_name: str
    brand: str | None
    category: TaxonomyRef
    subcategory: TaxonomyRef | None
    product_type: str | None
    variant_group: str | None
    unit_of_sale: str | None
    finish: str | None
    shape: str | None
    status: ProductStatus
    description: str | None
    internal_remarks: str | None
    decor: DecorRead
    size: ProductSize
    stock_attributes: StockAttributesRead
    provenance: ProvenanceRead
    specification: SpecificationRead | None
    packaging: PackagingRead | None
    dimensions: list[DimensionRead]
    completeness: CompletenessRead
    primary_image: MediaThumb | None = None
    media_count: int = 0
    sections: list[SectionRead]
    version: int
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None
    path: str
    #: server-computed from the product policy (``catalogue.product.update`` at company scope)
    capabilities: dict[str, Capability]
    #: product status is a master field changed through ``update``; the catalogue has no workflow transitions
    allowed_transitions: list[TransitionRead] = Field(default_factory=list)
    #: overview prices (UI-39): one per currency in which a real active standard list prices the product, with the
    #: order-value recommendation; only with ``pricing.price.read`` (absent and listed in ``redacted_fields``)
    prices: Annotated[list[ProductPriceColumn] | None, PRICE_COLUMNS_GUARD] = None
    redacted_fields: list[str] = Field(default_factory=list)


class ProductWriteResult(BaseModel):
    product: ProductDetail
    warnings: list[str]


class FacetValue(BaseModel):
    value: str
    label: str
    count: int


class ProductFacets(BaseModel):
    total: int
    categories: list[FacetValue]
    subcategories: list[FacetValue]
    families: list[FacetValue]
    sizes: list[FacetValue]
    thicknesses: list[FacetValue]
    decors: list[FacetValue]
    finishes: list[FacetValue]
    statuses: list[FacetValue]
    brands: list[FacetValue]


class CategoryCount(BaseModel):
    category_id: uuid.UUID
    name: str
    count: int


class RecentProduct(BaseModel):
    id: uuid.UUID
    product_key: str
    product_name: str
    updated_at: datetime
    updated_by_name: str | None
    path: str


class ProductStats(BaseModel):
    total: int
    by_status: dict[str, int]
    archived: int
    updated_last_7_days: int
    #: live products without a current active price (any list); null without ``pricing.price.read``
    without_active_price: int | None = None
    by_category: list[CategoryCount]
    recently_changed: list[RecentProduct]
    as_of: datetime


class CompletenessRuleCount(BaseModel):
    code: CompletenessRule
    label: str
    severity: Literal["warning", "info"]
    count: int
    filter_path: str


class CompletenessSummary(BaseModel):
    total_products: int
    complete_products: int
    rules: list[CompletenessRuleCount]
    not_evaluated: list[NotEvaluated]


class SubcategoryRead(BaseModel):
    id: uuid.UUID
    name: str
    display_order: int
    is_active: bool
    effective_active: bool
    description: str | None
    product_count: int


class CategoryRead(BaseModel):
    id: uuid.UUID
    name: str
    display_order: int
    is_active: bool
    description: str | None
    source_catalog_page_start: str | None
    source_catalog_page_end: str | None
    product_count: int
    subcategories: list[SubcategoryRead]


class ProductFilters(BaseModel):
    """List filters; every one is applied in SQL before LIMIT/OFFSET and feeds the same total."""

    model_config = ConfigDict(extra="forbid")

    q: Annotated[str, StringConstraints(max_length=200)] | None = None
    category_id: uuid.UUID | None = None
    subcategory_id: uuid.UUID | None = None
    family: Text | None = None
    size: Text | None = None
    thickness: Text | None = None
    decor: Text | None = None
    finish: Text | None = None
    status: list[ProductStatus] | None = None
    brand: Text | None = None
    issue: CompletenessRule | None = None
    has_image: bool | None = None
    has_price: bool | None = None
    include_archived: bool = False


ProductSort = Literal["relevance", "product_key", "product_name", "-updated_at"]


class ProductCandidate(BaseModel):
    product_id: uuid.UUID
    product_key: str
    display_sku: str
    product_name: str
    unit_of_sale: str | None
    decor_no: str | None
    status: ProductStatus
    match: Literal["product_key", "display_sku", "exact_name", "tokens"]


class ResolveProductInput(BaseModel):
    """Input of the ``resolve_product`` agent tool (no identity fields; the actor comes from the server)."""

    model_config = ConfigDict(extra="forbid")

    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)] = Field(
        description="Product key, SKU, or words of the product name (decor, finish, family)"
    )


class ProductResolution(BaseModel):
    """``unique``: one product matched; ``ambiguous``: several (ask the user, never pick); ``not_found``."""

    status: Literal["unique", "ambiguous", "not_found"]
    query: str
    candidates: list[ProductCandidate]
    total_matches: int
