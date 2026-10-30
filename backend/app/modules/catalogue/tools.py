"""Agent tools for the catalogue (thin descriptors over the same services the UI uses)."""

from __future__ import annotations

from pydantic import BaseModel

from app.modules.catalogue import service
from app.modules.catalogue.schemas import ProductResolution, ResolveProductInput
from app.platform.tools import ToolDef
from app.platform.uow import UnitOfWork


def _resolve_product(uow: UnitOfWork, data: BaseModel) -> ProductResolution:
    assert isinstance(data, ResolveProductInput)
    return service.resolve_product(uow, data.query)


RESOLVE_PRODUCT = ToolDef(
    name="resolve_product",
    group="Catalogue",
    description=(
        "Find the product the user means among live products they may see, by product key, SKU or name words. "
        "Returns status unique (one product), ambiguous (ask the user to choose; never pick) or not_found."
    ),
    input_model=ResolveProductInput,
    output_model=ProductResolution,
    handler=_resolve_product,
    effect="read",
    permission="catalogue.product.read",
)

TOOLS = [RESOLVE_PRODUCT]
