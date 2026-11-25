"""Catalogue services: the only entry point for routers, tools, seeds and other modules.

Reads go through ``ScopedRepository`` scope clauses; every list filter is applied in SQL before LIMIT/OFFSET and
the same WHERE clause feeds the total (legacy bug §10.1 #6). Search is tokenised escaped ILIKE over a maintained
``search_text`` (no regular expressions, legacy §10.2 #6). Completeness is computed from the actual columns with
one SQL definition per rule, shared by the list ``issue`` filter, the summary counts and the detail view.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import ColumnElement, Select, and_, case, exists, func, or_, select, true
from sqlalchemy.orm import aliased

from app.core.db.base import new_id
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.http.pagination import MAX_LIMIT, Page
from app.core.money import CURRENCY_EXPONENT
from app.core.text import LIKE_ESCAPE, contains_pattern, escape_like, normalize_search_text, tokens
from app.modules.catalogue import events as ev
from app.modules.catalogue.models import (
    Category,
    Product,
    ProductDimension,
    ProductMedia,
    ProductPackaging,
    ProductSpecification,
    Subcategory,
)
from app.modules.catalogue.normalise import (
    ALIAS_CONFLICT,
    normalise_identifier,
    normalise_thickness,
    packaging_cross_checks,
    parse_dimension,
    parse_length,
    plain_decimal,
    resolve_packaging_aliases,
)
from app.modules.catalogue.schemas import (
    SPEC_DIMENSION_FIELDS,
    Capability,
    CategoryCount,
    CategoryCreate,
    CategoryRead,
    CompletenessIssue,
    CompletenessRead,
    CompletenessRule,
    CompletenessRuleCount,
    CompletenessSummary,
    DecorRead,
    DimensionKind,
    DimensionRead,
    FacetValue,
    MediaThumb,
    NotEvaluated,
    PackagingIn,
    PackagingRead,
    ParseStatus,
    ProductCandidate,
    ProductCreate,
    ProductDetail,
    ProductFacets,
    ProductFilters,
    ProductPriceColumn,
    ProductResolution,
    ProductSize,
    ProductSort,
    ProductStats,
    ProductStatus,
    ProductSummary,
    ProductUpdate,
    ProductWriteResult,
    ProvenanceRead,
    RecentProduct,
    SectionRead,
    SizeBasis,
    SpecificationIn,
    SpecificationRead,
    StockAttributesRead,
    SubcategoryRead,
    TaxonomyRef,
)
from app.platform.service import query
from app.platform.sources import SourceFacts
from app.platform.uow import UnitOfWork

P = Product
S = ProductSpecification
K = ProductPackaging
C = Category
SC = Subcategory
D = ProductDimension

READ = "catalogue.product.read"
PRICE_READ = "pricing.price.read"
PRICE_LIST_READ = "pricing.price_list.read"


# =====================================================================================================
# price columns (contributed by the commercial module: pricing and commercial depend on the catalogue, so the
# catalogue reads prices through this registered contribution and never imports them)
# =====================================================================================================
#: (uow, product ids, currencies, price type or None) -> product id -> one column per requested currency
PriceColumnsProvider = Callable[
    [UnitOfWork, Sequence[uuid.UUID], Sequence[str], str | None], dict[uuid.UUID, list[ProductPriceColumn]]
]
_PRICE_COLUMNS: list[PriceColumnsProvider] = []


def register_price_columns(provider: PriceColumnsProvider) -> None:
    """Install the price-column provider (the commercial manifest's ``on_load``; one provider, last wins)."""
    _PRICE_COLUMNS[:] = [provider]


#: (uow) -> SELECT of product ids that have a current active price in any list (registered by a module that depends
#: on pricing, like the price columns); absent -> the price completeness rule and ``has_price`` are not evaluated
PricePresenceProvider = Callable[[UnitOfWork], Select[Any]]
_PRICE_PRESENCE: list[PricePresenceProvider] = []


def register_price_presence(provider: PricePresenceProvider) -> None:
    _PRICE_PRESENCE[:] = [provider]


def _priced_ids(uow: UnitOfWork) -> Select[Any] | None:
    if not _PRICE_PRESENCE or not uow.actor.can(PRICE_READ):
        return None
    return _PRICE_PRESENCE[0](uow)


def price_columns(
    uow: UnitOfWork, product_ids: Sequence[uuid.UUID], currencies: Sequence[str], price_type: str | None
) -> tuple[dict[uuid.UUID, list[ProductPriceColumn]] | None, list[str]]:
    """Public alias of the batch price-column read (recent products, exports)."""
    return _price_columns(uow, product_ids, currencies, price_type)


def _price_columns(
    uow: UnitOfWork, product_ids: Sequence[uuid.UUID], currencies: Sequence[str], price_type: str | None
) -> tuple[dict[uuid.UUID, list[ProductPriceColumn]] | None, list[str]]:
    """Price columns for a page of products in one batch (never per row); absent and listed in ``redacted_fields``
    without ``pricing.price.read`` (UI-35)."""
    if not uow.actor.can(PRICE_READ):
        return None, ["prices"]
    if not _PRICE_COLUMNS or not product_ids:
        return None, []
    return _PRICE_COLUMNS[0](uow, product_ids, currencies, price_type), []


# =====================================================================================================
# helpers
# =====================================================================================================
def name_key(name: str) -> str:
    return " ".join(name.split()).casefold()


def product_path(product_id: uuid.UUID) -> str:
    return f"/products/{product_id}"


def _origin(origin: str | None) -> dict[str, str]:
    return {"origin": origin} if origin else {}


class _Errors:
    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    def add(self, loc: Sequence[str | int], code: str, msg: str) -> None:
        self.items.append({"loc": ["body", *loc], "msg": msg, "code": code})

    def raise_if_any(self) -> None:
        if self.items:
            raise ValidationFailed("Some catalogue values are not valid", errors=self.items)


def _blank_to_none(value: Any) -> Any:
    if isinstance(value, str) and not value.strip():
        return None
    return value


# =====================================================================================================
# taxonomy
# =====================================================================================================
def find_category(uow: UnitOfWork, name: str) -> Category | None:
    return uow.session.scalars(
        select(C).where(C.company_id == uow.actor.company_id, C.name_key == name_key(name))
    ).first()


def find_subcategory(uow: UnitOfWork, category_id: uuid.UUID, name: str) -> Subcategory | None:
    return uow.session.scalars(
        select(SC).where(
            SC.company_id == uow.actor.company_id, SC.category_id == category_id, SC.name_key == name_key(name)
        )
    ).first()


def create_category(uow: UnitOfWork, data: CategoryCreate, *, origin: str | None = None) -> Category:
    """New categories are active unless stated otherwise (legacy bug §10.1 #7: created categories were invisible)."""
    uow.actor.require("catalogue.taxonomy.manage")
    if find_category(uow, data.name) is not None:
        raise Conflict("A category with this name already exists", code="category_exists")
    row = Category(
        name=" ".join(data.name.split()),
        name_key=name_key(data.name),
        display_order=data.display_order,
        is_active=data.is_active,
        description=data.description,
        source_catalog_page_start=data.source_catalog_page_start,
        source_catalog_page_end=data.source_catalog_page_end,
        legacy_product_count=data.legacy_product_count,
        origin=data.origin.value,
    )
    uow.add(row)
    uow.flush()
    changed = sorted(k for k, v in data.model_dump(exclude={"origin"}).items() if v not in (None, ""))
    uow.emit(
        ev.CATEGORY_CREATED,
        aggregate_id=row.id,
        aggregate_version=row.version,
        payload=ev.payload(ev.CategoryCreatedPayload(category_id=row.id, changed_fields=changed, origin=origin)),
    )
    uow.audit("catalogue.category.created", resource_type="catalogue.category", resource_id=row.id, resource_label=row.name)
    return row


def create_subcategory(
    uow: UnitOfWork, category_id: uuid.UUID, data: CategoryCreate, *, origin: str | None = None
) -> Subcategory:
    uow.actor.require("catalogue.taxonomy.manage")
    category = uow.repo(Category).get(category_id)
    if find_subcategory(uow, category.id, data.name) is not None:
        raise Conflict("A subcategory with this name already exists in the category", code="subcategory_exists")
    row = Subcategory(
        category_id=category.id,
        name=" ".join(data.name.split()),
        name_key=name_key(data.name),
        display_order=data.display_order,
        is_active=data.is_active,
        description=data.description,
        source_catalog_page_start=data.source_catalog_page_start,
        source_catalog_page_end=data.source_catalog_page_end,
        legacy_product_count=data.legacy_product_count,
        origin=data.origin.value,
    )
    uow.add(row)
    uow.flush()
    changed = sorted(k for k, v in data.model_dump(exclude={"origin"}).items() if v not in (None, ""))
    uow.emit(
        ev.SUBCATEGORY_CREATED,
        aggregate_id=row.id,
        aggregate_version=row.version,
        payload=ev.payload(
            ev.SubcategoryCreatedPayload(subcategory_id=row.id, category_id=category.id, changed_fields=changed, origin=origin)
        ),
    )
    uow.audit(
        "catalogue.subcategory.created", resource_type="catalogue.subcategory", resource_id=row.id, resource_label=row.name
    )
    return row


@query(READ)
def list_categories(uow: UnitOfWork, *, include_inactive: bool = False) -> list[CategoryRead]:
    """Taxonomy tree ordered by display order then name, with live counts of non-archived products."""
    categories = list(
        uow.session.scalars(uow.repo(Category).select().order_by(C.display_order, C.name_key, C.id))
    )
    subcategories = list(
        uow.session.scalars(uow.repo(Subcategory).select().order_by(SC.display_order, SC.name_key, SC.id))
    )
    live = uow.repo(Product).select().with_only_columns(P.category_id, P.subcategory_id).subquery()
    cat_counts = dict(uow.session.execute(select(live.c.category_id, func.count()).group_by(live.c.category_id)).all())
    sub_counts = dict(
        uow.session.execute(
            select(live.c.subcategory_id, func.count())
            .where(live.c.subcategory_id.is_not(None))
            .group_by(live.c.subcategory_id)
        ).all()
    )
    out: list[CategoryRead] = []
    for cat in categories:
        if not include_inactive and not cat.is_active:
            continue
        subs = [
            SubcategoryRead(
                id=s.id,
                name=s.name,
                display_order=s.display_order,
                is_active=s.is_active,
                effective_active=s.is_active and cat.is_active,
                description=s.description,
                product_count=int(sub_counts.get(s.id, 0)),
                version=s.version,
            )
            for s in subcategories
            if s.category_id == cat.id and (include_inactive or s.is_active)
        ]
        out.append(
            CategoryRead(
                id=cat.id,
                name=cat.name,
                display_order=cat.display_order,
                is_active=cat.is_active,
                description=cat.description,
                source_catalog_page_start=cat.source_catalog_page_start,
                source_catalog_page_end=cat.source_catalog_page_end,
                product_count=int(cat_counts.get(cat.id, 0)),
                subcategories=subs,
                version=cat.version,
            )
        )
    return out


# =====================================================================================================
# writes (UI forms arrive in Slice 2; seeds, imports and tests use the same code)
# =====================================================================================================
_MASTER_TEXT_FIELDS = (
    "display_sku", "product_name", "brand", "category_source", "subcategory_source", "product_type", "variant_group",
    "unit_of_sale", "decor_name", "decor_options_text", "finish", "shape", "description", "internal_remarks",
    "source_design_no", "source_shape_no", "source_sheet", "source_row", "source_catalog_page", "source_notes",
    "design_no",
)
_STOCK_FIELDS = ("hsn_sac", "stock_uom_code", "is_stock_tracked", "track_lots", "qc_required")
_SPEC_TEXT_FIELDS = (
    "thickness_text", "size_label", "material_type", "bowl_type", "top_sheet", "stand_material", "handle_type",
    "special_features", "care_instructions", "usage_notes",
)
_SPEC_INT_FIELDS = ("groove_count", "bowl_count", "no_of_boards")
_PACKAGING_DECIMALS = ("carton_length_cm", "carton_width_cm", "carton_height_cm", "net_weight_kg", "gross_weight_kg", "cbm")
_PACKAGING_TEXT = ("packaging_notes", "fragile_notes", "packaging_status", "notes")
_DECIMAL_SCALE = {
    "carton_length_cm": Decimal("0.001"),
    "carton_width_cm": Decimal("0.001"),
    "carton_height_cm": Decimal("0.001"),
    "net_weight_kg": Decimal("0.0001"),
    "gross_weight_kg": Decimal("0.0001"),
    "cbm": Decimal("0.000001"),
}
#: exclusive upper bounds of the NUMERIC columns (NUMERIC(12,3) cm, NUMERIC(12,4) kg, NUMERIC(12,6) cbm)
_DECIMAL_LIMIT = {
    "carton_length_cm": Decimal(10) ** 9,
    "carton_width_cm": Decimal(10) ** 9,
    "carton_height_cm": Decimal(10) ** 9,
    "net_weight_kg": Decimal(10) ** 8,
    "gross_weight_kg": Decimal(10) ** 8,
    "cbm": Decimal(10) ** 6,
}


def _taxonomy_check(
    uow: UnitOfWork, category_id: uuid.UUID, subcategory_id: uuid.UUID | None, errors: _Errors
) -> tuple[Category | None, Subcategory | None]:
    category = uow.session.scalars(
        select(C).where(C.id == category_id, C.company_id == uow.actor.company_id)
    ).first()
    if category is None:
        errors.add(["category_id"], "category_not_found", "The category does not exist")
        return None, None
    if not category.is_active:
        errors.add(["category_id"], "category_inactive", "The category is inactive")
    sub: Subcategory | None = None
    if subcategory_id is not None:
        sub = uow.session.scalars(
            select(SC).where(SC.id == subcategory_id, SC.company_id == uow.actor.company_id)
        ).first()
        if sub is None or sub.category_id != category.id:
            errors.add(["subcategory_id"], "subcategory_not_in_category", "The subcategory does not belong to the category")
            sub = None
        elif not sub.is_active:
            errors.add(["subcategory_id"], "subcategory_inactive", "The subcategory is inactive")
    return category, sub


def _set_decor(product: Product, fields: Mapping[str, Any], warnings: list[str], changed: set[str]) -> None:
    if "decor_no" in fields:
        result = normalise_identifier(fields["decor_no"], float_artefact_rule=True)
        if (product.decor_no, product.decor_no_source) != (result.value, result.source):
            changed.add("decor_no")
        product.decor_no, product.decor_no_source = result.value, result.source
        warnings.extend(f"decor_no:{w}" for w in result.warnings)
    if "decor_primary" in fields:
        result = normalise_identifier(fields["decor_primary"], float_artefact_rule=True)
        if product.decor_primary != result.value:
            changed.add("decor_primary")
        product.decor_primary = result.value
        warnings.extend(f"decor_primary:{w}" for w in result.warnings)
    if "decor_options" in fields:
        options: list[str] = []
        for i, raw in enumerate(fields["decor_options"] or []):
            result = normalise_identifier(raw, float_artefact_rule=True)
            if result.value:
                options.append(result.value)
            warnings.extend(f"decor_options[{i}]:{w}" for w in result.warnings)
        value = options or None
        if product.decor_options != value:
            changed.add("decor_options")
        product.decor_options = value


def _dimension_row(
    uow: UnitOfWork, product_id: uuid.UUID, kind: DimensionKind, field_name: str, text: str
) -> ProductDimension | None:
    parsed = parse_dimension(text)
    if parsed is None:
        return None
    return ProductDimension(
        company_id=uow.actor.company_id,
        product_id=product_id,
        kind=kind.value,
        source_field=field_name,
        source_text=parsed.source_text[:200],
        length_mm=parsed.length_mm,
        width_mm=parsed.width_mm,
        height_mm=parsed.height_mm,
        diameter_mm=parsed.diameter_mm,
        source_unit=parsed.source_unit,
        unit_inferred=parsed.unit_inferred,
        parse_status=parsed.status,
        parse_warnings=list(parsed.warnings),
    )


def _replace_dimensions(
    uow: UnitOfWork, product_id: uuid.UUID, rows: Mapping[DimensionKind, tuple[str, str | None]]
) -> bool:
    """Replace the dimension rows of the given kinds; returns True when anything changed."""
    kinds = [k.value for k in rows]
    existing = {
        d.kind: d
        for d in uow.session.scalars(select(D).where(D.product_id == product_id, D.kind.in_(kinds)))
    }
    changed = False
    for kind, (field_name, text) in rows.items():
        current = existing.get(kind.value)
        wanted = (text or "").strip() or None
        if current is not None and wanted is not None and current.source_text == wanted[:200]:
            continue
        if current is None and wanted is None:
            continue
        changed = True
        if current is not None:
            uow.session.delete(current)
            uow.flush()
        if wanted is not None:
            row = _dimension_row(uow, product_id, kind, field_name, wanted)
            if row is not None:
                uow.add(row)
    if changed:
        uow.flush()
    return changed


_SizeTuple = tuple[Any, Any, Any, Any, Any]  # length, width, height, diameter, basis
_NO_SIZE: _SizeTuple = (None, None, None, None, None)


def _choose_size(
    master: tuple[Any, Any, Any, Any] | None,
    spec_size: tuple[Any, Any, Any, Any] | None,
    spec_length_width: tuple[Any, Any, Any] | None,
) -> _SizeTuple:
    """Effective size: parsed master size, else parsed spec size, else spec length x width (design §4.2)."""
    if master is not None:
        return (*master, SizeBasis.MASTER_SIZE.value)
    if spec_size is not None:
        return (*spec_size, SizeBasis.SPEC_SIZE.value)
    if spec_length_width is not None and spec_length_width[0] is not None and spec_length_width[1] is not None:
        return (*spec_length_width, None, SizeBasis.SPEC_LENGTH_WIDTH.value)
    return _NO_SIZE


def _parsed_size(text: str | None) -> tuple[Any, Any, Any, Any] | None:
    parsed = parse_dimension(text) if text else None
    if parsed is None or parsed.status != ParseStatus.PARSED.value:
        return None
    return (parsed.length_mm, parsed.width_mm, parsed.height_mm, parsed.diameter_mm)


def _set_size(product: Product, size: _SizeTuple) -> None:
    (
        product.size_length_mm,
        product.size_width_mm,
        product.size_height_mm,
        product.size_diameter_mm,
        product.size_basis,
    ) = size


def _recompute_effective_size(uow: UnitOfWork, product: Product) -> None:
    dims = {d.kind: d for d in uow.session.scalars(select(D).where(D.product_id == product.id))}

    def parsed(kind: DimensionKind) -> tuple[Any, Any, Any, Any] | None:
        d = dims.get(kind.value)
        if d is None or d.parse_status != ParseStatus.PARSED.value:
            return None
        return (d.length_mm, d.width_mm, d.height_mm, d.diameter_mm)

    spec = uow.session.get(S, product.id)
    spec_lw = (spec.length_mm, spec.width_mm, spec.height_mm) if spec is not None else None
    _set_size(product, _choose_size(parsed(DimensionKind.MASTER_SIZE), parsed(DimensionKind.SPEC_SIZE), spec_lw))


def _search_text(product: Product, category_name: str | None, subcategory_name: str | None) -> str:
    parts = [
        product.product_key, product.display_sku, product.product_name, product.decor_no, product.decor_name,
        product.decor_primary, product.finish, product.variant_group, product.product_type, product.brand,
        category_name, subcategory_name,
    ]
    return normalize_search_text(" ".join(p for p in parts if p))


def _recompute_search_text(uow: UnitOfWork, product: Product) -> None:
    cat = uow.session.get(C, product.category_id)
    sub = uow.session.get(SC, product.subcategory_id) if product.subcategory_id else None
    product.search_text = _search_text(product, cat.name if cat else None, sub.name if sub else None)


def _spec_length_width(spec_in: SpecificationIn | None) -> tuple[Any, Any, Any] | None:
    """Spec length/width/height in canonical mm, for the effective size of a new product (invalid -> None;
    the specification section reports the error itself)."""
    if spec_in is None:
        return None
    out: list[Any] = []
    for raw in (spec_in.length_mm, spec_in.width_mm, spec_in.height_mm):
        try:
            out.append(parse_length(raw)[0] if raw and raw.strip() else None)
        except (TypeError, ValueError):
            out.append(None)
    return (out[0], out[1], out[2])


def _apply_specification(
    uow: UnitOfWork, product: Product, spec_in: SpecificationIn, errors: _Errors, warnings: list[str]
) -> bool:
    """Replace the specification section; returns True when it changed."""
    spec = uow.session.get(S, product.id)
    created = spec is None
    if spec is None:
        spec = ProductSpecification(product_id=product.id, company_id=uow.actor.company_id)
    before = {c.key: getattr(spec, c.key) for c in S.__table__.columns} if not created else {}
    data = spec_in.model_dump()
    for name in ("length_mm", "width_mm", "height_mm"):
        raw = _blank_to_none(data[name])
        if raw is None:
            setattr(spec, name, None)
            setattr(spec, f"{name}_source", None)
            continue
        try:
            mm, source = parse_length(raw)
        except ValueError as exc:
            errors.add(["specification", name], str(exc).lower(), f"{name} must be a positive length")
            continue
        setattr(spec, name, mm)
        setattr(spec, f"{name}_source", source[:80])
    raw_thickness = _blank_to_none(data["thickness_mm"])
    if raw_thickness is None:
        spec.thickness_mm, spec.thickness_mm_source = None, None
    else:
        try:
            spec.thickness_mm = normalise_thickness(raw_thickness)
            spec.thickness_mm_source = str(raw_thickness)[:80]
        except ValueError as exc:
            errors.add(["specification", "thickness_mm"], str(exc).lower(), "thickness_mm must be a positive length")
    for name in _SPEC_TEXT_FIELDS:
        setattr(spec, name, _blank_to_none(data[name]))
    for name in _SPEC_INT_FIELDS:
        setattr(spec, name, data[name])
    spec.spec_finish = _blank_to_none(data["finish"])
    spec.spec_type = _blank_to_none(data["type"])
    spec.source_extra = data["source_extra"]
    if created:
        uow.add(spec)
    uow.flush()
    dims_changed = _replace_dimensions(
        uow,
        product.id,
        {kind: (field_name, data[field_name]) for field_name, kind in SPEC_DIMENSION_FIELDS.items()},
    )
    for field_name in SPEC_DIMENSION_FIELDS:
        parsed = parse_dimension(data[field_name]) if data[field_name] else None
        if parsed is not None and parsed.status != ParseStatus.PARSED.value:
            warnings.append(f"specification.{field_name}:{parsed.status}:{','.join(parsed.warnings)}")
    after = {c.key: getattr(spec, c.key) for c in S.__table__.columns}
    return created or dims_changed or any(before.get(k) != v for k, v in after.items() if k not in ("updated_at",))


def _apply_packaging(
    uow: UnitOfWork, product: Product, pack_in: PackagingIn, errors: _Errors, warnings: list[str]
) -> bool:
    # attribute values keep Decimals (model_dump would serialise DecimalStr to strings)
    raw = {name: getattr(pack_in, name) for name in PackagingIn.model_fields}
    resolution = resolve_packaging_aliases(raw)
    for conflict in resolution.conflicts:
        shown = ", ".join(f"{k}={v}" for k, v in sorted(conflict.values.items()))
        errors.add(["packaging", conflict.field], ALIAS_CONFLICT.lower(), f"Alias values disagree: {shown}")
    for field_name, code in resolution.errors:
        errors.add(["packaging", field_name], code.lower(), f"{field_name} is not valid ({code})")
    pack = uow.session.get(K, product.id)
    created = pack is None
    if pack is None:
        pack = ProductPackaging(product_id=product.id, company_id=uow.actor.company_id)
    before = {c.key: getattr(pack, c.key) for c in K.__table__.columns} if not created else {}
    pack.carton_qty = resolution.values.get("carton_qty")
    pack.inner_qty = resolution.values.get("inner_qty")
    pack.unit_weight_g = resolution.values.get("unit_weight_g")
    pack.packing_type = resolution.values.get("packing_type")
    for name in _PACKAGING_DECIMALS:
        value = raw[name]
        if value is None:
            setattr(pack, name, None)
            continue
        if value <= 0:
            errors.add(["packaging", name], "not_positive", f"{name} must be positive")
            continue
        if value >= _DECIMAL_LIMIT[name]:
            errors.add(["packaging", name], "too_large", f"{name} must be below {_DECIMAL_LIMIT[name]}")
            continue
        stored = value.quantize(_DECIMAL_SCALE[name], rounding=ROUND_HALF_UP)
        if stored <= 0:  # positive, but below the column scale: it would be stored as zero
            errors.add(["packaging", name], "below_precision", f"{name} must be at least {_DECIMAL_SCALE[name]}")
            continue
        setattr(pack, name, stored)
    for name in _PACKAGING_TEXT:
        setattr(pack, name, _blank_to_none(raw[name]))
    pack.alias_provenance = resolution.provenance or None
    pack.source_extra = raw["source_extra"]
    warnings.extend(
        f"packaging:{w}"
        for w in packaging_cross_checks(
            carton_qty=pack.carton_qty,
            inner_qty=pack.inner_qty,
            carton_length_cm=pack.carton_length_cm,
            carton_width_cm=pack.carton_width_cm,
            carton_height_cm=pack.carton_height_cm,
            cbm=pack.cbm,
            net_weight_kg=pack.net_weight_kg,
            gross_weight_kg=pack.gross_weight_kg,
        )
    )
    if created:
        uow.add(pack)
    after = {c.key: getattr(pack, c.key) for c in K.__table__.columns}
    return created or any(before.get(k) != v for k, v in after.items() if k not in ("updated_at",))


def create_product(uow: UnitOfWork, data: ProductCreate) -> ProductWriteResult:
    """Create a product with its specification, packaging and parsed dimensions in one transaction."""
    uow.actor.require("catalogue.product.create")
    errors = _Errors()
    warnings: list[str] = []
    exists_already = uow.session.scalar(
        select(exists().where(P.company_id == uow.actor.company_id, P.product_key == data.product_key))
    )
    if exists_already:
        raise Conflict("A product with this product_key already exists", code="product_key_exists")
    category, subcategory = _taxonomy_check(uow, data.category_id, data.subcategory_id, errors)
    fields = data.model_dump(exclude_unset=False)
    product = Product(
        id=new_id(),
        company_id=uow.actor.company_id,
        product_key=data.product_key,
        display_sku=(data.display_sku or data.product_key),
        product_name=(data.product_name or data.product_key),
        category_id=data.category_id,
        subcategory_id=data.subcategory_id,
        status=(data.status or ProductStatus.ACTIVE).value,
        origin=data.origin.value,
        origin_ref=data.origin_ref,
        source_extra=data.source_extra,
        search_text="",
    )
    for name in _MASTER_TEXT_FIELDS:
        if name in ("display_sku", "product_name"):
            continue
        setattr(product, name, _blank_to_none(fields[name]))
    for name in _STOCK_FIELDS:
        setattr(product, name, fields[name])
    product.item_class = fields.get("item_class") or "finished"
    _set_decor(product, fields, warnings, set())
    errors.raise_if_any()
    # derived columns are set before the single INSERT, so a new product starts at version 1
    spec_size = data.specification.size_mm if data.specification is not None else None
    _set_size(
        product,
        _choose_size(_parsed_size(data.size_mm), _parsed_size(spec_size), _spec_length_width(data.specification)),
    )
    product.search_text = _search_text(
        product, category.name if category else None, subcategory.name if subcategory else None
    )
    uow.add(product)
    uow.flush()
    if data.size_mm:
        _replace_dimensions(uow, product.id, {DimensionKind.MASTER_SIZE: ("size_mm", data.size_mm)})
        parsed = parse_dimension(data.size_mm)
        if parsed is not None and parsed.status != ParseStatus.PARSED.value:
            warnings.append(f"size_mm:{parsed.status}:{','.join(parsed.warnings)}")
    if data.specification is not None:
        _apply_specification(uow, product, data.specification, errors, warnings)
    if data.packaging is not None:
        _apply_packaging(uow, product, data.packaging, errors, warnings)
    errors.raise_if_any()
    uow.flush()
    uow.emit(
        ev.PRODUCT_CREATED,
        aggregate_id=product.id,
        aggregate_version=product.version,
        payload=ev.payload(
            ev.ProductCreatedPayload(
                product_id=product.id,
                product_key=product.product_key,
                origin="seed" if data.origin.value == "seed" else None,
            )
        ),
    )
    uow.audit(
        "catalogue.product.created",
        resource_type="catalogue.product",
        resource_id=product.id,
        resource_label=f"{product.product_key} · {product.product_name}",
    )
    return ProductWriteResult(product=_detail(uow, product), warnings=warnings)


def update_product(uow: UnitOfWork, product_id: uuid.UUID, data: ProductUpdate) -> ProductWriteResult:
    """Update dirty master fields and/or replace the specification or packaging section (optimistic version)."""
    product = uow.repo(Product).get(product_id, "update", for_update=True)
    uow.expect_version(product, data.expected_version)
    errors = _Errors()
    warnings: list[str] = []
    fields = data.model_dump(exclude_unset=True, exclude={"expected_version", "specification", "packaging"})
    changed: set[str] = set()
    groups: set[str] = set()
    # child sections first: their flushes must not carry a dirty product row (one version bump per update)
    if "size_mm" in fields:
        if _replace_dimensions(uow, product.id, {DimensionKind.MASTER_SIZE: ("size_mm", fields["size_mm"])}):
            changed.add("size_mm")
            groups.add(ev.GROUP_DIMENSIONS)
    if data.specification is not None and _apply_specification(uow, product, data.specification, errors, warnings):
        changed.add("specification")
        groups.update({ev.GROUP_SPECIFICATION, ev.GROUP_DIMENSIONS})
    if data.packaging is not None and _apply_packaging(uow, product, data.packaging, errors, warnings):
        changed.add("packaging")
        groups.add(ev.GROUP_PACKAGING)
    if "category_id" in fields or "subcategory_id" in fields:
        cat_id = fields.get("category_id") or product.category_id
        sub_id = fields["subcategory_id"] if "subcategory_id" in fields else product.subcategory_id
        if cat_id != product.category_id and "subcategory_id" not in fields:
            sub_id = None
        if (cat_id, sub_id) != (product.category_id, product.subcategory_id):
            _taxonomy_check(uow, cat_id, sub_id, errors)
            product.category_id, product.subcategory_id = cat_id, sub_id
            changed.update({"category_id", "subcategory_id"})
            groups.add(ev.GROUP_TAXONOMY)
    for name in _MASTER_TEXT_FIELDS:
        if name not in fields:
            continue
        value = _blank_to_none(fields[name])
        if name in ("display_sku", "product_name") and value is None:
            errors.add([name], "required", f"{name} cannot be blank")
            continue
        if getattr(product, name) != value:
            setattr(product, name, value)
            changed.add(name)
            groups.add(ev.GROUP_TAXONOMY if name.endswith("_source") and "category" in name else ev.GROUP_MASTER)
    if fields.get("item_class") and product.item_class != fields["item_class"]:
        product.item_class = fields["item_class"]
        changed.add("item_class")
        groups.add(ev.GROUP_MASTER)
    if "status" in fields and fields["status"] is not None and product.status != fields["status"].value:
        product.status = fields["status"].value
        changed.add("status")
        groups.add(ev.GROUP_MASTER)
    if "source_extra" in fields and product.source_extra != fields["source_extra"]:
        product.source_extra = fields["source_extra"]
        changed.add("source_extra")
        groups.add(ev.GROUP_MASTER)
    for name in _STOCK_FIELDS:
        if name in fields and getattr(product, name) != fields[name]:
            setattr(product, name, fields[name])
            changed.add(name)
            groups.add(ev.GROUP_STOCK_ATTRIBUTES)
    decor_changed: set[str] = set()
    _set_decor(product, fields, warnings, decor_changed)
    if decor_changed:
        changed |= decor_changed
        groups.add(ev.GROUP_MASTER)
    errors.raise_if_any()
    if not changed:
        return ProductWriteResult(product=_detail(uow, product), warnings=warnings)
    # dimension and specification rows are already flushed (autoflush is off), so the derived columns, the
    # master fields and updated_at reach the database in one UPDATE: exactly one version bump
    _recompute_effective_size(uow, product)
    _recompute_search_text(uow, product)
    product.updated_at = uow.now()  # bumps the optimistic version even when only a child section changed
    uow.flush()
    uow.emit(
        ev.PRODUCT_UPDATED,
        aggregate_id=product.id,
        aggregate_version=product.version,
        payload=ev.payload(
            ev.ProductUpdatedPayload(
                product_id=product.id,
                product_key=product.product_key,
                changed_groups=sorted(groups),
                changed_fields=sorted(changed),
            )
        ),
    )
    uow.audit(
        "catalogue.product.updated",
        resource_type="catalogue.product",
        resource_id=product.id,
        resource_label=f"{product.product_key} · {product.product_name}",
        details={"changed_fields": sorted(changed)},
    )
    return ProductWriteResult(product=_detail(uow, product), warnings=warnings)


# =====================================================================================================
# list, facets, stats, completeness
# =====================================================================================================
_P2 = aliased(Product)

#: one SQL definition per completeness rule; True means the product FAILS the rule
M = ProductMedia
_LIVE_IMAGE = and_(M.product_id == P.id, M.deleted_at.is_(None), M.media_type == "image", M.ingest_status == "stored")
STATIC_RULES: dict[CompletenessRule, tuple[str, str, ColumnElement[bool]]] = {
    CompletenessRule.NO_DECOR: ("warning", "No decor number", and_(P.decor_no.is_(None), P.decor_primary.is_(None))),
    CompletenessRule.NO_SPECIFICATION: ("warning", "No specification", S.product_id.is_(None)),
    CompletenessRule.NO_THICKNESS: ("warning", "No thickness", S.thickness_mm.is_(None)),
    CompletenessRule.NO_SIZE: (
        "warning", "No parsed size", and_(P.size_length_mm.is_(None), P.size_diameter_mm.is_(None))
    ),
    CompletenessRule.UNPARSED_DIMENSIONS: (
        "warning",
        "Dimension text that could not be parsed",
        exists().where(D.product_id == P.id, D.parse_status != ParseStatus.PARSED.value),
    ),
    CompletenessRule.NO_PACKAGING: ("warning", "No packaging", K.product_id.is_(None)),
    CompletenessRule.NO_CARTON_QTY: ("warning", "No carton quantity", K.carton_qty.is_(None)),
    CompletenessRule.NO_UNIT_WEIGHT: ("warning", "No unit weight", K.unit_weight_g.is_(None)),
    CompletenessRule.CATEGORY_INACTIVE: (
        "warning", "Category or subcategory is inactive", or_(C.is_active.is_(False), SC.is_active.is_(False))
    ),
    CompletenessRule.NO_HSN_SAC: ("info", "No HSN/SAC code", P.hsn_sac.is_(None)),
    CompletenessRule.SHARED_DISPLAY_SKU: (
        "info",
        "Display SKU shared with another product",
        exists().where(
            _P2.company_id == P.company_id,
            _P2.display_sku == P.display_sku,
            _P2.id != P.id,
            _P2.archived_at.is_(None),
        ),
    ),
    CompletenessRule.NO_IMAGE: ("warning", "No stored image", ~exists().where(_LIVE_IMAGE)),
    CompletenessRule.NO_PRIMARY_IMAGE: (
        "warning", "No primary image", ~exists().where(_LIVE_IMAGE, M.is_primary.is_(True))
    ),
    CompletenessRule.MEDIA_INGEST_FAILED: (
        "info",
        "Media whose import could not be stored",
        exists().where(M.product_id == P.id, M.deleted_at.is_(None), M.ingest_status == "failed"),
    ),
}


def rules(uow: UnitOfWork) -> dict[CompletenessRule, tuple[str, str, ColumnElement[bool]]]:
    """Every rule this actor can evaluate (``no_active_price`` needs a price provider and ``pricing.price.read``)."""
    out = dict(STATIC_RULES)
    priced = _priced_ids(uow)
    if priced is not None:
        out[CompletenessRule.NO_ACTIVE_PRICE] = ("warning", "No current active price", P.id.not_in(priced))
    return out


def _not_evaluated(uow: UnitOfWork) -> list[NotEvaluated]:
    if _priced_ids(uow) is None:
        return [NotEvaluated(code="no_active_price", reason="needs pricing.price.read")]
    return []



def _joined(stmt: Select[Any]) -> Select[Any]:
    return (
        stmt.select_from(P)
        .outerjoin(S, S.product_id == P.id)
        .outerjoin(K, K.product_id == P.id)
        .join(C, C.id == P.category_id)
        .outerjoin(SC, SC.id == P.subcategory_id)
    )


@dataclass
class _Conditions:
    base: list[ColumnElement[bool]]
    by_filter: dict[str, ColumnElement[bool]]

    def all(self, *, exclude: str | None = None) -> list[ColumnElement[bool]]:
        return [*self.base, *(c for k, c in self.by_filter.items() if k != exclude)]


def _parse_size_filter(size: str) -> tuple[Decimal, Decimal, Decimal | None]:
    parsed = parse_dimension(size)
    if parsed is None or parsed.status != ParseStatus.PARSED.value or parsed.width_mm is None:
        raise ValidationFailed(
            "size must look like 450x300 (mm unless a unit is given)",
            errors=[{"loc": ["query", "size"], "msg": "not a length x width size", "code": "invalid_size"}],
        )
    assert parsed.length_mm is not None
    return parsed.length_mm, parsed.width_mm, parsed.height_mm


def _conditions(uow: UnitOfWork, f: ProductFilters) -> _Conditions:
    repo = uow.repo(Product)
    base: list[ColumnElement[bool]] = [repo.clause("read")]
    if not f.include_archived:
        base.append(P.archived_at.is_(None))
    by: dict[str, ColumnElement[bool]] = {}
    if f.q:
        parts = tokens(f.q)
        if parts:
            by["q"] = and_(*[P.search_text.ilike(contains_pattern(t), escape=LIKE_ESCAPE) for t in parts])
    if f.category_id:
        by["category"] = P.category_id == f.category_id
    if f.subcategory_id:
        by["subcategory"] = P.subcategory_id == f.subcategory_id
    if f.family:
        by["family"] = func.lower(P.variant_group) == f.family.strip().lower()
    if f.design:
        by["design"] = P.design_no == f.design.strip().upper()
    if f.item_class:
        by["item_class"] = P.item_class == f.item_class
    if f.size:
        length, width, height = _parse_size_filter(f.size)
        orient = or_(
            and_(P.size_length_mm == length, P.size_width_mm == width),
            and_(P.size_length_mm == width, P.size_width_mm == length),
        )
        by["size"] = and_(orient, P.size_height_mm == height) if height is not None else orient
    if f.thickness:
        try:
            thickness = normalise_thickness(f.thickness)
        except (ValueError, TypeError) as exc:
            raise ValidationFailed(
                "thickness must be a positive number of millimetres",
                errors=[{"loc": ["query", "thickness"], "msg": "not a thickness", "code": "invalid_thickness"}],
            ) from exc
        # a thickness filter requires a specification row (products without specs never pass; bug §10.1 #6)
        by["thickness"] = S.thickness_mm == thickness if thickness is not None else true()
    if f.decor:
        decor = normalise_identifier(f.decor, float_artefact_rule=True).value
        by["decor"] = P.decor_no == decor
    if f.finish:
        by["finish"] = func.lower(P.finish) == f.finish.strip().lower()
    if f.status:
        by["status"] = P.status.in_([s.value for s in f.status])
    if f.brand:
        by["brand"] = func.lower(P.brand) == f.brand.strip().lower()
    if f.issue:
        rule = rules(uow).get(f.issue)
        if rule is None:
            raise ValidationFailed(
                "This completeness rule is not available to you",
                errors=[{"loc": ["query", "issue"], "msg": "rule not evaluated", "code": "rule_not_evaluated"}],
            )
        by["issue"] = rule[2]
    if f.has_image is not None:
        has = exists().where(_LIVE_IMAGE)
        by["has_image"] = has if f.has_image else ~has
    if f.has_price is not None:
        priced = _priced_ids(uow)
        if priced is None:
            raise ValidationFailed(
                "Filtering by price needs pricing.price.read",
                errors=[{"loc": ["query", "has_price"], "msg": "not available", "code": "permission_denied"}],
            )
        by["has_price"] = P.id.in_(priced) if f.has_price else P.id.not_in(priced)
    return _Conditions(base, by)


def list_conditions(uow: UnitOfWork, filters: ProductFilters) -> list[ColumnElement[bool]]:
    """The list's WHERE clause (scope, archive state and every filter) for exports that share it."""
    return _conditions(uow, filters).all()


def _order(f: ProductFilters, sort: ProductSort) -> list[Any]:
    if sort == "relevance" and f.q and f.q.strip():
        term = f.q.strip().lower()
        rank = case(
            (func.lower(P.product_key) == term, 0),
            (func.lower(P.display_sku) == term, 1),
            (func.lower(P.product_name).like(escape_like(term) + "%", escape=LIKE_ESCAPE), 2),
            else_=3,
        )
        return [rank, P.product_key, P.id]
    if sort == "product_name":
        return [func.lower(P.product_name), P.product_key, P.id]
    if sort == "-updated_at":
        return [P.updated_at.desc(), P.id.desc()]
    return [P.product_key, P.id]


def _taxonomy_ref(id_: uuid.UUID | None, name: str | None, active: bool | None) -> TaxonomyRef | None:
    if id_ is None or name is None:
        return None
    return TaxonomyRef(id=id_, name=name, is_active=bool(active))


def _summary_row(
    row: Any,
    columns: dict[uuid.UUID, list[ProductPriceColumn]] | None = None,
    redacted: Sequence[str] = (),
) -> ProductSummary:
    product: Product = row[0]
    return ProductSummary(
        id=product.id,
        product_key=product.product_key,
        display_sku=product.display_sku,
        product_name=product.product_name,
        brand=product.brand,
        category=TaxonomyRef(id=product.category_id, name=row.category_name, is_active=row.category_active),
        subcategory=_taxonomy_ref(product.subcategory_id, row.subcategory_name, row.subcategory_active),
        product_type=product.product_type,
        variant_group=product.variant_group,
        design_no=product.design_no,
        item_class=product.item_class,
        unit_of_sale=product.unit_of_sale,
        decor_no=product.decor_no,
        decor_name=product.decor_name,
        finish=product.finish,
        shape=product.shape,
        status=ProductStatus(product.status),
        thickness_mm=row.thickness_mm,
        size=_size(product),
        carton_qty=row.carton_qty,
        archived=product.archived_at is not None,
        updated_at=product.updated_at,
        path=product_path(product.id),
        prices=columns.get(product.id) if columns is not None else None,
        redacted_fields=list(redacted),
    )


def _size(product: Product) -> ProductSize:
    return ProductSize(
        length_mm=product.size_length_mm,
        width_mm=product.size_width_mm,
        height_mm=product.size_height_mm,
        diameter_mm=product.size_diameter_mm,
        basis=SizeBasis(product.size_basis) if product.size_basis else None,
    )


def _summary_select() -> Select[Any]:
    return select(
        P,
        S.thickness_mm.label("thickness_mm"),
        K.carton_qty.label("carton_qty"),
        C.name.label("category_name"),
        C.is_active.label("category_active"),
        SC.name.label("subcategory_name"),
        SC.is_active.label("subcategory_active"),
    )


@query(READ)
def list_products(
    uow: UnitOfWork,
    filters: ProductFilters,
    *,
    sort: ProductSort = "product_key",
    limit: int = 50,
    offset: int = 0,
    price_currency: str = "EUR",
    price_type: str | None = None,
) -> Page[ProductSummary]:
    """Filters apply before paging. Rows carry the ``price_currency`` price and order-value recommendation from one
    batch read for the page (``pricing.price.read``; otherwise ``prices`` is absent and listed as redacted)."""
    if price_currency not in CURRENCY_EXPONENT:
        raise ValidationFailed(
            "price_currency is not an enabled currency",
            errors=[{"loc": ["query", "price_currency"], "msg": "not an enabled currency", "code": "invalid_currency"}],
        )
    conds = _conditions(uow, filters)
    where = conds.all()
    total = uow.session.scalar(_joined(select(func.count(P.id))).where(*where)) or 0
    limit = max(1, min(limit, MAX_LIMIT))
    offset = max(0, offset)
    if sort == "relevance" and not (filters.q and filters.q.strip()):
        sort = "product_key"
    rows = uow.session.execute(
        _joined(_summary_select()).where(*where).order_by(*_order(filters, sort)).limit(limit).offset(offset)
    ).all()
    columns, redacted = _price_columns(uow, [r[0].id for r in rows], [price_currency], price_type)
    thumbs = primary_images(uow, [r[0].id for r in rows])
    items = [_summary_row(r, columns, redacted) for r in rows]
    for item in items:
        item.primary_image = thumbs.get(item.id)
    return Page[ProductSummary](items=items, total=int(total), limit=limit, offset=offset)


def primary_images(uow: UnitOfWork, product_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, MediaThumb]:
    """The live primary image of each product, in one query (list thumbnails, LM-11)."""
    if not product_ids:
        return {}
    rows = uow.session.execute(
        select(ProductMedia.product_id, ProductMedia.id, ProductMedia.file_id, ProductMedia.alt_text).where(
            ProductMedia.product_id.in_(list(product_ids)),
            ProductMedia.is_primary.is_(True),
            ProductMedia.deleted_at.is_(None),
            ProductMedia.file_id.is_not(None),
        )
    ).all()
    return {
        pid: MediaThumb(media_id=mid, file_id=fid, url=f"/api/v1/files/{fid}/content", alt_text=alt)
        for pid, mid, fid, alt in rows
    }


def _facet(
    uow: UnitOfWork, conds: _Conditions, key: str, columns: Sequence[Any], not_null: ColumnElement[bool] | None = None
) -> list[Any]:
    stmt = _joined(select(*columns, func.count(P.id).label("n"))).where(*conds.all(exclude=key))
    if not_null is not None:
        stmt = stmt.where(not_null)
    return list(uow.session.execute(stmt.group_by(*columns)).all())


@query(READ)
def product_facets(uow: UnitOfWork, filters: ProductFilters) -> ProductFacets:
    """Counts per filter dimension, each computed with every other filter applied (exclude-self facets)."""
    conds = _conditions(uow, filters)
    total = uow.session.scalar(_joined(select(func.count(P.id))).where(*conds.all())) or 0

    def values(rows: Iterable[Any], fmt: Any) -> list[FacetValue]:
        out = [fmt(r) for r in rows]
        return sorted(out, key=lambda v: (-v.count, v.label.casefold(), v.value))

    categories = values(
        _facet(uow, conds, "category", [C.id, C.name]),
        lambda r: FacetValue(value=str(r[0]), label=r[1], count=r.n),
    )
    subcategories = values(
        _facet(uow, conds, "subcategory", [SC.id, SC.name], SC.id.is_not(None)),
        lambda r: FacetValue(value=str(r[0]), label=r[1], count=r.n),
    )
    families = values(
        _facet(uow, conds, "family", [P.variant_group], P.variant_group.is_not(None)),
        lambda r: FacetValue(value=r[0], label=r[0], count=r.n),
    )
    # orientation-normalised (smaller x larger), like the size filter that matches either orientation, so a facet
    # count always equals the total its value filters to
    size_lo = func.least(P.size_length_mm, P.size_width_mm).label("size_lo")
    size_hi = func.greatest(P.size_length_mm, P.size_width_mm).label("size_hi")
    sizes = values(
        _facet(uow, conds, "size", [size_lo, size_hi], and_(P.size_length_mm.is_not(None), P.size_width_mm.is_not(None))),
        lambda r: FacetValue(
            value=f"{plain_decimal(r[0])}x{plain_decimal(r[1])}",
            label=f"{plain_decimal(r[0])} × {plain_decimal(r[1])} mm",
            count=r.n,
        ),
    )
    thicknesses = sorted(
        (
            FacetValue(value=plain_decimal(r[0]), label=f"{plain_decimal(r[0])} mm", count=r.n)
            for r in _facet(uow, conds, "thickness", [S.thickness_mm], S.thickness_mm.is_not(None))
        ),
        key=lambda v: Decimal(v.value),
    )
    decors = values(
        _facet(uow, conds, "decor", [P.decor_no, P.decor_name], P.decor_no.is_not(None)),
        lambda r: FacetValue(value=r[0], label=f"{r[0]} {r[1]}" if r[1] else r[0], count=r.n),
    )
    finishes = values(
        _facet(uow, conds, "finish", [P.finish], P.finish.is_not(None)),
        lambda r: FacetValue(value=r[0], label=r[0], count=r.n),
    )
    statuses = values(
        _facet(uow, conds, "status", [P.status]),
        lambda r: FacetValue(value=r[0], label=r[0].replace("_", " ").capitalize(), count=r.n),
    )
    brands = values(
        _facet(uow, conds, "brand", [P.brand], P.brand.is_not(None)),
        lambda r: FacetValue(value=r[0], label=r[0], count=r.n),
    )
    return ProductFacets(
        total=int(total),
        categories=categories,
        subcategories=subcategories,
        families=families,
        sizes=sizes,
        thicknesses=thicknesses,
        decors=decors,
        finishes=finishes,
        statuses=statuses,
        brands=brands,
    )


@query(READ)
def product_stats(uow: UnitOfWork, *, recent_limit: int = 10) -> ProductStats:
    from app.platform.identity.models import AppUser

    repo = uow.repo(Product)
    scope = repo.clause("read")
    live = and_(scope, P.archived_at.is_(None))
    by_status = {
        status: int(n)
        for status, n in uow.session.execute(select(P.status, func.count(P.id)).where(live).group_by(P.status)).all()
    }
    archived = uow.session.scalar(select(func.count(P.id)).where(scope, P.archived_at.is_not(None))) or 0
    now = uow.now()
    recent_count = uow.session.scalar(
        select(func.count(P.id)).where(live, P.updated_at >= now - timedelta(days=7))
    ) or 0
    by_category = [
        CategoryCount(category_id=cid, name=name, count=int(n))
        for cid, name, n in uow.session.execute(
            select(C.id, C.name, func.count(P.id))
            .select_from(P)
            .join(C, C.id == P.category_id)
            .where(live)
            .group_by(C.id, C.name)
            .order_by(C.display_order, C.name)
        ).all()
    ]
    recent_rows = uow.session.execute(
        select(P, AppUser.display_name)
        .outerjoin(AppUser, AppUser.id == P.updated_by)
        .where(live)
        .order_by(P.updated_at.desc(), P.id.desc())
        .limit(max(1, min(recent_limit, 50)))
    ).all()
    priced = _priced_ids(uow)
    without_price = (
        uow.session.scalar(select(func.count(P.id)).where(live, P.id.not_in(priced))) if priced is not None else None
    )
    return ProductStats(
        total=sum(by_status.values()),
        by_status={s.value: by_status.get(s.value, 0) for s in ProductStatus},
        archived=int(archived),
        updated_last_7_days=int(recent_count),
        without_active_price=int(without_price) if without_price is not None else None,
        by_category=by_category,
        recently_changed=[
            RecentProduct(
                id=p.id,
                product_key=p.product_key,
                product_name=p.product_name,
                updated_at=p.updated_at,
                updated_by_name=name,
                path=product_path(p.id),
            )
            for p, name in recent_rows
        ],
        as_of=now,
    )


@query(READ)
def completeness_summary(uow: UnitOfWork) -> CompletenessSummary:
    """Per-rule counts of distinct non-archived products, computed from the actual columns."""
    conds = _conditions(uow, ProductFilters())
    where = conds.all()
    total = uow.session.scalar(_joined(select(func.count(P.id))).where(*where)) or 0
    active = rules(uow)
    counts = uow.session.execute(
        _joined(select(*[func.count(P.id).filter(rule).label(code.value) for code, (_s, _l, rule) in active.items()])).where(
            *where
        )
    ).one()
    warning_rules = [rule for (sev, _l, rule) in active.values() if sev == "warning"]
    incomplete = uow.session.scalar(_joined(select(func.count(P.id))).where(*where, or_(*warning_rules))) or 0
    return CompletenessSummary(
        total_products=int(total),
        complete_products=int(total) - int(incomplete),
        rules=[
            CompletenessRuleCount(
                code=code,
                label=label,
                severity=severity,  # type: ignore[arg-type]
                count=int(getattr(counts, code.value)),
                filter_path=f"/products?issue={code.value}",
            )
            for code, (severity, label, _rule) in active.items()
        ],
        not_evaluated=_not_evaluated(uow),
    )


def _completeness_for(uow: UnitOfWork, product_id: uuid.UUID) -> CompletenessRead:
    active = rules(uow)
    row = uow.session.execute(
        _joined(select(*[rule.label(code.value) for code, (_s, _l, rule) in active.items()])).where(P.id == product_id)
    ).one()
    missing = [
        CompletenessIssue(code=code, severity=severity, label=label)  # type: ignore[arg-type]
        for code, (severity, label, _rule) in active.items()
        if getattr(row, code.value)
    ]
    evaluated = [code for code, (severity, _l, _r) in active.items() if severity == "warning"]
    failed = [m for m in missing if m.severity == "warning"]
    passed = len(evaluated) - len(failed)
    return CompletenessRead(
        score_pct=(passed * 100) // len(evaluated) if evaluated else 100,
        checks_evaluated=len(evaluated),
        checks_passed=passed,
        missing=missing,
        not_evaluated=_not_evaluated(uow),
    )


# =====================================================================================================
# detail
# =====================================================================================================
def _packaging_summary(pack: ProductPackaging) -> str | None:
    parts: list[str] = []
    if pack.unit_weight_g is not None:
        parts.append(f"{plain_decimal(pack.unit_weight_g)}g")
    if pack.carton_qty is not None:
        parts.append(f"{pack.carton_qty}/ctn")
    if pack.packing_type:
        parts.append(pack.packing_type)
    return " · ".join(parts) or None  # FG-PKG-11: "450g · 24/ctn · Poly bag"


def packaging_summaries(uow: UnitOfWork, product_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, str | None]:
    """The packaging summary of each product in one query (FG-QLN-12, DEBT-02); products without packaging are absent."""
    if not product_ids:
        return {}
    packs = uow.session.scalars(select(K).where(K.product_id.in_(list(product_ids)))).all()
    return {pack.product_id: _packaging_summary(pack) for pack in packs}


def _sections(uow: UnitOfWork, product: Product) -> list[SectionRead]:
    base = product_path(product.id)
    sections = [
        SectionRead(key="overview", label="Overview", path=base),
        SectionRead(key="specifications", label="Specifications", path=f"{base}/specifications"),
        SectionRead(key="packaging", label="Packaging", path=f"{base}/packaging"),
    ]
    # UI-40: the pricing tab (lists, breakdown, provenance) needs pricing.price_list.read (legacy view_costing);
    # resolved selling prices for pricing.price.read holders are in the overview (``prices``)
    if uow.actor.can(PRICE_LIST_READ):
        sections.append(SectionRead(key="pricing", label="Pricing", path=f"{base}/pricing"))
    sections.append(SectionRead(key="media", label="Media", path=f"{base}/media"))
    sections.append(SectionRead(key="history", label="History", path=f"{base}/history"))
    return sections


def _capabilities(uow: UnitOfWork, product: Product) -> dict[str, Capability]:
    """update/archive/restore from the product policy plus the archive state; media management needs
    ``catalogue.media.manage`` (own scope may still only delete its own uploads, checked per media item)."""
    decided = uow.repo(Product).capabilities(product, ["update", "archive"])
    archived = product.archived_at is not None
    update = Capability(**decided["update"])
    if update.allowed and archived:
        update = Capability(allowed=False, reason_code="product_archived")
    can_archive = Capability(**decided["archive"])
    archive = can_archive if not archived else Capability(allowed=False, reason_code="product_archived")
    restore = can_archive if archived else Capability(allowed=False, reason_code="product_not_archived")
    media = uow.actor.can("catalogue.media.manage")
    return {
        "update": update,
        "archive": archive,
        "restore": restore,
        "manage_media": Capability(
            allowed=media and not archived,
            reason_code=None if media and not archived else ("product_archived" if media else "permission_denied"),
        ),
    }


def _detail(uow: UnitOfWork, product: Product) -> ProductDetail:
    category = uow.session.get(C, product.category_id)
    sub = uow.session.get(SC, product.subcategory_id) if product.subcategory_id else None
    spec = uow.session.get(S, product.id)
    pack = uow.session.get(K, product.id)
    dims = list(uow.session.scalars(select(D).where(D.product_id == product.id).order_by(D.kind)))
    assert category is not None
    # overview prices (UI-39): every currency in which a real active standard list prices the product
    columns, redacted = _price_columns(uow, [product.id], sorted(CURRENCY_EXPONENT), None)
    overview_prices = (
        [c for c in columns.get(product.id, []) if c.status != "not_found"] if columns is not None else None
    )
    pack_read: PackagingRead | None = None
    if pack is not None:
        pack_read = PackagingRead(
            carton_qty=pack.carton_qty,
            inner_qty=pack.inner_qty,
            unit_weight_g=pack.unit_weight_g,
            packing_type=pack.packing_type,
            carton_length_cm=pack.carton_length_cm,
            carton_width_cm=pack.carton_width_cm,
            carton_height_cm=pack.carton_height_cm,
            net_weight_kg=pack.net_weight_kg,
            gross_weight_kg=pack.gross_weight_kg,
            cbm=pack.cbm,
            packaging_notes=pack.packaging_notes,
            fragile_notes=pack.fragile_notes,
            packaging_status=pack.packaging_status,
            notes=pack.notes,
            alias_provenance=pack.alias_provenance,
            source_extra=pack.source_extra,
            summary=_packaging_summary(pack),
            warnings=packaging_cross_checks(
                carton_qty=pack.carton_qty,
                inner_qty=pack.inner_qty,
                carton_length_cm=pack.carton_length_cm,
                carton_width_cm=pack.carton_width_cm,
                carton_height_cm=pack.carton_height_cm,
                cbm=pack.cbm,
                net_weight_kg=pack.net_weight_kg,
                gross_weight_kg=pack.gross_weight_kg,
            ),
        )
    spec_read: SpecificationRead | None = None
    if spec is not None:
        spec_read = SpecificationRead(
            length_mm=spec.length_mm,
            length_mm_source=spec.length_mm_source,
            width_mm=spec.width_mm,
            width_mm_source=spec.width_mm_source,
            height_mm=spec.height_mm,
            height_mm_source=spec.height_mm_source,
            thickness_mm=spec.thickness_mm,
            thickness_mm_source=spec.thickness_mm_source,
            thickness_text=spec.thickness_text,
            size_label=spec.size_label,
            finish=spec.spec_finish,
            material_type=spec.material_type,
            groove_count=spec.groove_count,
            bowl_count=spec.bowl_count,
            bowl_type=spec.bowl_type,
            top_sheet=spec.top_sheet,
            stand_material=spec.stand_material,
            type=spec.spec_type,
            no_of_boards=spec.no_of_boards,
            handle_type=spec.handle_type,
            special_features=spec.special_features,
            care_instructions=spec.care_instructions,
            usage_notes=spec.usage_notes,
            source_extra=spec.source_extra,
        )
    return ProductDetail(
        id=product.id,
        product_key=product.product_key,
        display_sku=product.display_sku,
        product_name=product.product_name,
        brand=product.brand,
        category=TaxonomyRef(id=category.id, name=category.name, is_active=category.is_active),
        subcategory=TaxonomyRef(id=sub.id, name=sub.name, is_active=sub.is_active) if sub else None,
        product_type=product.product_type,
        variant_group=product.variant_group,
        design_no=product.design_no,
        item_class=product.item_class,
        unit_of_sale=product.unit_of_sale,
        finish=product.finish,
        shape=product.shape,
        status=ProductStatus(product.status),
        description=product.description,
        internal_remarks=product.internal_remarks,
        decor=DecorRead(
            decor_no=product.decor_no,
            decor_no_source=product.decor_no_source,
            decor_name=product.decor_name,
            decor_primary=product.decor_primary,
            decor_options=list(product.decor_options or []),
            decor_options_text=product.decor_options_text,
        ),
        size=_size(product),
        stock_attributes=StockAttributesRead(
            hsn_sac=product.hsn_sac,
            stock_uom_code=product.stock_uom_code,
            is_stock_tracked=product.is_stock_tracked,
            track_lots=product.track_lots,
            qc_required=product.qc_required,
        ),
        provenance=ProvenanceRead(
            category_source=product.category_source,
            subcategory_source=product.subcategory_source,
            source_design_no=product.source_design_no,
            source_shape_no=product.source_shape_no,
            source_sheet=product.source_sheet,
            source_row=product.source_row,
            source_catalog_page=product.source_catalog_page,
            source_notes=product.source_notes,
            source_extra=product.source_extra,
            origin=product.origin,  # type: ignore[arg-type]
            origin_ref=product.origin_ref,
        ),
        specification=spec_read,
        packaging=pack_read,
        dimensions=[
            DimensionRead(
                kind=DimensionKind(d.kind),
                source_field=d.source_field,
                source_text=d.source_text,
                length_mm=d.length_mm,
                width_mm=d.width_mm,
                height_mm=d.height_mm,
                diameter_mm=d.diameter_mm,
                source_unit=d.source_unit,
                unit_inferred=d.unit_inferred,
                parse_status=ParseStatus(d.parse_status),
                parse_warnings=list(d.parse_warnings or []),
            )
            for d in dims
        ],
        completeness=_completeness_for(uow, product.id),
        sections=_sections(uow, product),
        version=product.version,
        created_at=product.created_at,
        updated_at=product.updated_at,
        archived_at=product.archived_at,
        path=product_path(product.id),
        capabilities=_capabilities(uow, product),
        primary_image=primary_images(uow, [product.id]).get(product.id),
        media_count=int(
            uow.session.scalar(
                select(func.count(ProductMedia.id)).where(
                    ProductMedia.product_id == product.id, ProductMedia.deleted_at.is_(None)
                )
            )
            or 0
        ),
        prices=overview_prices,
        redacted_fields=redacted,
    )


def product_detail(uow: UnitOfWork, product: Product) -> ProductDetail:
    return _detail(uow, product)


@query(READ)
def get_product(uow: UnitOfWork, product_id: uuid.UUID) -> ProductDetail:
    return _detail(uow, uow.repo(Product).get(product_id))


@query(READ)
def get_product_by_key(uow: UnitOfWork, product_key: str) -> ProductDetail:
    return _detail(uow, uow.repo(Product).get_by_key(product_key.strip()))


def find_product_id(uow: UnitOfWork, product_key: str) -> uuid.UUID | None:
    """The id of a visible product with this key (None when absent or not visible)."""
    return uow.session.scalar(
        select(P.id).where(uow.repo(Product).clause("read"), P.product_key == product_key.strip())
    )


def _candidate(product: Product, match: str) -> ProductCandidate:
    return ProductCandidate(
        product_id=product.id,
        product_key=product.product_key,
        display_sku=product.display_sku,
        product_name=product.product_name,
        unit_of_sale=product.unit_of_sale,
        decor_no=product.decor_no,
        status=ProductStatus(product.status),
        match=match,  # type: ignore[arg-type]
    )


@query(READ)
def resolve_product(uow: UnitOfWork, text: str, *, limit: int = 10) -> ProductResolution:
    """Resolve a typed or spoken product reference among live (non-archived) products.

    An exact ``product_key`` wins; an exact ``display_sku`` is unique only when one product carries it (the SKU is
    non-unique); otherwise every token must match (key, SKU, name, decor, finish, family, taxonomy). Several matches
    are ``ambiguous`` unless exactly one product name equals the query; the caller asks, it never picks.
    """
    q = " ".join(text.split())
    limit = max(1, min(limit, 25))
    live = and_(uow.repo(Product).clause("read"), P.archived_at.is_(None))
    if not q:
        return ProductResolution(status="not_found", query=q, candidates=[], total_matches=0)
    by_key = uow.session.scalars(select(P).where(live, func.lower(P.product_key) == q.lower())).first()
    if by_key is not None:
        return ProductResolution(status="unique", query=q, candidates=[_candidate(by_key, "product_key")], total_matches=1)
    by_sku = list(
        uow.session.scalars(select(P).where(live, func.lower(P.display_sku) == q.lower()).order_by(P.product_key).limit(limit))
    )
    if by_sku:
        return ProductResolution(
            status="unique" if len(by_sku) == 1 else "ambiguous",
            query=q,
            candidates=[_candidate(p, "display_sku") for p in by_sku],
            total_matches=len(by_sku),
        )
    parts = tokens(q)
    if not parts:
        return ProductResolution(status="not_found", query=q, candidates=[], total_matches=0)
    cond = and_(live, *[P.search_text.ilike(contains_pattern(t), escape=LIKE_ESCAPE) for t in parts])
    total = int(uow.session.scalar(select(func.count(P.id)).where(cond)) or 0)
    rows = list(uow.session.scalars(select(P).where(cond).order_by(P.product_key, P.id).limit(limit)))
    exact = [p for p in rows if name_key(p.product_name) == name_key(q)]
    if total == 0:
        return ProductResolution(status="not_found", query=q, candidates=[], total_matches=0)
    if total == 1 or len(exact) == 1:
        chosen = rows[0] if total == 1 else exact[0]
        match = "exact_name" if chosen in exact else "tokens"
        return ProductResolution(status="unique", query=q, candidates=[_candidate(chosen, match)], total_matches=total)
    return ProductResolution(
        status="ambiguous",
        query=q,
        candidates=[_candidate(p, "exact_name" if p in exact else "tokens") for p in rows],
        total_matches=total,
    )


# =====================================================================================================
# references for other modules (pricing, commercial, sales)
# =====================================================================================================
@dataclass(frozen=True)
class ProductRef:
    id: uuid.UUID
    product_key: str
    display_sku: str
    product_name: str
    unit_of_sale: str | None
    status: str
    archived: bool
    carton_qty: int | None
    thickness_mm: Decimal | None

    @property
    def label(self) -> str:
        return f"{self.product_key} · {self.product_name}"


def product_refs(uow: UnitOfWork, product_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, ProductRef]:
    """Visible products by id (requires ``catalogue.product.read``; invisible ids are simply absent)."""
    ids = list(set(product_ids))
    if not ids or not uow.actor.can(READ):
        return {}
    rows = uow.session.execute(
        select(P, K.carton_qty, S.thickness_mm)
        .select_from(P)
        .outerjoin(K, K.product_id == P.id)
        .outerjoin(S, S.product_id == P.id)
        .where(uow.repo(Product).clause("read"), P.id.in_(ids))
    ).all()
    return {
        p.id: ProductRef(
            id=p.id,
            product_key=p.product_key,
            display_sku=p.display_sku,
            product_name=p.product_name,
            unit_of_sale=p.unit_of_sale,
            status=p.status,
            archived=p.archived_at is not None,
            carton_qty=carton,
            thickness_mm=thickness,
        )
        for p, carton, thickness in rows
    }


def get_product_ref(
    uow: UnitOfWork, *, product_id: uuid.UUID | None = None, product_key: str | None = None
) -> ProductRef:
    """One visible product by id or key; 404 when absent or not visible, 403 without catalogue read."""
    uow.actor.require(READ)
    if product_id is None and product_key is not None:
        product_id = find_product_id(uow, product_key)
    ref = product_refs(uow, [product_id]).get(product_id) if product_id else None  # type: ignore[list-item]
    if ref is None:
        raise NotFound(code="not_found", resource_type="catalogue.product")
    return ref


# =====================================================================================================
# source reader ("catalogue.product") for tasks, briefings and the agent
# =====================================================================================================
def read_product_facts(uow: UnitOfWork, product_id: uuid.UUID) -> SourceFacts | None:
    if not uow.actor.can(READ):
        return None
    product = uow.session.scalars(
        select(P).where(P.id == product_id, uow.repo(Product).clause("read"))
    ).first()
    if product is None:
        return None
    category = uow.session.get(C, product.category_id)
    spec = uow.session.get(S, product.id)
    pack = uow.session.get(K, product.id)
    facts: dict[str, Any] = {
        "product_key": product.product_key,
        "display_sku": product.display_sku,
        "product_name": product.product_name,
        "category": category.name if category else None,
        "unit_of_sale": product.unit_of_sale,
        "decor_no": product.decor_no,
        "decor_name": product.decor_name,
        "finish": product.finish,
    }
    if spec is not None and spec.thickness_mm is not None:
        facts["thickness_mm"] = plain_decimal(spec.thickness_mm)
    if pack is not None and pack.carton_qty is not None:
        facts["carton_qty"] = str(pack.carton_qty)
    return SourceFacts(
        source_type="catalogue.product",
        source_id=product.id,
        version=product.version,
        label=f"{product.product_key} · {product.product_name}",
        status=product.status,
        owner_user_id=None,
        branch_id=None,
        required_permission=READ,
        canonical_path=product_path(product.id),
        is_closed=product.archived_at is not None,
        updated_at=product.updated_at,
        facts={k: v for k, v in facts.items() if v is not None},
        media_hint=f"decor:{product.decor_no}" if product.decor_no else None,
    )
