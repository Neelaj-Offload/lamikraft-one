"""Challan events (names and fields frozen in docs/architecture/events.md §3.9), the ``DC-YYYY-NNNN`` sequence and
the ``challan_defaults`` setting. Payloads carry ids, numbers and codes only: never text or quantities."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.platform.numbering.defs import SequenceDef
from app.platform.org.settings import SettingDef

CHALLAN_ISSUED = "challans.challan.issued"
CHALLAN_CLOSED = "challans.challan.closed"
CHALLAN_CANCELLED = "challans.challan.cancelled"
RETURN_RECEIVED = "challans.return.received"
RETURNABLE_DUE = "challans.returnable.became_due"
RETURNABLE_OVERDUE = "challans.returnable.became_overdue"

#: every event this module emits in Slice 2 (contract test: all are in the frozen catalogue). The two scheduled
#: events come from the ``challans.returnables_sweep`` job; the ``ops.returnables`` rule family that consumes them
#: lives in the tasks module (work lane) and is documented in docs/lanes/challans-s2.md.
EMITTED_EVENTS: tuple[str, ...] = (
    CHALLAN_ISSUED,
    CHALLAN_CLOSED,
    CHALLAN_CANCELLED,
    RETURN_RECEIVED,
    RETURNABLE_DUE,
    RETURNABLE_OVERDUE,
)

#: ``DC-{yyyy}-{seq:04}``, reset yearly by the challan date in the company zone (legacy continuity; BR-08, BUG-13)
CHALLAN_SEQUENCE = SequenceDef(
    key="challans.challan",
    name="Delivery challan number",
    format_template="DC-{yyyy}-{seq:04}",
    reset_policy="yearly",
    resource_type="challans.challan",
)


class ChallanIssuedPayload(BaseModel):
    challan_id: uuid.UUID
    challan_number: str
    challan_type: str
    return_type: str
    destination_type: str
    party_id: uuid.UUID | None
    inventory_effect: str
    posting_id: uuid.UUID | None = None
    sample_id: uuid.UUID | None = None


class ChallanClosedPayload(BaseModel):
    challan_id: uuid.UUID


class ChallanCancelledPayload(BaseModel):
    challan_id: uuid.UUID
    reason_code: str
    reversal_posting_id: uuid.UUID | None = None


class ReturnReceivedPayload(BaseModel):
    return_challan_id: uuid.UUID
    original_challan_id: uuid.UUID
    original_line_ids: list[uuid.UUID]


class ReturnableDuePayload(BaseModel):
    challan_id: uuid.UUID
    expected_return_date: date


def payload(model: BaseModel) -> dict[str, object]:
    return model.model_dump(mode="json")


# ---- the challan defaults setting (UI-78: default source location from settings) ----------------------------
class ChallanDefaults(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    #: printed FROM text of a new challan (legacy hard-coded "Crown / Lamikraft Office")
    source_location: Annotated[str, StringConstraints(min_length=1, max_length=200)] = (
        "Crown / Lamikraft Office"
    )
    #: days after the challan date proposed as the expected return date of returnable challans (0: none)
    expected_return_days: int = Field(default=14, ge=0, le=365)


CHALLAN_DEFAULTS = SettingDef(
    key="challan_defaults",
    model=ChallanDefaults,
    description="Defaults for new delivery challans: printed source location and expected return days",
    read_permission="org.settings.read",
    manage_permission="org.settings.manage",
    owner_module="challans",
)
