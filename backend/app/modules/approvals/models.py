"""Proposals and decisions. Approval is bound to an exact proposal version and content hash.

Separation of duties is enforced by the database: a decision row must not be made by the requester.
Any change to a target after submission invalidates the pending proposal (fresh approval needed).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, IdMixin, TenantEntity, TenantMixin, VersionMixin

PROPOSAL_STATUSES = ("pending", "approved", "rejected", "expired", "invalidated", "superseded", "withdrawn")


class Proposal(TenantEntity, VersionMixin, Base):
    __tablename__ = "approvals_proposal"

    kind: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    facts: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_key: Mapped[str] = mapped_column(String(80), nullable=False)
    required_permission: Mapped[str] = mapped_column(String(120), nullable=False)
    requested_by: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("app_user.id"), nullable=False)
    requested_via: Mapped[str] = mapped_column(String(20), nullable=False, default="web")
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("app_user.id"), nullable=True)
    decision_reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    invalidated_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("approvals_proposal.id"), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','approved','rejected','expired','invalidated','superseded','withdrawn')",
            name="status_values",
        ),
        Index("ix_approvals_proposal_status", "company_id", "status", "kind"),
        Index("ix_approvals_proposal_requester", "company_id", "requested_by", "status"),
    )


class ProposalTarget(IdMixin, TenantMixin, Base):
    __tablename__ = "approvals_proposal_target"

    proposal_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("approvals_proposal.id"), nullable=False)
    target_type: Mapped[str] = mapped_column(String(80), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    target_version: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        Index("ix_approvals_target_lookup", "company_id", "target_type", "target_id"),
        Index("uq_approvals_target", "proposal_id", "target_type", "target_id", unique=True),
    )


class ProposalDecision(IdMixin, TenantMixin, Base):
    __tablename__ = "approvals_decision"
    __append_only__ = True

    proposal_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("approvals_proposal.id"), nullable=False)
    proposal_version: Mapped[int] = mapped_column(Integer, nullable=False)
    decision: Mapped[str] = mapped_column(String(10), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_by: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    decided_by: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("app_user.id"), nullable=False)
    decided_via: Mapped[str] = mapped_column(String(20), nullable=False, default="web")
    reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("decision IN ('approve','reject')", name="decision_values"),
        CheckConstraint("decided_by <> requested_by", name="separation_of_duties"),
        Index("uq_approvals_decision_once", "proposal_id", unique=True),
    )


__all__ = ["Proposal", "ProposalDecision", "ProposalTarget", "text"]
