"""Commercial rule-set parameters, read models and the calculation result schema (DecimalStr everywhere)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.core.money import CurrencyCode, DecimalStr, Money, Quantity

QUOTE_COMMERCIAL = "quote_commercial"
#: the DecimalStr wire bound (14 integer digits); larger inputs are a 422, never an arithmetic error
MAX_QUANTITY = Decimal("99999999999999")


class RuleSetStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    RETIRED = "retired"


class ThresholdParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    minimum_order_value: DecimalStr = Field(gt=0)
    surcharge_amount: DecimalStr = Field(ge=0)


class QuoteCommercialRulesV1(BaseModel):
    """``quote_commercial`` v1 parameters. Thresholds exist only for explicitly configured currencies."""

    model_config = ConfigDict(extra="forbid")

    thresholds: dict[CurrencyCode, ThresholdParams]
    applicable_line_types: list[Literal["catalog", "custom", "manual"]] = Field(min_length=1)
    surcharge_label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)] = (
        "Shipping surcharge"
    )
    min_invoice_note_template: Annotated[str, StringConstraints(max_length=500)] | None = None


class RuleSetRead(BaseModel):
    id: uuid.UUID
    code: str
    version_no: int
    status: RuleSetStatus
    effective_from: date
    params: QuoteCommercialRulesV1
    description: str | None
    activated_at: datetime | None
    version: int


class Capability(BaseModel):
    allowed: bool
    reason_code: str | None = None


class TransitionRead(BaseModel):
    action: str
    to_status: str
    requires_reason: bool


class RuleSetDetail(RuleSetRead):
    #: rule sets are immutable once created; the only action is activating a draft (``commercial.rule_set.manage``)
    capabilities: dict[str, Capability]
    allowed_transitions: list[TransitionRead] = Field(default_factory=list)


# ---- calculation result (mirrors engine.CalculationResult.as_dict) -------------------------------
# Money is {"amount", "currency"} and quantities {"value", "uom"} (api-conventions §4); never JSON numbers.
class RecommendationOut(BaseModel):
    status: Literal["AVAILABLE", "UNAVAILABLE", "NOT_EVALUATED", "NOT_APPLICABLE"]
    quantity: Quantity | None
    basis_unit_price: Money | None
    minimum_order_value: Money | None
    carton_qty: int | None
    explanation: str
    label: str


class LineResultOut(BaseModel):
    line_key: str
    line_type: Literal["catalog", "custom", "manual"]
    quantity: Quantity
    unit_price: Money | None
    price_status: Literal["priced", "missing", "zero"]
    gross: Money | None
    discount: Money | None
    net: Money | None
    applicable: bool
    recommendation: RecommendationOut
    product_moq: Quantity | None
    advisories: list[str]


class AdjustmentOut(BaseModel):
    kind: Literal["line_discount", "surcharge"]
    line_key: str | None
    label: str
    amount: Money


class MinimumOut(BaseModel):
    status: Literal["MEETS", "BELOW", "NOT_EVALUATED"]
    minimum_order_value: Money | None
    shortfall: Money | None
    reason_code: str | None


class SurchargeOut(BaseModel):
    applied: bool
    amount: Money
    reason_code: str
    label: str


class CalculationResultOut(BaseModel):
    engine_version: str
    rule_set_code: str
    rule_set_id: uuid.UUID | None
    rule_set_version: int
    currency: CurrencyCode
    surcharge_requested: bool
    lines: list[LineResultOut]
    line_count: int
    priced_line_count: int
    totals_complete: bool
    gross_subtotal: Money
    discount_total: Money
    net_subtotal: Money
    applicable_subtotal: Money
    adjustments: list[AdjustmentOut]
    minimum: MinimumOut
    surcharge: SurchargeOut
    tax: Money | None
    tax_status: str
    tax_label: str
    grand_total: Money | None
    reason_codes: list[str]
    warnings: list[str]
    input_hash: str
    #: the canonical, hashed input record (decimal strings; the hash basis, persisted by the sales module)
    inputs: dict[str, Any]


# ---- calculate_quote tool ------------------------------------------------------------------------
class CalculateQuoteLineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    line_key: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)] | None = None
    price_list_item_id: uuid.UUID = Field(description="item_id from a resolve_price result")
    #: in the item's unit; integer-only units take whole numbers, others at most 4 decimal places (conventions §6)
    quantity: DecimalStr = Field(gt=0, le=MAX_QUANTITY, decimal_places=6)


class CalculateQuoteInput(BaseModel):
    """Calculate totals over resolved lines. Prices come from the referenced price-list items, never the model."""

    model_config = ConfigDict(extra="forbid")

    currency: CurrencyCode
    surcharge_requested: bool = False
    lines: list[CalculateQuoteLineIn] = Field(min_length=1, max_length=200)


class CalculatedLineRef(BaseModel):
    line_key: str
    price_list_item_id: uuid.UUID
    price_list_code: str
    product_id: uuid.UUID
    product_key: str
    unit_code: str


class CalculateQuoteOutput(BaseModel):
    calculation: CalculationResultOut
    lines: list[CalculatedLineRef]
    warnings: list[str]
