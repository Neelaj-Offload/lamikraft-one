"""Typed payloads for party events (docs/architecture/events.md §3.5) and the party number sequence."""

from __future__ import annotations

import uuid

from pydantic import BaseModel

from app.platform.numbering.defs import SequenceDef

PARTY_CREATED = "parties.party.created"
PARTY_UPDATED = "parties.party.updated"
PARTY_ARCHIVED = "parties.party.archived"

#: P-NNNNN, never reset (fixtures.md §6)
PARTY_SEQUENCE = SequenceDef(
    key="parties.party",
    name="Party number",
    format_template="P-{seq:05}",
    reset_policy="never",
    resource_type="parties.party",
)


class PartyCreatedPayload(BaseModel):
    party_id: uuid.UUID
    party_number: str
    owner_user_id: uuid.UUID
    origin: str | None = None


class PartyUpdatedPayload(BaseModel):
    party_id: uuid.UUID
    party_number: str
    #: field names; child lists report ``contacts``, ``tax_identifiers`` and ``addresses.<kind>``
    changed_fields: list[str]
    origin: str | None = None


class PartyArchivedPayload(BaseModel):
    party_id: uuid.UUID
    origin: str | None = None


def payload(model: BaseModel) -> dict[str, object]:
    return model.model_dump(mode="json", exclude_none=True)


# ---- lead pipeline (CRM programme module 1) -------------------------------------------------------------------
LEAD_STAGE_CHANGED = "parties.lead.stage_changed"
ACTIVITY_LOGGED = "parties.activity.logged"


class LeadStageChangedPayload(BaseModel):
    party_id: uuid.UUID
    from_stage: str | None
    to_stage: str


class ActivityLoggedPayload(BaseModel):
    party_id: uuid.UUID
    activity_id: uuid.UUID
    kind: str
    next_follow_up_on: str | None = None
