"""Source readers (``sales.quote``, ``sales.customer_message``, ``sales.enquiry``) for tasks, briefings and the
agent (``app.platform.sources``). They expose ids, numbers, names, status, dates and the persisted money facts;
never message bodies. Visibility follows the resource policies (an invisible record reads as ``None``)."""

from __future__ import annotations

import uuid
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.core.errors import AppError, NotFound
from app.core.money import quantize_money
from app.modules.sales.common import company_zone, contact_of, enquiry_path, message_path, quote_path
from app.modules.sales.models import CustomerMessage, Enquiry, Quote
from app.modules.sales.schemas import CLOSED_STATUSES, EnquiryStatus
from app.platform.sources import MoneyFact, SourceFacts
from app.platform.uow import UnitOfWork

UTC = ZoneInfo("UTC")


def valid_until_end(valid_until: datetime | None, zone: str) -> datetime | None:
    """The instant the validity ends: the start of the next local day in the company zone, as UTC."""
    if valid_until is None:
        return None
    day = valid_until.date() if isinstance(valid_until, datetime) else valid_until
    return datetime.combine(day + timedelta(days=1), time(0, 0), tzinfo=ZoneInfo(zone)).astimezone(UTC)


def _quote_number(uow: UnitOfWork, quote_id: uuid.UUID | None) -> str | None:
    if quote_id is None:
        return None
    return uow.session.scalar(select(Quote.quote_number).where(Quote.id == quote_id, Quote.company_id == uow.actor.company_id))


def read_quote_facts(uow: UnitOfWork, quote_id: uuid.UUID) -> SourceFacts | None:
    try:
        q = uow.repo(Quote).get(quote_id, include_archived=True)
    except NotFound:
        return None
    if q.deleted_at is not None:
        return None
    zone = company_zone(uow)
    deadlines: dict[str, datetime] = {}
    if q.status == "sent" and q.valid_until is not None:
        end = valid_until_end(q.valid_until, zone)  # type: ignore[arg-type]
        if end is not None:
            deadlines["valid_until_end"] = end
    # the grand total in the currency's minor units ("5700.00"), the same text the API Money shape carries
    money = (
        [MoneyFact(amount=format(quantize_money(q.grand_total_amount, q.currency), "f"), currency=q.currency)]
        if q.grand_total_amount is not None
        else []
    )
    return SourceFacts(
        source_type="sales.quote",
        source_id=q.id,
        version=q.version,
        label=f"{q.quote_number} · {q.party_name}",
        status=q.status,
        owner_user_id=q.owner_user_id,
        branch_id=q.branch_id,
        required_permission="sales.quote.read",
        canonical_path=quote_path(q.id),
        is_closed=q.status in {s.value for s in CLOSED_STATUSES},
        updated_at=q.updated_at,
        deadlines=deadlines,
        facts={
            "quote_number": q.quote_number,
            "party_name": q.party_name,
            "party_id": str(q.party_id),
            "party_country": q.party_country,
            "currency": q.currency,
            "status": q.status,
            "revision_no": q.revision_no,
            "line_count": q.line_count,
            "valid_until": q.valid_until.isoformat() if q.valid_until else None,
            "issued_at": q.issued_at.isoformat() if q.issued_at else None,
            "sent_at": q.sent_at.isoformat() if q.sent_at else None,
            "won_at": q.won_at.isoformat() if q.won_at else None,
            "created_at": q.created_at.isoformat(),
            "origin": q.origin,
            "origin_message_id": str(q.origin_message_id) if q.origin_message_id else None,
            "enquiry_id": str(q.enquiry_id) if q.enquiry_id else None,
            "has_price_override": q.has_price_override,
            "has_discount": q.has_discount,
            "below_minimum": q.minimum_status == "BELOW",
            "review_proposal_id": str(q.review_proposal_id) if q.review_proposal_id else None,
            "approved_proposal_id": str(q.approved_proposal_id) if q.approved_proposal_id else None,
        },
        money=money,
    )


def read_message_facts(uow: UnitOfWork, message_id: uuid.UUID) -> SourceFacts | None:
    try:
        m = uow.repo(CustomerMessage).get(message_id)
    except NotFound:
        return None
    contact_name = None
    if m.contact_id is not None:
        try:
            contact = contact_of(uow, m.party_id, m.contact_id)
            contact_name = contact.name if contact else None
        except AppError:  # the party or contact is no longer readable; the label degrades gracefully
            contact_name = None
    party_name = uow.session.scalar(select(Quote.party_name).where(Quote.party_id == m.party_id, Quote.company_id == m.company_id).limit(1))
    if party_name is None:
        from app.modules.parties import service as parties

        labels = parties.party_labels(uow, [m.party_id])
        party_name = labels[m.party_id][1] if m.party_id in labels else "customer"
    linked_number = _quote_number(uow, m.quote_id)
    label = f"Message from {contact_name} ({party_name})" if contact_name else f"Message from {party_name}"
    return SourceFacts(
        source_type="sales.customer_message",
        source_id=m.id,
        version=m.version,
        label=label,
        status=m.status,
        owner_user_id=m.assignee_user_id,
        branch_id=m.branch_id,
        required_permission="sales.customer_message.read",
        canonical_path=message_path(m.id),
        is_closed=m.status == "replied",
        updated_at=m.updated_at,
        facts={
            "party_id": str(m.party_id),
            "party_name": party_name,
            "contact_name": contact_name,
            "channel": m.channel,
            "subject": m.subject,
            "received_at": m.received_at.isoformat(),
            "replied_at": m.replied_at.isoformat() if m.replied_at else None,
            "enquiry_id": str(m.enquiry_id) if m.enquiry_id else None,
            "linked_quote_ids": [str(m.quote_id)] if m.quote_id else [],
            "linked_quote_number": linked_number,
        },
    )


def read_enquiry_facts(uow: UnitOfWork, enquiry_id: uuid.UUID) -> SourceFacts | None:
    try:
        e = uow.repo(Enquiry).get(enquiry_id)
    except NotFound:
        return None
    from app.modules.parties import service as parties

    labels = parties.party_labels(uow, [e.party_id])
    party_name = labels[e.party_id][1] if e.party_id in labels else "customer"
    linked_number = _quote_number(uow, e.quote_id)
    return SourceFacts(
        source_type="sales.enquiry",
        source_id=e.id,
        version=e.version,
        label=f"{e.enquiry_number} · {party_name}",
        status=e.status,
        owner_user_id=e.owner_user_id,
        branch_id=e.branch_id,
        required_permission="sales.enquiry.read",
        canonical_path=enquiry_path(e.id),
        is_closed=e.status in (EnquiryStatus.QUOTED.value, EnquiryStatus.CLOSED.value),
        updated_at=e.updated_at,
        facts={
            "enquiry_number": e.enquiry_number,
            "party_id": str(e.party_id),
            "party_name": party_name,
            "channel": e.channel,
            "subject": e.subject,
            "received_at": e.received_at.isoformat(),
            "outcome_code": e.outcome_code,
            "linked_quote_id": str(e.quote_id) if e.quote_id else None,
            "linked_quote_number": linked_number,
        },
    )


READERS = {
    "sales.quote": read_quote_facts,
    "sales.customer_message": read_message_facts,
    "sales.enquiry": read_enquiry_facts,
}
