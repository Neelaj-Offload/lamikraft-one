"""Typed payloads for the sales events (names and fields frozen in docs/architecture/events.md §3.6) and the
document-number sequences (fixtures.md §6). Payloads carry ids, numbers and codes only: never amounts or text."""

from __future__ import annotations

import uuid
from datetime import date

from pydantic import BaseModel

from app.platform.numbering.defs import SequenceDef

ENQUIRY_RECEIVED = "sales.enquiry.received"
ENQUIRY_ASSIGNED = "sales.enquiry.assigned"
ENQUIRY_QUOTED = "sales.enquiry.quoted"
ENQUIRY_CLOSED = "sales.enquiry.closed"
MESSAGE_RECEIVED = "sales.customer_message.received"
MESSAGE_REPLIED = "sales.customer_message.replied"
QUOTE_CREATED = "sales.quote.created"
QUOTE_UPDATED = "sales.quote.updated"
QUOTE_REVIEW_REQUESTED = "sales.quote.review_requested"
QUOTE_REVIEW_WITHDRAWN = "sales.quote.review_withdrawn"
QUOTE_ISSUED = "sales.quote.issued"
QUOTE_MARKED_SENT = "sales.quote.marked_sent"
QUOTE_WON = "sales.quote.won"
QUOTE_LOST = "sales.quote.lost"
QUOTE_CANCELLED = "sales.quote.cancelled"
QUOTE_DELETED = "sales.quote.deleted"
QUOTE_STATUS_CHANGED = "sales.quote.status_changed"

#: every event this module emits in Slice 1 (contract test: all are in the frozen catalogue)
EMITTED_EVENTS: tuple[str, ...] = (
    ENQUIRY_RECEIVED, ENQUIRY_ASSIGNED, ENQUIRY_QUOTED, ENQUIRY_CLOSED, MESSAGE_RECEIVED, MESSAGE_REPLIED,
    QUOTE_CREATED, QUOTE_UPDATED, QUOTE_REVIEW_REQUESTED, QUOTE_REVIEW_WITHDRAWN, QUOTE_ISSUED, QUOTE_MARKED_SENT,
    QUOTE_WON, QUOTE_LOST, QUOTE_CANCELLED, QUOTE_DELETED, QUOTE_STATUS_CHANGED,
)

#: ``{brand}-QT-{yyyy}-{seq:04}``, never reset (legacy continuity; owner to confirm) — one counter shared by brands
QUOTE_SEQUENCE = SequenceDef(
    key="sales.quote",
    name="Quotation number",
    format_template="{brand}-QT-{yyyy}-{seq:04}",
    reset_policy="never",
    resource_type="sales.quote",
)
#: ``ENQ-{yyyy}-{seq:04}``, reset yearly (document date = business date in the company zone)
ENQUIRY_SEQUENCE = SequenceDef(
    key="sales.enquiry",
    name="Enquiry number",
    format_template="ENQ-{yyyy}-{seq:04}",
    reset_policy="yearly",
    resource_type="sales.enquiry",
)


class EnquiryReceivedPayload(BaseModel):
    enquiry_id: uuid.UUID
    enquiry_number: str
    party_id: uuid.UUID
    channel: str
    owner_user_id: uuid.UUID
    origin: str | None = None


class EnquiryAssignedPayload(BaseModel):
    enquiry_id: uuid.UUID
    from_user_id: uuid.UUID
    to_user_id: uuid.UUID
    origin: str | None = None


class EnquiryQuotedPayload(BaseModel):
    enquiry_id: uuid.UUID
    quote_id: uuid.UUID
    origin: str | None = None


class EnquiryClosedPayload(BaseModel):
    enquiry_id: uuid.UUID
    outcome_code: str
    origin: str | None = None


class MessageReceivedPayload(BaseModel):
    message_id: uuid.UUID
    party_id: uuid.UUID
    contact_id: uuid.UUID | None
    channel: str
    assignee_user_id: uuid.UUID
    enquiry_id: uuid.UUID | None
    quote_id: uuid.UUID | None
    origin: str | None = None


class MessageRepliedPayload(BaseModel):
    message_id: uuid.UUID
    reply_ref_type: str
    reply_ref_id: uuid.UUID | None
    origin: str | None = None


class QuoteCreatedPayload(BaseModel):
    quote_id: uuid.UUID
    quote_number: str
    owner_user_id: uuid.UUID
    branch_id: uuid.UUID | None
    party_id: uuid.UUID
    enquiry_id: uuid.UUID | None
    origin_message_id: uuid.UUID | None
    duplicated_from_quote_id: uuid.UUID | None = None
    origin: str | None = None


class QuoteUpdatedPayload(BaseModel):
    quote_id: uuid.UUID
    version: int
    changed_fields: list[str]
    line_change_kinds: list[str]
    origin: str | None = None


class QuoteProposalPayload(BaseModel):
    quote_id: uuid.UUID
    proposal_id: uuid.UUID
    origin: str | None = None


class QuoteIssuedPayload(BaseModel):
    quote_id: uuid.UUID
    revision_id: uuid.UUID
    revision_no: int
    valid_until: date
    origin: str | None = None


class QuoteMarkedSentPayload(BaseModel):
    quote_id: uuid.UUID
    revision_id: uuid.UUID
    dispatch_id: uuid.UUID
    origin: str | None = None


class QuoteWonPayload(BaseModel):
    quote_id: uuid.UUID
    accepted_revision_id: uuid.UUID
    origin: str | None = None


class QuoteReasonPayload(BaseModel):
    quote_id: uuid.UUID
    reason_code: str
    origin: str | None = None


class QuoteDeletedPayload(BaseModel):
    quote_id: uuid.UUID
    origin: str | None = None


class QuoteStatusChangedPayload(BaseModel):
    quote_id: uuid.UUID
    version: int
    action: str
    from_status: str
    to_status: str
    origin: str | None = None


def payload(model: BaseModel) -> dict[str, object]:
    """JSON payload; ``origin`` is omitted when unset so the platform fills it from the actor type."""
    data = model.model_dump(mode="json")
    if data.get("origin") is None:
        data.pop("origin", None)
    return data
