"""Proforma invoices (module 3, spec docs/superpowers/specs/2026-11-25-proforma-invoices-design.md).

A PI is what Lamikraft sends a client, priced from a quotation's issued revision. Lines, party block and totals are
copied into ``snapshot`` when the PI is created; the header (ports, terms, bank account, declaration) is edited while
draft and frozen at issue together with the company identity. The PDF is re-rendered from the frozen record on
download (like quotations), so nothing drifts after issue.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import CHAR, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, BranchMixin, TenantEntity, VersionMixin

PROFORMA_STATUSES = ("draft", "issued", "cancelled")
PI_NUMBER_PATTERN = r"^[A-Za-z0-9/_.-]{3,40}$"


class ProformaInvoice(TenantEntity, VersionMixin, BranchMixin, Base):
    __tablename__ = "sales_proforma_invoice"

    #: ``PI-YYYY-NNNN`` at issue, or the original number of a PI entered from history; NULL while draft
    pi_number: Mapped[str | None] = mapped_column(String(40), nullable=True)
    quote_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("sales_quote.id", ondelete="RESTRICT"), nullable=False
    )
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    party_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("parties_party.id", ondelete="RESTRICT"), nullable=False
    )
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    pi_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    #: lines, party block, totals and quotation header copied from the revision; company identity added at issue
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    port_of_loading: Mapped[str | None] = mapped_column(String(120), nullable=True)
    port_of_discharge: Mapped[str | None] = mapped_column(String(120), nullable=True)
    payment_terms: Mapped[str | None] = mapped_column(String(500), nullable=True)
    delivery_terms: Mapped[str | None] = mapped_column(String(200), nullable=True)
    bank_account_label: Mapped[str | None] = mapped_column(String(80), nullable=True)
    declaration: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    issued_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=True
    )
    #: True when entered from history with its original number and date
    backfilled: Mapped[bool] = mapped_column(nullable=False, default=False)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    __table_args__ = (
        Index("uq_sales_proforma_invoice_number", "company_id", "pi_number", unique=True,
              postgresql_where="pi_number IS NOT NULL"),
        Index("ix_sales_proforma_invoice_party", "company_id", "party_id"),
        Index("ix_sales_proforma_invoice_quote", "company_id", "quote_id"),
        CheckConstraint("status IN ('draft','issued','cancelled')", name="status_values"),
        # a draft has no number; an issued PI has one; a cancelled PI keeps whatever it had (a draft may be discarded)
        CheckConstraint(
            "(status <> 'draft' OR pi_number IS NULL) AND (status <> 'issued' OR pi_number IS NOT NULL)",
            name="number_when_issued",
        ),
        CheckConstraint("status <> 'cancelled' OR cancel_reason IS NOT NULL", name="cancel_reason_required"),
        CheckConstraint("declaration IS NULL OR char_length(declaration) <= 2000", name="declaration_length"),
        CheckConstraint("notes IS NULL OR char_length(notes) <= 4000", name="notes_length"),
    )
