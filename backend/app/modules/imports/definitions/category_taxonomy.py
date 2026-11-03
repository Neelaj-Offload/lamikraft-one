"""``category_taxonomy`` (LM-28, FG-TAX): key (category, subcategory); imported first.

A row with a blank subcategory carries the category's own attributes; a row with a subcategory creates or updates
that subcategory (and creates its category when the file or the database does not have it yet). Categories are
committed before subcategories. Former names (aliases written on rename) resolve with a warning.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import func, select

from app.modules.catalogue import service as catalogue
from app.modules.catalogue import taxonomy
from app.modules.catalogue.models import Category, Subcategory
from app.modules.catalogue.schemas import CategoryCreate, TaxonomyOrigin
from app.modules.imports.definitions.base import (
    WARNING,
    Change,
    FieldSpec,
    ImportDefinition,
    Issue,
    Plan,
    Prepared,
    as_bool,
    as_int,
    cell,
    compact,
    diff,
    need,
)
from app.platform.uow import UnitOfWork

_ATTRS = ("display_order", "is_active", "description", "source_catalog_page_start", "source_catalog_page_end",
          "legacy_product_count")


class CategoryTaxonomy(ImportDefinition):
    import_type = "category_taxonomy"
    label = "Category taxonomy"
    description = "Categories and subcategories with order, activation and catalogue pages. Import this first."
    fields = (
        FieldSpec("category", required=True),
        FieldSpec("subcategory", aliases=("sub_category",)),
        FieldSpec("display_order"),
        FieldSpec("is_active", aliases=("active",)),
        FieldSpec("description"),
        FieldSpec("source_catalog_page_start", aliases=("catalog_page_start",)),
        FieldSpec("source_catalog_page_end", aliases=("catalog_page_end",)),
        FieldSpec("product_count"),
    )
    writes = ("catalogue_category", "catalogue_subcategory")

    def normalise(self, values: Mapping[str, str | None], options: Mapping[str, Any]) -> Prepared:
        issues: list[Issue] = []
        category = need(values, "category", issues)
        sub = cell(values, "subcategory", issues)
        out: dict[str, Any] = {
            "category": " ".join(category.split()) if category else None,
            "subcategory": " ".join(sub.split()) if sub else None,
            "display_order": as_int(cell(values, "display_order", issues), "display_order", issues),
            "is_active": as_bool(cell(values, "is_active", issues), "is_active", issues),
            "description": cell(values, "description", issues),
            "source_catalog_page_start": (cell(values, "source_catalog_page_start", issues) or None),
            "source_catalog_page_end": (cell(values, "source_catalog_page_end", issues) or None),
            "legacy_product_count": as_int(cell(values, "product_count", issues), "product_count", issues),
        }
        key = None
        if out["category"]:
            key = f"{catalogue.name_key(out['category'])}|{catalogue.name_key(out['subcategory'] or '')}"
        return Prepared(values=out, key=key, issues=issues)

    def order_key(self, prepared: Prepared) -> tuple[Any, ...]:
        return (1 if prepared.values.get("subcategory") else 0,)

    def plan(self, uow: UnitOfWork, prepared: Prepared, options: Mapping[str, Any]) -> Plan:
        v = prepared.values
        issues: list[Issue] = []
        category, via_alias = taxonomy.resolve_category(uow, v["category"])
        if via_alias and category is not None:
            issues.append(Issue("TAXONOMY_ALIAS_USED", WARNING, f"'{v['category']}' is a former name of "
                                f"'{category.name}'", "category", v["category"]))
        attrs = compact({k: v[k] for k in _ATTRS})
        if not v["subcategory"]:
            if category is None:
                return Plan("insert", diff=diff({}, attrs | {"name": v["category"]}, ["name", *_ATTRS]), issues=issues)
            current = {k: getattr(category, k) for k in _ATTRS}
            changes = diff(current, attrs, _ATTRS)
            return Plan("update" if changes else "unchanged", category.id, category.version, changes, issues,
                        {"category_id": str(category.id)})
        if category is None:
            return Plan("insert", diff={"name": [None, v["subcategory"]], "category": [None, v["category"]]},
                        issues=issues, context={"create_category": True})
        sub, sub_alias = taxonomy.resolve_subcategory(uow, category.id, v["subcategory"])
        if sub_alias and sub is not None:
            issues.append(Issue("TAXONOMY_ALIAS_USED", WARNING, f"'{v['subcategory']}' is a former name of "
                                f"'{sub.name}'", "subcategory", v["subcategory"]))
        if sub is None:
            return Plan("insert", diff=diff({}, attrs | {"name": v["subcategory"]}, ["name", *_ATTRS]), issues=issues,
                        context={"category_id": str(category.id)})
        current = {k: getattr(sub, k) for k in _ATTRS}
        changes = diff(current, attrs, _ATTRS)
        return Plan("update" if changes else "unchanged", sub.id, sub.version, changes, issues,
                    {"category_id": str(category.id)})

    def apply(self, uow: UnitOfWork, prepared: Prepared, plan: Plan, options: Mapping[str, Any]) -> list[Change]:
        v = prepared.values
        attrs = compact({k: v[k] for k in _ATTRS})
        changes: list[Change] = []
        if plan.action == "update":
            model = Subcategory if v["subcategory"] else Category
            row = uow.session.get(model, plan.target_id)
            assert row is not None
            before = {k: getattr(row, k) for k in plan.diff}
            for k in plan.diff:
                setattr(row, k, attrs[k])
            row.updated_at = uow.now()
            uow.flush()
            return [Change(model.__tablename__, row.id, "update", before, {k: attrs[k] for k in plan.diff},
                           sorted(plan.diff), row.version)]
        create = CategoryCreate(name=v["subcategory"] or v["category"], origin=TaxonomyOrigin.IMPORT,
                                **{k: val for k, val in attrs.items() if k != "legacy_product_count"},
                                legacy_product_count=attrs.get("legacy_product_count"))
        if not v["subcategory"]:
            row = catalogue.create_category(uow, create, origin="import")
            return [Change("catalogue_category", row.id, "insert", None, {"name": row.name}, ["name"], row.version)]
        category, _ = taxonomy.resolve_category(uow, v["category"])
        if category is None:
            category = catalogue.create_category(
                uow, CategoryCreate(name=v["category"], origin=TaxonomyOrigin.IMPORT,
                                    display_order=attrs.get("display_order", 0)), origin="import"
            )
            changes.append(Change("catalogue_category", category.id, "insert", None, {"name": category.name}, ["name"],
                                  category.version))
        sub = catalogue.create_subcategory(uow, category.id, create, origin="import")
        changes.append(Change("catalogue_subcategory", sub.id, "insert", None, {"name": sub.name}, ["name"], sub.version))
        return changes

    def dependency_status(self, uow: UnitOfWork) -> dict[str, Any]:
        n = uow.session.scalar(select(func.count(Category.id)).where(Category.company_id == uow.actor.company_id))
        return {"categories": int(n or 0)}
