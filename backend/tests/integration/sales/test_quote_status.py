"""The quote state machine (LM-51/52, BUG-01, FG-QUO-03): one transition table, append-only history, review
approvals bound to the content hash, issue guards and dispatch records."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.core.errors import Conflict, Forbidden, InvalidTransition, NotFound, ValidationFailed
from app.modules.approvals import service as approvals
from app.modules.sales import service as sales
from app.modules.sales.models import QuoteDispatch, QuoteRevision, QuoteStatusHistory
from app.modules.sales.schemas import QuoteLineUpdate, QuoteTransition, QuoteUpdate
from app.modules.sales.state import TRANSITIONS
from app.platform.events.models import DomainEvent
from app.seed.world import keys
from tests.integration.sales.world import SalesWorld

pytestmark = pytest.mark.db
MEERA, NEHA, SAHIL, RAVI, PRIYA = keys.USERS.MEERA, keys.USERS.NEHA, keys.USERS.SAHIL, keys.USERS.RAVI, keys.USERS.PRIYA


def _events(world: SalesWorld, quote_id: uuid.UUID) -> list[tuple[str, dict]]:  # type: ignore[type-arg]
    with world.uow(SAHIL) as uow:
        rows = uow.session.execute(
            select(DomainEvent.event_type, DomainEvent.payload).where(DomainEvent.aggregate_id == quote_id).order_by(DomainEvent.seq)
        ).all()
    return [(r[0], r[1]) for r in rows]


def _decide(world: SalesWorld, person: str, proposal_id: uuid.UUID, decision: str, reason: str | None = None) -> str:
    with world.uow(person) as uow:
        proposal = approvals.get(uow, proposal_id)
        decided = approvals.decide(uow, proposal_id, decision=decision, content_hash_seen=proposal.content_hash,
                                   expected_version=proposal.version, reason=reason)
        return decided.status


def test_quote_status_machine_table(world: SalesWorld) -> None:
    """Every row of the table is exercised once; everything else is 409 invalid_transition with allowed_transitions."""
    assert {(f, a) for f, a in TRANSITIONS} == {
        ("draft", "submit_review"), ("internal_review", "withdraw_review"), ("draft", "mark_sent"), ("internal_review", "mark_sent"),
        ("sent", "mark_won"), ("sent", "mark_lost"), ("draft", "cancel"), ("internal_review", "cancel"), ("sent", "cancel"),
    }
    d = world.new_draft(MEERA, "NORDHAUS", ("OAK_TRAY", "240"))
    assert [t.action for t in d.allowed_transitions] == ["submit_review", "mark_sent", "cancel"]
    assert d.capabilities["issue"].allowed and d.capabilities["transition"].allowed

    # draft -> internal_review (proposal created) -> draft (withdrawn) -> internal_review -> approved -> sent -> won
    r = world.transition(MEERA, d.id, "submit_review")
    assert r.status == "internal_review" and r.review.review_proposal_id is not None
    assert [t.action for t in r.allowed_transitions] == ["withdraw_review", "mark_sent", "cancel"]
    with pytest.raises(Forbidden):  # not editable while under review
        with world.uow(MEERA) as uow:
            sales.update_quote(uow, d.id, QuoteUpdate(expected_version=r.version, remarks="x"))
    w = world.transition(MEERA, d.id, "withdraw_review")
    assert w.status == "draft" and w.review.review_proposal_id is None
    with world.uow(SAHIL) as uow:
        assert approvals.get(uow, r.review.review_proposal_id).status == "withdrawn"
    r = world.transition(MEERA, d.id, "submit_review")
    assert _decide(world, SAHIL, r.review.review_proposal_id, "approve") == "approved"
    with world.uow(MEERA) as uow:
        approved = sales.get_quote(uow, d.id)
    assert approved.status == "internal_review" and approved.review.approved_proposal_id == r.review.review_proposal_id
    assert approved.review.approval_current and approved.capabilities["issue"].allowed
    s = world.transition(MEERA, d.id, "mark_sent", dispatch_channel="email", sent_to="lena.brandt@nordhaus-interiors.test")
    assert s.status == "sent" and s.revision_no == 1 and s.valid_until is not None and s.sent_at is not None
    assert [t.action for t in s.allowed_transitions] == ["mark_won", "mark_lost", "cancel"]
    with pytest.raises(ValidationFailed):  # mark_lost needs a reason
        world.transition(MEERA, d.id, "mark_lost")
    won = world.transition(MEERA, d.id, "mark_won")
    assert won.status == "won" and won.won_at is not None and won.accepted_revision_id is not None and won.allowed_transitions == []
    with pytest.raises(InvalidTransition) as exc:
        world.transition(MEERA, d.id, "cancel", reason="too late")
    assert exc.value.code == "invalid_transition" and exc.value.extra["allowed_transitions"] == []

    names = [name for name, _p in _events(world, d.id)]
    assert names == [
        "sales.quote.created", "sales.quote.updated",
        "sales.quote.review_requested", "sales.quote.status_changed",
        "sales.quote.review_withdrawn", "sales.quote.status_changed",
        "sales.quote.review_requested", "sales.quote.status_changed",
        "sales.quote.issued", "sales.quote.marked_sent", "sales.quote.status_changed",
        "sales.quote.won", "sales.quote.status_changed",
    ]
    changed = [p for n, p in _events(world, d.id) if n == "sales.quote.status_changed"]
    assert [(p["action"], p["from_status"], p["to_status"]) for p in changed] == [
        ("submit_review", "draft", "internal_review"), ("withdraw_review", "internal_review", "draft"),
        ("submit_review", "draft", "internal_review"), ("mark_sent", "internal_review", "sent"), ("mark_won", "sent", "won"),
    ]
    with world.uow(SAHIL) as uow:
        dispatches = list(uow.session.scalars(select(QuoteDispatch).where(QuoteDispatch.quote_id == d.id)))
    assert len(dispatches) == 1 and dispatches[0].channel == "email" and dispatches[0].sent_to == "lena.brandt@nordhaus-interiors.test"

    # lost needs a reason code; the second quote exercises mark_lost and the review rejection path
    d2 = world.new_draft(MEERA, "NORDHAUS", ("OAK_TRAY", "240"))
    sent2 = world.transition(MEERA, d2.id, "mark_sent")
    lost = world.transition(MEERA, d2.id, "mark_lost", reason_code="price", reason="Customer chose a lower-priced offer")
    assert lost.status == "lost" and lost.lost_reason_code == "price" and sent2.revision_no == 1


def test_review_rejection_returns_to_draft_and_override_needs_approval(world: SalesWorld) -> None:
    """Scenario F: an override quote cannot be issued without an approved review; a rejection returns it to draft; a
    content change after approval invalidates the approval (fresh review needed)."""
    d = world.new_draft(MEERA, "MAISON")
    with world.uow(MEERA) as uow:
        from decimal import Decimal

        from app.modules.sales.schemas import QuoteLineCreate

        quote, line = sales.add_line(uow, d.id, QuoteLineCreate(expected_version=d.version, product_id=world.ref("ASH_BOARD"), quantity=Decimal("320"),
                                                                 unit_price=Decimal("16.5"), override_reason="Volume price agreed"))
        d = sales.detail(uow, quote)
    assert d.review.requires_approval and not d.capabilities["issue"].allowed and d.capabilities["issue"].reason_code == "review_approval_required"
    with pytest.raises(Conflict) as exc:
        world.transition(MEERA, d.id, "mark_sent")
    assert exc.value.code == "review_approval_required"

    r = world.transition(MEERA, d.id, "submit_review")
    pid = r.review.review_proposal_id
    with world.uow(SAHIL) as uow:
        proposal = approvals.get(uow, pid)
        assert proposal.facts["price_override"] is True and proposal.facts["exceptions"] == ["price_override"]
        assert proposal.facts["grand_total"] == "5280.0000" and proposal.facts["currency"] == "EUR"
        assert proposal.content_hash == r.content_hash and proposal.required_permission == "sales.quote.approve"
    # Meera (initiator) and Ravi (no approve key) are not eligible; Sahil needs sales.quote_price.approve (held)
    with world.uow(MEERA) as uow:
        assert approvals.is_eligible(uow, approvals.get(uow, pid)) is False
    with world.uow(RAVI) as uow:
        assert approvals.can_view(uow, uow.session.get(type(proposal), pid)) is False  # type: ignore[arg-type]
    sahil_without_price = world.actor(SAHIL).with_(permissions={k: v for k, v in world.actor(SAHIL).permissions.items() if k != "sales.quote_price.approve"})
    from app.platform.uow import UnitOfWork

    with UnitOfWork(sahil_without_price, clock=world.ctx.clock) as uow:  # not eligible, not the requester: invisible
        assert approvals.is_eligible(uow, uow.session.get(type(proposal), pid)) is False  # type: ignore[arg-type]
        with pytest.raises(NotFound):
            approvals.get(uow, pid)
    assert _decide(world, SAHIL, pid, "reject", reason="Margin too thin") == "rejected"
    with world.uow(MEERA) as uow:
        back = sales.get_quote(uow, d.id)
        history = sales.list_status_history(uow, d.id)
    assert back.status == "draft" and back.review.review_proposal_id is None and back.review.approved_proposal_id is None
    assert [(h.action, h.to_status) for h in history][-1] == ("review_rejected", "draft") and history[-1].actor.id == world.user_id(SAHIL)
    assert history[-1].reason == "Margin too thin"

    # approved, then changed: the approval no longer covers the content
    r = world.transition(MEERA, d.id, "submit_review")
    assert _decide(world, SAHIL, r.review.review_proposal_id, "approve") == "approved"
    w = world.transition(MEERA, d.id, "withdraw_review") if False else None  # noqa: F841 - stays in review, edit blocked
    with world.uow(MEERA) as uow:
        approved = sales.get_quote(uow, d.id)
    assert approved.capabilities["issue"].allowed and approved.review.approval_current
    # a management edit of the quoted price after approval (drafts only -> withdraw first) invalidates the approval
    world.transition(MEERA, d.id, "withdraw_review")
    with world.uow(SAHIL) as uow:
        current = sales.get_quote(uow, d.id)
        sales.update_line(uow, d.id, current.lines[0].id, QuoteLineUpdate(expected_version=current.version, unit_price=Decimal("16")))
        stale = sales.get_quote(uow, d.id)
    assert stale.review.approved_proposal_id is not None and stale.review.approval_current is False
    assert not stale.capabilities["issue"].allowed
    with pytest.raises(Conflict):
        world.transition(MEERA, d.id, "mark_sent")
    # a plain quote (no override) is issued directly from draft; a withdrawn review proposal is not pending
    plain = world.new_draft(MEERA, "NORDHAUS", ("OAK_TRAY", "240"))
    assert world.transition(MEERA, plain.id, "mark_sent").status == "sent"


def test_status_history_append_only(world: SalesWorld) -> None:
    d = world.new_draft(MEERA, "BERG", ("MAPLE_TRIVET", "600"))
    world.transition(MEERA, d.id, "mark_sent")
    with world.uow(MEERA) as uow:
        history = sales.list_status_history(uow, d.id)
    assert [(h.action, h.from_status, h.to_status) for h in history] == [("mark_sent", "draft", "sent")]
    assert history[0].actor is not None and history[0].actor.id == world.user_id(MEERA) and history[0].quote_version == d.version + 1
    with world.uow(PRIYA) as uow:
        row_id = uow.session.scalars(select(QuoteStatusHistory.id).where(QuoteStatusHistory.quote_id == d.id)).one()
        rev_id = uow.session.scalars(select(QuoteRevision.id).where(QuoteRevision.quote_id == d.id)).one()
    # the app role has no UPDATE/DELETE grant and the trigger rejects them for the owner: either refusal will do
    with pytest.raises(DBAPIError, match="append-only|permission denied"), world.uow(PRIYA) as uow:
        uow.session.execute(text("UPDATE sales_quote_status_history SET reason = 'x' WHERE id = :id"), {"id": row_id})
    with pytest.raises(DBAPIError, match="append-only|permission denied"), world.uow(PRIYA) as uow:
        uow.session.execute(text("DELETE FROM sales_quote_status_history WHERE quote_id = :id"), {"id": d.id})
    with pytest.raises(DBAPIError, match="append-only|permission denied"), world.uow(PRIYA) as uow:  # issued revisions too
        uow.session.execute(text("UPDATE sales_quote_revision SET revision_no = 9 WHERE id = :id"), {"id": rev_id})


def test_issued_revision_immutable_by_trigger(world: SalesWorld) -> None:
    d = world.new_draft(MEERA, "BERG", ("MAPLE_TRIVET", "600"))
    sent = world.transition(MEERA, d.id, "mark_sent")
    with world.uow(MEERA) as uow:
        revisions = sales.list_revisions(uow, d.id)
        rev = sales.get_revision(uow, d.id, 1)
    assert len(revisions) == 1 and revisions[0].revision_no == 1 and revisions[0].issued_by.id == world.user_id(MEERA)
    assert rev.snapshot["header"]["quote_number"] == sent.quote_number and rev.snapshot["totals"]["grand_total"] == "5700.0000"
    assert rev.content_hash == sent.content_hash and len(rev.document_sha256) == 64
    assert "internal_note" not in rev.snapshot["lines"][0]
    with pytest.raises(DBAPIError, match="append-only|permission denied"), world.uow(PRIYA) as uow:
        uow.session.execute(text("UPDATE sales_quote_revision SET snapshot = '{}' WHERE id = :id"), {"id": rev.id})


def test_cancelled_and_archived_transitions(world: SalesWorld) -> None:
    """BUG-01: cancel works from draft, internal_review and sent; archive is Slice 2 and answers 409 with the
    allowed transitions (never a 400)."""
    for start in ("draft", "internal_review", "sent"):
        d = world.new_draft(MEERA, "NORDHAUS", ("OAK_TRAY", "240"))
        if start == "internal_review":
            world.transition(MEERA, d.id, "submit_review")
        elif start == "sent":
            world.transition(MEERA, d.id, "mark_sent")
        with pytest.raises(ValidationFailed):
            world.transition(MEERA, d.id, "cancel")
        c = world.transition(MEERA, d.id, "cancel", reason_code="customer_withdrew", reason="Customer withdrew the enquiry")
        assert c.status == "cancelled" and c.cancelled_reason_code == "customer_withdrew" and c.allowed_transitions == []
        if start == "internal_review":
            with world.uow(SAHIL) as uow:
                assert approvals.list_for_actor(uow, status="withdrawn")
        with pytest.raises(InvalidTransition) as exc:
            world.transition(MEERA, d.id, "archive")
        assert exc.value.code == "invalid_transition" and exc.value.extra["current_status"] == "cancelled"
    d = world.new_draft(MEERA, "NORDHAUS", ("OAK_TRAY", "240"))
    with pytest.raises(InvalidTransition) as exc:
        world.transition(MEERA, d.id, "archive")
    assert [t["action"] for t in exc.value.extra["allowed_transitions"]] == ["submit_review", "mark_sent", "cancel"]
    with pytest.raises(InvalidTransition):
        world.transition(MEERA, d.id, "mark_won")  # not sent yet
    with pytest.raises(InvalidTransition):
        world.transition(MEERA, d.id, "revise")  # Slice 2


def test_transition_permissions_and_versions(world: SalesWorld) -> None:
    d = world.new_draft(MEERA, "NORDHAUS", ("OAK_TRAY", "240"))
    with pytest.raises(Forbidden) as exc:  # Ravi reads company-wide but cannot issue
        with world.uow(RAVI, idempotency_key=str(uuid.uuid7())) as uow:
            sales.transition_quote_command(uow, d.id, QuoteTransition(action="mark_sent", expected_version=d.version))
    assert exc.value.extra["permission"] == "sales.quote.issue"
    with pytest.raises(ValidationFailed) as idem:  # issue-like commands need an Idempotency-Key through the API
        with world.uow(MEERA) as uow:
            sales.transition_quote_command(uow, d.id, QuoteTransition(action="mark_sent", expected_version=d.version))
    assert idem.value.code == "idempotency_key_required"
    from app.core.errors import VersionConflict

    with pytest.raises(VersionConflict):
        with world.uow(MEERA, idempotency_key=str(uuid.uuid7())) as uow:
            sales.transition_quote_command(uow, d.id, QuoteTransition(action="mark_sent", expected_version=d.version + 5))
    key = str(uuid.uuid7())
    with world.uow(MEERA, idempotency_key=key) as uow:
        first, replayed = sales.transition_quote_command(uow, d.id, QuoteTransition(action="mark_sent", expected_version=d.version))
    with world.uow(MEERA, idempotency_key=key) as uow:
        again, replayed2 = sales.transition_quote_command(uow, d.id, QuoteTransition(action="mark_sent", expected_version=d.version))
    assert (replayed, replayed2) == (False, True) and again.revision_no == first.revision_no == 1
    # Sahil (management, company scope) may transition Meera's quote
    assert world.transition(SAHIL, d.id, "mark_won").status == "won"


def test_marked_sent_distinct_from_delivery_status(world: SalesWorld) -> None:
    """LP-06.9: marking sent records a dispatch; provider delivery (Slice 3) is a separate concern."""
    d = world.new_draft(MEERA, "NORDHAUS", ("OAK_TRAY", "240"))
    s = world.transition(MEERA, d.id, "mark_sent", dispatch_channel="whatsapp", note="Sent from the phone")
    with world.uow(MEERA) as uow:
        dispatch = uow.session.scalars(select(QuoteDispatch).where(QuoteDispatch.quote_id == d.id)).one()
        revision = uow.session.scalars(select(QuoteRevision).where(QuoteRevision.quote_id == d.id)).one()
    assert dispatch.channel == "whatsapp" and dispatch.note == "Sent from the phone" and dispatch.revision_id == revision.id
    assert dispatch.sent_at == s.sent_at and s.issued_at == revision.issued_at
    marked = [p for n, p in _events(world, d.id) if n == "sales.quote.marked_sent"][0]
    assert marked["dispatch_id"] == str(dispatch.id) and marked["revision_id"] == str(revision.id)
    issued = [p for n, p in _events(world, d.id) if n == "sales.quote.issued"][0]
    assert issued["revision_no"] == 1 and issued["valid_until"] == s.valid_until.isoformat()
