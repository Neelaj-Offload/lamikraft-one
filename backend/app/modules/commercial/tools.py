"""Agent tool: calculate quote totals over resolved price-list items (the persisted calculation is sales')."""

from __future__ import annotations

from pydantic import BaseModel

from app.modules.commercial import service
from app.modules.commercial.schemas import CalculateQuoteInput, CalculateQuoteOutput
from app.platform.tools import ToolDef
from app.platform.uow import UnitOfWork


def _calculate_quote(uow: UnitOfWork, data: BaseModel) -> CalculateQuoteOutput:
    assert isinstance(data, CalculateQuoteInput)
    return service.calculate_resolved_lines(uow, data)


CALCULATE_QUOTE = ToolDef(
    name="calculate_quote",
    group="Sales",
    description=(
        "Calculate line totals, the EUR minimum-order check, the optional EUR surcharge and the order-value "
        "recommendation for lines that reference price-list items returned by resolve_price. Prices are taken "
        "from those items, never supplied by the model. Totals exclude taxes."
    ),
    input_model=CalculateQuoteInput,
    output_model=CalculateQuoteOutput,
    handler=_calculate_quote,
    effect="read",
    permission="pricing.price.read",
)

TOOLS = [CALCULATE_QUOTE]
