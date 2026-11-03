"""``specifications`` (LM-32, FG-SPC): key ``product_key``; needs the product.

Lengths and size strings keep the entered text (``*_source`` / dimension rows) next to the canonical millimetres;
unparsable or ambiguous dimension text is a warning, never a guess. The header normaliser turns "Plate 1 Size (mm)"
into ``plate_1_size_mm``, accepted as ``plate1_size_mm``; the legacy ``type`` column maps to ``spec_type``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import select

from app.modules.catalogue import service as catalogue
from app.modules.catalogue.models import ProductDimension, ProductSpecification
from app.modules.catalogue.normalise import parse_dimension, parse_length
from app.modules.catalogue.schemas import SPEC_DIMENSION_FIELDS, ProductUpdate, SpecificationIn
from app.modules.imports.definitions.base import (
    ERROR,
    WARNING,
    Change,
    FieldSpec,
    ImportDefinition,
    Issue,
    Plan,
    Prepared,
    as_int,
    cell,
    diff,
    need,
)
from app.modules.imports.definitions.sections import find_product, orphan
from app.platform.uow import UnitOfWork

LENGTHS = ("length_mm", "width_mm", "height_mm", "thickness_mm")
DIMENSIONS = tuple(SPEC_DIMENSION_FIELDS)  # size_mm, board_size_mm, ..., plate3_size_mm
INTS = ("groove_count", "bowl_count", "no_of_boards")
TEXTS = (
    "thickness_text", "size_label", "finish", "material_type", "bowl_type", "top_sheet", "stand_material", "type",
    "handle_type", "special_features", "care_instructions", "usage_notes",
)
ALL = (*LENGTHS, *DIMENSIONS, *INTS, *TEXTS)
_ALIASES = {
    "plate1_size_mm": ("plate_1_size_mm", "plate_1_size"),
    "plate2_size_mm": ("plate_2_size_mm", "plate_2_size"),
    "plate3_size_mm": ("plate_3_size_mm", "plate_3_size"),
    "type": ("spec_type",),
    "finish": ("spec_finish",),
    "thickness_mm": ("thickness",),
}


def current_section(uow: UnitOfWork, product_id: Any) -> dict[str, Any] | None:
    """The section as entered text (lengths from their ``*_source``, sizes from the dimension rows)."""
    spec = uow.session.get(ProductSpecification, product_id)
    if spec is None:
        return None
    out: dict[str, Any] = {name: getattr(spec, f"{name}_source") for name in LENGTHS}
    dims = dict(
        uow.session.execute(
            select(ProductDimension.kind, ProductDimension.source_text).where(ProductDimension.product_id == product_id)
        ).all()
    )
    for name, kind in SPEC_DIMENSION_FIELDS.items():
        out[name] = dims.get(kind.value)
    for name in INTS:
        out[name] = getattr(spec, name)
    for name in TEXTS:
        out[name] = getattr(spec, {"finish": "spec_finish", "type": "spec_type"}.get(name, name))
    return out


class SpecificationsMaster(ImportDefinition):
    import_type = "specifications"
    label = "Specifications"
    description = "Dimensions, thickness, materials and features per product."
    fields = (FieldSpec("product_key", required=True), *(FieldSpec(n, aliases=_ALIASES.get(n, ())) for n in ALL))
    depends_on = ("products_master",)
    writes = ("catalogue_product",)

    def normalise(self, values: Mapping[str, str | None], options: Mapping[str, Any]) -> Prepared:
        issues: list[Issue] = []
        key = need(values, "product_key", issues)
        out: dict[str, Any] = {"product_key": key}
        for name in LENGTHS:
            text = cell(values, name, issues)
            if text is not None:
                try:
                    parse_length(text)
                except (TypeError, ValueError):
                    issues.append(Issue("NOT_A_LENGTH", ERROR, f"{name} must be a positive length", name, text))
                    text = None
            out[name] = text
        for name in DIMENSIONS:
            text = cell(values, name, issues)
            parsed = parse_dimension(text) if text else None
            if parsed is not None and parsed.status != "parsed":
                issues.append(Issue("DIMENSION_" + parsed.status.upper(), WARNING,
                                    f"{name} '{text}' kept as text ({', '.join(parsed.warnings) or parsed.status})",
                                    name, text))
            out[name] = text
        for name in INTS:
            out[name] = as_int(cell(values, name, issues), name, issues)
        for name in TEXTS:
            out[name] = cell(values, name, issues)
        return Prepared(values=out, key=key, issues=issues)

    def plan(self, uow: UnitOfWork, prepared: Prepared, options: Mapping[str, Any]) -> Plan:
        v = prepared.values
        product = find_product(uow, v["product_key"])
        if product is None:
            return orphan(v["product_key"])
        current = current_section(uow, product.id) or {}
        wanted = dict(current) | {k: v[k] for k in ALL if v[k] is not None}
        changes = diff(current, wanted, ALL)
        action = "unchanged" if not changes and current else "update"
        return Plan(action, product.id, product.version, changes)

    def apply(self, uow: UnitOfWork, prepared: Prepared, plan: Plan, options: Mapping[str, Any]) -> list[Change]:
        v = prepared.values
        assert plan.target_id is not None
        before = current_section(uow, plan.target_id)
        body = {k: val for k, val in (before or {}).items() if val is not None}
        body.update({k: v[k] for k in ALL if v[k] is not None})
        result = catalogue.update_product(
            uow, plan.target_id,
            ProductUpdate(expected_version=plan.target_version or 0, specification=SpecificationIn.model_validate(body)),
        )
        return [Change("catalogue_product", plan.target_id, "update", {"specification": before},
                       {"specification": current_section(uow, plan.target_id)}, ["specification"],
                       result.product.version)]
