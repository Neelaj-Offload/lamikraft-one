"""Agent tools of the channels module (registered through the manifest ``tools`` list, the agents registry API).

``prepare_quote_send`` never sends: it binds the recipient (the party contact's WhatsApp identity), the message
text (built by the server from the issued revision, never from model prose) and the PDF hash into a
``channels.message.send`` proposal. Only another person's approval queues the message (``send_approval``).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.core.errors import ValidationFailed
from app.modules.approvals import service as approvals
from app.modules.approvals.service import TargetRef
from app.modules.channels import events as ev
from app.modules.channels.policies import MESSAGE_SEND
from app.modules.channels.send_approval import latest_revision, render_revision
from app.modules.channels.whatsapp import accounts
from app.modules.channels.whatsapp import identity as identities
from app.modules.channels.whatsapp.render import money
from app.platform.tools import ToolDef
from app.platform.uow import UnitOfWork

PROPOSAL_TTL = timedelta(days=2)


class PrepareQuoteSendInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quote_id: uuid.UUID
    #: a contact of the quote's party with a WhatsApp number; the primary contact with a phone when omitted
    contact_id: uuid.UUID | None = None


class PrepareQuoteSendOutput(BaseModel):
    proposal_id: uuid.UUID
    short_ref: str
    status: str
    title: str
    quote_number: str
    revision_no: int
    recipient_masked: str
    document_sha256: str
    filename: str
    text: str
    expires_at: datetime | None


def _recipient(uow: UnitOfWork, party_id: uuid.UUID, contact_id: uuid.UUID | None) -> tuple[uuid.UUID, str]:
    from app.modules.parties.models import PartyContact

    stmt = select(PartyContact).where(
        PartyContact.company_id == uow.actor.company_id, PartyContact.party_id == party_id, PartyContact.archived_at.is_(None),
        PartyContact.phone.is_not(None),
    )
    if contact_id is not None:
        stmt = stmt.where(PartyContact.id == contact_id)
    contact = uow.session.scalars(stmt.order_by(PartyContact.is_primary.desc(), PartyContact.sort_order, PartyContact.id)).first()
    if contact is None or len(identities.digits(contact.phone)) < 8:
        raise ValidationFailed(
            "The customer has no contact with a WhatsApp number", code="recipient_missing",
            errors=[{"loc": ["body", "contact_id"], "msg": "no WhatsApp number", "type": "recipient_missing"}],
        )
    return contact.id, identities.digits(contact.phone)


def prepare_quote_send(uow: UnitOfWork, data: PrepareQuoteSendInput) -> PrepareQuoteSendOutput:
    from app.modules.sales.models import Quote

    uow.actor.require(MESSAGE_SEND)
    quote = uow.repo(Quote).get(data.quote_id)  # read scope: another user's quote is a 404
    revision = latest_revision(uow, quote.id)
    if revision is None:
        raise ValidationFailed("Issue the quote before sending it to the customer", code="quote_not_issued")
    _pdf, digest, filename = render_revision(revision)
    contact_id, wa_id = _recipient(uow, quote.party_id, data.contact_id)
    account = accounts.ensure_account(uow, purpose="customer_service")
    identity = identities.ensure_customer_identity(uow, account, wa_id=wa_id, bsuid=None, party_id=quote.party_id, contact_id=contact_id)
    totals = (revision.snapshot or {}).get("totals") or {}
    total = money(totals.get("grand_total"), str(totals.get("currency") or quote.currency)) if totals.get("grand_total") is not None else None
    text = f"Quotation {quote.quote_number} (revision {revision.revision_no}) from {accounts.company_label(uow)}" + (f": total {total}." if total else ".")
    content = {
        "kind": ev.SEND_PROPOSAL_KIND, "identity_id": str(identity.id), "quote_id": str(quote.id), "revision_id": str(revision.id),
        "document_sha256": digest, "text": text,
    }
    masked = identities.mask(wa_id) or "WhatsApp"
    proposal = approvals.submit(
        uow,
        kind=ev.SEND_PROPOSAL_KIND,
        targets=[TargetRef("sales.quote", quote.id, quote.version), TargetRef("channels.identity", identity.id, identity.version)],
        content=content,
        title=f"Send {quote.quote_number} to {quote.party_name} on WhatsApp",
        summary=f"{filename} to {masked}",
        facts={**content, "recipient_masked": masked, "filename": filename, "quote_number": quote.quote_number, "revision_no": revision.revision_no},
        expires_in=PROPOSAL_TTL,
    )
    return PrepareQuoteSendOutput(
        proposal_id=proposal.id, short_ref=str(proposal.id)[-6:].upper(), status=proposal.status, title=proposal.title,
        quote_number=quote.quote_number, revision_no=revision.revision_no, recipient_masked=masked, document_sha256=digest,
        filename=filename, text=text, expires_at=proposal.expires_at,
    )


def _handler(uow: UnitOfWork, data: BaseModel) -> PrepareQuoteSendOutput:
    assert isinstance(data, PrepareQuoteSendInput)
    return prepare_quote_send(uow, data)


PREPARE_QUOTE_SEND = ToolDef(
    name="prepare_quote_send",
    group="Sales",
    description=(
        "Prepare sending an issued quotation to the customer on WhatsApp. Creates an approval request that binds the "
        "recipient, the message and the PDF; nothing is sent until another person approves it."
    ),
    input_model=PrepareQuoteSendInput,
    output_model=PrepareQuoteSendOutput,
    handler=_handler,
    effect="propose",
    permission=MESSAGE_SEND,
)

TOOLS = [PREPARE_QUOTE_SEND]

__all__ = ["PREPARE_QUOTE_SEND", "TOOLS", "PrepareQuoteSendInput", "PrepareQuoteSendOutput", "prepare_quote_send"]
