"""Challan enumerations, request models and read models (quantities are ``DecimalStr`` everywhere).

Legacy parity (CURRENT_STATE_SPEC §4.15, §5.8): six types, returnable / non-returnable, six destination types, four
statuses, every header field and every line field. The structured links (party, consignee, office branch, warehouse,
product, custom product, original challan line) are new and optional, so a legacy-style free-text challan still works.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints

from app.core.http.capabilities import Capability, TransitionRead
from app.core.money import DecimalStr
from app.platform.org.settings import EMAIL_PATTERN, GSTIN_PATTERN, PHONE_PATTERN


class ChallanType(StrEnum):
    OUTWARD = "outward"
    INWARD = "inward"
    RETURN = "return"
    JOB_WORK = "job_work"
    TRANSFER = "transfer"
    SAMPLE = "sample"


class ReturnType(StrEnum):
    RETURNABLE = "returnable"
    NON_RETURNABLE = "non_returnable"


class DestinationType(StrEnum):
    FABRICATOR = "fabricator"
    CUSTOMER = "customer"
    WAREHOUSE = "warehouse"
    VENDOR = "vendor"
    OFFICE = "office"
    TRANSPORTER = "transporter"


class ChallanStatus(StrEnum):
    DRAFT = "draft"
    ISSUED = "issued"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class ChallanLineType(StrEnum):
    CATALOG = "catalog"
    CUSTOM = "custom"
    MANUAL = "manual"


class InventoryEffect(StrEnum):
    #: Slice 2: challans are documents only (no stock postings); Slice 4 adds ``posting``
    NONE = "none"
    POSTING = "posting"


class ChallanOrigin(StrEnum):
    USER = "user"
    AGENT = "agent"
    SEED = "seed"
    IMPORT = "import"
    MIGRATION = "migration"
    DUPLICATE = "duplicate"


class TransitionAction(StrEnum):
    ISSUE = "issue"
    CLOSE = "close"
    CANCEL = "cancel"


class ReturnLinkKind(StrEnum):
    RETURNED = "returned"


class ChallanPeriod(StrEnum):
    THIS_WEEK = "this_week"
    THIS_MONTH = "this_month"


#: legacy labels (UI and CSV) for the enums
TYPE_LABELS = {
    ChallanType.OUTWARD: "Outward",
    ChallanType.INWARD: "Inward",
    ChallanType.RETURN: "Return",
    ChallanType.JOB_WORK: "Job Work",
    ChallanType.TRANSFER: "Transfer",
    ChallanType.SAMPLE: "Sample",
}
RETURN_LABELS = {ReturnType.RETURNABLE: "Returnable", ReturnType.NON_RETURNABLE: "Non-returnable"}
DESTINATION_LABELS = {
    DestinationType.FABRICATOR: "Fabricator",
    DestinationType.CUSTOMER: "Customer",
    DestinationType.WAREHOUSE: "Warehouse",
    DestinationType.VENDOR: "Vendor",
    DestinationType.OFFICE: "Office",
    DestinationType.TRANSPORTER: "Transporter",
}
STATUS_LABELS = {
    ChallanStatus.DRAFT: "Draft",
    ChallanStatus.ISSUED: "Issued",
    ChallanStatus.CLOSED: "Closed",
    ChallanStatus.CANCELLED: "Cancelled",
}

Short = Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
OptName = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
ReasonCode = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[a-z][a-z0-9_]{0,39}$")]


#: format check only: a GSTIN is never reported as "verified" (FG-DC-07)
def _upper(value: object) -> object:
    return value.strip().upper() if isinstance(value, str) else value


Gstin = Annotated[str, BeforeValidator(_upper), StringConstraints(pattern=GSTIN_PATTERN)]
Phone = Annotated[str, StringConstraints(strip_whitespace=True, pattern=PHONE_PATTERN)]
Email = Annotated[str, StringConstraints(strip_whitespace=True, max_length=254, pattern=EMAIL_PATTERN)]
HsnSac = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[0-9]{4,8}$")]
ItemCode = Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)]
ItemName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
UnitText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]


# =====================================================================================================
# requests
# =====================================================================================================
class _Header(BaseModel):
    """Header fields shared by create and update (legacy §4.15 plus the structured links)."""

    model_config = ConfigDict(extra="forbid")

    challan_date: date | None = None
    challan_type: ChallanType | None = None
    return_type: ReturnType | None = None
    #: printed FROM text; defaults to the ``challan_defaults`` setting (legacy "Crown / Lamikraft Office")
    source_location: OptName | None = None
    source_branch_id: uuid.UUID | None = None
    #: Slice 4 (inventory): the source warehouse; stored, not validated yet
    source_warehouse_id: uuid.UUID | None = None
    destination_type: DestinationType | None = None
    #: printed TO name (legacy ``destination_party``); filled from the linked party / branch when omitted
    destination_party: OptName | None = None
    party_id: uuid.UUID | None = None
    consignee_party_id: uuid.UUID | None = None
    destination_warehouse_id: uuid.UUID | None = None
    office_branch_id: uuid.UUID | None = None
    shipping_name: OptName | None = None
    gstin: Gstin | None = None
    phone: Phone | None = None
    email: Email | None = None
    address: LongText | None = None
    reference_no: Short | None = None
    #: printed remarks (internal notes live in collab and are never printed)
    remarks: LongText | None = None
    expected_return_date: date | None = None
    #: Return challans: the issued challan the goods come back against
    original_challan_id: uuid.UUID | None = None


class ChallanUpdate(_Header):
    """Dirty header fields of a draft plus ``expected_version`` (409 ``version_conflict`` when stale)."""

    expected_version: int


class ChallanLineCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    line_type: ChallanLineType = ChallanLineType.MANUAL
    #: catalog lines: the product fills code, name, HSN/SAC and unit (overridable)
    product_id: uuid.UUID | None = None
    #: custom lines: the custom-product id (link checked when the custom-products module is installed)
    custom_product_id: uuid.UUID | None = None
    item_code: ItemCode | None = None
    item_name: ItemName | None = None
    hsn_sac: HsnSac | None = None
    quantity: DecimalStr = Field(gt=0)
    #: unit code or alias from the UOM master (default ``pcs``); integer units take whole numbers only
    unit: UnitText | None = None
    remarks: LongText | None = None
    #: Return challans: the line of the original challan this line returns
    original_line_id: uuid.UUID | None = None
    #: Slice 4: the lot shipped (lot-tracked products, when the challan posts stock)
    lot_id: uuid.UUID | None = None


class ChallanLineAdd(ChallanLineCreate):
    expected_version: int


class ChallanCreate(_Header):
    challan_type: ChallanType = ChallanType.OUTWARD
    destination_type: DestinationType = DestinationType.CUSTOMER
    lines: list[ChallanLineCreate] = Field(default_factory=list, max_length=200)


class ChallanLineUpdate(BaseModel):
    """A versioned line edit (the UI debounces quantity edits 600 ms and surfaces failures inline)."""

    model_config = ConfigDict(extra="forbid")

    expected_version: int
    item_code: ItemCode | None = None
    item_name: ItemName | None = None
    hsn_sac: HsnSac | None = None
    quantity: DecimalStr | None = Field(default=None, gt=0)
    unit: UnitText | None = None
    remarks: LongText | None = None
    original_line_id: uuid.UUID | None = None
    lot_id: uuid.UUID | None = None


class ChallanTransition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[a-z][a-z_]{1,39}$")]
    expected_version: int
    reason: Reason | None = None
    reason_code: ReasonCode | None = None


class ChallanDuplicate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: the new draft's date (default: today in the company zone)
    challan_date: date | None = None


class ChallanFilters(BaseModel):
    q: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None
    status: list[ChallanStatus] | None = None
    challan_type: list[ChallanType] | None = None
    return_type: ReturnType | None = None
    destination_type: list[DestinationType] | None = None
    party_id: uuid.UUID | None = None
    #: free-text destination match (legacy "destination party" filter)
    destination: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None
    period: ChallanPeriod | None = None
    date_from: date | None = None
    date_to: date | None = None
    pending_returnable: bool = False
    scope: Literal["mine", "all"] = "all"
    include_deleted: bool = False


# =====================================================================================================
# reads
# =====================================================================================================
class ChallanUserRef(BaseModel):
    id: uuid.UUID
    display_name: str | None


class PartyLink(BaseModel):
    id: uuid.UUID
    party_number: str | None
    display_name: str | None


class BranchLink(BaseModel):
    id: uuid.UUID
    branch_code: str
    name: str


class ChallanLink(BaseModel):
    id: uuid.UUID
    challan_number: str
    status: ChallanStatus
    path: str


class ChallanSummaryRow(BaseModel):
    id: uuid.UUID
    challan_number: str
    revision_no: int
    challan_date: date
    challan_type: ChallanType
    return_type: ReturnType
    destination_type: DestinationType
    destination_party: str
    party: PartyLink | None
    reference_no: str | None
    status: ChallanStatus
    line_count: int
    #: sum of line quantities per unit (``{"pcs": "12"}``); mixed units are never added together
    quantity_by_unit: dict[str, DecimalStr]
    #: returnable quantity still out per unit (issued returnable challans only; never added across units)
    outstanding_by_unit: dict[str, DecimalStr]
    expected_return_date: date | None
    owner: ChallanUserRef
    created_by: ChallanUserRef | None
    branch_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
    version: int
    path: str


class ChallanLineRead(BaseModel):
    id: uuid.UUID
    line_no: int
    line_type: ChallanLineType
    product_id: uuid.UUID | None
    custom_product_id: uuid.UUID | None
    item_code: str | None
    item_name: str
    hsn_sac: str | None
    quantity: DecimalStr
    unit: str
    remarks: str | None
    original_line_id: uuid.UUID | None
    returned_quantity: DecimalStr
    outstanding_quantity: DecimalStr
    #: Slice 4: explicitly non-stock (no movement), the order line delivered and the lot shipped
    is_non_stock: bool = False
    sales_order_line_id: uuid.UUID | None = None
    lot_id: uuid.UUID | None = None


class ReturnLinkRead(BaseModel):
    id: uuid.UUID
    return_challan: ChallanLink
    original_challan: ChallanLink
    return_line_id: uuid.UUID
    original_line_id: uuid.UUID
    quantity: DecimalStr
    kind: ReturnLinkKind
    created_at: datetime
    reversed_at: datetime | None


class ChallanHistoryRead(BaseModel):
    action: str
    from_status: str
    to_status: str
    actor: ChallanUserRef | None
    reason_code: str | None
    reason: str | None
    occurred_at: datetime


class ChallanDetail(ChallanSummaryRow):
    source_location: str
    source_branch: BranchLink | None
    source_warehouse_id: uuid.UUID | None
    consignee_party: PartyLink | None
    destination_warehouse_id: uuid.UUID | None
    office_branch: BranchLink | None
    shipping_name: str | None
    gstin: str | None
    #: always false: the GSTIN is format-checked, never verified against the GST portal
    gstin_verified: bool = False
    phone: str | None
    email: str | None
    address: str | None
    remarks: str | None
    direction: Literal["outward", "inward"]
    inventory_effect: InventoryEffect
    #: Slice 4: the stock posting of the issue and of the cancellation (null while documents only)
    issue_posting_id: uuid.UUID | None = None
    reversal_posting_id: uuid.UUID | None = None
    #: Slice 4: the sales order this challan delivers
    sales_order_id: uuid.UUID | None = None
    original_challan: ChallanLink | None
    duplicated_from: ChallanLink | None
    issued_at: datetime | None
    issued_by: ChallanUserRef | None
    closed_at: datetime | None
    close_reason: str | None
    cancelled_at: datetime | None
    cancel_reason_code: str | None
    cancel_reason: str | None
    updated_by: ChallanUserRef | None
    origin: ChallanOrigin
    lines: list[ChallanLineRead]
    #: returns recorded against this challan (as the original) and made by it (as a return challan)
    return_links: list[ReturnLinkRead]
    history: list[ChallanHistoryRead]
    capabilities: dict[str, Capability]
    allowed_transitions: list[TransitionRead]


class ChallanRevisionSummary(BaseModel):
    id: uuid.UUID
    revision_no: int
    kind: str
    issued_at: datetime
    issued_by: ChallanUserRef | None
    document_sha256: str
    document_path: str


class ChallanRevisionRead(ChallanRevisionSummary):
    snapshot: dict[str, Any]


class ChallanCountBucket(BaseModel):
    key: str
    label: str
    count: int


class ChallanSummary(BaseModel):
    """The legacy summary cards, computed over the same filters and the same read scope as the list (LM-88)."""

    total: int
    this_week: int
    this_month: int
    pending_returnable: int
    #: outstanding returnable quantity per unit
    pending_returnable_quantity: dict[str, DecimalStr]
    issued: int
    by_type: list[ChallanCountBucket]
    by_destination: list[ChallanCountBucket]
    by_status: list[ChallanCountBucket]
    week_start: date
    month_start: date
    today: date


class ChallanPrintLine(BaseModel):
    line_no: int
    item_code: str | None
    item_name: str
    hsn_sac: str | None
    quantity: DecimalStr
    unit: str
    remarks: str | None


class ChallanPrintParty(BaseModel):
    title: str
    lines: list[str]


class ChallanPrint(BaseModel):
    """Everything the browser print view shows; the same data the PDF is rendered from. Never includes internal
    notes."""

    challan_id: uuid.UUID
    challan_number: str
    challan_date: date
    status: ChallanStatus
    type_label: str
    return_label: str
    destination_label: str
    reference_no: str | None
    expected_return_date: date | None
    company_name: str
    company_lines: list[str]
    #: labels of company-identity values that are not configured (printed as placeholders)
    not_configured: list[str]
    from_block: ChallanPrintParty
    to_block: ChallanPrintParty
    lines: list[ChallanPrintLine]
    total_quantity: dict[str, DecimalStr]
    remarks: str | None
    terms: list[str]
    terms_are_demo: bool
    signatures: list[str]
    watermark: str | None


# =====================================================================================================
# agent tool input (no identity fields: the actor is the server-built context)
# =====================================================================================================
class DraftChallanLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: a catalogue product (code, name, HSN/SAC and unit are filled from it) or free text
    product_id: uuid.UUID | None = None
    product_key: Annotated[str, StringConstraints(strip_whitespace=True, max_length=60)] | None = None
    item_name: ItemName | None = None
    quantity: DecimalStr = Field(gt=0)
    unit: UnitText | None = None
    remarks: LongText | None = None


class DraftChallanInput(BaseModel):
    """``draft_challan``: a draft delivery challan owned by the user; nothing is issued and no stock moves."""

    model_config = ConfigDict(extra="forbid")

    challan_type: ChallanType = ChallanType.OUTWARD
    return_type: ReturnType | None = None
    destination_type: DestinationType = DestinationType.CUSTOMER
    party_id: uuid.UUID | None = None
    destination_party: OptName | None = None
    reference_no: Short | None = None
    remarks: LongText | None = None
    expected_return_date: date | None = None
    lines: list[DraftChallanLine] = Field(default_factory=list, max_length=100)


# short names used inside the module (the OpenAPI component names are the Challan-prefixed class names)
LineType = ChallanLineType
Period = ChallanPeriod
CountBucket = ChallanCountBucket
HistoryRead = ChallanHistoryRead
PrintLine = ChallanPrintLine
PrintParty = ChallanPrintParty
UserRef = ChallanUserRef
