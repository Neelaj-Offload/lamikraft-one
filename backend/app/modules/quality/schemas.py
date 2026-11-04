"""Quality request and read models (quantities ``DecimalStr`` in the inspected unit)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.core.http.capabilities import Capability
from app.core.money import DecimalStr
from app.modules.quality.enums import CheckResult, InspectionStatus, SubjectType

Text = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]
Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Code = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{1,39}$")]
NonNegative = Annotated[DecimalStr, Field(ge=0)]


class ChecklistItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: Code
    label: Label
    result: CheckResult
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None


class InspectionDecision(BaseModel):
    """Record the results: accepted + rejected must equal the inspected quantity."""

    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    qty_accepted: NonNegative
    qty_rejected: NonNegative
    checklist: list[ChecklistItem] = Field(default_factory=list, max_length=50)
    findings: Text | None = None
    reject_reason_code: Code | None = None
    #: a stock bin of the warehouse for the accepted quantity (default: its STOCK location)
    release_location_id: uuid.UUID | None = None


class InspectionCreate(BaseModel):
    """An inspection of stock already in a warehouse's QC hold (returns, holds placed by hand)."""

    model_config = ConfigDict(extra="forbid")

    product_id: uuid.UUID
    warehouse_id: uuid.UUID
    quantity: Annotated[DecimalStr, Field(gt=0)]
    unit: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=16)] | None = None
    lot_id: uuid.UUID | None = None
    note: Text | None = None


class Versioned(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)] | None = (
        None
    )


class InspectionProduct(BaseModel):
    id: uuid.UUID
    product_key: str
    name: str


class InspectionWarehouse(BaseModel):
    id: uuid.UUID
    code: str
    name: str


class InspectionSummary(BaseModel):
    id: uuid.UUID
    inspection_number: str
    status: InspectionStatus
    subject_type: SubjectType
    subject_id: uuid.UUID
    subject_label: str
    source_path: str | None
    product: InspectionProduct
    warehouse: InspectionWarehouse
    lot_code: str | None
    quantity: DecimalStr
    unit: str
    qty_accepted: DecimalStr
    qty_rejected: DecimalStr
    requested_at: datetime
    decided_at: datetime | None
    path: str
    version: int


class InspectionDetail(InspectionSummary):
    checklist: list[ChecklistItem]
    findings: str | None
    reject_reason_code: str | None
    decided_by_name: str | None
    posting_id: uuid.UUID | None
    work_order_id: uuid.UUID | None
    #: the default checklist offered for a new decision
    suggested_checklist: list[ChecklistItem]
    capabilities: dict[str, Capability]
