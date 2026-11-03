"""Customer sends over WhatsApp: the ``prepare_quote_send`` proposal (kind ``channels.message.send``) binds the
recipient identity, the message text and the SHA-256 of the issued revision's PDF. Only an approval by another
person queues the message (``on_approved`` writes the outbox row in the decision transaction); the PDF is
re-rendered deterministically from the immutable revision snapshot and must hash to the bound value, so a changed
document can never ride on an earlier approval. The PDF is the customer document: no internal notes, no costs."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from app.core.errors import Conflict, NotFound
from app.modules.approvals import service as approvals
from app.modules.approvals.service import ApprovalHandler, TargetRef
from app.modules.channels import events as ev
from app.modules.channels.models import ChannelIdentity
from app.modules.channels.policies import MESSAGE_SEND
from app.platform.uow import UnitOfWork


def latest_revision(uow: UnitOfWork, quote_id: uuid.UUID) -> Any | None:
    from app.modules.sales.models import QuoteRevision

    return uow.session.scalars(
        select(QuoteRevision)
        .where(QuoteRevision.company_id == uow.actor.company_id, QuoteRevision.quote_id == quote_id)
        .order_by(QuoteRevision.revision_no.desc())
        .limit(1)
    ).first()


def render_revision(revision: Any) -> tuple[bytes, str, str]:
    """(pdf bytes, sha256, filename) of an issued revision, rendered from its immutable snapshot."""
    from app.modules.sales import documents

    pdf = documents.render_quote_pdf(revision.snapshot)
    return pdf, documents.sha256_of(pdf), documents.document_filename(revision.snapshot)


def _current_version(uow: UnitOfWork, target: TargetRef) -> int | None:
    if target.target_type == "sales.quote":
        from app.modules.sales.models import Quote

        quote = uow.session.scalars(select(Quote).where(Quote.id == target.target_id, Quote.company_id == uow.actor.company_id)).first()
        return None if quote is None or quote.deleted_at is not None else quote.version
    if target.target_type == "channels.identity":
        identity = uow.session.get(ChannelIdentity, target.target_id)
        if identity is None or identity.company_id != uow.actor.company_id or identity.status != "active":
            return None
        return identity.version
    return None


def _can_decide(uow: UnitOfWork, proposal: Any) -> bool:
    """The approver must be able to read the quote being sent (their own scope)."""
    from app.modules.sales.models import Quote

    for target in approvals.targets_of(uow, proposal):
        if target.target_type == "sales.quote":
            try:
                uow.repo(Quote).get(target.target_id)
            except NotFound:
                return False
    return True


def _on_approved(uow: UnitOfWork, proposal: Any) -> None:
    from app.modules.channels.whatsapp import outbound

    facts = dict(proposal.facts or {})
    identity = uow.session.get(ChannelIdentity, uuid.UUID(str(facts["identity_id"])))
    if identity is None or identity.status != "active":
        raise Conflict("The recipient is no longer linked", code="recipient_unavailable")
    revision = latest_revision(uow, uuid.UUID(str(facts["quote_id"])))
    if revision is None or str(revision.id) != str(facts["revision_id"]):
        raise Conflict("The quote was revised after this send was prepared", code="document_changed")
    _pdf, digest, filename = render_revision(revision)
    if digest != facts["document_sha256"] or digest != revision.document_sha256:
        raise Conflict("The document does not match the approved content", code="document_changed")
    outbound.queue_message(
        uow, identity,
        kind="media",
        payload={"type": "document", "revision_id": str(revision.id), "document_sha256": digest, "filename": filename, "caption": facts["text"]},
        text=facts["text"],
        purpose="transactional",
        idempotency_key=f"proposal:{proposal.id}",
        cause_ref=f"approvals.proposal:{proposal.id}",
        proposal_id=proposal.id,
    )


def _on_rejected(uow: UnitOfWork, proposal: Any) -> None:  # noqa: ARG001 - nothing was queued
    return None


HANDLER = ApprovalHandler(
    kind=ev.SEND_PROPOSAL_KIND,
    approve_permission=MESSAGE_SEND,
    current_version=_current_version,
    on_approved=_on_approved,
    on_rejected=_on_rejected,
    can_decide=_can_decide,
)


def register() -> None:
    approvals.register_handler(HANDLER)


__all__ = ["HANDLER", "latest_revision", "register", "render_revision"]
