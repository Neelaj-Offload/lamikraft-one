"""Parties enumerations, request models and read models."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Any, ClassVar, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    GetCoreSchemaHandler,
    StringConstraints,
    field_validator,
)
from pydantic_core import core_schema

from app.core.http.capabilities import Capability, TransitionRead
from app.core.money import CurrencyCode


class PartyRole(StrEnum):
    CUSTOMER = "customer"
    VENDOR = "vendor"
    FABRICATOR = "fabricator"
    JOB_WORKER = "job_worker"


class PartyStatus(StrEnum):
    PROSPECT = "prospect"
    ACTIVE = "active"
    INACTIVE = "inactive"
    BLOCKED = "blocked"


CUSTOMER_TYPE_PATTERN = r"^[a-z][a-z0-9_]{1,19}$"


class CustomerType(str):
    """A customer-type code from the ``parties_customer_type`` table (SC-13). On the wire it is the plain code string;
    ``.value`` keeps the call sites written against the former StrEnum (``detail.customer_type.value``) working."""

    STANDARD: ClassVar[str] = "standard"
    DEALER: ClassVar[str] = "dealer"
    DISTRIBUTOR: ClassVar[str] = "distributor"

    @property
    def value(self) -> str:
        return str(self)

    @classmethod
    def __get_pydantic_core_schema__(cls, _source: Any, _handler: GetCoreSchemaHandler) -> core_schema.CoreSchema:
        return core_schema.no_info_after_validator_function(
            cls,
            core_schema.str_schema(pattern=CUSTOMER_TYPE_PATTERN, min_length=2, max_length=20),
            serialization=core_schema.plain_serializer_function_ser_schema(str),
        )


class AddressKind(StrEnum):
    BILLING = "billing"
    SHIPPING = "shipping"


class TaxScheme(StrEnum):
    GSTIN = "gstin"
    VAT = "vat"
    EORI = "eori"
    PAN = "pan"
    IEC = "iec"
    OTHER = "other"


Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Short = Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)]
Country = Annotated[
    str,
    BeforeValidator(lambda v: v.strip().upper() if isinstance(v, str) else v),
    StringConstraints(pattern=r"^[A-Z]{2}$"),
]


# ---- lead pipeline (spec 2026-11-25-leads-module-design.md) ---------------------------------------------------------
class LeadStage(StrEnum):
    NEW = "new"
    CONTACTED = "contacted"
    QUALIFIED = "qualified"
    NEGOTIATING = "negotiating"
    WON = "won"
    LOST = "lost"


OPEN_STAGES = frozenset({LeadStage.NEW, LeadStage.CONTACTED, LeadStage.QUALIFIED, LeadStage.NEGOTIATING})


class Interest(StrEnum):
    LAMIKRAFT = "lamikraft"
    TABLE_TOP = "table_top"
    STANDARD_DECORATIVE = "standard_decorative"
    STANDARD_COMPACT = "standard_compact"


class Priority(StrEnum):
    A = "A"
    B = "B"
    C = "C"


class Temperature(StrEnum):
    HOT = "hot"
    WARM = "warm"
    COLD = "cold"


class ActivityKind(StrEnum):
    CALL = "call"
    EMAIL = "email"
    WHATSAPP = "whatsapp"
    MEETING = "meeting"
    VISIT = "visit"
    NOTE = "note"


LEAD_SOURCE_PATTERN = r"^[a-z][a-z0-9_]{1,19}$"
LeadSourceCode = Annotated[
    str,
    BeforeValidator(lambda v: v.strip().lower() if isinstance(v, str) else v),
    StringConstraints(pattern=LEAD_SOURCE_PATTERN),
]
Website = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Requirement = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]


class ContactIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID | None = None
    name: Name
    job_title: Short | None = None
    email: Annotated[str, StringConstraints(strip_whitespace=True, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")] | None = None
    phone: Annotated[str, StringConstraints(strip_whitespace=True, max_length=40)] | None = None
    is_primary: bool = False


class AddressIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID | None = None
    kind: AddressKind
    line1: Name
    line2: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None
    city: Short | None = None
    region: Short | None = None
    postal_code: Annotated[str, StringConstraints(strip_whitespace=True, max_length=20)] | None = None
    country_code: Country
    is_default: bool = True


class TaxIdentifierIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID | None = None
    scheme: TaxScheme
    value: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]
    country_code: Country | None = None

    @field_validator("value")
    @classmethod
    def _normalise(cls, value: str) -> str:
        return "".join(value.split()).upper()


class PartyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    legal_name: Name
    display_name: Name | None = None
    country_code: Country
    default_currency: CurrencyCode
    customer_type: CustomerType | None = None
    roles: list[PartyRole] = Field(min_length=1)
    status: PartyStatus = PartyStatus.ACTIVE
    owner_user_id: uuid.UUID | None = None
    branch_id: uuid.UUID | None = None
    contacts: list[ContactIn] = Field(default_factory=list, max_length=50)
    addresses: list[AddressIn] = Field(default_factory=list, max_length=20)
    tax_identifiers: list[TaxIdentifierIn] = Field(default_factory=list, max_length=20)
    # lead fields (ignored for parties without the customer role); the stage starts at ``new``
    website: Website | None = None
    lead_source: LeadSourceCode | None = None
    interests: list[Interest] = Field(default_factory=list, max_length=4)
    requirement: Requirement | None = None
    first_contact_on: date | None = None
    priority: Priority | None = None
    temperature: Temperature | None = None


class PartyUpdate(BaseModel):
    """Dirty fields plus ``expected_version``. Child lists, when sent, replace the current set: items with an
    ``id`` update that row, items without one are added, and rows left out are archived."""

    model_config = ConfigDict(extra="forbid")

    expected_version: int
    legal_name: Name | None = None
    display_name: Name | None = None
    country_code: Country | None = None
    default_currency: CurrencyCode | None = None
    customer_type: CustomerType | None = None
    roles: list[PartyRole] | None = Field(default=None, min_length=1)
    status: PartyStatus | None = None
    branch_id: uuid.UUID | None = None
    contacts: list[ContactIn] | None = Field(default=None, max_length=50)
    addresses: list[AddressIn] | None = Field(default=None, max_length=20)
    tax_identifiers: list[TaxIdentifierIn] | None = Field(default=None, max_length=20)
    website: Website | None = None
    lead_source: LeadSourceCode | None = None
    interests: list[Interest] | None = Field(default=None, max_length=4)
    requirement: Requirement | None = None
    first_contact_on: date | None = None
    priority: Priority | None = None
    temperature: Temperature | None = None


# ---- read models ----------------------------------------------------------------------------------
class UserRef(BaseModel):
    id: uuid.UUID
    display_name: str | None


class ContactRead(BaseModel):
    id: uuid.UUID
    name: str
    job_title: str | None
    email: str | None
    phone: str | None
    is_primary: bool


class AddressRead(BaseModel):
    id: uuid.UUID
    kind: AddressKind
    line1: str
    line2: str | None
    city: str | None
    region: str | None
    postal_code: str | None
    country_code: str
    is_default: bool


class TaxIdentifierRead(BaseModel):
    id: uuid.UUID
    scheme: TaxScheme
    value: str
    country_code: str | None
    verification_status: Literal["unverified"]


class LeadSourceRef(BaseModel):
    code: str
    label: str


class PartySummary(BaseModel):
    id: uuid.UUID
    party_number: str
    legal_name: str
    display_name: str
    country_code: str
    default_currency: str
    customer_type: CustomerType | None
    roles: list[PartyRole]
    status: PartyStatus
    owner: UserRef
    branch_id: uuid.UUID | None
    primary_contact: str | None
    updated_at: datetime
    path: str
    lead_stage: LeadStage | None = None
    lead_source: LeadSourceRef | None = None
    interests: list[Interest] = Field(default_factory=list)
    priority: Priority | None = None
    temperature: Temperature | None = None
    next_follow_up_on: date | None = None


class PartyDetail(PartySummary):
    contacts: list[ContactRead]
    addresses: list[AddressRead]
    tax_identifiers: list[TaxIdentifierRead]
    version: int
    created_at: datetime
    archived_at: datetime | None
    capabilities: dict[str, Capability]
    #: status changes go through ``update`` in Slice 1; archive and owner changes arrive in Slice 2
    allowed_transitions: list[TransitionRead] = Field(default_factory=list)
    website: str | None = None
    requirement: str | None = None
    first_contact_on: date | None = None
    lost_reason: str | None = None


class PartyFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    q: Annotated[str, StringConstraints(max_length=200)] | None = None
    role: PartyRole | None = None
    country_code: Country | None = None
    customer_type: CustomerType | None = None
    status: list[PartyStatus] | None = None
    owner_user_id: uuid.UUID | None = None
    include_archived: bool = False
    lead_stage: list[LeadStage] | None = None
    lead_source: LeadSourceCode | None = None
    interest: Interest | None = None
    priority: Priority | None = None
    temperature: Temperature | None = None
    #: follow-ups due before today, today, or within the next seven days (company time zone)
    follow_up: Literal["overdue", "today", "week"] | None = None
    sort: Literal["name", "follow_up", "recent"] = "name"


class PartyCandidate(BaseModel):
    party_id: uuid.UUID
    party_number: str
    display_name: str
    legal_name: str
    country_code: str
    default_currency: str
    customer_type: CustomerType | None
    roles: list[PartyRole]
    match: Literal["party_number", "exact_name", "name_tokens"]


class PartyResolution(BaseModel):
    """``unique``: one party matched; ``ambiguous``: several (ask the user, never pick); ``not_found``."""

    status: Literal["unique", "ambiguous", "not_found"]
    query: str
    candidates: list[PartyCandidate]
    total_matches: int


class ResolvePartyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)] = Field(
        description="Party name, part of it, or a party number such as P-00001"
    )
    party_role: PartyRole | None = Field(default=None, description="Limit to customers, vendors, ...")
    country_code: Country | None = None


# ---- customer types (SC-13) ---------------------------------------------------------------------------------------
class CustomerTypeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: Annotated[
        str,
        BeforeValidator(lambda v: v.strip().lower() if isinstance(v, str) else v),
        StringConstraints(pattern=CUSTOMER_TYPE_PATTERN),
    ]
    label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    description: Annotated[str, StringConstraints(max_length=2000)] | None = None
    display_order: int = Field(default=0, ge=0, le=100000)
    is_active: bool = True


class CustomerTypeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)] | None = None
    description: Annotated[str, StringConstraints(max_length=2000)] | None = None
    display_order: int | None = Field(default=None, ge=0, le=100000)
    is_active: bool | None = None


class CustomerTypeRead(BaseModel):
    id: uuid.UUID
    code: str
    label: str
    description: str | None
    display_order: int
    is_active: bool
    is_system: bool
    party_count: int
    version: int
    capabilities: dict[str, Capability]


# ---- lead sources ----------------------------------------------------------------------------------------------
class LeadSourceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: LeadSourceCode
    label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    description: Annotated[str, StringConstraints(max_length=2000)] | None = None
    display_order: int = Field(default=0, ge=0, le=100000)
    is_active: bool = True


class LeadSourceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)] | None = None
    description: Annotated[str, StringConstraints(max_length=2000)] | None = None
    display_order: int | None = Field(default=None, ge=0, le=100000)
    is_active: bool | None = None


class LeadSourceRead(BaseModel):
    id: uuid.UUID
    code: str
    label: str
    description: str | None
    display_order: int
    is_active: bool
    is_system: bool
    lead_count: int
    version: int
    capabilities: dict[str, Capability]


# ---- stage, activities, summary --------------------------------------------------------------------------------
class LeadStageChange(BaseModel):
    """Move a lead through the pipeline. ``lost`` needs a reason; ``won`` makes the lead a customer and is final."""

    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    stage: LeadStage
    lost_reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)] | None = None


class ActivityCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: ActivityKind
    #: when it happened; defaults to now (a call logged later keeps its real time)
    occurred_at: datetime | None = None
    outcome: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)] | None = None
    notes: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)] | None = None
    next_follow_up_on: date | None = None


class ActivityRead(BaseModel):
    id: uuid.UUID
    party_id: uuid.UUID
    kind: ActivityKind
    occurred_at: datetime
    outcome: str | None
    notes: str | None
    next_follow_up_on: date | None
    created_by: UserRef
    created_at: datetime


class ActivityPage(BaseModel):
    items: list[ActivityRead]
    next_cursor: str | None


class CountRow(BaseModel):
    key: str
    label: str
    count: int


class LeadSummary(BaseModel):
    """Lead numbers in the caller's read scope; ``conversion_rate`` is won / all leads as a percentage string."""

    open: int
    won: int
    lost: int
    won_this_month: int
    conversion_rate: str
    follow_ups_overdue: int
    follow_ups_today: int
    by_stage: list[CountRow]
    by_source: list[CountRow]
    by_owner: list[CountRow]
