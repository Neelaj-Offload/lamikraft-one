"""The ``sales.quote.review`` approval handler (permissions.md §10, fixtures.md §6).

Eligibility: ``sales.quote.approve`` at a scope covering the quote, plus ``sales.quote_price.approve`` when the
proposal facts carry a price override, a discount or a below-minimum applicable subtotal. The initiator can
never decide (approvals engine). On approval the quote stays in ``internal_review`` and records the approved
proposal and content hash, which ``mark_sent`` compares with the current content; on rejection the quote
returns to ``draft`` with a history row and ``sales.quote.status_changed``.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, exists, select

from app.modules.approvals import service as approvals
from app.modules.approvals.service import ApprovalHandler, TargetRef
from app.modules.sales import events as ev
from app.modules.sales.models import Quote, QuoteStatusHistory
from app.modules.sales.schemas import REVIEW_KIND, QuoteStatus, TransitionAction
from app.platform.authz.policy import get_policy, scope_clause
from app.platform.uow import UnitOfWork

PRICE_EXCEPTIONS = ("price_override", "discount", "below_minimum")


def _quote(uow: UnitOfWork, target: TargetRef) -> Quote | None:
    if target.target_type != "sales.quote":
        return None
    return uow.session.scalars(
        select(Quote).where(Quote.id == target.target_id, Quote.company_id == uow.actor.company_id)
    ).first()


def current_version(uow: UnitOfWork, target: TargetRef) -> int | None:
    quote = _quote(uow, target)
    if quote is None or quote.deleted_at is not None:
        return None
    return quote.version


def _covers(uow: UnitOfWork, quote_id: Any) -> bool:
    """The actor's ``sales.quote.approve`` scope covers the quote (own/team/branch/company)."""
    policy = get_policy("sales.quote")
    return bool(
        uow.session.scalar(select(exists().where(and_(Quote.id == quote_id, scope_clause(uow.actor, policy, "approve")))))
    )


def can_decide(uow: UnitOfWork, proposal: Any) -> bool:
    facts = proposal.facts or {}
    exceptions = set(facts.get("exceptions") or []) | {k for k in PRICE_EXCEPTIONS if facts.get(k)}
    if exceptions and not uow.actor.can("sales.quote_price.approve"):
        return False
    for target in approvals.targets_of(uow, proposal):
        if target.target_type != "sales.quote" or not _covers(uow, target.target_id):
            return False
    return True


def _history(uow: UnitOfWork, quote: Quote, *, action: str, from_status: str, to_status: str, reason: str | None) -> None:
    uow.add(
        QuoteStatusHistory(
            company_id=uow.actor.company_id,
            quote_id=quote.id,
            action=action,
            from_status=from_status,
            to_status=to_status,
            actor_user_id=uow.actor.user_id,
            reason_code=None,
            reason=reason,
            occurred_at=uow.now(),
            quote_version=quote.version,
        )
    )


def on_approved(uow: UnitOfWork, proposal: Any) -> None:
    for target in approvals.targets_of(uow, proposal):
        quote = _quote(uow, target)
        if quote is None:
            continue
        quote.approved_proposal_id = proposal.id
        quote.approved_content_hash = proposal.content_hash
        quote.review_proposal_id = None
        quote.updated_at = uow.now()
        uow.flush()
        uow.audit("sales.quote.review_approved", resource_type="sales.quote", resource_id=quote.id,
                  resource_label=quote.quote_number, reason=proposal.decision_reason)


def on_rejected(uow: UnitOfWork, proposal: Any) -> None:
    for target in approvals.targets_of(uow, proposal):
        quote = _quote(uow, target)
        if quote is None or quote.status != QuoteStatus.INTERNAL_REVIEW.value:
            continue
        from_status = quote.status
        # back to the working copy: draft when never issued, revised when it has an issued revision
        quote.status = QuoteStatus.REVISED.value if quote.revision_no >= 1 else QuoteStatus.DRAFT.value
        quote.review_proposal_id = None
        quote.updated_at = uow.now()
        uow.flush()
        _history(uow, quote, action=TransitionAction.REVIEW_REJECTED.value, from_status=from_status,
                 to_status=quote.status, reason=proposal.decision_reason)
        uow.emit(
            ev.QUOTE_STATUS_CHANGED,
            aggregate_id=quote.id,
            aggregate_version=quote.version,
            payload=ev.payload(
                ev.QuoteStatusChangedPayload(
                    quote_id=quote.id, version=quote.version, action=TransitionAction.REVIEW_REJECTED.value,
                    from_status=from_status, to_status=quote.status,
                )
            ),
        )
        uow.audit("sales.quote.review_rejected", resource_type="sales.quote", resource_id=quote.id,
                  resource_label=quote.quote_number, reason=proposal.decision_reason)


QUOTE_REVIEW_HANDLER = ApprovalHandler(
    kind=REVIEW_KIND,
    approve_permission="sales.quote.approve",
    current_version=current_version,
    on_approved=on_approved,
    on_rejected=on_rejected,
    can_decide=can_decide,
)
