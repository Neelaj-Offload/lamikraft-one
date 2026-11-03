"""Typed payloads for the cutting events (names and fields frozen in docs/architecture/events.md §3.9) and the plan
number sequence (fixtures.md §6). Payloads carry ids, numbers and hashes only."""

from __future__ import annotations

import uuid

from pydantic import BaseModel

from app.platform.numbering.defs import SequenceDef

PLAN_SAVED = "cutting.plan.saved"
PLAN_CALCULATED = "cutting.plan.calculated"
PLAN_VERIFICATION_REQUIRED = "cutting.plan.verification_required"
PLAN_VERIFIED = "cutting.plan.verified"
PLAN_ARCHIVED = "cutting.plan.archived"

#: every event this module emits in Slice 2 (``cutting.plan.released`` arrives with work-order links in Slice 4)
EMITTED_EVENTS: tuple[str, ...] = (PLAN_SAVED, PLAN_CALCULATED, PLAN_VERIFICATION_REQUIRED, PLAN_VERIFIED, PLAN_ARCHIVED)

#: ``CUT-{yyyy}-{seq:04}``, reset yearly by the company-local business date
PLAN_SEQUENCE = SequenceDef(
    key="cutting.plan",
    name="Cut plan number",
    format_template="CUT-{yyyy}-{seq:04}",
    reset_policy="yearly",
    resource_type="cutting.plan",
)


class PlanSavedPayload(BaseModel):
    plan_id: uuid.UUID
    plan_number: str
    owner_user_id: uuid.UUID


class PlanCalculatedPayload(BaseModel):
    plan_id: uuid.UUID
    calculation_id: uuid.UUID
    calc_no: int
    input_hash: str
    requires_physical_verification: bool


class PlanRefPayload(BaseModel):
    plan_id: uuid.UUID


def payload(model: BaseModel) -> dict[str, object]:
    return model.model_dump(mode="json", exclude_none=True)
