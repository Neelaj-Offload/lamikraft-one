"""Atomic document numbering. Numbers are allocated inside the business transaction, registered in
``issued_document_number`` and never reused (voided documents keep their number)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import ArchivableMixin, Base, IdMixin, TenantMixin, TimestampMixin, VersionMixin


class DocumentSequence(IdMixin, TenantMixin, TimestampMixin, VersionMixin, ArchivableMixin, Base):
    __tablename__ = "document_sequence"

    branch_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("branch.id", ondelete="RESTRICT"), nullable=True
    )
    sequence_key: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    format_template: Mapped[str] = mapped_column(String(120), nullable=False)
    reset_policy: Mapped[str] = mapped_column(String(20), nullable=False)
    period_time_zone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Kolkata")
    financial_year_start_month: Mapped[int] = mapped_column(Integer, nullable=False, default=4)
    start_value: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)

    __table_args__ = (
        Index(
            "uq_document_sequence_key",
            "company_id",
            "branch_id",
            "sequence_key",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint("reset_policy IN ('never','yearly','financial_year')", name="reset_policy_values"),
        CheckConstraint("format_template LIKE '%{seq%'", name="format_has_seq"),
    )


class DocumentSequenceCounter(Base):
    __tablename__ = "document_sequence_counter"

    sequence_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("document_sequence.id", ondelete="RESTRICT"), primary_key=True
    )
    period_key: Mapped[str] = mapped_column(String(16), primary_key=True)
    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("company.id", ondelete="RESTRICT"), nullable=False
    )
    next_value: Mapped[int] = mapped_column(BigInteger, nullable=False)

    __table_args__ = (CheckConstraint("next_value > 0", name="next_value_positive"),)


class IssuedDocumentNumber(IdMixin, TenantMixin, Base):
    __tablename__ = "issued_document_number"

    sequence_key: Mapped[str] = mapped_column(String(80), nullable=False)
    document_number: Mapped[str] = mapped_column(String(80), nullable=False)
    sequence_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("document_sequence.id", ondelete="RESTRICT"), nullable=False
    )
    period_key: Mapped[str] = mapped_column(String(16), nullable=False)
    seq_value: Mapped[int] = mapped_column(BigInteger, nullable=False)
    resource_type: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    issued_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="active")
    void_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    __table_args__ = (
        Index("uq_issued_number", "company_id", "sequence_key", "document_number", unique=True),
        Index("uq_issued_resource", "company_id", "resource_type", "resource_id", "sequence_key", unique=True),
        CheckConstraint("status IN ('active','voided')", name="status_values"),
    )


__all__ = ["DocumentSequence", "DocumentSequenceCounter", "IssuedDocumentNumber", "text"]
