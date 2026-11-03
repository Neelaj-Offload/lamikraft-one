"""Product commands for the HTTP forms (Slice 2): create, update, section replacement, archive/restore, history,
recent products and the import-compatible product export.

Writes reuse ``service.create_product`` / ``service.update_product`` (the same code the import handlers call), so the
UI and the import workbench share normalisation, alias reconciliation and the one-version-bump rule. Products are
archived, never deleted, through the UI (LM-18); hard delete happens only through import rollback or the demo reset.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from app.core.csv_safe import write_csv
from app.core.errors import Conflict
from app.core.http.pagination import MAX_LIMIT, Page
from app.modules.catalogue import events as ev
from app.modules.catalogue import service
from app.modules.catalogue.models import (
    Category,
    Product,
    ProductPackaging,
    ProductSpecification,
    Subcategory,
)
from app.modules.catalogue.normalise import plain_decimal
from app.modules.catalogue.schemas import (
    PackagingIn,
    ProductCreate,
    ProductDetail,
    ProductFilters,
    ProductOrigin,
    ProductPriceColumn,
    ProductUpdate,
    ProductWriteResult,
    SpecificationIn,
)
from app.platform.idempotency.service import run_idempotent
from app.platform.service import query
from app.platform.uow import UnitOfWork

READ = "catalogue.product.read"
EXPORT = "catalogue.product.export"


class SpecificationPut(BaseModel):
    """Full replacement of the specification section (dimension text is parsed into canonical millimetres)."""

    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    specification: SpecificationIn


class PackagingPut(BaseModel):
    """Full replacement of the packaging section (alias pairs reconciled; a disagreement is ``alias_conflict``)."""

    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    packaging: PackagingIn


class ArchiveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    reason: str | None = Field(default=None, max_length=500)


class HistoryEntry(BaseModel):
    id: uuid.UUID
    occurred_at: datetime
    action: str
    actor_name: str | None
    actor_type: str
    changed_fields: list[str]
    reason: str | None


class RecentProductRow(BaseModel):
    id: uuid.UUID
    product_key: str
    product_name: str
    origin: str
    updated_at: datetime
    updated_by_name: str | None
    path: str
    prices: list[ProductPriceColumn] | None = None
    redacted_fields: list[str] = Field(default_factory=list)


def _idempotent(
    uow: UnitOfWork, operation: str, body: BaseModel, fn: Callable[[], ProductWriteResult], status: int = 200
) -> tuple[ProductWriteResult, bool]:
    out, replayed = run_idempotent(
        uow,
        key=uow.actor.idempotency_key,
        operation=operation,
        body=body.model_dump(mode="json"),
        fn=lambda: fn().model_dump(mode="json"),
        status=status,
    )
    return ProductWriteResult.model_validate(out), replayed


def create_product_command(uow: UnitOfWork, data: ProductCreate) -> tuple[ProductWriteResult, bool]:
    """HTTP create: UI origin only (``seed``/``import``/``migration`` origins are set by their own callers)."""
    uow.actor.require("catalogue.product.create")
    data = data.model_copy(update={"origin": ProductOrigin.UI, "origin_ref": None})
    return _idempotent(uow, "catalogue.create_product", data, lambda: service.create_product(uow, data), status=201)


def _require_live(uow: UnitOfWork, product_id: uuid.UUID) -> Product:
    product = uow.repo(Product).get(product_id, "update")
    if product.archived_at is not None:
        raise Conflict("The product is archived; restore it before editing", code="product_archived")
    return product


def update_product_command(uow: UnitOfWork, product_id: uuid.UUID, data: ProductUpdate) -> tuple[ProductWriteResult, bool]:
    _require_live(uow, product_id)
    return _idempotent(
        uow, f"catalogue.update_product:{product_id}", data, lambda: service.update_product(uow, product_id, data)
    )


def put_specification(uow: UnitOfWork, product_id: uuid.UUID, body: SpecificationPut) -> ProductWriteResult:
    _require_live(uow, product_id)
    return service.update_product(
        uow, product_id, ProductUpdate(expected_version=body.expected_version, specification=body.specification)
    )


def put_packaging(uow: UnitOfWork, product_id: uuid.UUID, body: PackagingPut) -> ProductWriteResult:
    _require_live(uow, product_id)
    return service.update_product(
        uow, product_id, ProductUpdate(expected_version=body.expected_version, packaging=body.packaging)
    )


def set_archived(uow: UnitOfWork, product_id: uuid.UUID, body: ArchiveRequest, *, archived: bool) -> ProductDetail:
    """Archive hides the product from lists, pickers and search; quotes keep their snapshots. Restore undoes it."""
    product = uow.repo(Product).get(product_id, "archive", for_update=True)
    uow.expect_version(product, body.expected_version)
    if (product.archived_at is not None) == archived:
        raise Conflict(
            "The product is already " + ("archived" if archived else "active"),
            code="product_archived" if archived else "product_not_archived",
        )
    product.archived_at = uow.now() if archived else None
    product.archived_by = uow.actor.user_id if archived else None
    product.updated_at = uow.now()
    uow.flush()
    name = ev.PRODUCT_ARCHIVED if archived else ev.PRODUCT_RESTORED
    uow.emit(
        name,
        aggregate_id=product.id,
        aggregate_version=product.version,
        payload=ev.payload(ev.ProductKeyPayload(product_id=product.id, product_key=product.product_key)),
    )
    uow.audit(
        name,
        resource_type="catalogue.product",
        resource_id=product.id,
        resource_label=f"{product.product_key} · {product.product_name}",
        reason=body.reason,
    )
    return service.product_detail(uow, product)


@query(READ)
def product_history(uow: UnitOfWork, product_id: uuid.UUID, *, limit: int = 50, offset: int = 0) -> Page[HistoryEntry]:
    """The product's audit trail, newest first: who changed which fields (values are not repeated here)."""
    from app.platform.audit.models import AuditLog
    from app.platform.identity.models import AppUser

    product = uow.repo(Product).get(product_id)
    where = (
        AuditLog.company_id == uow.actor.company_id,
        AuditLog.resource_type == "catalogue.product",
        AuditLog.resource_id == product.id,
    )
    total = uow.session.scalar(select(func.count(AuditLog.id)).where(*where)) or 0
    rows = uow.session.execute(
        select(AuditLog, AppUser.display_name)
        .outerjoin(AppUser, AppUser.id == AuditLog.actor_user_id)
        .where(*where)
        .order_by(AuditLog.occurred_at.desc(), AuditLog.id.desc())
        .limit(max(1, min(limit, MAX_LIMIT)))
        .offset(max(0, offset))
    ).all()
    return Page[HistoryEntry](
        items=[
            HistoryEntry(
                id=a.id,
                occurred_at=a.occurred_at,
                action=a.action,
                actor_name=name,
                actor_type=a.actor_type,
                changed_fields=list((a.details or {}).get("changed_fields") or []),
                reason=a.reason,
            )
            for a, name in rows
        ],
        total=int(total),
        limit=max(1, min(limit, MAX_LIMIT)),
        offset=max(0, offset),
    )


@query(READ)
def recent_products(uow: UnitOfWork, *, limit: int = 6, price_currency: str = "INR") -> list[RecentProductRow]:
    """Latest updated live products with the change origin, the actor and (for ``pricing.price.read``) the price in
    ``price_currency`` from the standard lists (LM-15: domestic INR by default)."""
    from app.platform.identity.models import AppUser

    P = Product
    rows = uow.session.execute(
        select(P, AppUser.display_name)
        .outerjoin(AppUser, AppUser.id == P.updated_by)
        .where(uow.repo(Product).clause("read"), P.archived_at.is_(None))
        .order_by(P.updated_at.desc(), P.id.desc())
        .limit(max(1, min(limit, 50)))
    ).all()
    price_type = "domestic" if price_currency == "INR" else None
    columns, redacted = service.price_columns(uow, [p.id for p, _n in rows], [price_currency], price_type)
    return [
        RecentProductRow(
            id=p.id,
            product_key=p.product_key,
            product_name=p.product_name,
            origin=p.origin,
            updated_at=p.updated_at,
            updated_by_name=name,
            path=service.product_path(p.id),
            prices=columns.get(p.id) if columns is not None else None,
            redacted_fields=list(redacted),
        )
        for p, name in rows
    ]


#: products_master import columns, in template order (the export is import-compatible)
EXPORT_COLUMNS: tuple[str, ...] = (
    "product_key", "display_sku", "product_name", "brand", "category", "subcategory", "product_type", "variant_group",
    "unit_of_sale", "size_mm", "decor_no", "decor_name", "decor_primary", "decor_options", "finish", "shape", "status",
    "description", "internal_remarks", "source_design_no", "source_shape_no", "source_sheet", "source_row",
    "source_catalog_page", "source_notes", "hsn_sac", "thickness_mm", "carton_qty", "unit_weight_g", "packing_type",
)


@query(EXPORT)
def export_products_csv(uow: UnitOfWork, filters: ProductFilters, *, which: Literal["all", "page"] = "all") -> bytes:
    """Import-compatible CSV of the filtered products (every cell through ``core.csv_safe``; UTF-8 BOM)."""
    from app.modules.catalogue.models import ProductDimension

    conds = service.list_conditions(uow, filters)
    P, S, K, C, SC = Product, ProductSpecification, ProductPackaging, Category, Subcategory
    rows = uow.session.execute(
        select(P, S.thickness_mm, K.carton_qty, K.unit_weight_g, K.packing_type, C.name, SC.name)
        .select_from(P)
        .outerjoin(S, S.product_id == P.id)
        .outerjoin(K, K.product_id == P.id)
        .join(C, C.id == P.category_id)
        .outerjoin(SC, SC.id == P.subcategory_id)
        .where(*conds)
        .order_by(P.product_key, P.id)
        .limit(50_000)
    ).all()
    sizes = dict(
        uow.session.execute(
            select(ProductDimension.product_id, ProductDimension.source_text).where(
                ProductDimension.kind == "master_size", ProductDimension.product_id.in_([r[0].id for r in rows])
            )
        ).all()
    ) if rows else {}

    def line(r: Any) -> Sequence[Any]:
        p: Product = r[0]
        values = {
            **{c: getattr(p, c, None) for c in EXPORT_COLUMNS if hasattr(p, c)},
            "category": r[5],
            "subcategory": r[6],
            "size_mm": sizes.get(p.id),
            "decor_options": ", ".join(p.decor_options or []) or None,
            "thickness_mm": plain_decimal(r[1]) if r[1] is not None else None,
            "carton_qty": r[2],
            "unit_weight_g": plain_decimal(r[3]) if r[3] is not None else None,
            "packing_type": r[4],
        }
        return [values.get(c) for c in EXPORT_COLUMNS]

    data = write_csv(EXPORT_COLUMNS, (line(r) for r in rows))
    uow.audit("catalogue.product.exported", resource_type="catalogue.product", details={"rows": len(rows)})
    return data
