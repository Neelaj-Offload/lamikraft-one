"""Parties enumerations, request models and read models."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints, field_validator

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


class CustomerType(StrEnum):
    STANDARD = "standard"
    DEALER = "dealer"
    DISTRIBUTOR = "distributor"


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


# ---- read models ----------------------------------------------------------------------------------
class Capability(BaseModel):
    allowed: bool
    reason_code: str | None = None


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


class TransitionRead(BaseModel):
    action: str
    to_status: str
    requires_reason: bool


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


class PartyFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    q: Annotated[str, StringConstraints(max_length=200)] | None = None
    role: PartyRole | None = None
    country_code: Country | None = None
    customer_type: CustomerType | None = None
    status: list[PartyStatus] | None = None
    owner_user_id: uuid.UUID | None = None
    include_archived: bool = False


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
