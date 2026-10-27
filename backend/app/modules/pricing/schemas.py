"""Pricing enumerations and read models.

Field guards (permissions.md §5): the price breakdown and provenance on items (base/addon prices and labels,
yield, price basis, item thickness, source references) need ``pricing.price_list.read``; product cost needs
``pricing.cost.read`` and is never exposed to a model, even for permitted users.

Money travels as ``{"amount", "currency"}`` and quantities as ``{"value", "uom"}`` (api-conventions §4).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.core.money import CurrencyCode, DecimalStr, Money, Quantity
from app.modules.catalogue.schemas import Measure, UomCode
from app.platform.authz.redaction import Restricted

PRICE_LIST_GUARD = Restricted("pricing.price_list.read", model_exposure="allow")
COST_GUARD = Restricted("pricing.cost.read", model_exposure="deny")

#: restricted field names, also registered with the log redactor so they never reach logs
COST_FIELD_NAMES = ("unit_cost", "unit_cost_amount", "cost_components", "current_cost", "costs")


class PriceType(StrEnum):
    DOMESTIC = "domestic"
    EXPORT = "export"
    SAMPLE = "sample"
    DISTRIBUTOR = "distributor"


class PriceScope(StrEnum):
    STANDARD = "standard"
    CUSTOMER_TYPE = "customer_type"
    CUSTOMER = "customer"


class PriceListStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    RETIRED = "retired"


class PriceItemStatus(StrEnum):
    ACTIVE = "active"
    RETIRED = "retired"


class PriceSourceKind(StrEnum):
    MANUAL = "manual"
    IMPORT = "import"
    MIGRATION = "migration"
    SEED = "seed"


class PriceHistoryKind(StrEnum):
    CREATED = "created"
    EDITED_DRAFT = "edited_draft"
    SUPERSEDED = "superseded"
    RETIRED = "retired"
    LIST_ACTIVATED = "list_activated"
    LIST_RETIRED = "list_retired"


class CostSourceKind(StrEnum):
    MANUAL = "manual"
    IMPORT = "import"
    MIGRATION = "migration"
    ROLLUP = "rollup"
    SEED = "seed"


#: resolution tiers, most specific first
Tier = Literal["customer", "customer_type", "standard"]
TIERS: tuple[Tier, ...] = ("customer", "customer_type", "standard")

Label = Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)]


# ---- write models (services; price-list CRUD endpoints arrive in Slice 2) ------------------------
class PriceListCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, pattern=r"^[A-Z0-9][A-Z0-9_-]{1,39}$")]
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    price_type: PriceType
    scope_kind: PriceScope = PriceScope.STANDARD
    party_id: uuid.UUID | None = None
    customer_type: Literal["standard", "dealer", "distributor"] | None = None
    currency: CurrencyCode
    default_unit_code: UomCode | None = None
    price_basis: Label | None = None
    valid_from: date
    valid_to: date | None = None
    priority: int | None = Field(default=None, ge=0, le=1000)
    notes: Annotated[str, StringConstraints(max_length=4000)] | None = None
    source_kind: PriceSourceKind = PriceSourceKind.MANUAL
    source_ref: Annotated[str, StringConstraints(max_length=200)] | None = None


class PriceListItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: uuid.UUID
    unit_code: UomCode
    unit_price: DecimalStr = Field(ge=0)
    final_price: DecimalStr | None = Field(default=None, ge=0)
    base_price: DecimalStr | None = Field(default=None, ge=0)
    base_price_label: Label | None = None
    addon_price: DecimalStr | None = Field(default=None, ge=0)
    addon_price_label: Label | None = None
    price_basis: Label | None = None
    yield_qty_per_board: DecimalStr | None = Field(default=None, gt=0)
    thickness_mm: DecimalStr | None = Field(default=None, gt=0)
    moq: DecimalStr | None = Field(default=None, gt=0)
    moq_unit_code: UomCode | None = None
    notes: Annotated[str, StringConstraints(max_length=4000)] | None = None
    valid_from: date | None = None  # defaults to the list's valid_from
    valid_to: date | None = None
    source_kind: PriceSourceKind = PriceSourceKind.MANUAL
    source_ref: Annotated[str, StringConstraints(max_length=200)] | None = None
    source_sheet: Annotated[str, StringConstraints(max_length=200)] | None = None
    source_row: Annotated[str, StringConstraints(max_length=40)] | None = None


class SupersedeItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unit_price: DecimalStr = Field(ge=0)
    valid_from: date
    reason: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None


class CostComponent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    amount: DecimalStr


class ProductCostCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unit_cost_amount: DecimalStr = Field(ge=0)
    unit_cost_currency: CurrencyCode
    unit_code: UomCode
    effective_from: date
    cost_components: list[CostComponent] = Field(default_factory=list, max_length=50)
    source_kind: CostSourceKind = CostSourceKind.MANUAL
    source_ref: Annotated[str, StringConstraints(max_length=200)] | None = None
    notes: Annotated[str, StringConstraints(max_length=4000)] | None = None


# ---- read models ----------------------------------------------------------------------------------
class PartyMini(BaseModel):
    id: uuid.UUID
    party_number: str
    display_name: str


class PriceListSummary(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    price_type: PriceType
    scope_kind: PriceScope
    party: PartyMini | None
    customer_type: str | None
    currency: str
    default_unit_code: str | None
    valid_from: date
    valid_to: date | None
    status: PriceListStatus
    priority: int | None
    item_count: int
    path: str


class Capability(BaseModel):
    allowed: bool
    reason_code: str | None = None


class TransitionRead(BaseModel):
    action: str
    to_status: str
    requires_reason: bool


class PriceListDetail(PriceListSummary):
    price_basis: Annotated[str | None, PRICE_LIST_GUARD] = None
    notes: str | None
    source_kind: Annotated[str | None, PRICE_LIST_GUARD] = None
    source_ref: Annotated[str | None, PRICE_LIST_GUARD] = None
    activated_at: datetime | None
    retired_at: datetime | None
    version: int
    #: ``add_item`` (draft lists only) and ``supersede_item`` (effective-dated change), both ``pricing.price_list.manage``
    capabilities: dict[str, Capability] = Field(default_factory=dict)
    #: ``activate`` (draft -> active) when the actor manages price lists
    allowed_transitions: list[TransitionRead] = Field(default_factory=list)
    redacted_fields: list[str] = Field(default_factory=list)


class PriceListItemRead(BaseModel):
    id: uuid.UUID
    price_list_id: uuid.UUID
    price_list_code: str
    product_id: uuid.UUID
    product_key: str
    display_sku: str | None
    unit_code: str
    #: per ``unit_code``, in the list currency (never relabelled)
    unit_price: Money
    final_price: Money | None
    base_price: Annotated[Money | None, PRICE_LIST_GUARD] = None
    base_price_label: Annotated[str | None, PRICE_LIST_GUARD] = None
    addon_price: Annotated[Money | None, PRICE_LIST_GUARD] = None
    addon_price_label: Annotated[str | None, PRICE_LIST_GUARD] = None
    price_basis: Annotated[str | None, PRICE_LIST_GUARD] = None
    yield_qty_per_board: Annotated[DecimalStr | None, PRICE_LIST_GUARD] = None
    thickness_mm: Annotated[Measure | None, PRICE_LIST_GUARD] = None
    source_kind: Annotated[str | None, PRICE_LIST_GUARD] = None
    source_ref: Annotated[str | None, PRICE_LIST_GUARD] = None
    source_sheet: Annotated[str | None, PRICE_LIST_GUARD] = None
    source_row: Annotated[str | None, PRICE_LIST_GUARD] = None
    #: the product MOQ of this price (distinct from the order-value recommendation)
    moq: Quantity | None
    notes: str | None
    valid_from: date
    valid_to: date | None
    status: PriceItemStatus
    superseded_by_item_id: uuid.UUID | None
    version: int
    redacted_fields: list[str] = Field(default_factory=list)


class ProductPriceRead(PriceListItemRead):
    price_list_name: str
    price_type: PriceType
    scope_kind: PriceScope
    party: PartyMini | None
    customer_type: str | None


class ProductCostRead(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    cost_version: int
    #: per ``unit_code``
    unit_cost: Annotated[Money | None, COST_GUARD] = None
    unit_code: str
    cost_components: Annotated[list[dict[str, Any]] | None, COST_GUARD] = None
    source_kind: CostSourceKind
    effective_from: date
    recorded_at: datetime
    redacted_fields: list[str] = Field(default_factory=list)


class ProductPrices(BaseModel):
    """Active prices of a product on a date across the price lists the actor may see, plus the product cost of
    record for actors holding ``pricing.cost.read`` (absent and listed in ``redacted_fields`` otherwise)."""

    product_id: uuid.UUID
    product_key: str
    on_date: date
    prices: list[ProductPriceRead]
    current_cost: Annotated[ProductCostRead | None, COST_GUARD] = None
    redacted_fields: list[str] = Field(default_factory=list)


class PriceCandidate(BaseModel):
    tier: Tier
    price_list_id: uuid.UUID
    price_list_code: str
    item_id: uuid.UUID
    priority: int | None
    unit_price: Money
    unit_code: str
    valid_from: date
    valid_to: date | None


class TierCheck(BaseModel):
    tier: Tier
    outcome: Literal[
        "matched", "ambiguous", "zero_price", "no_list", "no_item", "not_effective", "currency_mismatch", "unit_mismatch",
        "skipped",
    ]
    detail: str


class PriceResolution(BaseModel):
    """The result of ``resolve_price``. ``found`` carries provenance (tier, list code, item id); ``ambiguous``
    lists the candidates and never falls through to a less specific tier; a price is only ever returned in the
    currency of the list it came from, so a currency label is never relabelled."""

    status: Literal["found", "ambiguous", "not_found", "unavailable"]
    reason_code: str | None
    explanation: str
    product_id: uuid.UUID
    product_key: str
    party_id: uuid.UUID | None
    customer_type: str | None
    requested_currency: str
    requested_uom: str
    on_date: date
    price_type: PriceType | None
    #: per ``unit_code`` in the list currency; present only when ``status`` is ``found``
    unit_price: Money | None = None
    #: currency of the matched list (also set for ``unavailable``); always equal to ``requested_currency``
    currency: str | None = None
    unit_code: str | None = None
    tier: Tier | None = None
    price_list_id: uuid.UUID | None = None
    price_list_code: str | None = None
    item_id: uuid.UUID | None = None
    price_basis: Annotated[str | None, PRICE_LIST_GUARD] = None
    product_moq: Quantity | None = None
    valid_to: date | None = None
    candidates: list[PriceCandidate] = Field(default_factory=list)
    checks: list[TierCheck] = Field(default_factory=list)
    hints: list[str] = Field(default_factory=list)
    redacted_fields: list[str] = Field(default_factory=list)


class ResolvePriceInput(BaseModel):
    """Tool input. Identify the product by ``product_id`` (from an earlier tool result) or ``product_key``."""

    model_config = ConfigDict(extra="forbid")

    product_id: uuid.UUID | None = None
    product_key: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)] | None = None
    party_id: uuid.UUID | None = None
    currency: CurrencyCode
    uom: UomCode
    on_date: date | None = None
    price_type: PriceType | None = None


class PricedItem(BaseModel):
    """A resolved price-list item for calculation (prices come from the list, never from a model)."""

    item_id: uuid.UUID
    price_list_id: uuid.UUID
    price_list_code: str
    product_id: uuid.UUID
    product_key: str
    unit_code: str
    unit_price: DecimalStr
    currency: str
    moq: DecimalStr | None
    moq_unit_code: str | None
    valid_from: date
    valid_to: date | None
    status: PriceItemStatus
    #: the list's status and validity: a calculation uses an item only when the list is active and both the list
    #: and the item are effective on the business date
    list_status: PriceListStatus
    list_valid_from: date
    list_valid_to: date | None

    def is_current(self, on: date) -> bool:
        return (
            self.list_status == PriceListStatus.ACTIVE
            and self.status == PriceItemStatus.ACTIVE
            and self.list_valid_from <= on
            and (self.list_valid_to is None or self.list_valid_to >= on)
            and self.valid_from <= on
            and (self.valid_to is None or self.valid_to >= on)
        )


DisplayPriceStatus = Literal["found", "ambiguous", "not_found", "unavailable"]


class DisplayPrice(BaseModel):
    """The standard-tier price of one product in one currency (product list and overview columns).

    Resolved like ``resolve_price`` without a party: active standard lists effective on ``on_date`` in that currency,
    per the product's unit of sale; several matches without a unique explicit priority are ``ambiguous`` (never a
    guess); a zero price is ``unavailable``. The price is only ever in its own list currency.
    """

    product_id: uuid.UUID
    currency: CurrencyCode
    status: DisplayPriceStatus
    unit_price: Money | None = None
    unit_code: str | None = None
    price_list_code: str | None = None
    item_id: uuid.UUID | None = None
    product_moq: Quantity | None = None
    candidate_count: int = 0
