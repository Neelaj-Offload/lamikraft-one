"""``packaging`` (LM-31, FG-PKG-01..09, BUG-09, SCN-G2): key ``product_key``; needs the product.

Every documented alias pair (carton_qty/master_carton_qty, inner_qty/inner_pack_qty, unit_weight_g/unit_weight_kg,
packing_type/unit_packing_type) resolves to one canonical column. When both sides are present and disagree the row is
quarantined ``ALIAS_CONFLICT`` with both raw values; nothing is guessed. A row for an unknown product is quarantined
``ORPHAN_PRODUCT`` (released by a recheck after the products import). Blank cells keep the current value.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.modules.catalogue import service as catalogue
from app.modules.catalogue.models import ProductPackaging
from app.modules.catalogue.normalise import resolve_packaging_aliases
from app.modules.catalogue.schemas import PackagingIn, ProductUpdate
from app.modules.imports.definitions.base import (
    ERROR,
    QUARANTINE,
    Change,
    FieldSpec,
    ImportDefinition,
    Issue,
    Plan,
    Prepared,
    as_decimal,
    cell,
    diff,
    jsonable,
    need,
)
from app.modules.imports.definitions.sections import find_product, orphan
from app.platform.uow import UnitOfWork

PAIRS = (
    ("carton_qty", "master_carton_qty"),
    ("inner_qty", "inner_pack_qty"),
    ("unit_weight_g", "unit_weight_kg"),
    ("packing_type", "unit_packing_type"),
)
DECIMALS = ("carton_length_cm", "carton_width_cm", "carton_height_cm", "net_weight_kg", "gross_weight_kg", "cbm")
TEXTS = ("packaging_notes", "fragile_notes", "packaging_status", "notes")
CANONICAL = ("carton_qty", "inner_qty", "unit_weight_g", "packing_type", *DECIMALS, *TEXTS)


def current_section(row: ProductPackaging | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {name: jsonable(getattr(row, name)) for name in CANONICAL}


class PackagingMaster(ImportDefinition):
    import_type = "packaging"
    label = "Packaging"
    description = "Carton and unit packaging per product, with the legacy alias columns reconciled."
    fields = (
        FieldSpec("product_key", required=True),
        *(FieldSpec(name) for pair in PAIRS for name in pair),
        *(FieldSpec(name) for name in DECIMALS),
        *(FieldSpec(name) for name in TEXTS),
    )
    depends_on = ("products_master",)
    writes = ("catalogue_product",)

    def normalise(self, values: Mapping[str, str | None], options: Mapping[str, Any]) -> Prepared:
        issues: list[Issue] = []
        key = need(values, "product_key", issues)
        raw_pairs = {name: cell(values, name, issues) for pair in PAIRS for name in pair}
        resolution = resolve_packaging_aliases(raw_pairs)
        for conflict in resolution.conflicts:
            shown = ", ".join(f"{k}={v}" for k, v in sorted(conflict.values.items()))
            issues.append(Issue("ALIAS_CONFLICT", QUARANTINE, f"Alias values disagree: {shown}", conflict.field, shown))
        for name, code in resolution.errors:
            issues.append(Issue(code, ERROR, f"{name} is not valid ({code})", name, raw_pairs.get(name)))
        out: dict[str, Any] = {
            "product_key": key,
            "pairs": {k: v for k, v in raw_pairs.items() if v is not None},
            "canonical": jsonable(resolution.values),
        }
        for name in DECIMALS:
            out[name] = jsonable(as_decimal(cell(values, name, issues), name, issues, positive=True))
        for name in TEXTS:
            out[name] = cell(values, name, issues)
        return Prepared(values=out, key=key, issues=issues)

    def plan(self, uow: UnitOfWork, prepared: Prepared, options: Mapping[str, Any]) -> Plan:
        v = prepared.values
        product = find_product(uow, v["product_key"])
        if product is None:
            return orphan(v["product_key"])
        current = current_section(uow.session.get(ProductPackaging, product.id)) or {}
        wanted = dict(current)
        wanted.update({k: val for k, val in v["canonical"].items() if val is not None})
        wanted.update({k: v[k] for k in (*DECIMALS, *TEXTS) if v[k] is not None})
        changes = diff(current, wanted, CANONICAL)
        action = "unchanged" if not changes and current else "update"
        return Plan(action, product.id, product.version, changes, context={"had_section": bool(current)})

    def apply(self, uow: UnitOfWork, prepared: Prepared, plan: Plan, options: Mapping[str, Any]) -> list[Change]:
        v = prepared.values
        assert plan.target_id is not None
        before = current_section(uow.session.get(ProductPackaging, plan.target_id))
        body: dict[str, Any] = {k: val for k, val in (before or {}).items() if val is not None}
        for canonical, alias in PAIRS:
            if canonical in v["pairs"] or alias in v["pairs"]:  # the row's own alias values replace the pair
                body.pop(canonical, None)
                body.update({k: v["pairs"][k] for k in (canonical, alias) if k in v["pairs"]})
        body.update({k: v[k] for k in (*DECIMALS, *TEXTS) if v[k] is not None})
        result = catalogue.update_product(
            uow, plan.target_id,
            ProductUpdate(expected_version=plan.target_version or 0, packaging=PackagingIn.model_validate(body)),
        )
        after = current_section(uow.session.get(ProductPackaging, plan.target_id))
        return [Change("catalogue_product", plan.target_id, "update", {"packaging": before}, {"packaging": after},
                       ["packaging"], result.product.version)]

