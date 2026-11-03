"""Sales tables (Slice 1): enquiries, customer messages, quotes with lines, status history, issued revisions
and dispatch records.

Design notes (docs/PLAN.md Slice 1, ADR-036, ADR-046, legacy §10.1 bugs 1/3/13):
- ``sales_quote.quote_number`` is the immutable business key (allocator ``sales.quote``), unique per company and
  never reused: drafts are soft-deleted (``deleted_at``).
- Totals are persisted in NUMERIC(18,4) columns plus the full engine result (``calculation`` JSONB) and are
  recomputed by the commercial engine in the same transaction as every content change.
- Lines carry JSONB snapshots (product, packaging, media, commercial provenance) written through Pydantic models;
  catalogue changes never alter an existing line. ``(quote_id, line_no)`` is a *deferrable* unique constraint so a
  removal can renumber the remaining lines atomically (``uow.defer_constraints``).
- ``sales_quote_status_history`` and ``sales_quote_revision`` are append-only (trigger in the migration).
- Enquiry and message bodies are external content: stored verbatim, never fed to rules as facts.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CHAR,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import (
    ArchivableMixin,
    Base,
    BranchMixin,
    IdMixin,
    TenantEntity,
    TenantMixin,
    VersionMixin,
)

_CURRENCIES = "('INR','EUR','USD','GBP')"
#: the deferrable unique constraint ``uow.defer_constraints`` names when lines are renumbered
LINE_NO_CONSTRAINT = "uq_sales_quote_line_line_no"
#: the deferred composite FK from a line's (quote_id, currency) to its quote (anti-relabel, AVOID-08 / Scenario E)
LINE_CURRENCY_FK = "fk_sales_quote_line_quote_currency"
QUOTE_ID_CURRENCY_KEY = "uq_sales_quote_id_currency"


class Enquiry(TenantEntity, VersionMixin, BranchMixin, Base):
    __tablename__ = "sales_enquiry"

    enquiry_number: Mapped[str] = mapped_column(String(30), nullable=False)
    party_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("parties_party.id", ondelete="RESTRICT"), nullable=False
    )
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("parties_party_contact.id", ondelete="RESTRICT"), nullable=True
    )
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=False
    )
    subject: Mapped[str | None] = mapped_column(String(200), nullable=True)
    #: external content (customer words): stored as given, never a rule fact
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="received")
    outcome_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    quote_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("sales_quote.id", ondelete="RESTRICT", name="fk_sales_enquiry_quote_id_sales_quote", use_alter=True),
        nullable=True,
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: provenance key for idempotent seeds and imports (e.g. ``seed:ENQ_MAISON``)
    origin_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)

    __table_args__ = (
        UniqueConstraint("company_id", "enquiry_number", name="uq_sales_enquiry_number"),
        Index("ix_sales_enquiry_owner", "company_id", "owner_user_id", "status"),
        Index("ix_sales_enquiry_party", "company_id", "party_id"),
        CheckConstraint("enquiry_number ~ '^ENQ-[0-9]{4}-[0-9]{4,}$'", name="enquiry_number_format"),
    )


class CustomerMessage(TenantEntity, VersionMixin, BranchMixin, Base):
    __tablename__ = "sales_customer_message"

    party_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("parties_party.id", ondelete="RESTRICT"), nullable=False
    )
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("parties_party_contact.id", ondelete="RESTRICT"), nullable=True
    )
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    assignee_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=False
    )
    enquiry_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("sales_enquiry.id", ondelete="RESTRICT"), nullable=True
    )
    #: the linked quote: the quote the customer wrote about, or the draft created from this message
    quote_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "sales_quote.id", ondelete="RESTRICT", name="fk_sales_customer_message_quote_id_sales_quote", use_alter=True
        ),
        nullable=True,
    )
    subject: Mapped[str | None] = mapped_column(String(200), nullable=True)
    #: external content: stored as given, never a rule fact
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="received")
    replied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reply_ref_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    reply_ref_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    origin_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)

    __table_args__ = (
        Index("ix_sales_customer_message_assignee", "company_id", "assignee_user_id", "status"),
        Index("ix_sales_customer_message_party", "company_id", "party_id", "received_at"),
        CheckConstraint(
            "(status = 'received' AND replied_at IS NULL) OR (status = 'replied' AND replied_at IS NOT NULL)",
            name="replied_consistent",
        ),
    )


class Quote(TenantEntity, VersionMixin, BranchMixin, ArchivableMixin, Base):
    __tablename__ = "sales_quote"

    quote_number: Mapped[str] = mapped_column(String(30), nullable=False)
    party_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("parties_party.id", ondelete="RESTRICT"), nullable=False
    )
    #: PartySnapshot (name, country, currency, contact, addresses) taken at creation, refreshed only explicitly
    party_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    party_snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: flattened from the snapshot for list filters and search (legacy customer_name / customer_country)
    party_name: Mapped[str] = mapped_column(String(200), nullable=False)
    party_country: Mapped[str] = mapped_column(CHAR(2), nullable=False)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=False
    )
    enquiry_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("sales_enquiry.id", ondelete="RESTRICT"), nullable=True
    )
    origin_message_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("sales_customer_message.id", ondelete="RESTRICT"), nullable=True
    )
    #: who drafted it: user | agent | seed | import | migration
    origin: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
    origin_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    brand: Mapped[str] = mapped_column(String(4), nullable=False)
    price_type: Mapped[str] = mapped_column(String(20), nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    incoterm: Mapped[str | None] = mapped_column(String(10), nullable=True)
    incoterm_place: Mapped[str | None] = mapped_column(String(120), nullable=True)
    payment_terms: Mapped[str | None] = mapped_column(String(200), nullable=True)
    validity_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    customer_reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
    apply_minimum_surcharge: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    #: number of issued revisions (0 = never issued)
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    won_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "sales_quote_revision.id",
            ondelete="RESTRICT",
            name="fk_sales_quote_accepted_revision_id_sales_quote_revision",
            use_alter=True,
        ),
        nullable=True,
    )
    lost_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lost_reason_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_reason_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    #: the status an archived quote came from (``unarchive`` restores it)
    archived_from_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    #: lineage of a duplicate (the source quote) and of a restore (the revision copied into the working copy)
    duplicated_from_quote_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("sales_quote.id", ondelete="RESTRICT", name="fk_sales_quote_duplicated_from_quote_id_sales_quote"),
        nullable=True,
    )
    restored_from_revision_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # ---- persisted commercial result (BUG-03: one result for UI, API, PDF and tools) ----
    gross_subtotal_amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal(0))
    discount_total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal(0))
    net_subtotal_amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal(0))
    applicable_subtotal_amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal(0))
    surcharge_amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal(0))
    grand_total_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    totals_currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    line_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    totals_complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    minimum_status: Mapped[str] = mapped_column(String(20), nullable=False, default="NOT_EVALUATED")
    surcharge_applied: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    surcharge_reason_code: Mapped[str] = mapped_column(String(40), nullable=False, default="ZERO_SUBTOTAL")
    engine_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    rule_set_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    rule_set_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    calc_input_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: the full engine result (``CalculationResult.as_dict``) for this content
    calculation: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    #: stable hash of header + lines + totals; approvals bind to it
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    has_price_override: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    has_discount: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # ---- review ----
    review_proposal_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    approved_proposal_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    approved_content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # ---- soft delete (never-issued drafts only; the number is never reused) ----
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("company_id", "quote_number", name="uq_sales_quote_number"),
        #: target of the lines' deferred (quote_id, currency) FK: a header currency cannot change alone (anti-relabel)
        UniqueConstraint("id", "currency", name=QUOTE_ID_CURRENCY_KEY),
        Index("ix_sales_quote_owner", "company_id", "owner_user_id", "status"),
        Index("ix_sales_quote_party", "company_id", "party_id", "status"),
        Index("ix_sales_quote_status", "company_id", "status", "valid_until"),
        CheckConstraint("quote_number ~ '^[A-Z]{2,4}-QT-[0-9]{4}-[0-9]{4,}$'", name="quote_number_format"),
        CheckConstraint("brand ~ '^[A-Z]{2,4}$'", name="brand_format"),
        CheckConstraint(f"currency IN {_CURRENCIES}", name="currency_enabled"),
        CheckConstraint("totals_currency = currency", name="totals_currency_matches"),
        CheckConstraint("validity_days > 0 AND validity_days <= 365", name="validity_days_range"),
        CheckConstraint("revision_no >= 0", name="revision_no_non_negative"),
        CheckConstraint("line_count >= 0", name="line_count_non_negative"),
        CheckConstraint("(status <> 'won') OR won_at IS NOT NULL", name="won_has_date"),
        CheckConstraint("(status <> 'lost') OR lost_reason_code IS NOT NULL", name="lost_has_reason"),
        CheckConstraint("(status <> 'cancelled') OR cancelled_reason_code IS NOT NULL", name="cancelled_has_reason"),
        CheckConstraint("(deleted_at IS NULL) OR (status = 'draft' AND revision_no = 0)", name="deleted_draft_only"),
        CheckConstraint("(status <> 'archived') OR archived_from_status IS NOT NULL", name="archived_has_origin"),
    )


class QuoteLine(TenantEntity, Base):
    __tablename__ = "sales_quote_line"

    quote_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("sales_quote.id", ondelete="RESTRICT"), nullable=False
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    #: stable identity across renumbering and revisions (compare in Slice 2)
    line_key: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    line_type: Mapped[str] = mapped_column(String(20), nullable=False)
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("catalogue_product.id", ondelete="RESTRICT"), nullable=True
    )
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    manual_preset: Mapped[str | None] = mapped_column(String(40), nullable=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    unit_code: Mapped[str] = mapped_column(String(20), nullable=False)
    default_unit_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    override_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    override_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=True
    )
    override_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    discount_pct: Mapped[Decimal | None] = mapped_column(Numeric(7, 4), nullable=True)
    gross_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    discount_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    #: net line total (``quoted price x quantity`` less the line discount), from the engine
    line_total: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    #: customer-visible line remarks (printed) and the internal note (never printed)
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
    internal_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    price_list_item_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    #: custom lines: the custom product quoted (FK RESTRICT; its spec is snapshotted into ``product_snapshot``)
    custom_product_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("sales_custom_product.id", ondelete="RESTRICT", name="fk_sales_quote_line_custom_product_id", use_alter=True),
        nullable=True,
    )
    #: price provenance: the currency and unit price the line was priced from, and the approved FX rate that
    #: converted it (a line whose currency differs from its source currency must carry an FX rate)
    source_currency: Mapped[str | None] = mapped_column(CHAR(3), nullable=True)
    source_unit_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    fx_rate_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("pricing_fx_rate.id", ondelete="RESTRICT"), nullable=True
    )
    fx_rate: Mapped[Decimal | None] = mapped_column(Numeric(20, 10), nullable=True)
    restored_from_revision_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    product_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    packaging_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    media_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    commercial_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        UniqueConstraint("quote_id", "line_no", name=LINE_NO_CONSTRAINT, deferrable=True, initially="IMMEDIATE"),
        UniqueConstraint("quote_id", "line_key", name="uq_sales_quote_line_line_key"),
        Index("ix_sales_quote_line_product", "company_id", "product_id"),
        CheckConstraint("line_no > 0", name="line_no_positive"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("default_unit_price IS NULL OR default_unit_price >= 0", name="default_price_non_negative"),
        CheckConstraint("unit_price IS NULL OR unit_price >= 0", name="unit_price_non_negative"),
        CheckConstraint("discount_pct IS NULL OR (discount_pct >= 0 AND discount_pct <= 100)", name="discount_range"),
        CheckConstraint(f"currency IN {_CURRENCIES}", name="currency_enabled"),
        CheckConstraint(
            "(line_type = 'catalog' AND product_id IS NOT NULL AND custom_product_id IS NULL) "
            "OR (line_type = 'manual' AND product_id IS NULL AND custom_product_id IS NULL) "
            "OR (line_type = 'custom' AND custom_product_id IS NOT NULL AND product_id IS NULL)",
            name="line_type_reference",
        ),
        CheckConstraint(
            "source_currency IS NULL OR currency = source_currency OR fx_rate_id IS NOT NULL", name="no_currency_relabel"
        ),
        CheckConstraint("(fx_rate_id IS NULL) = (fx_rate IS NULL)", name="fx_rate_pair"),
        ForeignKeyConstraint(
            ["quote_id", "currency"],
            ["sales_quote.id", "sales_quote.currency"],
            name=LINE_CURRENCY_FK,
            deferrable=True,
            initially="DEFERRED",
            ondelete="RESTRICT",
        ),
    )


class QuoteStatusHistory(IdMixin, TenantMixin, Base):
    __tablename__ = "sales_quote_status_history"
    __append_only__ = True

    quote_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("sales_quote.id", ondelete="RESTRICT"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    from_status: Mapped[str] = mapped_column(String(20), nullable=False)
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=True
    )
    reason_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: the quote version after the transition
    quote_version: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (Index("ix_sales_quote_status_history_quote", "quote_id", "occurred_at"),)


class QuoteRevision(IdMixin, TenantMixin, Base):
    __tablename__ = "sales_quote_revision"
    __append_only__ = True

    quote_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("sales_quote.id", ondelete="RESTRICT"), nullable=False
    )
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="issued")
    #: RevisionSnapshot: header + lines + totals + terms + company identity (the document input)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    valid_until: Mapped[date] = mapped_column(Date, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    issued_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=True
    )
    #: sha256 of the deterministic PDF rendered from ``snapshot`` (verified again by ``sales.document_render``)
    document_sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint("quote_id", "revision_no", name="uq_sales_quote_revision_no"),
        CheckConstraint("revision_no > 0", name="revision_no_positive"),
    )


class QuoteDispatch(IdMixin, TenantMixin, Base):
    __tablename__ = "sales_quote_dispatch"

    quote_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("sales_quote.id", ondelete="RESTRICT"), nullable=False
    )
    revision_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("sales_quote_revision.id", ondelete="RESTRICT"), nullable=False
    )
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sent_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=True
    )
    sent_to: Mapped[str | None] = mapped_column(String(254), nullable=True)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)

    __table_args__ = (Index("ix_sales_quote_dispatch_quote", "quote_id", "sent_at"),)


class CustomProduct(TenantEntity, VersionMixin, BranchMixin, ArchivableMixin, Base):
    """A custom (non-catalogue) product: the legacy custom-product library with every legacy field (spec 4.13).

    ``custom_code`` (``CP-NNNN``) comes from the never-reset allocator ``sales.custom_product``. Costing lives in the
    protected, versioned ``sales_custom_product_costing`` table and never in this row or its read models.
    """

    __tablename__ = "sales_custom_product"

    custom_code: Mapped[str] = mapped_column(String(20), nullable=False)
    custom_type: Mapped[str] = mapped_column(String(20), nullable=False)
    base_product_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("catalogue_product.id", ondelete="RESTRICT"), nullable=True
    )
    base_product_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    customer_specific_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    party_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("parties_party.id", ondelete="RESTRICT"), nullable=True
    )
    legacy_customer_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    inquiry_reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    product_name: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("catalogue_category.id", ondelete="RESTRICT"), nullable=True
    )
    subcategory_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("catalogue_subcategory.id", ondelete="RESTRICT"), nullable=True
    )
    dimensions_text: Mapped[str | None] = mapped_column(String(200), nullable=True)
    length_mm: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    width_mm: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    height_mm: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    thickness_mm: Mapped[Decimal | None] = mapped_column(Numeric(8, 3), nullable=True)
    thickness_text: Mapped[str | None] = mapped_column(String(40), nullable=True)
    decor_no: Mapped[str | None] = mapped_column(String(40), nullable=True)
    decor_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    finish: Mapped[str | None] = mapped_column(String(120), nullable=True)
    shape: Mapped[str | None] = mapped_column(String(120), nullable=True)
    groove_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bowl_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    handle_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    packaging_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: CustomPackaging (carton/inner qty, packing type, unit weight g, carton dimensions, cbm) through Pydantic
    packaging: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    quoted_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    quoted_currency: Mapped[str | None] = mapped_column(CHAR(3), nullable=True)
    unit_code: Mapped[str] = mapped_column(String(20), nullable=False, default="pcs")
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="inquiry")
    dormant_from_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    status_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=False
    )
    promoted_product_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("catalogue_product.id", ondelete="RESTRICT"), nullable=True
    )
    duplicated_from_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("sales_custom_product.id", ondelete="RESTRICT", name="fk_sales_custom_product_duplicated_from"),
        nullable=True,
    )
    legacy_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    origin_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)

    __table_args__ = (
        UniqueConstraint("company_id", "custom_code", name="uq_sales_custom_product_code"),
        Index("ix_sales_custom_product_status", "company_id", "status"),
        Index("ix_sales_custom_product_owner", "company_id", "owner_user_id", "status"),
        Index("ix_sales_custom_product_party", "company_id", "party_id"),
        Index("ix_sales_custom_product_category", "company_id", "category_id"),
        CheckConstraint("custom_code ~ '^CP-[0-9]{4,}$'", name="custom_code_format"),
        CheckConstraint("(quoted_price IS NULL) = (quoted_currency IS NULL)", name="quoted_price_pair"),
        CheckConstraint("quoted_price IS NULL OR quoted_price >= 0", name="quoted_price_non_negative"),
        CheckConstraint(f"quoted_currency IS NULL OR quoted_currency IN {_CURRENCIES}", name="quoted_currency_enabled"),
        CheckConstraint(
            "(length_mm IS NULL OR length_mm > 0) AND (width_mm IS NULL OR width_mm > 0) AND "
            "(height_mm IS NULL OR height_mm > 0) AND (thickness_mm IS NULL OR thickness_mm > 0)",
            name="dimensions_positive",
        ),
        CheckConstraint(
            "(groove_count IS NULL OR groove_count >= 0) AND (bowl_count IS NULL OR bowl_count >= 0)",
            name="counts_non_negative",
        ),
        CheckConstraint("custom_type <> 'modified_catalog' OR base_product_id IS NOT NULL", name="modified_catalog_has_base"),
        CheckConstraint("(status = 'converted_to_standard') = (promoted_product_id IS NOT NULL)", name="converted_has_product"),
        CheckConstraint("(status <> 'dormant') OR dormant_from_status IS NOT NULL", name="dormant_has_origin"),
    )


class CustomProductCosting(IdMixin, TenantMixin, Base):
    """Protected, versioned costing of a custom product (guard ``pricing.cost.read``; reads are audited)."""

    __tablename__ = "sales_custom_product_costing"
    __append_only__ = True

    custom_product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("sales_custom_product.id", ondelete="RESTRICT"), nullable=False
    )
    cost_version: Mapped[int] = mapped_column(Integer, nullable=False)
    cost_amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    cost_currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    components: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    basis_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("custom_product_id", "cost_version", name="uq_sales_custom_product_costing_version"),
        CheckConstraint("cost_amount >= 0", name="cost_non_negative"),
        CheckConstraint("cost_version > 0", name="cost_version_positive"),
        CheckConstraint(f"cost_currency IN {_CURRENCIES}", name="cost_currency_enabled"),
    )


class CustomProductSpecRevision(TenantEntity, VersionMixin, Base):
    """A specification of a custom product with its sample history and outcome (LP-08.5)."""

    __tablename__ = "sales_custom_product_spec_revision"

    custom_product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("sales_custom_product.id", ondelete="RESTRICT"), nullable=False
    )
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    spec_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    sample_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("sales_sample.id", ondelete="RESTRICT", name="fk_sales_custom_product_spec_revision_sample", use_alter=True),
        nullable=True,
    )
    sample_reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    sample_sent_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("custom_product_id", "revision_no", name="uq_sales_custom_product_spec_revision_no"),
        CheckConstraint("revision_no > 0", name="revision_no_positive"),
        CheckConstraint("(outcome = 'pending') = (decided_at IS NULL)", name="decision_recorded"),
    )


class CustomProductStatusHistory(IdMixin, TenantMixin, Base):
    __tablename__ = "sales_custom_product_status_history"
    __append_only__ = True

    custom_product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("sales_custom_product.id", ondelete="RESTRICT"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    from_status: Mapped[str] = mapped_column(String(30), nullable=False)
    to_status: Mapped[str] = mapped_column(String(30), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=True
    )
    #: the quote whose issue moved the product forward (system transitions)
    quote_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("sales_quote.id", ondelete="RESTRICT"), nullable=True
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_sales_custom_product_status_history_product", "custom_product_id", "occurred_at"),)


class CustomProductPromotion(TenantEntity, VersionMixin, Base):
    """Promotion of an approved custom product to a catalogue master product: the payload is bound to an approval
    by its hash; execution is idempotent and records lineage on both sides."""

    __tablename__ = "sales_custom_product_promotion"

    custom_product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("sales_custom_product.id", ondelete="RESTRICT"), nullable=False
    )
    spec_revision_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("sales_custom_product_spec_revision.id", ondelete="RESTRICT"), nullable=False
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending_approval")
    proposal_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    executed_product_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("catalogue_product.id", ondelete="RESTRICT"), nullable=True
    )
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    executed_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=True
    )
    failure_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    __table_args__ = (
        Index("ix_sales_custom_product_promotion_product", "custom_product_id", "status"),
        CheckConstraint("(status = 'executed') = (executed_product_id IS NOT NULL)", name="executed_has_product"),
    )


class Sample(TenantEntity, VersionMixin, BranchMixin, Base):
    """A sample sent to a customer (``SMP-YYYY-NNNN``) with lineage to a quote and/or a custom product."""

    __tablename__ = "sales_sample"

    sample_number: Mapped[str] = mapped_column(String(20), nullable=False)
    party_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("parties_party.id", ondelete="RESTRICT"), nullable=False
    )
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=False
    )
    quote_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("sales_quote.id", ondelete="RESTRICT"), nullable=True
    )
    custom_product_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("sales_custom_product.id", ondelete="RESTRICT"), nullable=True
    )
    spec_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("sales_custom_product_spec_revision.id", ondelete="RESTRICT", name="fk_sales_sample_spec_revision_id"),
        nullable=True,
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("catalogue_product.id", ondelete="RESTRICT"), nullable=True
    )
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    unit_code: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="requested")
    requested_on: Mapped[date] = mapped_column(Date, nullable=False)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dispatch_reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    #: the delivery challan that carried the sample (challans module; no FK across lanes yet)
    #: the challan that dispatched the sample (FK added at the Slice-2 merge, migration 0015)
    challan_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("challans_challan.id", ondelete="RESTRICT"), nullable=True
    )
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivery_evidence_kind: Mapped[str | None] = mapped_column(String(30), nullable=True)
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    feedback_outcome: Mapped[str | None] = mapped_column(String(30), nullable=True)
    feedback_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    close_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("company_id", "sample_number", name="uq_sales_sample_number"),
        Index("ix_sales_sample_owner", "company_id", "owner_user_id", "status"),
        Index("ix_sales_sample_party", "company_id", "party_id"),
        Index("ix_sales_sample_quote", "company_id", "quote_id"),
        Index("ix_sales_sample_custom_product", "company_id", "custom_product_id"),
        CheckConstraint("sample_number ~ '^SMP-[0-9]{4}-[0-9]{4,}$'", name="sample_number_format"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("(status IN ('requested', 'cancelled')) OR dispatched_at IS NOT NULL", name="dispatched_recorded"),
        CheckConstraint(
            "(status NOT IN ('delivered', 'feedback_received')) OR delivered_at IS NOT NULL", name="delivered_recorded"
        ),
    )


__all__ = [
    "LINE_CURRENCY_FK",
    "LINE_NO_CONSTRAINT",
    "QUOTE_ID_CURRENCY_KEY",
    "CustomProduct",
    "CustomProductCosting",
    "CustomProductPromotion",
    "CustomProductSpecRevision",
    "CustomProductStatusHistory",
    "CustomerMessage",
    "Enquiry",
    "Quote",
    "QuoteDispatch",
    "QuoteLine",
    "QuoteRevision",
    "QuoteStatusHistory",
    "Sample",
]
