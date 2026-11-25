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


#: quote state-machine actions (also the ``sales_quote_status_history.action`` CHECK); ``review_rejected`` is written
#: by the approvals handler and ``restore``/``change_currency``/``change_owner`` by their own commands
class TransitionAction(StrEnum):
    SUBMIT_REVIEW = "submit_review"
    WITHDRAW_REVIEW = "withdraw_review"
    MARK_SENT = "mark_sent"
    MARK_WON = "mark_won"
    MARK_LOST = "mark_lost"
    CANCEL = "cancel"
    REVIEW_REJECTED = "review_rejected"  # written by the approvals handler, never requested directly
    REVISE = "revise"
    DISCARD_REVISION = "discard_revision"
    ARCHIVE = "archive"
    UNARCHIVE = "unarchive"
    CORRECT_STATUS = "correct_status"
    EXTEND_VALIDITY = "extend_validity"
    RESTORE = "restore"  # history only (POST .../revisions/{n}/restore)
    CHANGE_CURRENCY = "change_currency"  # history only (POST .../currency-change)
    CHANGE_OWNER = "change_owner"  # history only (PUT .../owner)


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
    #: FG-QLN-05: the canonical millimetres behind ``size_text`` (absent on snapshots taken before Slice 2)
    length_mm: DecimalStr | None = None
    width_mm: DecimalStr | None = None
    height_mm: DecimalStr | None = None
    diameter_mm: DecimalStr | None = None


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
    #: brand, price type, incoterm and validity default to the company's quote defaults (setting ``quote_defaults``)
    brand: Brand | None = None
    price_type: PriceType | None = None
    #: defaults to the party's currency, then the quote defaults
    currency: CurrencyCode | None = None
    incoterm: Incoterm | None = None
    incoterm_place: Short | None = None
    payment_terms: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None
    validity_days: int | None = Field(default=None, ge=1, le=365)
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
    line_type: Literal["catalog", "manual", "custom"] = "catalog"
    product_id: uuid.UUID | None = None
    product_key: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)] | None = None
    #: custom lines: the custom product (priced from its quoted price, converted at an approved rate if needed)
    custom_product_id: uuid.UUID | None = None
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
            if self.custom_product_id is not None:
                raise ValueError("a catalog line has no custom product")
        elif self.line_type == "custom":
            if self.custom_product_id is None:
                raise ValueError("a custom line needs a custom_product_id")
            if self.product_id is not None or self.product_key is not None:
                raise ValueError("a custom line has no catalogue product")
        else:
            if self.custom_product_id is not None:
                raise ValueError("a manual line has no custom product")
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
    #: extend_validity: the new last day of validity (after the current one, not in the past)
    valid_until: date | None = None


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
    custom_product_id: uuid.UUID | None = None
    product_snapshot: ProductSnapshot | None
    custom_snapshot: CustomProductSnapshot | None = None
    packaging_snapshot: PackagingSnapshot | None
    media_snapshot: MediaSnapshot | None
    commercial_snapshot: CommercialSnapshot | None
    #: price provenance: the currency/price the line was priced from and the approved FX rate that converted it
    source_currency: str | None = None
    source_unit_price: DecimalStr | None = None
    fx_rate_id: uuid.UUID | None = None
    fx_rate: str | None = None
    restored_from_revision_no: int | None = None
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
    archived_from_status: str | None = None
    duplicated_from_quote_id: uuid.UUID | None = None
    restored_from_revision_no: int | None = None
    is_expired: bool = False
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
    currency: CurrencyCode | None = None
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


# =====================================================================================================
# Slice 2: quote lifecycle commands, revisions compare/restore, duplicate, currency change, exports, settings
# =====================================================================================================
class PriceMode(StrEnum):
    KEEP = "keep"
    REFRESH = "refresh"


class DuplicateQuote(BaseModel):
    """Copy a quote into a new draft: new number, real totals, ``customer_reference`` cleared, the owner per the
    ``quote_defaults.duplicate_copies_assignee`` policy. ``price_mode=refresh`` re-resolves catalog prices."""

    model_config = ConfigDict(extra="forbid")

    from_revision_no: int | None = Field(default=None, ge=1)
    party_id: uuid.UUID | None = None
    price_mode: PriceMode = PriceMode.KEEP


class RestoreRevision(BaseModel):
    """Copy an issued revision into the working copy (a sent quote is revised first); history is never overwritten."""

    model_config = ConfigDict(extra="forbid")

    expected_version: int
    reason: Reason | None = None


class CurrencyChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to_currency: CurrencyCode
    expected_version: int


class CurrencyLinePreview(BaseModel):
    line_id: uuid.UUID
    line_no: int
    line_type: LineType
    description: str
    from_unit_price: DecimalStr | None
    to_unit_price: DecimalStr | None
    to_default_unit_price: DecimalStr | None
    #: list (a price list in the new currency), fx (an approved dated rate), custom_price (the custom product's own
    #: price in that currency) or none (blocked)
    method: Literal["list", "fx", "custom_price", "none"]
    status: Literal["ok", "blocked"]
    reason_code: str | None
    explanation: str
    fx_rate_id: uuid.UUID | None = None
    fx_rate: str | None = None
    fx_rate_date: date | None = None


class CurrencyChangePreview(BaseModel):
    quote_id: uuid.UUID
    from_currency: str
    to_currency: str
    applicable: bool
    blocked_count: int
    lines: list[CurrencyLinePreview]


class ChangeOwner(BaseModel):
    model_config = ConfigDict(extra="forbid")

    owner_user_id: uuid.UUID
    expected_version: int
    reason: Reason | None = None


class FieldChange(BaseModel):
    field: str
    before: Any
    after: Any


class LineDiff(BaseModel):
    line_key: str
    change: Literal["added", "removed", "changed", "moved", "unchanged"]
    line_no_before: int | None
    line_no_after: int | None
    description: str
    changes: list[FieldChange]


class TotalDiff(BaseModel):
    field: str
    before: DecimalStr | None
    after: DecimalStr | None
    delta: DecimalStr | None


class RevisionCompare(BaseModel):
    """Header fields, lines by ``line_key`` (added, removed, changed, moved) and totals between two issued revisions,
    or between an issued revision and the working copy (``to_revision_no`` null)."""

    quote_id: uuid.UUID
    currency_before: str
    currency_after: str
    from_revision_no: int
    to_revision_no: int | None
    header: list[FieldChange]
    lines: list[LineDiff]
    totals: list[TotalDiff]
    summary: str


class QuoteSettingsRead(BaseModel):
    """Quote defaults (the ``quote_defaults`` setting) plus the numbering display (next number previews, never
    allocating one)."""

    defaults: dict[str, Any]
    version: int
    brands: list[str]
    next_quote_numbers: dict[str, str]
    next_custom_product_code: str
    next_sample_number: str
    quote_sequence_reset_policy: str
    capabilities: dict[str, Capability]


class QuoteSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    defaults: dict[str, Any]
    expected_version: int = Field(ge=0)
    change_reason: Reason | None = None


# =====================================================================================================
# Slice 2: custom products (spec 4.13) and samples
# =====================================================================================================
class CustomType(StrEnum):
    MODIFIED_CATALOG = "modified_catalog"
    FULLY_NEW = "fully_new"
    QUOTE_ONLY = "quote_only"


class CustomProductStatus(StrEnum):
    INQUIRY = "inquiry"
    UNDER_DEVELOPMENT = "under_development"
    SAMPLE_STAGE = "sample_stage"
    QUOTED = "quoted"
    APPROVED = "approved"
    REJECTED = "rejected"
    DORMANT = "dormant"
    CONVERTED_TO_STANDARD = "converted_to_standard"


class CustomHistoryAction(StrEnum):
    CREATE = "create"
    TRANSITION = "transition"
    AUTO_QUOTED = "auto_quoted"
    PROMOTE = "promote"
    ARCHIVE = "archive"
    UNARCHIVE = "unarchive"
    DUPLICATE = "duplicate"


class SpecOutcome(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class PromotionStatus(StrEnum):
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    EXECUTED = "executed"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
    FAILED = "failed"


PROMOTION_KIND = "sales.custom_product.promotion"

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
Text120 = Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)]
Mm = Annotated[DecimalStr, Field(gt=0)]


class CustomPackaging(BaseModel):
    model_config = ConfigDict(extra="forbid")

    carton_qty: int | None = Field(default=None, gt=0)
    inner_qty: int | None = Field(default=None, gt=0)
    packing_type: Text120 | None = None
    unit_weight_g: DecimalStr | None = Field(default=None, gt=0)
    carton_length_cm: DecimalStr | None = Field(default=None, gt=0)
    carton_width_cm: DecimalStr | None = Field(default=None, gt=0)
    carton_height_cm: DecimalStr | None = Field(default=None, gt=0)
    cbm: DecimalStr | None = Field(default=None, gt=0)


class CustomProductFields(BaseModel):
    """Every legacy custom-product field (spec 4.13) except costing, which has its own protected endpoint."""

    model_config = ConfigDict(extra="forbid")

    custom_type: CustomType | None = None
    base_product_id: uuid.UUID | None = None
    customer_specific_flag: bool | None = None
    party_id: uuid.UUID | None = None
    legacy_customer_name: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None
    inquiry_reference: Text120 | None = None
    product_name: Name | None = None
    description: LongText | None = None
    category_id: uuid.UUID | None = None
    subcategory_id: uuid.UUID | None = None
    dimensions_text: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None
    length_mm: Mm | None = None
    width_mm: Mm | None = None
    height_mm: Mm | None = None
    thickness_mm: Mm | None = None
    thickness_text: Annotated[str, StringConstraints(strip_whitespace=True, max_length=40)] | None = None
    decor_no: Annotated[str, StringConstraints(strip_whitespace=True, max_length=40)] | None = None
    decor_name: Text120 | None = None
    finish: Text120 | None = None
    shape: Text120 | None = None
    groove_count: int | None = Field(default=None, ge=0, le=1000)
    bowl_count: int | None = Field(default=None, ge=0, le=1000)
    handle_type: Text120 | None = None
    packaging_notes: LongText | None = None
    packaging: CustomPackaging | None = None
    quoted_price: DecimalStr | None = Field(default=None, ge=0)
    quoted_currency: CurrencyCode | None = None
    unit_code: UomCode | None = None
    remarks: LongText | None = None


class CustomProductCreate(CustomProductFields):
    custom_type: CustomType = CustomType.FULLY_NEW
    product_name: Name
    owner_user_id: uuid.UUID | None = None
    branch_id: uuid.UUID | None = None


class CustomProductUpdate(CustomProductFields):
    expected_version: int


class CustomProductTransition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[a-z][a-z_]{1,39}$")]
    expected_version: int
    reason: Reason | None = None


class CustomProductArchive(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int
    reason: Reason | None = None


class CostingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cost_amount: DecimalStr = Field(ge=0)
    cost_currency: CurrencyCode
    components: list[dict[str, Any]] = Field(default_factory=list, max_length=50)
    basis_note: LongText | None = None


class SpecRevisionCreate(BaseModel):
    """Record the current specification as a revision (optionally with the sample it was sent as)."""

    model_config = ConfigDict(extra="forbid")

    sample_id: uuid.UUID | None = None
    sample_reference: Text120 | None = None
    sample_sent_on: date | None = None
    feedback: LongText | None = None


class SpecOutcomeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: Literal["approved", "rejected"]
    expected_version: int
    feedback: LongText | None = None


class PromotionRequest(BaseModel):
    """The master product to create from an approved custom product (validated against the catalogue first)."""

    model_config = ConfigDict(extra="forbid")

    product_key: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    display_sku: Text120 | None = None
    brand: Annotated[str, StringConstraints(strip_whitespace=True, max_length=40)] | None = None
    category_id: uuid.UUID | None = None
    subcategory_id: uuid.UUID | None = None
    unit_of_sale: UomCode | None = None
    hsn_sac: Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[0-9]{4,8}$")] | None = None


class CustomProductSummary(BaseModel):
    id: uuid.UUID
    custom_code: str
    custom_type: CustomType
    product_name: str
    status: CustomProductStatus
    party: PartyRef | None
    legacy_customer_name: str | None
    inquiry_reference: str | None
    base_product_key: str | None
    dimensions_text: str | None
    decor_no: str | None
    finish: str | None
    quoted_price: Money | None
    owner: UserRef
    promoted_product_id: uuid.UUID | None
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime
    version: int
    path: str


class SpecRevisionRead(BaseModel):
    id: uuid.UUID
    revision_no: int
    spec_snapshot: dict[str, Any]
    sample_id: uuid.UUID | None
    sample_number: str | None
    sample_reference: str | None
    sample_sent_on: date | None
    feedback: str | None
    outcome: SpecOutcome
    decided_at: datetime | None
    decided_by: UserRef | None
    created_at: datetime
    version: int


class CustomHistoryRead(BaseModel):
    id: uuid.UUID
    action: CustomHistoryAction
    from_status: str
    to_status: str
    reason: str | None
    actor: UserRef | None
    quote_id: uuid.UUID | None
    occurred_at: datetime


class PromotionRead(BaseModel):
    id: uuid.UUID
    status: PromotionStatus
    spec_revision_id: uuid.UUID
    payload: dict[str, Any]
    payload_hash: str
    proposal_id: uuid.UUID | None
    requested_by: UserRef | None
    decided_at: datetime | None
    decision_reason: str | None
    executed_product_id: uuid.UUID | None
    executed_at: datetime | None
    failure_reason: str | None
    created_at: datetime
    version: int


class CustomQuoteRef(BaseModel):
    quote_id: uuid.UUID
    quote_number: str
    status: QuoteStatus
    line_no: int


class CustomProductDetail(CustomProductSummary):
    base_product_id: uuid.UUID | None
    customer_specific_flag: bool
    description: str | None
    category_id: uuid.UUID | None
    subcategory_id: uuid.UUID | None
    category_name: str | None
    subcategory_name: str | None
    length_mm: DecimalStr | None
    width_mm: DecimalStr | None
    height_mm: DecimalStr | None
    thickness_mm: DecimalStr | None
    thickness_text: str | None
    decor_name: str | None
    shape: str | None
    groove_count: int | None
    bowl_count: int | None
    handle_type: str | None
    packaging_notes: str | None
    packaging: CustomPackaging | None
    unit_code: str
    remarks: str | None
    status_reason: str | None
    dormant_from_status: str | None
    duplicated_from_id: uuid.UUID | None
    created_by: UserRef | None
    branch_id: uuid.UUID | None
    spec_revisions: list[SpecRevisionRead]
    promotions: list[PromotionRead]
    quotes: list[CustomQuoteRef]
    capabilities: dict[str, Capability]
    allowed_transitions: list[TransitionRead]
    #: costing is never part of this model; ``costing`` here lists that a separate, guarded endpoint exists
    redacted_fields: list[str] = Field(default_factory=list)


class CostingRead(BaseModel):
    id: uuid.UUID
    cost_version: int
    cost: Money
    components: list[dict[str, Any]] | None
    basis_note: str | None
    recorded_at: datetime
    recorded_by: UserRef | None


class CustomProductFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    q: Annotated[str, StringConstraints(max_length=200)] | None = None
    status: list[CustomProductStatus] | None = None
    custom_type: CustomType | None = None
    party_id: uuid.UUID | None = None
    category_id: uuid.UUID | None = None
    scope: Literal["mine", "all"] = "all"
    include_archived: bool = False


class CustomProductSnapshot(BaseModel):
    """The spec of a custom product on a quote line (``product_snapshot`` of a custom line; document-compatible keys)."""

    custom_product_id: uuid.UUID
    custom_code: str
    custom_type: str
    product_key: str
    display_sku: str
    product_name: str
    decor_no: str | None
    decor_name: str | None
    finish: str | None
    shape: str | None
    size_text: str | None
    thickness_mm: DecimalStr | None
    specification_summary: str | None
    unit_of_sale: str | None
    product_version: int


class SampleStatus(StrEnum):
    REQUESTED = "requested"
    DISPATCHED = "dispatched"
    DELIVERED = "delivered"
    FEEDBACK_RECEIVED = "feedback_received"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class DeliveryEvidence(StrEnum):
    CUSTOMER_CONFIRMATION = "customer_confirmation"
    COURIER_TRACKING = "courier_tracking"
    CHALLAN_SIGNED = "challan_signed"
    OTHER = "other"


class FeedbackOutcome(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    CHANGES_REQUESTED = "changes_requested"
    NO_RESPONSE = "no_response"


class SampleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    party_id: uuid.UUID
    description: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)] | None = None
    quantity: DecimalStr = Field(gt=0)
    unit_code: UomCode = "pcs"
    quote_id: uuid.UUID | None = None
    custom_product_id: uuid.UUID | None = None
    spec_revision_id: uuid.UUID | None = None
    product_id: uuid.UUID | None = None
    owner_user_id: uuid.UUID | None = None
    branch_id: uuid.UUID | None = None
    notes: LongText | None = None
    #: record a sample already sent before (today or earlier): it is created dispatched on that date
    sent_on: date | None = None
    #: courier or challan reference of a sample recorded as already sent
    dispatch_reference: Text120 | None = None


class SampleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int
    description: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)] | None = None
    quantity: DecimalStr | None = Field(default=None, gt=0)
    notes: LongText | None = None


class SampleTransition(BaseModel):
    """``dispatch`` (dispatch_reference or challan_id), ``deliver`` (evidence), ``record_feedback`` (outcome + text),
    ``close`` and ``cancel`` (reason)."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["dispatch", "deliver", "record_feedback", "close", "cancel"]
    expected_version: int
    dispatch_reference: Text120 | None = None
    challan_id: uuid.UUID | None = None
    evidence_kind: DeliveryEvidence | None = None
    feedback: LongText | None = None
    feedback_outcome: FeedbackOutcome | None = None
    reason: Reason | None = None
    #: when ``dispatch``, ``deliver`` or ``record_feedback`` really happened (entering history); default now
    occurred_on: date | None = None


class SampleRead(BaseModel):
    id: uuid.UUID
    sample_number: str
    party: PartyRef
    owner: UserRef
    quote_id: uuid.UUID | None
    quote_number: str | None
    custom_product_id: uuid.UUID | None
    custom_code: str | None
    spec_revision_id: uuid.UUID | None
    product_id: uuid.UUID | None
    description: str
    quantity: DecimalStr
    unit_code: str
    status: SampleStatus
    requested_on: date
    dispatched_at: datetime | None
    dispatch_reference: str | None
    challan_id: uuid.UUID | None
    delivered_at: datetime | None
    delivery_evidence_kind: DeliveryEvidence | None
    feedback: str | None
    feedback_outcome: FeedbackOutcome | None
    feedback_at: datetime | None
    closed_at: datetime | None
    close_reason: str | None
    notes: str | None
    branch_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    version: int
    path: str
    capabilities: dict[str, Capability] = Field(default_factory=dict)
    allowed_transitions: list[TransitionRead] = Field(default_factory=list)


class SampleFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    q: Annotated[str, StringConstraints(max_length=200)] | None = None
    status: list[SampleStatus] | None = None
    party_id: uuid.UUID | None = None
    quote_id: uuid.UUID | None = None
    custom_product_id: uuid.UUID | None = None


class SampleChallanLink(BaseModel):
    """Link (or, with ``challan_id: null``, unlink) the delivery challan that will carry a requested sample. Issuing
    that challan dispatches the sample (``sales.sample_dispatch``); linking an already issued challan dispatches it now."""

    model_config = ConfigDict(extra="forbid")

    expected_version: int
    challan_id: uuid.UUID | None


LineageKind = Literal["custom_product", "spec_revision", "quote", "challan", "product", "sample"]


class LineageNode(BaseModel):
    """One record a sample is linked to. ``not_visible``: the link exists but the record is outside the actor's scope
    (its identity is not shown)."""

    kind: LineageKind
    state: Literal["linked", "not_visible"]
    id: uuid.UUID | None = None
    label: str | None = None
    title: str | None = None
    status: str | None = None
    path: str | None = None
    facts: dict[str, str] = Field(default_factory=dict)


class LineageEvent(BaseModel):
    at: datetime | None
    on: date
    kind: Literal["custom_product_created", "spec_revision_recorded", "quote_issued", "sample_requested",
                  "challan_issued", "sample_dispatched", "sample_delivered", "feedback_recorded", "sample_closed",
                  "product_promoted"]
    label: str
    ref_kind: LineageKind | None = None


class SampleLineage(BaseModel):
    """Where a sample comes from and where it went: custom product (and spec revision), quote, delivery challan, the
    catalogue product (direct or promoted), other samples of the same custom product, and a dated timeline."""

    sample_id: uuid.UUID
    sample_number: str
    status: SampleStatus
    custom_product: LineageNode | None
    spec_revision: LineageNode | None
    quote: LineageNode | None
    challan: LineageNode | None
    product: LineageNode | None
    related_samples: list[LineageNode]
    timeline: list[LineageEvent]
    #: links the sample does not have yet (``custom_product``, ``quote``, ``challan``)
    missing: list[Literal["custom_product", "quote", "challan"]]


QuoteLineRead.model_rebuild()
QuoteDetail.model_rebuild()
