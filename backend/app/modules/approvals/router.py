"""Approvals API: list my requests and decisions, review one, decide with the exact content hash."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.http.authz_decl import authenticated
from app.core.http.capabilities import Capability
from app.core.http.deps import Actor
from app.modules.approvals import service
from app.modules.approvals.models import Proposal
from app.platform.identity.models import AppUser
from app.platform.uow import UnitOfWork

router = APIRouter(prefix="/approvals", tags=["approvals"])


class TargetOut(BaseModel):
    target_type: str
    target_id: uuid.UUID
    target_version: int | None


class ProposalOut(BaseModel):
    id: uuid.UUID
    kind: str
    status: str
    title: str
    summary: str | None
    facts: dict[str, Any]
    content_hash: str
    requested_by: uuid.UUID
    requested_by_name: str | None
    requested_at: datetime
    expires_at: datetime | None
    decided_at: datetime | None
    decision_reason: str | None
    version: int
    targets: list[TargetOut]
    capabilities: dict[str, Capability]


class DecideIn(BaseModel):
    decision: Literal["approve", "reject"]
    content_hash: str = Field(min_length=64, max_length=64)
    expected_version: int
    reason: str | None = Field(default=None, max_length=1000)


def _out(uow: UnitOfWork, p: Proposal) -> ProposalOut:
    name = uow.session.scalar(select(AppUser.display_name).where(AppUser.id == p.requested_by))
    eligible = p.status == "pending" and service.is_eligible(uow, p)
    can_withdraw = p.status == "pending" and p.requested_by == uow.actor.user_id
    return ProposalOut(
        id=p.id,
        kind=p.kind,
        status=p.status,
        title=p.title,
        summary=p.summary,
        facts=p.facts,
        content_hash=p.content_hash,
        requested_by=p.requested_by,
        requested_by_name=name,
        requested_at=p.created_at,
        expires_at=p.expires_at,
        decided_at=p.decided_at,
        decision_reason=p.decision_reason,
        version=p.version,
        targets=[TargetOut(**t.__dict__) for t in service.targets_of(uow, p)],
        capabilities={
            "decide": Capability(allowed=eligible, reason_code=None if eligible else "not_an_eligible_approver"),
            "withdraw": Capability(allowed=can_withdraw, reason_code=None if can_withdraw else "only_requester_can_withdraw"),
        },
    )


@router.get("/proposals", openapi_extra=authenticated())
def list_proposals(actor: Actor, status: Literal["pending", "approved", "rejected", "expired", "invalidated", "superseded", "withdrawn"] | None = "pending") -> list[ProposalOut]:
    with UnitOfWork(actor) as uow:
        return [_out(uow, p) for p in service.list_for_actor(uow, status=status)]


@router.get("/proposals/{proposal_id}", openapi_extra=authenticated())
def get_proposal(actor: Actor, proposal_id: uuid.UUID) -> ProposalOut:
    with UnitOfWork(actor) as uow:
        return _out(uow, service.get(uow, proposal_id))


@router.post("/proposals/{proposal_id}/decide", openapi_extra=authenticated())
def decide_proposal(actor: Actor, proposal_id: uuid.UUID, body: DecideIn) -> ProposalOut:
    with UnitOfWork(actor) as uow:
        proposal = service.decide(
            uow,
            proposal_id,
            decision=body.decision,
            content_hash_seen=body.content_hash,
            expected_version=body.expected_version,
            reason=body.reason,
        )
        out = _out(uow, proposal)
    service.raise_if_not_decided(proposal)
    return out


@router.post("/proposals/{proposal_id}/withdraw", openapi_extra=authenticated())
def withdraw_proposal(actor: Actor, proposal_id: uuid.UUID) -> ProposalOut:
    with UnitOfWork(actor) as uow:
        return _out(uow, service.withdraw(uow, proposal_id))
