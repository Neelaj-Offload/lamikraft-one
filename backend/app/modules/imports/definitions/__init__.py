"""The seven import types (legacy order: taxonomy -> products -> pricing/packaging/specifications/media -> lookups)."""

from __future__ import annotations

from app.modules.imports.definitions.base import ImportDefinition
from app.modules.imports.definitions.category_taxonomy import CategoryTaxonomy
from app.modules.imports.definitions.lookup_reference import LookupReferenceImport
from app.modules.imports.definitions.media_master import MediaMaster
from app.modules.imports.definitions.packaging_master import PackagingMaster
from app.modules.imports.definitions.pricing_master import PricingMaster
from app.modules.imports.definitions.products_master import ProductsMaster
from app.modules.imports.definitions.specifications_master import SpecificationsMaster

DEFINITIONS: dict[str, ImportDefinition] = {
    d.import_type: d
    for d in (
        CategoryTaxonomy(),
        ProductsMaster(),
        PricingMaster(),
        PackagingMaster(),
        SpecificationsMaster(),
        MediaMaster(),
        LookupReferenceImport(),
    )
}


def definition(import_type: str) -> ImportDefinition:
    return DEFINITIONS[import_type]
