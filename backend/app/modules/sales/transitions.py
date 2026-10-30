"""``transition_quote``: every status change of a quote through one table (``state.TRANSITIONS``).

Each transition locks the quote, checks the actor's scope for the required ``sales.quote.<verb>``, checks the
optimistic version, evaluates the guard, appends a status-history row, emits the specific event **and**
``sales.quote.status_changed`` and audits. ``mark_sent`` is the issue: it freezes the content into an immutable
revision with its deterministic document hash, sets ``valid_until`` in the company zone and records a dispatch.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from app.core.clock import local_date
from app.core.errors import Conflict, InvalidTransition, NotFound, ValidationFailed
from app.modules.approvals import service as approvals
from app.modules.approvals.service import TargetRef
from app.modules.sales import documents, quotes
from app.modules.sales import events as ev
from app.modules.sales.common import company_zone, idempotent
from app.modules.sales.models import Quote, QuoteDispatch, QuoteLine, QuoteRevision, QuoteStatusHistory
from app.modules.sales.schemas import (
    REVIEW_KIND,
    QuoteDetail,
    QuoteStatus,
    QuoteTransition,
    RevisionKind,
    TransitionAction,
)
from app.modules.sales.state import KNOWN_FUTURE_ACTIONS, TRANSITIONS, Transition
from app.platform.uow import UnitOfWork

REVIEW_EXPIRY = timedelta(hours=24)


def _invalid(uow: UnitOfWork, quote: Quote, action: str) -> InvalidTransition:
    allowed = quotes.allowed_transitions(uow, quote, quotes.lines_of(uow, quote))
    detail = (
        f"{action} is not available in Slice 1" if action in KNOWN_FUTURE_ACTIONS else f"{action} is not allowed while the quote is {quote.status}"
    )
    return InvalidTransition(detail, allowed_transitions=[t.model_dump() for t in allowed], current_status=quote.status)


def _history(uow: UnitOfWork, quote: Quote, t: Transition, data: QuoteTransition) -> None:
    uow.add(
        QuoteStatusHistory(
            company_id=uow.actor.company_id,
            quote_id=quote.id,
            action=t.action,
            from_status=t.from_status,
            to_status=t.to_status,
            actor_user_id=uow.actor.user_id,
            reason_code=data.reason_code,
            reason=data.reason,
            occurred_at=uow.now(),
            quote_version=quote.version,
        )
    )


def _status_changed(uow: UnitOfWork, quote: Quote, t: Transition, *, origin: str | None) -> None:
    uow.emit(
        ev.QUOTE_STATUS_CHANGED,
        aggregate_id=quote.id,
        aggregate_version=quote.version,
        payload=ev.payload(
            ev.QuoteStatusChangedPayload(
                quote_id=quote.id, version=quote.version, action=t.action, from_status=t.from_status, to_status=t.to_status,
                origin=origin,
            )
        ),
    )


def review_facts(quote: Quote) -> dict[str, object]:
    reasons = quotes.needs_review(quote)
    return {
        "quote_number": quote.quote_number,
        "party_name": quote.party_name,
        "price_override": quote.has_price_override,
        "discount": quote.has_discount,
        "below_minimum": quote.minimum_status == "BELOW",
        "grand_total": format(quote.grand_total_amount, "f") if quote.grand_total_amount is not None else None,
        "currency": quote.currency,
        "exceptions": reasons,
    }


# ---- per-action effects (run after the generic checks, before history/events) ------------------------
def _submit_review(uow: UnitOfWork, quote: Quote, lines: list[QuoteLine], data: QuoteTransition) -> dict[str, object]:
    # The proposal binds to the version the quote has *after* this transition. The quote is not dirty yet (the
    # submit flushes only the proposal), and status + review_proposal_id are written in one UPDATE by the
    # transition's flush, so that version is exactly ``version + 1``. Binding to an intermediate version would
    # make the approvals engine invalidate the proposal at decision time (target_changed).
    proposal = approvals.submit(
        uow,
        kind=REVIEW_KIND,
        targets=[TargetRef("sales.quote", quote.id, quote.version + 1)],
        content=quotes.content_of(quote, lines),
        title=f"Review {quote.quote_number} · {quote.party_name}",
        summary=data.reason,
        facts=review_facts(quote),
        expires_in=REVIEW_EXPIRY,
    )
    quote.status = QuoteStatus.INTERNAL_REVIEW.value
    quote.review_proposal_id = proposal.id
    quote.updated_at = uow.now()
    return {"proposal_id": proposal.id}


def _close_pending_review(uow: UnitOfWork, quote: Quote, *, reason: str) -> None:
    """The requester withdraws their own pending request; anyone else (management) leaves it invalidated."""
    proposal_id = quote.review_proposal_id
    if proposal_id is not None:
        try:
            proposal = approvals.get(uow, proposal_id)
        except NotFound:  # neither requester nor eligible approver: invalidated below
            proposal = None
        if proposal is not None and proposal.status == "pending" and proposal.requested_by == uow.actor.user_id:
            approvals.withdraw(uow, proposal_id)
            uow.flush()  # the session does not autoflush: the withdrawal must land before the pending lookup
    approvals.invalidate_for_target(uow, "sales.quote", quote.id, reason=reason)


def _withdraw_review(uow: UnitOfWork, quote: Quote, _lines: list[QuoteLine], _data: QuoteTransition) -> dict[str, object]:
    proposal_id = quote.review_proposal_id
    _close_pending_review(uow, quote, reason="review_withdrawn")
    quote.status = QuoteStatus.DRAFT.value
    quote.review_proposal_id = None
    quote.updated_at = uow.now()
    # an approved review stays recorded (bound to its content hash); the event names the request being left
    return {"proposal_id": proposal_id or quote.approved_proposal_id}


def _issue(uow: UnitOfWork, quote: Quote, lines: list[QuoteLine], data: QuoteTransition) -> dict[str, object]:
    now = uow.now()
    zone = company_zone(uow)
    issue_date = local_date(now, zone)
    valid_until = issue_date + timedelta(days=quote.validity_days)
    revision_no = quote.revision_no + 1
    snapshot = documents.build_revision_snapshot(uow, quote, lines, revision_no=revision_no, issued_at=now, valid_until=valid_until)
    pdf = documents.render_quote_pdf(snapshot)
    revision = QuoteRevision(
        company_id=uow.actor.company_id,
        quote_id=quote.id,
        revision_no=revision_no,
        kind=RevisionKind.ISSUED.value,
        snapshot=snapshot,
        content_hash=quote.content_hash,
        valid_until=valid_until,
        issued_at=now,
        issued_by=uow.actor.user_id,
        document_sha256=documents.sha256_of(pdf),
    )
    uow.add(revision)
    uow.flush()
    dispatch = QuoteDispatch(
        company_id=uow.actor.company_id,
        quote_id=quote.id,
        revision_id=revision.id,
        channel=data.dispatch_channel.value,
        sent_at=now,
        sent_by=uow.actor.user_id,
        sent_to=data.sent_to,
        note=data.note,
    )
    uow.add(dispatch)
    # a review still pending when the quote is issued (a plain quote sent from internal_review) is moot
    approvals.invalidate_for_target(uow, "sales.quote", quote.id, reason="target_issued")
    quote.revision_no = revision_no
    quote.issued_at = now
    quote.sent_at = now
    quote.valid_until = valid_until
    quote.status = QuoteStatus.SENT.value
    quote.review_proposal_id = None
    quote.updated_at = now
    return {"revision": revision, "dispatch": dispatch}


def _won(uow: UnitOfWork, quote: Quote, _lines: list[QuoteLine], data: QuoteTransition) -> dict[str, object]:
    revision_no = data.accepted_revision_no or quote.revision_no
    revision = quotes.revision_row(uow, quote, revision_no)
    quote.status = QuoteStatus.WON.value
    quote.won_at = uow.now()
    quote.accepted_revision_id = revision.id
    quote.updated_at = uow.now()
    return {"revision": revision}


def _lost(uow: UnitOfWork, quote: Quote, _lines: list[QuoteLine], data: QuoteTransition) -> dict[str, object]:
    quote.status = QuoteStatus.LOST.value
    quote.lost_at = uow.now()
    quote.lost_reason_code = data.reason_code or "other"
    quote.updated_at = uow.now()
    return {}


def _cancel(uow: UnitOfWork, quote: Quote, _lines: list[QuoteLine], data: QuoteTransition) -> dict[str, object]:
    _close_pending_review(uow, quote, reason="target_cancelled")
    quote.status = QuoteStatus.CANCELLED.value
    quote.cancelled_at = uow.now()
    quote.cancelled_reason_code = data.reason_code or "other"
    quote.review_proposal_id = None
    quote.updated_at = uow.now()
    return {}


EFFECTS = {
    TransitionAction.SUBMIT_REVIEW.value: _submit_review,
    TransitionAction.WITHDRAW_REVIEW.value: _withdraw_review,
    TransitionAction.MARK_SENT.value: _issue,
    TransitionAction.MARK_WON.value: _won,
    TransitionAction.MARK_LOST.value: _lost,
    TransitionAction.CANCEL.value: _cancel,
}


def _guard(uow: UnitOfWork, quote: Quote, lines: list[QuoteLine], t: Transition) -> None:
    if t.guard == "lines_present" and not lines:
        raise Conflict("Add at least one line before requesting a review", code="no_lines")
    if t.guard == "issue_allowed":
        if not lines:
            raise Conflict("Add at least one line before issuing the quotation", code="no_lines")
        if not quote.totals_complete:
            raise Conflict("Every line needs a price before the quotation can be issued", code="totals_incomplete")
        reasons = quotes.needs_review(quote)
        if reasons and not quotes.approval_current(quote):
            raise Conflict(
                "This quotation needs an approved review before it can be issued "
                f"({', '.join(reasons)}); request a review and wait for the approval",
                code="review_approval_required",
                reasons=reasons,
            )


def _emit_specific(uow: UnitOfWork, quote: Quote, t: Transition, effect: dict[str, object], data: QuoteTransition, *, origin: str | None) -> None:
    if t.action == TransitionAction.SUBMIT_REVIEW.value or t.action == TransitionAction.WITHDRAW_REVIEW.value:
        proposal_id = effect.get("proposal_id")
        if proposal_id is not None:
            uow.emit(
                t.event or "",
                aggregate_id=quote.id,
                aggregate_version=quote.version,
                payload=ev.payload(ev.QuoteProposalPayload(quote_id=quote.id, proposal_id=proposal_id, origin=origin)),  # type: ignore[arg-type]
            )
    elif t.action == TransitionAction.MARK_SENT.value:
        revision: QuoteRevision = effect["revision"]  # type: ignore[assignment]
        dispatch: QuoteDispatch = effect["dispatch"]  # type: ignore[assignment]
        uow.emit(
            ev.QUOTE_ISSUED,
            aggregate_id=quote.id,
            aggregate_version=quote.version,
            payload=ev.payload(
                ev.QuoteIssuedPayload(quote_id=quote.id, revision_id=revision.id, revision_no=revision.revision_no,
                                      valid_until=revision.valid_until, origin=origin)
            ),
        )
        uow.emit(
            ev.QUOTE_MARKED_SENT,
            aggregate_id=quote.id,
            aggregate_version=quote.version,
            payload=ev.payload(ev.QuoteMarkedSentPayload(quote_id=quote.id, revision_id=revision.id, dispatch_id=dispatch.id, origin=origin)),
        )
        uow.enqueue(
            "sales.document_render",
            {"quote_id": str(quote.id), "revision_id": str(revision.id)},
            dedupe_key=f"sales.document_render:{revision.id}",
            resource_type="sales.quote",
            resource_id=quote.id,
        )
    elif t.action == TransitionAction.MARK_WON.value:
        revision = effect["revision"]  # type: ignore[assignment]
        uow.emit(ev.QUOTE_WON, aggregate_id=quote.id, aggregate_version=quote.version,
                 payload=ev.payload(ev.QuoteWonPayload(quote_id=quote.id, accepted_revision_id=revision.id, origin=origin)))
    elif t.action == TransitionAction.MARK_LOST.value:
        uow.emit(ev.QUOTE_LOST, aggregate_id=quote.id, aggregate_version=quote.version,
                 payload=ev.payload(ev.QuoteReasonPayload(quote_id=quote.id, reason_code=quote.lost_reason_code or "other", origin=origin)))
    elif t.action == TransitionAction.CANCEL.value:
        uow.emit(ev.QUOTE_CANCELLED, aggregate_id=quote.id, aggregate_version=quote.version,
                 payload=ev.payload(ev.QuoteReasonPayload(quote_id=quote.id, reason_code=quote.cancelled_reason_code or "other", origin=origin)))


def transition_quote(uow: UnitOfWork, quote_id: uuid.UUID, data: QuoteTransition, *, origin: str | None = None) -> Quote:
    """Apply one state-machine action. 409 ``invalid_transition`` (with ``allowed_transitions``) when the action is not
    in the table for the current status; 403 when the actor lacks the verb in scope; 409 ``version_conflict`` when
    stale; 409 with a guard code when a precondition fails."""
    repo = uow.repo(Quote)
    quote = repo.get(quote_id, for_update=True, include_archived=False)
    t = TRANSITIONS.get((quote.status, data.action))
    if t is None:
        raise _invalid(uow, quote, data.action)
    repo.require_action(quote, t.permission_action)
    uow.expect_version(quote, data.expected_version)
    if t.requires_reason and not (data.reason or data.reason_code):
        raise ValidationFailed(
            f"{t.action} needs a reason",
            errors=[{"loc": ["body", "reason"], "msg": "a reason or reason code is required", "code": "reason_required"}],
        )
    lines = quotes.lines_of(uow, quote)
    _guard(uow, quote, lines, t)
    effect = EFFECTS[t.action](uow, quote, lines, data)
    uow.flush()
    _history(uow, quote, t, data)
    _emit_specific(uow, quote, t, effect, data, origin=origin)
    _status_changed(uow, quote, t, origin=origin)
    uow.audit(
        f"sales.quote.{t.action}", resource_type="sales.quote", resource_id=quote.id, resource_label=quote.quote_number,
        reason=data.reason, details={"from_status": t.from_status, "to_status": t.to_status, "reason_code": data.reason_code},
    )
    return quote


def transition_quote_command(uow: UnitOfWork, quote_id: uuid.UUID, data: QuoteTransition) -> tuple[QuoteDetail, bool]:
    """HTTP entry point: ``Idempotency-Key`` is required for issue-like commands (api-conventions §6)."""
    quote = uow.repo(Quote).get(quote_id, include_archived=False)
    t = TRANSITIONS.get((quote.status, data.action))
    if t is not None and t.idempotency_required and not uow.actor.idempotency_key:
        raise ValidationFailed(
            f"{data.action} requires an Idempotency-Key header",
            code="idempotency_key_required",
            errors=[{"loc": ["header", "Idempotency-Key"], "msg": "required for this command", "code": "idempotency_key_required"}],
        )
    return idempotent(
        uow, f"sales.transition_quote:{quote_id}", data, lambda: quotes.detail(uow, transition_quote(uow, quote_id, data)), QuoteDetail
    )
