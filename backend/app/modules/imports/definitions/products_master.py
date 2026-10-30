"""``products_master`` (LM-29, LM-41, FG-PRD): key ``product_key``; needs the taxonomy.

The category must exist (quarantined ``CATEGORY_NOT_FOUND`` otherwise; former names resolve with a warning). An
unknown subcategory is a warning: the text is kept in ``subcategory_source`` and listed by the taxonomy validation.
``display_sku`` and ``product_name`` default to the key on insert; status labels are normalised; decor identifiers
keep leading zeros and lose only the ``120.0`` float artefact (with a warning). Unmapped columns go to
``source_extra``. Writes go through ``catalogue.service.create_product`` / ``update_product``.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import func, select

from app.modules.catalogue import service as catalogue
from app.modules.catalogue import taxonomy
from app.modules.catalogue.models import Product, ProductDimension
from app.modules.catalogue.normalise import normalise_identifier
from app.modules.catalogue.schemas import UOM_CODES, ProductCreate, ProductOrigin, ProductUpdate
from app.modules.imports.definitions.base import (
    ERROR,
    QUARANTINE,
    WARNING,
    Change,
    FieldSpec,
    ImportDefinition,
    Issue,
    Plan,
    Prepared,
    cell,
    diff,
    jsonable,
    need,
    product_status,
)
from app.platform.uow import UnitOfWork

TEXT_FIELDS = (
    "display_sku", "product_name", "brand", "product_type", "variant_group", "decor_name", "finish", "shape",
    "description", "internal_remarks", "source_design_no", "source_shape_no", "source_sheet", "source_row",
    "source_catalog_page", "source_notes", "size_mm",
)
COMPARED = (
    *TEXT_FIELDS, "category_id", "subcategory_id", "subcategory_source", "category_source", "unit_of_sale", "status",
    "decor_no", "decor_primary", "decor_options", "hsn_sac",
)
_UOM_ALIASES = {
    "pc": "pcs", "piece": "pcs", "pieces": "pcs", "nos.": "nos", "no": "nos", "no.": "nos", "number": "nos",
    "sheet": "sheets", "kgs": "kg", "kilogram": "kg", "gram": "g", "grams": "g", "metre": "m", "meter": "m",
    "set of": "set", "sets": "set", "boxes": "box", "rolls": "roll", "bundles": "bundle", "cartons": "carton",
    "ctn": "carton",
}


def uom_code(uow: UnitOfWork, text: str | None, name: str, issues: list[Issue]) -> str | None:
    if text is None:
        return None
    from app.platform.org.reference import resolve_uom_code

    code = resolve_uom_code(uow, text)
    if code is None:
        lowered = " ".join(text.split()).casefold()
        code = lowered if lowered in UOM_CODES else _UOM_ALIASES.get(lowered)
    if code is None or code not in UOM_CODES:
        issues.append(Issue("UOM_UNKNOWN", ERROR, f"'{text}' is not a known unit", name, text))
        return None
    return code


def _identifier(text: str | None, name: str, issues: list[Issue], *, artefact_rule: bool) -> str | None:
    if text is None:
        return None
    result = normalise_identifier(text, float_artefact_rule=artefact_rule)
    for warning in result.warnings:
        issues.append(Issue(warning, WARNING, f"{name} '{text}' read as '{result.value}'", name, text))
    return result.value


class ProductsMaster(ImportDefinition):
    import_type = "products_master"
    label = "Products master"
    description = "Product master records keyed by product_key. Needs the taxonomy first."
    fields = (
        FieldSpec("product_key", aliases=("key", "sku_key"), required=True),
        FieldSpec("display_sku", aliases=("sku",)),
        FieldSpec("product_name", aliases=("name",)),
        FieldSpec("brand"),
        FieldSpec("category", required=True),
        FieldSpec("subcategory", aliases=("sub_category",)),
        FieldSpec("product_type"),
        FieldSpec("variant_group"),
        FieldSpec("unit_of_sale", aliases=("uom", "unit")),
        FieldSpec("size_mm", aliases=("size",)),
        FieldSpec("decor_no", aliases=("decor",)),
        FieldSpec("decor_name"),
        FieldSpec("decor_primary"),
        FieldSpec("decor_options"),
        FieldSpec("finish"),
        FieldSpec("shape"),
        FieldSpec("status"),
        FieldSpec("description"),
        FieldSpec("internal_remarks"),
        FieldSpec("source_design_no"),
        FieldSpec("source_shape_no"),
        FieldSpec("source_sheet"),
        FieldSpec("source_row"),
        FieldSpec("source_catalog_page"),
        FieldSpec("source_notes"),
        FieldSpec("hsn_sac", aliases=("hsn", "hsn_code")),
    )
    depends_on = ("category_taxonomy",)
    writes = ("catalogue_product",)

    def normalise(self, values: Mapping[str, str | None], options: Mapping[str, Any]) -> Prepared:
        issues: list[Issue] = []
        key = need(values, "product_key", issues)
        out: dict[str, Any] = {name: cell(values, name, issues) for name in TEXT_FIELDS}
        out["product_key"] = key
        out["category"] = need(values, "category", issues)
        out["subcategory"] = cell(values, "subcategory", issues)
        out["unit_of_sale_text"] = cell(values, "unit_of_sale", issues)
        out["status"] = product_status(cell(values, "status", issues), issues)
        artefact = bool(options.get("decor_float_artefact_rule", True))
        out["decor_no"] = _identifier(cell(values, "decor_no", issues), "decor_no", issues, artefact_rule=artefact)
        out["decor_primary"] = _identifier(cell(values, "decor_primary", issues), "decor_primary", issues,
                                           artefact_rule=artefact)
        options_text = cell(values, "decor_options", issues)
        out["decor_options"] = (
            [v for v in (_identifier(p.strip() or None, "decor_options", issues, artefact_rule=artefact)
                         for p in options_text.replace(";", ",").split(",")) if v]
            if options_text else None
        )
        out["decor_options_text"] = options_text
        hsn = cell(values, "hsn_sac", issues)
        if hsn is not None and not (hsn.isdigit() and 4 <= len(hsn) <= 8):
            issues.append(Issue("HSN_FORMAT", ERROR, "hsn_sac must be 4 to 8 digits", "hsn_sac", hsn))
            hsn = None
        out["hsn_sac"] = hsn
        if key is not None and (key != key.strip() or len(key) > 120 or any(ord(c) < 32 for c in key)):
            issues.append(Issue("KEY_FORMAT", ERROR, "product_key must be 1-120 printable characters", "product_key", key))
        extra = values.get("__extra__")
        out["source_extra"] = dict(extra) if isinstance(extra, Mapping) and extra else None
        out["__cleared__"] = list(values.get("__cleared__") or [])  # type: ignore[arg-type]
        return Prepared(values=out, key=key, issues=issues)

    def _current(self, uow: UnitOfWork, product: Product) -> dict[str, Any]:
        size = uow.session.scalar(
            select(ProductDimension.source_text).where(
                ProductDimension.product_id == product.id, ProductDimension.kind == "master_size"
            )
        )
        current = {name: getattr(product, name, None) for name in COMPARED if name != "size_mm"}
        current["size_mm"] = size
        current["decor_options"] = list(product.decor_options) if product.decor_options else None
        return current

    def plan(self, uow: UnitOfWork, prepared: Prepared, options: Mapping[str, Any]) -> Plan:
        v = prepared.values
        issues: list[Issue] = []
        unit = uom_code(uow, v["unit_of_sale_text"], "unit_of_sale", issues)
        category, via_alias = taxonomy.resolve_category(uow, v["category"])
        if category is None:
            issues.append(Issue("CATEGORY_NOT_FOUND", QUARANTINE, f"Category '{v['category']}' is not in the taxonomy",
                                "category", v["category"]))
            return Plan("insert", issues=issues)
        if via_alias:
            issues.append(Issue("TAXONOMY_ALIAS_USED", WARNING, f"'{v['category']}' is a former name of '{category.name}'",
                                "category", v["category"]))
        sub_id: uuid.UUID | None = None
        sub_source: str | None = None
        if v["subcategory"]:
            sub, sub_alias = taxonomy.resolve_subcategory(uow, category.id, v["subcategory"])
            if sub is None:
                issues.append(Issue("SUBCATEGORY_UNKNOWN", WARNING, f"Subcategory '{v['subcategory']}' is not in "
                                    f"'{category.name}'; kept as text", "subcategory", v["subcategory"]))
                sub_source = v["subcategory"]
            else:
                sub_id = sub.id
                if sub_alias:
                    issues.append(Issue("TAXONOMY_ALIAS_USED", WARNING, f"'{v['subcategory']}' is a former name",
                                        "subcategory", v["subcategory"]))
        wanted = {name: v[name] for name in TEXT_FIELDS}
        wanted.update(
            category_id=category.id, subcategory_id=sub_id, subcategory_source=sub_source,
            category_source=v["category"] if via_alias else None, unit_of_sale=unit, status=v["status"],
            decor_no=v["decor_no"], decor_primary=v["decor_primary"], decor_options=v["decor_options"],
            hsn_sac=v["hsn_sac"],
        )
        context = {"wanted": jsonable(wanted), "subcategory_set": bool(v["subcategory"])}
        product = uow.session.scalars(
            select(Product).where(Product.company_id == uow.actor.company_id, Product.product_key == v["product_key"])
        ).first()
        if product is None:
            case_twin = uow.session.scalar(
                select(Product.product_key).where(
                    Product.company_id == uow.actor.company_id, func.lower(Product.product_key) == v["product_key"].lower()
                )
            )
            if case_twin:
                issues.append(Issue("PRODUCT_KEY_CASE_VARIANT", WARNING, f"'{case_twin}' differs only by case",
                                    "product_key", v["product_key"]))
            return Plan("insert", diff=diff({}, wanted, COMPARED), issues=issues, context=context)
        current = self._current(uow, product)
        compared = [n for n in COMPARED if n not in ("subcategory_id", "subcategory_source") or v["subcategory"]]
        if not v["subcategory"]:
            wanted.pop("subcategory_id"), wanted.pop("subcategory_source")
        if wanted.get("category_source") is None:
            compared = [n for n in compared if n != "category_source"]
        changes = diff(current, wanted, compared)
        for name in v.get("__cleared__") or []:
            if name in TEXT_FIELDS and name not in ("display_sku", "product_name") and current.get(name) is not None:
                changes[name] = [jsonable(current.get(name)), None]
        if v["subcategory"] and current.get("subcategory_id") != sub_id and "subcategory_id" not in changes:
            changes["subcategory_id"] = [jsonable(current.get("subcategory_id")), jsonable(sub_id)]
        return Plan("update" if changes else "unchanged", product.id, product.version, changes, issues, context)

    def apply(self, uow: UnitOfWork, prepared: Prepared, plan: Plan, options: Mapping[str, Any]) -> list[Change]:
        v = prepared.values
        wanted = plan.context["wanted"]
        job_ref = str(options.get("job_id") or "")
        if plan.action == "insert":
            data = {k: val for k, val in wanted.items() if val is not None and k != "size_mm"}
            result = catalogue.create_product(
                uow,
                ProductCreate.model_validate(
                    {**data, "product_key": v["product_key"], "size_mm": wanted.get("size_mm"),
                     "decor_options_text": v["decor_options_text"], "source_extra": v["source_extra"],
                     "origin": ProductOrigin.IMPORT, "origin_ref": f"import:{job_ref}"[:200]}
                ),
            )
            p = result.product
            return [Change("catalogue_product", p.id, "insert", None, {"product_key": p.product_key},
                           ["product_key"], p.version)]
        fields = {name: pair[1] for name, pair in plan.diff.items()}
        if "category_id" in fields and "subcategory_id" not in fields:
            fields["subcategory_id"] = wanted.get("subcategory_id")
        if v["source_extra"]:
            fields["source_extra"] = v["source_extra"]
        result = catalogue.update_product(
            uow, plan.target_id, ProductUpdate.model_validate({**fields, "expected_version": plan.target_version})  # type: ignore[arg-type]
        )
        before = {name: pair[0] for name, pair in plan.diff.items()}
        return [Change("catalogue_product", result.product.id, "update", before, fields, sorted(plan.diff),
                       result.product.version)]

    def dependency_status(self, uow: UnitOfWork) -> dict[str, Any]:
        n = uow.session.scalar(select(func.count(Product.id)).where(Product.company_id == uow.actor.company_id))
        return {"products": int(n or 0)}
