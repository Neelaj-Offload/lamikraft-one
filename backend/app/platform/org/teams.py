"""Teams and team members (org-owned tables; membership changes are made through the identity service).

Team membership feeds ``ActorContext.team_peer_user_ids`` for ``team``-scoped permissions, so every change
increments ``company.authz_epoch`` and emits ``identity.membership.access_changed`` (permissions.md §10).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import ArchivableMixin, Base, IdMixin, TenantMixin, TimestampMixin, VersionMixin


class TeamRole(StrEnum):
    MEMBER = "member"
    LEAD = "lead"


class Team(IdMixin, TenantMixin, TimestampMixin, VersionMixin, ArchivableMixin, Base):
    __tablename__ = "team"

    team_key: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    branch_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("branch.id", ondelete="RESTRICT"), nullable=True
    )

    __table_args__ = (
        Index("uq_team_company_key", "company_id", "team_key", unique=True),
        CheckConstraint("team_key ~ '^[A-Z0-9][A-Z0-9-]{1,39}$'", name="team_key_format"),
    )


class TeamMember(TenantMixin, Base):
    __tablename__ = "team_member"

    team_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("team.id", ondelete="CASCADE"), primary_key=True
    )
    membership_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("membership.id", ondelete="CASCADE"), primary_key=True
    )
    team_role: Mapped[str] = mapped_column(String(10), nullable=False, default=TeamRole.MEMBER.value)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_team_member_membership", "company_id", "membership_id"),
        CheckConstraint("team_role IN ('member','lead')", name="team_role_values"),
    )
