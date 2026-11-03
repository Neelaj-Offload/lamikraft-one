"""Taxonomy management (LM-40..42, FG-TAX, BUG-07, BUG-16): create, update, safe rename with aliases, activation,
reorder, reference counts, delete-or-reassign and the taxonomy validation report.

References are counted from the database's foreign keys (SQLAlchemy metadata introspection, so a table another module
adds later is counted automatically). A delete is refused while anything references the row, unless the caller names
a reassignment target together with the reference counts it saw; tables without a registered reassign handler block
the reassignment (the safe default). Renames keep the old name as an alias so older spreadsheets still resolve.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import Table, delete, func, select

from app.core.db.base import Base
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.modules.catalogue import events as ev
from app.modules.catalogue import service
from app.modules.catalogue.models import Category, Product, Subcategory, TaxonomyAlias
from app.modules.catalogue.schemas import CategoryCreate, CategoryRead, TaxonomyOrigin
from app.platform.service import query
from app.platform.uow import UnitOfWork

MANAGE = "catalogue.taxonomy.manage"
READ = "catalogue.product.read"
PageText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=40)]


class TaxonomyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)] | None = None
    display_order: int | None = Field(default=None, ge=0, le=1_000_000)
    is_active: bool | None = None
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000)] | None = None
    source_catalog_page_start: PageText | None = None
    source_catalog_page_end: PageText | None = None


class ReorderRequest(BaseModel):
    """The complete new order of the categories (or of one category's subcategories)."""

    model_config = ConfigDict(extra="forbid")

    category_id: uuid.UUID | None = None
    ordered_ids: list[uuid.UUID] = Field(min_length=1, max_length=2000)


class ReassignTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category_id: uuid.UUID
    subcategory_id: uuid.UUID | None = None


class TaxonomyDelete(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    reassign_to: ReassignTarget | None = None
    #: the reference counts the user confirmed (``GET .../references``); a change since then is a 409
    expected_reference_counts: dict[str, int] | None = None


class ReferenceCount(BaseModel):
    table: str
    label: str
    count: int
    reassignable: bool


class TaxonomyReferences(BaseModel):
    id: uuid.UUID
    kind: str
    name: str
    total: int
    references: list[ReferenceCount]
    aliases: list[str]


class TaxonomyDeleteResult(BaseModel):
    deleted_id: uuid.UUID
    reassigned: dict[str, int]


class ValidationItem(BaseModel):
    code: str
    severity: str
    message: str
    product_id: uuid.UUID | None = None
    product_key: str | None = None
    category_id: uuid.UUID | None = None
    value: str | None = None


class TaxonomyValidation(BaseModel):
    counts: dict[str, int]
    items: list[ValidationItem]


#: table -> human label of a reference (tables not listed keep their table name)
_LABELS = {"catalogue_product": "Products", "catalogue_subcategory": "Subcategories"}


def _fk_columns(target: str) -> list[tuple[Table, Any]]:
    """(referencing table, referencing column) for every non-cascading FK pointing at ``target.id``."""
    out: list[tuple[Table, Any]] = []
    for table in Base.metadata.sorted_tables:
        for fk in table.foreign_keys:
            if fk.column.table.name == target and fk.column.name == "id" and (fk.ondelete or "").upper() != "CASCADE":
                out.append((table, fk.parent))
    return out


#: (target table, referencing table) -> reassign handler(uow, from_id, target) -> rows moved
ReassignHandler = Callable[[UnitOfWork, uuid.UUID, ReassignTarget], int]
_HANDLERS: dict[tuple[str, str], ReassignHandler] = {}


def register_reassign_handler(target: str, table: str, handler: ReassignHandler) -> None:
    """Modules whose rows reference taxonomy (e.g. custom products) register how to move them on reassignment."""
    _HANDLERS[(target, table)] = handler


def _reference_counts(uow: UnitOfWork, target: str, row_id: uuid.UUID) -> list[ReferenceCount]:
    counts: dict[str, int] = {}
    for table, column in _fk_columns(target):
        n = uow.session.scalar(select(func.count()).select_from(table).where(column == row_id)) or 0
        counts[table.name] = counts.get(table.name, 0) + int(n)
    return [
        ReferenceCount(table=t, label=_LABELS.get(t, t), count=n, reassignable=(target, t) in _HANDLERS)
        for t, n in sorted(counts.items())
        if n
    ]


def _aliases(uow: UnitOfWork, category_id: uuid.UUID, subcategory_id: uuid.UUID | None) -> list[str]:
    stmt = select(TaxonomyAlias.alias_name).where(TaxonomyAlias.category_id == category_id)
    stmt = stmt.where(
        TaxonomyAlias.subcategory_id == subcategory_id if subcategory_id else TaxonomyAlias.subcategory_id.is_(None)
    )
    return sorted(uow.session.scalars(stmt))


def _get_category(uow: UnitOfWork, category_id: uuid.UUID, *, lock: bool = False) -> Category:
    stmt = select(Category).where(Category.id == category_id, Category.company_id == uow.actor.company_id)
    row = uow.session.scalars(stmt.with_for_update() if lock else stmt).first()
    if row is None:
        raise NotFound(code="not_found", resource_type="catalogue.category")
    return row


def _get_subcategory(uow: UnitOfWork, subcategory_id: uuid.UUID, *, lock: bool = False) -> Subcategory:
    stmt = select(Subcategory).where(Subcategory.id == subcategory_id, Subcategory.company_id == uow.actor.company_id)
    row = uow.session.scalars(stmt.with_for_update() if lock else stmt).first()
    if row is None:
        raise NotFound(code="not_found", resource_type="catalogue.subcategory")
    return row


# ---- name resolution (also used by the import workbench) ------------------------------------------------------------
def resolve_category(uow: UnitOfWork, name: str) -> tuple[Category | None, bool]:
    """(category, matched_through_alias) for a typed or imported name."""
    found = service.find_category(uow, name)
    if found is not None:
        return found, False
    alias = uow.session.scalars(
        select(TaxonomyAlias).where(
            TaxonomyAlias.company_id == uow.actor.company_id,
            TaxonomyAlias.subcategory_id.is_(None),
            TaxonomyAlias.alias_key == service.name_key(name),
        )
    ).first()
    return (uow.session.get(Category, alias.category_id), True) if alias else (None, False)


def resolve_subcategory(uow: UnitOfWork, category_id: uuid.UUID, name: str) -> tuple[Subcategory | None, bool]:
    found = service.find_subcategory(uow, category_id, name)
    if found is not None:
        return found, False
    alias = uow.session.scalars(
        select(TaxonomyAlias).where(
            TaxonomyAlias.category_id == category_id,
            TaxonomyAlias.subcategory_id.is_not(None),
            TaxonomyAlias.alias_key == service.name_key(name),
        )
    ).first()
    return (uow.session.get(Subcategory, alias.subcategory_id), True) if alias else (None, False)


def _name_taken(uow: UnitOfWork, key: str, *, category_id: uuid.UUID | None, exclude_id: uuid.UUID) -> bool:
    """A live name or an alias in the same scope (company for categories, the category for subcategories)."""
    if category_id is None:
        live = select(Category.id).where(
            Category.company_id == uow.actor.company_id, Category.name_key == key, Category.id != exclude_id
        )
        alias = select(TaxonomyAlias.id).where(
            TaxonomyAlias.company_id == uow.actor.company_id,
            TaxonomyAlias.subcategory_id.is_(None),
            TaxonomyAlias.alias_key == key,
            TaxonomyAlias.category_id != exclude_id,
        )
    else:
        live = select(Subcategory.id).where(
            Subcategory.category_id == category_id, Subcategory.name_key == key, Subcategory.id != exclude_id
        )
        alias = select(TaxonomyAlias.id).where(
            TaxonomyAlias.category_id == category_id,
            TaxonomyAlias.subcategory_id.is_not(None),
            TaxonomyAlias.subcategory_id != exclude_id,
            TaxonomyAlias.alias_key == key,
        )
    return bool(uow.session.scalar(select(live.exists())) or uow.session.scalar(select(alias.exists())))


def _recompute_products(uow: UnitOfWork, *conditions: Any) -> int:
    """Refresh search text of the products whose taxonomy name changed (one version bump each, no event)."""
    products = list(uow.session.scalars(select(Product).where(Product.company_id == uow.actor.company_id, *conditions)))
    for product in products:
        service._recompute_search_text(uow, product)
    uow.flush()
    return len(products)


# ---- commands --------------------------------------------------------------------------------------------------------
def create_category(uow: UnitOfWork, data: CategoryCreate) -> CategoryRead:
    if service.find_category(uow, data.name) is not None or _name_taken(
        uow, service.name_key(data.name), category_id=None, exclude_id=uuid.uuid4()
    ):
        raise Conflict("A category or former category name already uses this name", code="category_exists")
    row = service.create_category(uow, data.model_copy(update={"origin": TaxonomyOrigin.UI}))
    return _category_read(uow, row.id)


def create_subcategory(uow: UnitOfWork, category_id: uuid.UUID, data: CategoryCreate) -> CategoryRead:
    _get_category(uow, category_id)
    if _name_taken(uow, service.name_key(data.name), category_id=category_id, exclude_id=uuid.uuid4()):
        raise Conflict("A subcategory or former subcategory name already uses this name", code="subcategory_exists")
    service.create_subcategory(uow, category_id, data.model_copy(update={"origin": TaxonomyOrigin.UI}))
    return _category_read(uow, category_id)


def _apply_update(
    uow: UnitOfWork, row: Category | Subcategory, data: TaxonomyUpdate, *, category_id: uuid.UUID | None
) -> tuple[list[str], str | None]:
    """Returns (changed field names, old name when renamed)."""
    uow.expect_version(row, data.expected_version)
    changed: list[str] = []
    old_name: str | None = None
    if data.name is not None and " ".join(data.name.split()) != row.name:
        new_name = " ".join(data.name.split())
        key = service.name_key(new_name)
        if key != row.name_key and _name_taken(uow, key, category_id=category_id, exclude_id=row.id):
            raise Conflict("This name is already used (or was used before) in the same scope", code="name_taken")
        old_name = row.name
        sub_id = row.id if isinstance(row, Subcategory) else None
        cat_id = row.category_id if isinstance(row, Subcategory) else row.id
        if key != row.name_key:
            uow.session.execute(
                delete(TaxonomyAlias).where(
                    TaxonomyAlias.category_id == cat_id,
                    TaxonomyAlias.subcategory_id == sub_id if sub_id else TaxonomyAlias.subcategory_id.is_(None),
                    TaxonomyAlias.alias_key == key,
                )
            )
            uow.add(
                TaxonomyAlias(
                    company_id=uow.actor.company_id,
                    category_id=cat_id,
                    subcategory_id=sub_id,
                    alias_name=row.name,
                    alias_key=row.name_key,
                )
            )
        row.name, row.name_key = new_name, key
        changed.append("name")
    for field_name in ("display_order", "is_active", "description", "source_catalog_page_start", "source_catalog_page_end"):
        if field_name not in data.model_fields_set:
            continue
        value = getattr(data, field_name)
        if field_name in ("display_order", "is_active") and value is None:
            continue
        if getattr(row, field_name) != value:
            setattr(row, field_name, value)
            changed.append(field_name)
    if changed:
        row.updated_at = uow.now()
        uow.flush()
    return changed, old_name


def update_category(uow: UnitOfWork, category_id: uuid.UUID, data: TaxonomyUpdate) -> CategoryRead:
    uow.actor.require(MANAGE)
    row = _get_category(uow, category_id, lock=True)
    changed, old_name = _apply_update(uow, row, data, category_id=None)
    if old_name is not None:
        _recompute_products(uow, Product.category_id == row.id)
    if changed:
        name = ev.CATEGORY_RENAMED if old_name is not None else ev.CATEGORY_UPDATED
        uow.emit(
            name,
            aggregate_id=row.id,
            aggregate_version=row.version,
            payload=ev.payload(ev.CategoryCreatedPayload(category_id=row.id, changed_fields=sorted(changed))),
        )
        uow.audit(name, resource_type="catalogue.category", resource_id=row.id, resource_label=row.name,
                  details={"changed_fields": sorted(changed), "previous_name": old_name})
    return _category_read(uow, row.id)


def update_subcategory(uow: UnitOfWork, subcategory_id: uuid.UUID, data: TaxonomyUpdate) -> CategoryRead:
    uow.actor.require(MANAGE)
    row = _get_subcategory(uow, subcategory_id, lock=True)
    changed, old_name = _apply_update(uow, row, data, category_id=row.category_id)
    if old_name is not None:
        _recompute_products(uow, Product.subcategory_id == row.id)
    if changed:
        name = ev.SUBCATEGORY_RENAMED if old_name is not None else ev.SUBCATEGORY_UPDATED
        uow.emit(
            name,
            aggregate_id=row.id,
            aggregate_version=row.version,
            payload=ev.payload(
                ev.SubcategoryCreatedPayload(subcategory_id=row.id, category_id=row.category_id, changed_fields=sorted(changed))
            ),
        )
        uow.audit(name, resource_type="catalogue.subcategory", resource_id=row.id, resource_label=row.name,
                  details={"changed_fields": sorted(changed), "previous_name": old_name})
    return _category_read(uow, row.category_id)


def reorder(uow: UnitOfWork, data: ReorderRequest) -> list[CategoryRead]:
    """Set display_order to the given sequence (10, 20, ...); the list must name every row of that level once."""
    uow.actor.require(MANAGE)
    model: type[Category] | type[Subcategory] = Category if data.category_id is None else Subcategory
    stmt = select(model).where(model.company_id == uow.actor.company_id)
    if data.category_id is not None:
        _get_category(uow, data.category_id)
        stmt = stmt.where(Subcategory.category_id == data.category_id)
    rows = {r.id: r for r in uow.session.scalars(stmt.with_for_update())}
    if len(set(data.ordered_ids)) != len(data.ordered_ids) or set(data.ordered_ids) != set(rows):
        raise ValidationFailed(
            "The order must list every row of this level exactly once",
            errors=[{"loc": ["body", "ordered_ids"], "msg": "incomplete or duplicated", "code": "order_incomplete"}],
        )
    for index, row_id in enumerate(data.ordered_ids):
        row = rows[row_id]
        if row.display_order != (index + 1) * 10:
            row.display_order = (index + 1) * 10
            row.updated_at = uow.now()
    uow.flush()
    uow.audit("catalogue.taxonomy.reordered", resource_type="catalogue.category", resource_id=data.category_id)
    return service.list_categories(uow, include_inactive=True)


def category_references(uow: UnitOfWork, category_id: uuid.UUID) -> TaxonomyReferences:
    uow.actor.require(READ)
    row = _get_category(uow, category_id)
    refs = _reference_counts(uow, "catalogue_category", row.id)
    return TaxonomyReferences(id=row.id, kind="category", name=row.name, total=sum(r.count for r in refs),
                              references=refs, aliases=_aliases(uow, row.id, None))


def subcategory_references(uow: UnitOfWork, subcategory_id: uuid.UUID) -> TaxonomyReferences:
    uow.actor.require(READ)
    row = _get_subcategory(uow, subcategory_id)
    refs = _reference_counts(uow, "catalogue_subcategory", row.id)
    return TaxonomyReferences(id=row.id, kind="subcategory", name=row.name, total=sum(r.count for r in refs),
                              references=refs, aliases=_aliases(uow, row.category_id, row.id))


def _move_products(uow: UnitOfWork, condition: Any, target: ReassignTarget) -> int:
    products = list(
        uow.session.scalars(
            select(Product).where(Product.company_id == uow.actor.company_id, condition).with_for_update()
        )
    )
    for product in products:
        product.category_id, product.subcategory_id = target.category_id, target.subcategory_id
        service._recompute_search_text(uow, product)
        product.updated_at = uow.now()
    uow.flush()
    return len(products)


register_reassign_handler(
    "catalogue_category",
    "catalogue_product",
    lambda uow, from_id, target: _move_products(uow, Product.category_id == from_id, target),
)
register_reassign_handler(
    "catalogue_subcategory",
    "catalogue_product",
    lambda uow, from_id, target: _move_products(uow, Product.subcategory_id == from_id, target),
)


def _check_target(uow: UnitOfWork, target: ReassignTarget, *, from_category: uuid.UUID | None,
                  from_sub: uuid.UUID | None) -> None:
    category = _get_category(uow, target.category_id)
    errors: list[dict[str, Any]] = []
    if not category.is_active:
        errors.append({"loc": ["body", "reassign_to", "category_id"], "msg": "inactive", "code": "category_inactive"})
    if from_category is not None and target.category_id == from_category:
        errors.append({"loc": ["body", "reassign_to", "category_id"], "msg": "same category", "code": "same_target"})
    if target.subcategory_id is not None:
        sub = _get_subcategory(uow, target.subcategory_id)
        if sub.category_id != category.id:
            errors.append(
                {"loc": ["body", "reassign_to", "subcategory_id"], "msg": "not in the category",
                 "code": "subcategory_not_in_category"}
            )
        elif not sub.is_active:
            errors.append(
                {"loc": ["body", "reassign_to", "subcategory_id"], "msg": "inactive", "code": "subcategory_inactive"}
            )
        if from_sub is not None and sub.id == from_sub:
            errors.append({"loc": ["body", "reassign_to", "subcategory_id"], "msg": "same", "code": "same_target"})
    if errors:
        raise ValidationFailed("The reassignment target is not valid", errors=errors)


def _delete(uow: UnitOfWork, target_table: str, row: Category | Subcategory, data: TaxonomyDelete,
            *, from_category: uuid.UUID | None, from_sub: uuid.UUID | None) -> dict[str, int]:
    uow.expect_version(row, data.expected_version)
    refs = _reference_counts(uow, target_table, row.id)
    current = {r.table: r.count for r in refs}
    moved: dict[str, int] = {}
    if refs:
        if data.reassign_to is None:
            raise Conflict(
                "The row is still referenced; reassign the references or remove them first",
                code="taxonomy_referenced",
                references=current,
            )
        if data.expected_reference_counts is None or data.expected_reference_counts != current:
            raise Conflict("The references changed since they were counted", code="references_changed",
                           references=current)
        blocked = [r.table for r in refs if not r.reassignable]
        if blocked:
            raise Conflict("Some references cannot be reassigned automatically", code="reassign_unsupported",
                           tables=blocked)
        _check_target(uow, data.reassign_to, from_category=from_category, from_sub=from_sub)
        for ref in refs:
            moved[ref.table] = _HANDLERS[(target_table, ref.table)](uow, row.id, data.reassign_to)
        left = _reference_counts(uow, target_table, row.id)
        if left:
            raise Conflict("References remain after reassignment", code="references_changed",
                           references={r.table: r.count for r in left})
        uow.emit(
            ev.TAXONOMY_REASSIGNED,
            aggregate_id=row.id,
            aggregate_version=row.version,
            payload=ev.payload(
                ev.ReassignedPayload(
                    from_category_id=from_category or row.category_id,  # type: ignore[union-attr]
                    from_subcategory_id=from_sub,
                    to_category_id=data.reassign_to.category_id,
                    to_subcategory_id=data.reassign_to.subcategory_id,
                )
            ),
        )
    uow.session.delete(row)
    uow.flush()
    return moved


def delete_category(uow: UnitOfWork, category_id: uuid.UUID, data: TaxonomyDelete) -> TaxonomyDeleteResult:
    uow.actor.require(MANAGE)
    row = _get_category(uow, category_id, lock=True)
    name = row.name
    moved = _delete(uow, "catalogue_category", row, data, from_category=row.id, from_sub=None)
    uow.emit(ev.CATEGORY_DELETED, aggregate_id=category_id, aggregate_version=None,
             payload=ev.payload(ev.CategoryCreatedPayload(category_id=category_id, changed_fields=[])))
    uow.audit(ev.CATEGORY_DELETED, resource_type="catalogue.category", resource_id=category_id, resource_label=name,
              details={"reassigned": moved})
    return TaxonomyDeleteResult(deleted_id=category_id, reassigned=moved)


def delete_subcategory(uow: UnitOfWork, subcategory_id: uuid.UUID, data: TaxonomyDelete) -> TaxonomyDeleteResult:
    uow.actor.require(MANAGE)
    row = _get_subcategory(uow, subcategory_id, lock=True)
    name, category_id = row.name, row.category_id
    moved = _delete(uow, "catalogue_subcategory", row, data, from_category=None, from_sub=row.id)
    uow.emit(ev.SUBCATEGORY_DELETED, aggregate_id=subcategory_id, aggregate_version=None,
             payload=ev.payload(ev.SubcategoryCreatedPayload(subcategory_id=subcategory_id, category_id=category_id,
                                                             changed_fields=[])))
    uow.audit(ev.SUBCATEGORY_DELETED, resource_type="catalogue.subcategory", resource_id=subcategory_id,
              resource_label=name, details={"reassigned": moved})
    return TaxonomyDeleteResult(deleted_id=subcategory_id, reassigned=moved)


def _category_read(uow: UnitOfWork, category_id: uuid.UUID) -> CategoryRead:
    return next(c for c in service.list_categories(uow, include_inactive=True) if c.id == category_id)


@query(READ)
def validation_report(uow: UnitOfWork) -> TaxonomyValidation:
    """API-22 / LM-36: products whose subcategory text did not resolve, products in inactive taxonomy, categories
    inferred by migration, and empty categories."""
    P, C, SC = Product, Category, Subcategory
    live = (uow.repo(Product).clause("read"), P.archived_at.is_(None))
    items: list[ValidationItem] = []
    for p in uow.session.scalars(
        select(P).where(*live, P.subcategory_id.is_(None), P.subcategory_source.is_not(None)).order_by(P.product_key)
    ):
        items.append(ValidationItem(code="SUBCATEGORY_UNRESOLVED", severity="warning", product_id=p.id,
                                    product_key=p.product_key, value=p.subcategory_source,
                                    message=f"Subcategory '{p.subcategory_source}' is not in the taxonomy"))
    inactive = uow.session.execute(
        select(P.id, P.product_key, C.name, SC.name)
        .join(C, C.id == P.category_id)
        .outerjoin(SC, SC.id == P.subcategory_id)
        .where(*live, (C.is_active.is_(False)) | (SC.is_active.is_(False)))
        .order_by(P.product_key)
    ).all()
    for pid, key, cname, sname in inactive:
        items.append(ValidationItem(code="TAXONOMY_INACTIVE", severity="warning", product_id=pid, product_key=key,
                                    value=sname or cname, message="The product's category or subcategory is inactive"))
    for c in uow.session.scalars(select(C).where(C.company_id == uow.actor.company_id, C.origin == "migration_inferred")):
        items.append(ValidationItem(code="CATEGORY_INFERRED", severity="info", category_id=c.id, value=c.name,
                                    message="Category inferred from product data; review it"))
    used = select(P.category_id).where(P.company_id == uow.actor.company_id)
    for c in uow.session.scalars(
        select(C).where(C.company_id == uow.actor.company_id, C.id.not_in(used)).order_by(C.display_order, C.name)
    ):
        items.append(ValidationItem(code="CATEGORY_EMPTY", severity="info", category_id=c.id, value=c.name,
                                    message="No product uses this category"))
    counts: dict[str, int] = {}
    for item in items:
        counts[item.code] = counts.get(item.code, 0) + 1
    return TaxonomyValidation(counts=counts, items=items)


def reference_counts(uow: UnitOfWork, target: str, row_id: uuid.UUID) -> list[ReferenceCount]:
    """Non-cascading FK references to ``target.id`` per referencing table (import rollback, demo reset)."""
    return _reference_counts(uow, target, row_id)
