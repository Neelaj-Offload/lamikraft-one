"""The approvals engine (Slice-1 interface, frozen for other lanes).

Domain modules register an :class:`ApprovalHandler` per proposal ``kind``. ``submit`` records the
exact target versions and a content hash; ``decide`` re-checks status, expiry, content hash, the
decider's permission, separation of duties and the current target versions *inside the decision
transaction*, then calls the handler. Editing a target calls ``invalidate_for_target`` so a changed
quantity or price can never ride on an earlier approval. The model has no approve tool: decisions
come only from authenticated human actions (web, WhatsApp interactive reply, review link).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select

from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.modules.approvals.models import Proposal, ProposalDecision, ProposalTarget
from app.platform.uow import UnitOfWork


@dataclass(frozen=True)
class TargetRef:
    target_type: str
    target_id: uuid.UUID
    target_version: int | None = None


@dataclass(frozen=True)
class ApprovalHandler:
    kind: str
    #: permission an approver must hold (scope checked against the target by the handler if needed)
    approve_permission: str
    #: current version of a target, for staleness checks (None = target gone)
    current_version: Callable[[UnitOfWork, TargetRef], int | None]
    on_approved: Callable[[UnitOfWork, Proposal], None]
    on_rejected: Callable[[UnitOfWork, Proposal], None]
    #: optional extra eligibility rule (e.g. approver must be able to read the quote)
    can_decide: Callable[[UnitOfWork, Proposal], bool] | None = None


_HANDLERS: dict[str, ApprovalHandler] = {}


def register_handler(handler: ApprovalHandler) -> None:
    _HANDLERS[handler.kind] = handler


def handler_for(kind: str) -> ApprovalHandler:
    try:
        return _HANDLERS[kind]
    except KeyError as exc:
        raise ValidationFailed(f"no approval handler registered for {kind}", code="approval_kind_unknown") from exc


def content_hash(content: Any) -> str:
    if isinstance(content, BaseModel):
        content = content.model_dump(mode="json")
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def submit(
    uow: UnitOfWork,
    *,
    kind: str,
    targets: Sequence[TargetRef],
    content: Any,
    title: str,
    summary: str | None = None,
    facts: dict[str, Any] | None = None,
    policy_key: str | None = None,
    expires_in: timedelta | None = timedelta(days=7),
) -> Proposal:
    handler = handler_for(kind)
    actor = uow.actor
    if actor.user_id is None:
        raise Forbidden("only a person can request an approval", code="requester_required")
    for target in targets:
        for pending in _pending_for(uow, target.target_type, target.target_id):
            pending.status = "superseded"
            pending.invalidated_reason = "superseded_by_new_request"
            uow.emit("approvals.proposal.superseded", aggregate_id=pending.id, aggregate_version=pending.version)
    proposal = Proposal(
        kind=kind,
        status="pending",
        title=title[:200],
        summary=summary,
        facts=json.loads(json.dumps(facts or {}, default=str)),
        content_hash=content_hash(content),
        policy_key=policy_key or kind,
        required_permission=handler.approve_permission,
        requested_by=actor.user_id,
        requested_via=actor.channel,
        agent_run_id=actor.agent_run_id,
        expires_at=(uow.now() + expires_in) if expires_in else None,
    )
    uow.add(proposal)
    uow.flush()
    for target in targets:
        uow.add(
            ProposalTarget(
                proposal_id=proposal.id,
                target_type=target.target_type,
                target_id=target.target_id,
                target_version=target.target_version,
            )
        )
    uow.emit(
        "approvals.proposal.submitted",
        aggregate_id=proposal.id,
        aggregate_version=proposal.version,
        payload={"kind": kind, "targets": [{"type": t.target_type, "id": str(t.target_id)} for t in targets]},
    )
    uow.audit("approvals.proposal.submitted", resource_type="approvals.proposal", resource_id=proposal.id, resource_label=title)
    return proposal


def _pending_for(uow: UnitOfWork, target_type: str, target_id: uuid.UUID) -> list[Proposal]:
    stmt = (
        select(Proposal)
        .join(ProposalTarget, ProposalTarget.proposal_id == Proposal.id)
        .where(
            Proposal.company_id == uow.actor.company_id,
            Proposal.status == "pending",
            ProposalTarget.target_type == target_type,
            ProposalTarget.target_id == target_id,
        )
        .with_for_update(of=Proposal)
    )
    return list(uow.session.scalars(stmt).unique())


def invalidate_for_target(uow: UnitOfWork, target_type: str, target_id: uuid.UUID, reason: str = "target_changed") -> int:
    count = 0
    for proposal in _pending_for(uow, target_type, target_id):
        proposal.status = "invalidated"
        proposal.invalidated_reason = reason
        uow.emit("approvals.proposal.invalidated", aggregate_id=proposal.id, aggregate_version=proposal.version, payload={"reason": reason})
        count += 1
    return count


def get(uow: UnitOfWork, proposal_id: uuid.UUID) -> Proposal:
    proposal = uow.session.scalars(
        select(Proposal).where(Proposal.id == proposal_id, Proposal.company_id == uow.actor.company_id)
    ).first()
    if proposal is None or not can_view(uow, proposal):
        raise NotFound(code="not_found", resource_type="approvals.proposal")
    return proposal


def targets_of(uow: UnitOfWork, proposal: Proposal) -> list[TargetRef]:
    rows = uow.session.scalars(select(ProposalTarget).where(ProposalTarget.proposal_id == proposal.id)).all()
    return [TargetRef(r.target_type, r.target_id, r.target_version) for r in rows]


def can_view(uow: UnitOfWork, proposal: Proposal) -> bool:
    actor = uow.actor
    return actor.is_system or proposal.requested_by == actor.user_id or is_eligible(uow, proposal)


def is_eligible(uow: UnitOfWork, proposal: Proposal) -> bool:
    actor = uow.actor
    if actor.user_id is None or actor.user_id == proposal.requested_by:
        return False
    if not actor.can(proposal.required_permission):
        return False
    handler = _HANDLERS.get(proposal.kind)
    if handler is not None and handler.can_decide is not None:
        return handler.can_decide(uow, proposal)
    return True


def decide(
    uow: UnitOfWork,
    proposal_id: uuid.UUID,
    *,
    decision: str,
    content_hash_seen: str,
    expected_version: int,
    reason: str | None = None,
) -> Proposal:
    if decision not in ("approve", "reject"):
        raise ValidationFailed("decision must be approve or reject", code="invalid_decision")
    proposal = uow.session.scalars(
        select(Proposal).where(Proposal.id == proposal_id, Proposal.company_id == uow.actor.company_id).with_for_update()
    ).first()
    if proposal is None or not can_view(uow, proposal):
        raise NotFound(code="not_found", resource_type="approvals.proposal")
    if proposal.version != expected_version:
        raise Conflict("This request changed since you opened it", code="proposal_changed", current_version=proposal.version)
    if proposal.status != "pending":
        raise Conflict(f"This request is {proposal.status}", code=f"proposal_{proposal.status}")
    if proposal.expires_at is not None and proposal.expires_at <= uow.now():
        proposal.status = "expired"
        uow.emit("approvals.proposal.expired", aggregate_id=proposal.id, aggregate_version=proposal.version)
        raise Conflict("This request has expired", code="proposal_expired")
    if content_hash_seen != proposal.content_hash:
        raise Conflict("The content you reviewed is not the current proposal", code="proposal_content_mismatch")
    if uow.actor.user_id == proposal.requested_by:
        raise Forbidden("You cannot decide your own request", code="separation_of_duties")
    if not is_eligible(uow, proposal):
        raise Forbidden(code="not_an_eligible_approver")
    handler = handler_for(proposal.kind)
    for target in targets_of(uow, proposal):
        current = handler.current_version(uow, target)
        if current is None or (target.target_version is not None and current != target.target_version):
            proposal.status = "invalidated"
            proposal.invalidated_reason = "target_changed"
            uow.emit("approvals.proposal.invalidated", aggregate_id=proposal.id, aggregate_version=proposal.version, payload={"reason": "target_changed"})
            raise Conflict("The document changed after this request; it needs a fresh review", code="proposal_stale")
    now = uow.now()
    uow.add(
        ProposalDecision(
            proposal_id=proposal.id,
            proposal_version=proposal.version,
            decision=decision,
            content_hash=proposal.content_hash,
            requested_by=proposal.requested_by,
            decided_by=uow.actor.user_id,  # type: ignore[arg-type]
            decided_via=uow.actor.channel,
            reason=reason,
            decided_at=now,
        )
    )
    proposal.status = "approved" if decision == "approve" else "rejected"
    proposal.decided_at = now
    proposal.decided_by = uow.actor.user_id
    proposal.decision_reason = reason
    if decision == "approve":
        handler.on_approved(uow, proposal)
    else:
        handler.on_rejected(uow, proposal)
    uow.flush()
    uow.emit(f"approvals.proposal.{proposal.status}", aggregate_id=proposal.id, aggregate_version=proposal.version, payload={"kind": proposal.kind})
    uow.audit(f"approvals.proposal.{decision}", resource_type="approvals.proposal", resource_id=proposal.id, resource_label=proposal.title, reason=reason)
    return proposal


def withdraw(uow: UnitOfWork, proposal_id: uuid.UUID) -> Proposal:
    proposal = get(uow, proposal_id)
    if proposal.requested_by != uow.actor.user_id:
        raise Forbidden(code="only_requester_can_withdraw")
    if proposal.status != "pending":
        raise Conflict(code=f"proposal_{proposal.status}")
    proposal.status = "withdrawn"
    uow.emit("approvals.proposal.withdrawn", aggregate_id=proposal.id, aggregate_version=proposal.version)
    return proposal


def list_for_actor(uow: UnitOfWork, *, status: str | None = "pending", limit: int = 50) -> list[Proposal]:
    stmt = select(Proposal).where(Proposal.company_id == uow.actor.company_id)
    if status:
        stmt = stmt.where(Proposal.status == status)
    rows = uow.session.scalars(stmt.order_by(Proposal.created_at.desc()).limit(500)).all()
    return [p for p in rows if can_view(uow, p)][:limit]


def expire_due(uow: UnitOfWork) -> int:
    rows = uow.session.scalars(
        select(Proposal).where(
            Proposal.company_id == uow.actor.company_id, Proposal.status == "pending", Proposal.expires_at <= uow.now()
        ).with_for_update(skip_locked=True)
    ).all()
    for proposal in rows:
        proposal.status = "expired"
        uow.emit("approvals.proposal.expired", aggregate_id=proposal.id, aggregate_version=proposal.version)
    return len(rows)
