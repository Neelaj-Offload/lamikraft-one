"""Sales enumerations, JSONB snapshot models, request models and read models (DecimalStr everywhere)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints, model_validator

from app.core.money import CurrencyCode, DecimalStr, Money
from app.modules.catalogue.schemas import UomCode
from app.modules.commercial.schemas import CalculationResultOut
from app.modules.pricing.schemas import PriceType

# =====================================================================================================
# enumerations (varchar + CHECK in the migration; the contract test compares both)
# =====================================================================================================
QUOTE_SOURCE = "sales.quote"
ENQUIRY_SOURCE = "sales.enquiry"
MESSAGE_SOURCE = "sales.customer_message"
REVIEW_KIND = "sales.quote.review"


class QuoteStatus(StrEnum):
    DRAFT = "draft"
    INTERNAL_REVIEW = "internal_review"
    SENT = "sent"
    REVISED = "revised"
    WON = "won"
    LOST = "lost"
    CANCELLED = "cancelled"
    ARCHIVED = "archived"


CLOSED_STATUSES = frozenset({QuoteStatus.WON, QuoteStatus.LOST, QuoteStatus.CANCELLED, QuoteStatus.ARCHIVED})


class LineType(StrEnum):
    CATALOG = "catalog"
    MANUAL = "manual"
    CUSTOM = "custom"  # Slice 2


class ManualPreset(StrEnum):
    DEVELOPMENT = "development"
    TOOLING = "tooling"
    SPECIAL_PACKAGING = "special_packaging"
    FREIGHT = "freight"
    SAMPLE = "sample"
    MISCELLANEOUS = "miscellaneous"


#: default description and unit per manual preset (legacy configurator chips)
MANUAL_PRESETS: dict[ManualPreset, tuple[str, str]] = {
    ManualPreset.DEVELOPMENT: ("Development charges", "set"),
    ManualPreset.TOOLING: ("Tooling charges", "set"),
    ManualPreset.SPECIAL_PACKAGING: ("Special packaging", "set"),
    ManualPreset.FREIGHT: ("Freight", "set"),
    ManualPreset.SAMPLE: ("Sample", "pcs"),
    ManualPreset.MISCELLANEOUS: ("Miscellaneous charges", "set"),
}


class QuoteOrigin(StrEnum):
    USER = "user"
    AGENT = "agent"
    SEED = "seed"
    IMPORT = "import"
    MIGRATION = "migration"


class Incoterm(StrEnum):
    FOB = "FOB"
    CIF = "CIF"
    CFR = "CFR"
    EXW = "EXW"
    DDP = "DDP"
    DAP = "DAP"
    FCA = "FCA"


class Channel(StrEnum):
    EMAIL = "email"
    PHONE = "phone"
    WHATSAPP = "whatsapp"
    WEB = "web"
    OTHER = "other"


class EnquiryStatus(StrEnum):
    RECEIVED = "received"
    ASSIGNED = "assigned"
    QUOTED = "quoted"
    CLOSED = "closed"


class MessageStatus(StrEnum):
    RECEIVED = "received"
    REPLIED = "replied"


class DispatchChannel(StrEnum):
    MANUAL = "manual"
    EMAIL = "email"
    WHATSAPP = "whatsapp"
    POST = "post"
    OTHER = "other"


class RevisionKind(StrEnum):
    ISSUED = "issued"


#: Slice-1 transition actions; ``archive``, ``revise``, ``extend_validity``, ``correct`` arrive in Slice 2
class TransitionAction(StrEnum):
    SUBMIT_REVIEW = "submit_review"
    WITHDRAW_REVIEW = "withdraw_review"
    MARK_SENT = "mark_sent"
    MARK_WON = "mark_won"
    MARK_LOST = "mark_lost"
    CANCEL = "cancel"
    REVIEW_REJECTED = "review_rejected"  # written by the approvals handler, never requested directly


Short = Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
ReasonCode = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[a-z][a-z0-9_]{0,39}$")]
Brand = Annotated[
    str,
    BeforeValidator(lambda v: v.strip().upper() if isinstance(v, str) else v),
    StringConstraints(pattern=r"^[A-Z]{2,4}$"),
]
LongText = Annotated[str, StringConstraints(max_length=4000)]
ExternalText = Annotated[str, StringConstraints(max_length=20000)]


# =====================================================================================================
# snapshots (JSONB through Pydantic models on write)
# =====================================================================================================
class PartyAddressSnapshot(BaseModel):
    kind: str
    lines: list[str]


class PartySnapshot(BaseModel):
    party_id: uuid.UUID
    party_number: str
    display_name: str
    legal_name: str
    country_code: str
    default_currency: str
    customer_type: str | None
    contact_name: str | None
    contact_email: str | None
    addresses: list[PartyAddressSnapshot]
    taken_at: datetime


class ProductSnapshot(BaseModel):
    product_id: uuid.UUID
    product_key: str
    display_sku: str
    product_name: str
    category: str | None
    subcategory: str | None
    unit_of_sale: str | None
    decor_no: str | None
    decor_name: str | None
    finish: str | None
    shape: str | None
    size_text: str | None
    thickness_mm: DecimalStr | None
    specification_summary: str | None
    product_version: int


class PackagingSnapshot(BaseModel):
    carton_qty: int | None
    inner_qty: int | None
    unit_weight_g: DecimalStr | None
    packing_type: str | None
    cbm: DecimalStr | None
    net_weight_kg: DecimalStr | None
    gross_weight_kg: DecimalStr | None
    summary: str | None


class MediaSnapshot(BaseModel):
    #: imagery hint only: product media tables arrive in Slice 2 (then ``file_object`` ids are recorded here)
    hint: str | None
    file_id: uuid.UUID | None = None


class CommercialSnapshot(BaseModel):
    price_list_id: uuid.UUID | None
    price_list_code: str | None
    item_id: uuid.UUID | None
    tier: str | None
    unit_price: DecimalStr | None
    currency: str
    unit_code: str
    product_moq: DecimalStr | None
    moq_unit_code: str | None
    resolved_on: date
    reason_code: str | None = None


# =====================================================================================================
# write models: enquiries and customer messages
# =====================================================================================================
class EnquiryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    party_id: uuid.UUID
    contact_id: uuid.UUID | None = None
    channel: Channel
    received_at: datetime | None = None
    owner_user_id: uuid.UUID | None = None
    branch_id: uuid.UUID | None = None
    subject: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None
    body: ExternalText | None = None


class EnquiryUpdate(BaseModel):
    """Dirty fields plus ``expected_version``; ``owner_user_id`` assigns (``sales.enquiry.assign``),
    ``status='closed'`` with an ``outcome_code`` closes."""

    model_config = ConfigDict(extra="forbid")

    expected_version: int
    contact_id: uuid.UUID | None = None
    subject: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None
    body: ExternalText | None = None
    owner_user_id: uuid.UUID | None = None
    status: Literal["closed"] | None = None
    outcome_code: ReasonCode | None = None


class CustomerMessageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    party_id: uuid.UUID
    contact_id: uuid.UUID | None = None
    channel: Channel
    received_at: datetime | None = None
    assignee_user_id: uuid.UUID | None = None
    branch_id: uuid.UUID | None = None
    enquiry_id: uuid.UUID | None = None
    quote_id: uuid.UUID | None = None
    subject: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None
    body: Annotated[str, StringConstraints(min_length=1, max_length=20000)]


class CustomerMessageUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int
    assignee_user_id: uuid.UUID | None = None
    enquiry_id: uuid.UUID | None = None
    quote_id: uuid.UUID | None = None
    subject: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None


class MarkReplied(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int
    reply_ref_type: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)] = "manual"
    reply_ref_id: uuid.UUID | None = None


# =====================================================================================================
# write models: quotes
# =====================================================================================================
class QuoteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    party_id: uuid.UUID
    enquiry_id: uuid.UUID | None = None
    origin_message_id: uuid.UUID | None = None
    owner_user_id: uuid.UUID | None = None
    branch_id: uuid.UUID | None = None
    brand: Brand = "LK"
    price_type: PriceType = PriceType.EXPORT
    #: defaults to the party's currency
    currency: CurrencyCode | None = None
    incoterm: Incoterm | None = Incoterm.FOB
    incoterm_place: Short | None = None
    payment_terms: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None
    validity_days: int = Field(default=30, ge=1, le=365)
    customer_reference: Short | None = None
    remarks: LongText | None = None
    apply_minimum_surcharge: bool = False


class QuoteUpdate(BaseModel):
    """Header edits (drafts only). Currency changes are Slice 2 (list or approved FX), brand is fixed by the number."""

    model_config = ConfigDict(extra="forbid")

    expected_version: int
    price_type: PriceType | None = None
    incoterm: Incoterm | None = None
    incoterm_place: Short | None = None
    payment_terms: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None
    validity_days: int | None = Field(default=None, ge=1, le=365)
    customer_reference: Short | None = None
    remarks: LongText | None = None
    apply_minimum_surcharge: bool | None = None
    #: re-read the party master into the snapshot (explicit only)
    refresh_party_snapshot: bool = False


class QuoteLineCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int
    line_type: Literal["catalog", "manual"] = "catalog"
    product_id: uuid.UUID | None = None
    product_key: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)] | None = None
    quantity: DecimalStr = Field(gt=0)
    unit_code: UomCode | None = None
    #: catalog lines: an override of the resolved default (needs ``sales.quote_price.override`` and a reason);
    #: manual lines: the price itself
    unit_price: DecimalStr | None = Field(default=None, ge=0)
    override_reason: Reason | None = None
    discount_pct: DecimalStr | None = Field(default=None, ge=0, le=100)
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None
    manual_preset: ManualPreset | None = None
    remarks: LongText | None = None
    internal_note: LongText | None = None

    @model_validator(mode="after")
    def _shape(self) -> QuoteLineCreate:
        if self.line_type == "catalog":
            if (self.product_id is None) == (self.product_key is None):
                raise ValueError("a catalog line needs exactly one of product_id or product_key")
        else:
            if self.product_id is not None or self.product_key is not None:
                raise ValueError("a manual line has no product")
            if self.unit_price is None:
                raise ValueError("a manual line needs a unit_price")
            if self.description is None and self.manual_preset is None:
                raise ValueError("a manual line needs a description or a preset")
        return self


class QuoteLineUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int
    quantity: DecimalStr | None = Field(default=None, gt=0)
    unit_price: DecimalStr | None = Field(default=None, ge=0)
    override_reason: Reason | None = None
    #: restore the resolved default price and clear the override
    clear_override: bool = False
    discount_pct: DecimalStr | None = Field(default=None, ge=0, le=100)
    clear_discount: bool = False
    description: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)] | None = None
    remarks: LongText | None = None
    internal_note: LongText | None = None


class QuoteTransition(BaseModel):
    """One request for every state-machine action. Unknown or not-allowed actions are 409 ``invalid_transition``."""

    model_config = ConfigDict(extra="forbid")

    action: Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[a-z][a-z_]{1,39}$")]
    expected_version: int
    reason: Reason | None = None
    reason_code: ReasonCode | None = None
    #: mark_sent: the dispatch record
    dispatch_channel: DispatchChannel = DispatchChannel.MANUAL
    sent_to: Annotated[str, StringConstraints(strip_whitespace=True, max_length=254)] | None = None
    note: Reason | None = None
    #: mark_won: the accepted revision (defaults to the latest issued revision)
    accepted_revision_no: int | None = Field(default=None, ge=1)


class RefreshSnapshots(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int


class PreviewLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    line_key: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)] | None = None
    line_type: Literal["catalog", "manual"] = "catalog"
    product_id: uuid.UUID | None = None
    quantity: DecimalStr = Field(gt=0)
    unit_code: UomCode | None = None
    unit_price: DecimalStr | None = Field(default=None, ge=0)
    discount_pct: DecimalStr | None = Field(default=None, ge=0, le=100)

    @model_validator(mode="after")
    def _shape(self) -> PreviewLine:
        if self.line_type == "catalog" and self.product_id is None:
            raise ValueError("a catalog line needs a product_id")
        if self.line_type == "manual" and self.unit_price is None:
            raise ValueError("a manual line needs a unit_price")
        return self


class QuotePreviewIn(BaseModel):
    """Run the engine over proposed lines without persisting anything (live totals in the UI)."""

    model_config = ConfigDict(extra="forbid")

    currency: CurrencyCode
    party_id: uuid.UUID | None = None
    price_type: PriceType = PriceType.EXPORT
    surcharge_requested: bool = False
    lines: list[PreviewLine] = Field(default_factory=list, max_length=200)


class PreviewLineOut(BaseModel):
    line_key: str
    line_type: str
    product_id: uuid.UUID | None
    product_key: str | None
    unit_code: str
    default_unit_price: DecimalStr | None
    unit_price: DecimalStr | None
    price_status: str
    reason_code: str | None


class QuotePreviewOut(BaseModel):
    calculation: CalculationResultOut
    lines: list[PreviewLineOut]
    warnings: list[str]


# =====================================================================================================
# read models
# =====================================================================================================
class Capability(BaseModel):
    allowed: bool
    reason_code: str | None = None


class TransitionRead(BaseModel):
    action: str
    to_status: str
    requires_reason: bool


class UserRef(BaseModel):
    id: uuid.UUID
    display_name: str | None


class PartyRef(BaseModel):
    id: uuid.UUID
    party_number: str
    display_name: str
    country_code: str


class MinimumRead(BaseModel):
    status: str
    minimum_order_value: DecimalStr | None
    shortfall: DecimalStr | None
    reason_code: str | None


class QuoteTotals(BaseModel):
    """The persisted engine result in money form (never recomputed by a client)."""

    currency: str
    gross_subtotal: Money
    discount_total: Money
    net_subtotal: Money
    applicable_subtotal: Money
    surcharge: Money
    surcharge_applied: bool
    surcharge_reason_code: str
    surcharge_label: str
    grand_total: Money | None
    totals_complete: bool
    line_count: int
    minimum: MinimumRead
    tax_status: str
    tax_label: str
    threshold_note: str | None
    engine_version: str | None
    rule_set_version: int | None
    input_hash: str | None


class RecommendationRead(BaseModel):
    status: str
    quantity: int | None
    carton_qty: int | None
    explanation: str
    label: str


class QuoteLineRead(BaseModel):
    id: uuid.UUID
    line_no: int
    line_key: uuid.UUID
    line_type: LineType
    product_id: uuid.UUID | None
    description: str
    manual_preset: ManualPreset | None
    quantity: DecimalStr
    unit_code: str
    default_unit_price: DecimalStr | None
    unit_price: DecimalStr | None
    currency: str
    is_overridden: bool
    override_reason: str | None
    discount_pct: DecimalStr | None
    gross_amount: DecimalStr | None
    discount_amount: DecimalStr | None
    line_total: DecimalStr | None
    remarks: str | None
    internal_note: str | None
    price_list_item_id: uuid.UUID | None
    product_snapshot: ProductSnapshot | None
    packaging_snapshot: PackagingSnapshot | None
    media_snapshot: MediaSnapshot | None
    commercial_snapshot: CommercialSnapshot | None
    recommendation: RecommendationRead | None
    #: engine advisories (BELOW_ORDER_VALUE_RECOMMENDATION, NOT_CARTON_MULTIPLE ...) plus
    #: PRICE_CHANGED_SINCE_SNAPSHOT when the current list price differs from the snapshot
    advisories: list[str]
    current_unit_price: DecimalStr | None = None


class QuoteSummary(BaseModel):
    id: uuid.UUID
    quote_number: str
    revision_no: int
    status: QuoteStatus
    party: PartyRef
    customer_reference: str | None
    currency: str
    line_count: int
    grand_total: Money | None
    owner: UserRef
    created_by: UserRef | None
    branch_id: uuid.UUID | None
    origin: QuoteOrigin
    valid_until: date | None
    issued_at: datetime | None
    sent_at: datetime | None
    created_at: datetime
    updated_at: datetime
    version: int
    path: str


class ReviewRead(BaseModel):
    requires_approval: bool
    reasons: list[str]
    review_proposal_id: uuid.UUID | None
    approved_proposal_id: uuid.UUID | None
    approval_current: bool


class QuoteDetail(QuoteSummary):
    party_snapshot: PartySnapshot
    enquiry_id: uuid.UUID | None
    origin_message_id: uuid.UUID | None
    brand: str
    price_type: PriceType
    incoterm: str | None
    incoterm_place: str | None
    payment_terms: str | None
    validity_days: int
    remarks: str | None
    apply_minimum_surcharge: bool
    won_at: datetime | None
    accepted_revision_id: uuid.UUID | None
    lost_reason_code: str | None
    cancelled_reason_code: str | None
    deleted_at: datetime | None
    lines: list[QuoteLineRead]
    totals: QuoteTotals
    calculation: CalculationResultOut | None
    content_hash: str
    review: ReviewRead
    capabilities: dict[str, Capability]
    allowed_transitions: list[TransitionRead]
    redacted_fields: list[str] = Field(default_factory=list)


class QuoteFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    q: Annotated[str, StringConstraints(max_length=200)] | None = None
    status: list[QuoteStatus] | None = None
    scope: Literal["mine", "all"] = "all"
    owner_user_id: uuid.UUID | None = None
    party_id: uuid.UUID | None = None
    include_deleted: bool = False


class QuoteHistoryRead(BaseModel):
    id: uuid.UUID
    action: str
    from_status: str
    to_status: str
    actor: UserRef | None
    reason_code: str | None
    reason: str | None
    occurred_at: datetime
    quote_version: int


class QuoteRevisionSummary(BaseModel):
    id: uuid.UUID
    revision_no: int
    kind: RevisionKind
    issued_at: datetime
    issued_by: UserRef | None
    valid_until: date
    document_sha256: str
    content_hash: str
    document_path: str


class QuoteRevisionRead(QuoteRevisionSummary):
    snapshot: dict[str, Any]


class EnquiryRead(BaseModel):
    id: uuid.UUID
    enquiry_number: str
    party: PartyRef
    contact_id: uuid.UUID | None
    channel: Channel
    received_at: datetime
    owner: UserRef
    branch_id: uuid.UUID | None
    subject: str | None
    body: str | None
    status: EnquiryStatus
    outcome_code: str | None
    quote_id: uuid.UUID | None
    quote_number: str | None
    closed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    version: int
    path: str
    capabilities: dict[str, Capability]
    allowed_transitions: list[TransitionRead] = Field(default_factory=list)


class EnquiryFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    q: Annotated[str, StringConstraints(max_length=200)] | None = None
    status: list[EnquiryStatus] | None = None
    owner_user_id: uuid.UUID | None = None
    party_id: uuid.UUID | None = None


class CustomerMessageRead(BaseModel):
    id: uuid.UUID
    party: PartyRef
    contact_id: uuid.UUID | None
    contact_name: str | None
    channel: Channel
    received_at: datetime
    assignee: UserRef
    branch_id: uuid.UUID | None
    enquiry_id: uuid.UUID | None
    quote_id: uuid.UUID | None
    quote_number: str | None
    subject: str | None
    body: str
    status: MessageStatus
    replied_at: datetime | None
    reply_ref_type: str | None
    reply_ref_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    version: int
    path: str
    capabilities: dict[str, Capability]
    allowed_transitions: list[TransitionRead] = Field(default_factory=list)


class CustomerMessageFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: list[MessageStatus] | None = None
    assignee_user_id: uuid.UUID | None = None
    party_id: uuid.UUID | None = None
    quote_id: uuid.UUID | None = None


# =====================================================================================================
# agent tools
# =====================================================================================================
class FindUsualOrderInput(BaseModel):
    """The most recent won quote of a party the user may see, as the basis for a repeat quote."""

    model_config = ConfigDict(extra="forbid")

    party_id: uuid.UUID = Field(description="party_id from a resolve_party result")


class BasisLine(BaseModel):
    line_no: int
    line_type: LineType
    product_id: uuid.UUID | None
    product_key: str | None
    product_name: str
    quantity: DecimalStr
    unit_code: str
    unit_price: DecimalStr | None
    currency: str


class UsualOrderOutput(BaseModel):
    status: Literal["found", "none"]
    party_id: uuid.UUID
    quote_id: uuid.UUID | None = None
    quote_number: str | None = None
    won_at: datetime | None = None
    currency: str | None = None
    grand_total: Money | None = None
    lines: list[BasisLine] = Field(default_factory=list)
    explanation: str


class DraftQuoteLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: uuid.UUID | None = Field(default=None, description="product_id from resolve_product / find_usual_order")
    product_key: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)] | None = None
    quantity: DecimalStr = Field(gt=0)
    unit_code: UomCode | None = None

    @model_validator(mode="after")
    def _one_ref(self) -> DraftQuoteLine:
        if (self.product_id is None) == (self.product_key is None):
            raise ValueError("give exactly one of product_id or product_key")
        return self


class DraftQuoteInput(BaseModel):
    """Create a draft quote for a party from catalog lines priced through resolve_price. Prices are never model
    inputs: the resolved list price is used; overrides need a person in the app."""

    model_config = ConfigDict(extra="forbid")

    party_id: uuid.UUID
    lines: list[DraftQuoteLine] = Field(min_length=1, max_length=200)
    currency: CurrencyCode | None = Field(default=None, description="defaults to the party's currency")
    price_type: PriceType = PriceType.EXPORT
    origin_message_id: uuid.UUID | None = None
    enquiry_id: uuid.UUID | None = None
    customer_reference: Short | None = None
    remarks: LongText | None = None
    apply_minimum_surcharge: bool = False
