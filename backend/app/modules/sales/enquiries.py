"""Enquiries and customer messages (ADR-036).

Bodies are external content: stored as written by the customer and never turned into rule facts (the readers
expose only ids, numbers, names, channel and dates). Enquiry numbers come from the ``sales.enquiry`` sequence
(``ENQ-{yyyy}-{seq:04}``, yearly); messages have no business number.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ColumnElement, or_, select

from app.core.db.base import new_id
from app.core.errors import AppError, Forbidden
from app.core.http.pagination import MAX_LIMIT, Page
from app.core.text import LIKE_ESCAPE, contains_pattern, tokens
from app.modules.sales import events as ev
from app.modules.sales.common import (
    Errors,
    business_date,
    check_member,
    contact_of,
    enquiry_path,
    idempotent,
    message_path,
    party_ref,
    party_refs,
    user_refs,
)
from app.modules.sales.models import CustomerMessage, Enquiry, Quote
from app.modules.sales.schemas import (
    Capability,
    CustomerMessageCreate,
    CustomerMessageFilters,
    CustomerMessageRead,
    CustomerMessageUpdate,
    EnquiryCreate,
    EnquiryFilters,
    EnquiryRead,
    EnquiryStatus,
    EnquiryUpdate,
    MarkReplied,
    MessageStatus,
    TransitionRead,
)
from app.platform.service import query
from app.platform.uow import UnitOfWork

ENQUIRY_READ = "sales.enquiry.read"
MESSAGE_READ = "sales.customer_message.read"


def _quote_numbers(uow: UnitOfWork, ids: list[uuid.UUID | None]) -> dict[uuid.UUID, str]:
    wanted = {i for i in ids if i is not None}
    if not wanted:
        return {}
    rows = uow.session.execute(select(Quote.id, Quote.quote_number).where(Quote.id.in_(wanted))).all()
    return {r[0]: r[1] for r in rows}


# =====================================================================================================
# enquiries
# =====================================================================================================
def _enquiry_read(uow: UnitOfWork, rows: list[Enquiry]) -> list[EnquiryRead]:
    if not rows:
        return []
    users = user_refs(uow, [e.owner_user_id for e in rows])
    numbers = _quote_numbers(uow, [e.quote_id for e in rows])
    refs = party_refs(uow, [e.party_id for e in rows], {})
    repo = uow.repo(Enquiry)
    out: list[EnquiryRead] = []
    for e in rows:
        caps = repo.capabilities(e, ["update"])
        can_assign = uow.actor.can("sales.enquiry.assign") and e.status != EnquiryStatus.CLOSED.value
        caps["assign"] = {"allowed": can_assign, "reason_code": None if can_assign else "permission_denied"}
        out.append(
            EnquiryRead(
                id=e.id,
                enquiry_number=e.enquiry_number,
                party=refs[e.party_id],
                contact_id=e.contact_id,
                channel=e.channel,  # type: ignore[arg-type]
                received_at=e.received_at,
                owner=users[e.owner_user_id],
                branch_id=e.branch_id,
                subject=e.subject,
                body=e.body,
                status=EnquiryStatus(e.status),
                outcome_code=e.outcome_code,
                quote_id=e.quote_id,
                quote_number=numbers.get(e.quote_id) if e.quote_id else None,
                closed_at=e.closed_at,
                created_at=e.created_at,
                updated_at=e.updated_at,
                version=e.version,
                path=enquiry_path(e.id),
                capabilities={k: Capability(**v) for k, v in caps.items()},
                allowed_transitions=(
                    [TransitionRead(action="close", to_status="closed", requires_reason=True)]
                    if caps["update"]["allowed"]
                    else []
                ),
            )
        )
    return out


def create_enquiry(uow: UnitOfWork, data: EnquiryCreate, *, origin: str | None = None, origin_ref: str | None = None) -> EnquiryRead:
    actor = uow.actor
    actor.require("sales.enquiry.create")
    errors = Errors()
    party = party_ref(uow, data.party_id)
    owner_id = data.owner_user_id or actor.user_id
    if owner_id is None:
        errors.add(["owner_user_id"], "required", "An enquiry needs an owner")
        errors.raise_if_any()
    assert owner_id is not None
    if owner_id != actor.user_id and not actor.can("sales.enquiry.assign"):
        raise Forbidden("Assigning an enquiry to someone else needs sales.enquiry.assign", code="permission_denied",
                        permission="sales.enquiry.assign")
    check_member(uow, owner_id, errors, "owner_user_id")
    errors.raise_if_any()
    contact = contact_of(uow, party.id, data.contact_id) if data.contact_id else None
    received_at = data.received_at or uow.now()
    row = Enquiry(
        id=new_id(),
        company_id=actor.company_id,
        party_id=party.id,
        contact_id=contact.id if contact else None,
        channel=data.channel.value,
        received_at=received_at,
        owner_user_id=owner_id,
        branch_id=data.branch_id or party.branch_id,
        subject=data.subject,
        body=data.body,
        status=EnquiryStatus.ASSIGNED.value if owner_id != actor.user_id else EnquiryStatus.RECEIVED.value,
        origin_ref=origin_ref,
    )
    row.enquiry_number = uow.allocate_number(
        ev.ENQUIRY_SEQUENCE.key,
        document_date=business_date(uow),
        resource_type="sales.enquiry",
        resource_id=row.id,
    )
    uow.add(row)
    uow.flush()
    uow.emit(
        ev.ENQUIRY_RECEIVED,
        aggregate_id=row.id,
        aggregate_version=row.version,
        payload=ev.payload(
            ev.EnquiryReceivedPayload(
                enquiry_id=row.id, enquiry_number=row.enquiry_number, party_id=party.id, channel=row.channel,
                owner_user_id=owner_id, origin=origin,
            )
        ),
    )
    uow.audit("sales.enquiry.created", resource_type="sales.enquiry", resource_id=row.id, resource_label=row.enquiry_number)
    return _enquiry_read(uow, [row])[0]


def update_enquiry(uow: UnitOfWork, enquiry_id: uuid.UUID, data: EnquiryUpdate, *, origin: str | None = None) -> EnquiryRead:
    actor = uow.actor
    row = uow.repo(Enquiry).get(enquiry_id, "update", for_update=True)
    uow.expect_version(row, data.expected_version)
    errors = Errors()
    fields = data.model_dump(exclude_unset=True, exclude={"expected_version"})
    changed = False
    if "contact_id" in fields and fields["contact_id"] != row.contact_id:
        contact = contact_of(uow, row.party_id, fields["contact_id"]) if fields["contact_id"] else None
        row.contact_id = contact.id if contact else None
        changed = True
    for name in ("subject", "body"):
        if name in fields and getattr(row, name) != fields[name]:
            setattr(row, name, fields[name])
            changed = True
    new_owner = fields.get("owner_user_id")
    if new_owner is not None and new_owner != row.owner_user_id:
        actor.require("sales.enquiry.assign")
        check_member(uow, new_owner, errors, "owner_user_id")
        errors.raise_if_any()
        previous = row.owner_user_id
        row.owner_user_id = new_owner
        if row.status == EnquiryStatus.RECEIVED.value:
            row.status = EnquiryStatus.ASSIGNED.value
        changed = True
        uow.flush()
        uow.emit(
            ev.ENQUIRY_ASSIGNED,
            aggregate_id=row.id,
            aggregate_version=row.version,
            payload=ev.payload(ev.EnquiryAssignedPayload(enquiry_id=row.id, from_user_id=previous, to_user_id=new_owner, origin=origin)),
        )
    if fields.get("status") == "closed":
        if not data.outcome_code:
            errors.add(["outcome_code"], "required", "Closing an enquiry needs an outcome code")
            errors.raise_if_any()
        row.status = EnquiryStatus.CLOSED.value
        row.outcome_code = data.outcome_code
        row.closed_at = uow.now()
        changed = True
        uow.flush()
        uow.emit(
            ev.ENQUIRY_CLOSED,
            aggregate_id=row.id,
            aggregate_version=row.version,
            payload=ev.payload(ev.EnquiryClosedPayload(enquiry_id=row.id, outcome_code=data.outcome_code or "", origin=origin)),
        )
    if changed:
        row.updated_at = uow.now()
        uow.flush()
        uow.audit("sales.enquiry.updated", resource_type="sales.enquiry", resource_id=row.id, resource_label=row.enquiry_number)
    return _enquiry_read(uow, [row])[0]


def mark_enquiry_quoted(uow: UnitOfWork, enquiry_id: uuid.UUID, quote: Quote, *, origin: str | None = None) -> None:
    """Link a new quote to its enquiry (called by ``create_quote`` inside the same transaction)."""
    row = uow.repo(Enquiry).get(enquiry_id, "update", for_update=True)
    row.quote_id = quote.id
    row.status = EnquiryStatus.QUOTED.value
    row.updated_at = uow.now()
    uow.flush()
    uow.emit(
        ev.ENQUIRY_QUOTED,
        aggregate_id=row.id,
        aggregate_version=row.version,
        payload=ev.payload(ev.EnquiryQuotedPayload(enquiry_id=row.id, quote_id=quote.id, origin=origin)),
    )


@query(ENQUIRY_READ)
def get_enquiry(uow: UnitOfWork, enquiry_id: uuid.UUID) -> EnquiryRead:
    return _enquiry_read(uow, [uow.repo(Enquiry).get(enquiry_id)])[0]


def _enquiry_conditions(uow: UnitOfWork, f: EnquiryFilters) -> list[ColumnElement[bool]]:
    conds: list[ColumnElement[bool]] = []
    if f.q:
        for tok in tokens(f.q):
            conds.append(
                or_(
                    Enquiry.enquiry_number.ilike(contains_pattern(tok), escape=LIKE_ESCAPE),
                    Enquiry.subject.ilike(contains_pattern(tok), escape=LIKE_ESCAPE),
                )
            )
    if f.status:
        conds.append(Enquiry.status.in_([s.value for s in f.status]))
    if f.owner_user_id:
        conds.append(Enquiry.owner_user_id == f.owner_user_id)
    if f.party_id:
        conds.append(Enquiry.party_id == f.party_id)
    return conds


@query(ENQUIRY_READ)
def list_enquiries(uow: UnitOfWork, filters: EnquiryFilters, *, limit: int = 50, offset: int = 0) -> Page[EnquiryRead]:
    page = uow.repo(Enquiry).list(
        *_enquiry_conditions(uow, filters),
        order_by=[Enquiry.received_at.desc(), Enquiry.id.desc()],
        limit=max(1, min(limit, MAX_LIMIT)),
        offset=max(0, offset),
    )
    return Page[EnquiryRead](items=_enquiry_read(uow, page.items), total=page.total, limit=page.limit, offset=page.offset)


def create_enquiry_command(uow: UnitOfWork, data: EnquiryCreate) -> tuple[EnquiryRead, bool]:
    uow.actor.require("sales.enquiry.create")
    return idempotent(uow, "sales.create_enquiry", data, lambda: create_enquiry(uow, data), EnquiryRead, status=201)


def update_enquiry_command(uow: UnitOfWork, enquiry_id: uuid.UUID, data: EnquiryUpdate) -> tuple[EnquiryRead, bool]:
    uow.repo(Enquiry).get(enquiry_id, "update")
    return idempotent(uow, f"sales.update_enquiry:{enquiry_id}", data, lambda: update_enquiry(uow, enquiry_id, data), EnquiryRead)


# =====================================================================================================
# customer messages
# =====================================================================================================
def _message_read(uow: UnitOfWork, rows: list[CustomerMessage]) -> list[CustomerMessageRead]:
    if not rows:
        return []
    users = user_refs(uow, [m.assignee_user_id for m in rows])
    numbers = _quote_numbers(uow, [m.quote_id for m in rows])
    refs = party_refs(uow, [m.party_id for m in rows], {})
    contact_names: dict[uuid.UUID, str] = {}
    for m in rows:
        if m.contact_id and m.contact_id not in contact_names:
            try:
                contact = contact_of(uow, m.party_id, m.contact_id)
            except AppError:  # the party is no longer visible, or the contact was removed from it
                contact = None
            if contact is not None:
                contact_names[m.contact_id] = contact.name
    repo = uow.repo(CustomerMessage)
    out: list[CustomerMessageRead] = []
    for m in rows:
        caps = repo.capabilities(m, ["update"])
        can_reply = caps["update"]["allowed"]
        caps["mark_replied"] = dict(caps["update"])
        out.append(
            CustomerMessageRead(
                id=m.id,
                party=refs[m.party_id],
                contact_id=m.contact_id,
                contact_name=contact_names.get(m.contact_id) if m.contact_id else None,
                channel=m.channel,  # type: ignore[arg-type]
                received_at=m.received_at,
                assignee=users[m.assignee_user_id],
                branch_id=m.branch_id,
                enquiry_id=m.enquiry_id,
                quote_id=m.quote_id,
                quote_number=numbers.get(m.quote_id) if m.quote_id else None,
                subject=m.subject,
                body=m.body,
                status=MessageStatus(m.status),
                replied_at=m.replied_at,
                reply_ref_type=m.reply_ref_type,
                reply_ref_id=m.reply_ref_id,
                created_at=m.created_at,
                updated_at=m.updated_at,
                version=m.version,
                path=message_path(m.id),
                capabilities={k: Capability(**v) for k, v in caps.items()},
                allowed_transitions=(
                    [TransitionRead(action="mark_replied", to_status="replied", requires_reason=False)] if can_reply else []
                ),
            )
        )
    return out


def record_customer_message(
    uow: UnitOfWork, data: CustomerMessageCreate, *, origin: str | None = None, origin_ref: str | None = None
) -> CustomerMessageRead:
    """Record an inbound customer message (UI, channels webhook processing, seeds); emits ``received``."""
    actor = uow.actor
    actor.require("sales.customer_message.create")
    errors = Errors()
    party = party_ref(uow, data.party_id)
    assignee = data.assignee_user_id or actor.user_id or party.owner_user_id
    check_member(uow, assignee, errors, "assignee_user_id")
    errors.raise_if_any()
    contact = contact_of(uow, party.id, data.contact_id)
    if data.enquiry_id is not None:
        uow.repo(Enquiry).get(data.enquiry_id)
    if data.quote_id is not None:
        uow.repo(Quote).get(data.quote_id, include_archived=False)
    row = CustomerMessage(
        id=new_id(),
        company_id=actor.company_id,
        party_id=party.id,
        contact_id=contact.id if contact else None,
        channel=data.channel.value,
        received_at=data.received_at or uow.now(),
        assignee_user_id=assignee,
        branch_id=data.branch_id or party.branch_id,
        enquiry_id=data.enquiry_id,
        quote_id=data.quote_id,
        subject=data.subject,
        body=data.body,
        status=MessageStatus.RECEIVED.value,
        origin_ref=origin_ref,
    )
    uow.add(row)
    uow.flush()
    uow.emit(
        ev.MESSAGE_RECEIVED,
        aggregate_id=row.id,
        aggregate_version=row.version,
        payload=ev.payload(
            ev.MessageReceivedPayload(
                message_id=row.id, party_id=party.id, contact_id=row.contact_id, channel=row.channel,
                assignee_user_id=assignee, enquiry_id=row.enquiry_id, quote_id=row.quote_id, origin=origin,
            )
        ),
    )
    uow.audit("sales.customer_message.received", resource_type="sales.customer_message", resource_id=row.id,
              resource_label=f"Message from {party.display_name}")
    return _message_read(uow, [row])[0]


def update_customer_message(uow: UnitOfWork, message_id: uuid.UUID, data: CustomerMessageUpdate) -> CustomerMessageRead:
    row = uow.repo(CustomerMessage).get(message_id, "update", for_update=True)
    uow.expect_version(row, data.expected_version)
    errors = Errors()
    fields = data.model_dump(exclude_unset=True, exclude={"expected_version"})
    changed = False
    if fields.get("assignee_user_id") is not None and fields["assignee_user_id"] != row.assignee_user_id:
        check_member(uow, fields["assignee_user_id"], errors, "assignee_user_id")
        errors.raise_if_any()
        row.assignee_user_id = fields["assignee_user_id"]
        changed = True
    if "enquiry_id" in fields and fields["enquiry_id"] != row.enquiry_id:
        if fields["enquiry_id"] is not None:
            uow.repo(Enquiry).get(fields["enquiry_id"])
        row.enquiry_id = fields["enquiry_id"]
        changed = True
    if "quote_id" in fields and fields["quote_id"] != row.quote_id:
        if fields["quote_id"] is not None:
            uow.repo(Quote).get(fields["quote_id"], include_archived=False)
        row.quote_id = fields["quote_id"]
        changed = True
    if "subject" in fields and fields["subject"] != row.subject:
        row.subject = fields["subject"]
        changed = True
    if changed:
        row.updated_at = uow.now()
        uow.flush()
        uow.audit("sales.customer_message.updated", resource_type="sales.customer_message", resource_id=row.id)
    return _message_read(uow, [row])[0]


def mark_replied(uow: UnitOfWork, message_id: uuid.UUID, data: MarkReplied, *, origin: str | None = None) -> CustomerMessageRead:
    row = uow.repo(CustomerMessage).get(message_id, "update", for_update=True)
    uow.expect_version(row, data.expected_version)
    row.status = MessageStatus.REPLIED.value
    row.replied_at = uow.now()
    row.reply_ref_type = data.reply_ref_type
    row.reply_ref_id = data.reply_ref_id
    row.updated_at = uow.now()
    uow.flush()
    uow.emit(
        ev.MESSAGE_REPLIED,
        aggregate_id=row.id,
        aggregate_version=row.version,
        payload=ev.payload(
            ev.MessageRepliedPayload(message_id=row.id, reply_ref_type=row.reply_ref_type or "manual",
                                     reply_ref_id=row.reply_ref_id, origin=origin)
        ),
    )
    uow.audit("sales.customer_message.replied", resource_type="sales.customer_message", resource_id=row.id)
    return _message_read(uow, [row])[0]


def link_quote_to_message(uow: UnitOfWork, message_id: uuid.UUID, quote: Quote) -> None:
    """Record the draft created from a message as its linked quote (``draft_quote`` with ``origin_message_id``)."""
    row = uow.repo(CustomerMessage).get(message_id, for_update=True)
    if row.quote_id is None:
        row.quote_id = quote.id
        row.updated_at = uow.now()
        uow.flush()


@query(MESSAGE_READ)
def get_customer_message(uow: UnitOfWork, message_id: uuid.UUID) -> CustomerMessageRead:
    return _message_read(uow, [uow.repo(CustomerMessage).get(message_id)])[0]


def _message_conditions(f: CustomerMessageFilters) -> list[ColumnElement[bool]]:
    conds: list[ColumnElement[bool]] = []
    if f.status:
        conds.append(CustomerMessage.status.in_([s.value for s in f.status]))
    if f.assignee_user_id:
        conds.append(CustomerMessage.assignee_user_id == f.assignee_user_id)
    if f.party_id:
        conds.append(CustomerMessage.party_id == f.party_id)
    if f.quote_id:
        conds.append(CustomerMessage.quote_id == f.quote_id)
    return conds


@query(MESSAGE_READ)
def list_customer_messages(
    uow: UnitOfWork, filters: CustomerMessageFilters, *, limit: int = 50, offset: int = 0
) -> Page[CustomerMessageRead]:
    page = uow.repo(CustomerMessage).list(
        *_message_conditions(filters),
        order_by=[CustomerMessage.received_at.desc(), CustomerMessage.id.desc()],
        limit=max(1, min(limit, MAX_LIMIT)),
        offset=max(0, offset),
    )
    return Page[CustomerMessageRead](items=_message_read(uow, page.items), total=page.total, limit=page.limit, offset=page.offset)


def create_customer_message_command(uow: UnitOfWork, data: CustomerMessageCreate) -> tuple[CustomerMessageRead, bool]:
    uow.actor.require("sales.customer_message.create")
    return idempotent(uow, "sales.record_customer_message", data, lambda: record_customer_message(uow, data), CustomerMessageRead, status=201)


def update_customer_message_command(uow: UnitOfWork, message_id: uuid.UUID, data: CustomerMessageUpdate) -> tuple[CustomerMessageRead, bool]:
    uow.repo(CustomerMessage).get(message_id, "update")
    return idempotent(uow, f"sales.update_customer_message:{message_id}", data, lambda: update_customer_message(uow, message_id, data), CustomerMessageRead)


def mark_replied_command(uow: UnitOfWork, message_id: uuid.UUID, data: MarkReplied) -> tuple[CustomerMessageRead, bool]:
    uow.repo(CustomerMessage).get(message_id, "update")
    return idempotent(uow, f"sales.mark_replied:{message_id}", data, lambda: mark_replied(uow, message_id, data), CustomerMessageRead)


def message_facts(uow: UnitOfWork, message_id: uuid.UUID) -> dict[str, Any] | None:
    """Internal helper for other sales services (quote drafting from a message)."""
    row = uow.session.scalars(select(CustomerMessage).where(CustomerMessage.id == message_id, uow.repo(CustomerMessage).clause("read"))).first()
    if row is None:
        return None
    return {"id": row.id, "party_id": row.party_id, "quote_id": row.quote_id, "enquiry_id": row.enquiry_id}
