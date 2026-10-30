"""Pricing tables: price lists, items, append-only item history and the protected product cost of record.

Customer agreements are price lists with ``scope_kind='customer'`` (party_id set); customer-type lists carry a
``customer_type``. Items never overlap in validity for the same (list, product, unit) while active (exclusion
constraint in the migration). Changing a price on an active list is an effective-dated supersede with history;
Slice-2 FX snapshots attach to quote lines (fx_rate_id) and never relabel a list currency.
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

from app.core.db.base import Base, IdMixin, TenantEntity, TenantMixin, VersionMixin

_CURRENCIES = "('INR','EUR','USD','GBP')"


class PriceList(TenantEntity, VersionMixin, Base):
    __tablename__ = "pricing_price_list"

    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    price_type: Mapped[str] = mapped_column(String(20), nullable=False)
    scope_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="standard")
    party_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("parties_party.id", ondelete="RESTRICT"), nullable=True
    )
    customer_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    default_unit_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    price_basis: Mapped[str | None] = mapped_column(String(120), nullable=True)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    #: explicit priority among overlapping lists of one tier (higher wins); NULL means "no explicit priority"
    priority: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    source_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    activated_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=True
    )
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retired_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=True
    )
    retire_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    __table_args__ = (
        UniqueConstraint("company_id", "code", name="uq_pricing_price_list_code"),
        UniqueConstraint("id", "currency", name="uq_pricing_price_list_id_currency"),
        CheckConstraint(f"currency IN {_CURRENCIES}", name="currency_enabled"),
        CheckConstraint("valid_to IS NULL OR valid_to >= valid_from", name="validity_order"),
        CheckConstraint(
            "(scope_kind = 'customer' AND party_id IS NOT NULL AND customer_type IS NULL) OR "
            "(scope_kind = 'customer_type' AND party_id IS NULL AND customer_type IS NOT NULL) OR "
            "(scope_kind = 'standard' AND party_id IS NULL AND customer_type IS NULL)",
            name="scope_target",
        ),
        CheckConstraint("priority IS NULL OR priority >= 0", name="priority_non_negative"),
        Index("ix_pricing_price_list_lookup", "company_id", "status", "scope_kind", "price_type", "currency"),
        Index("ix_pricing_price_list_party", "company_id", "party_id"),
    )


class PriceListItem(TenantEntity, VersionMixin, Base):
    __tablename__ = "pricing_price_list_item"

    price_list_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("pricing_price_list.id", ondelete="RESTRICT"), nullable=False
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("catalogue_product.id", ondelete="RESTRICT"), nullable=False
    )
    product_key: Mapped[str] = mapped_column(String(120), nullable=False)
    display_sku: Mapped[str | None] = mapped_column(String(120), nullable=True)
    unit_code: Mapped[str] = mapped_column(String(20), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    final_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    base_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    base_price_label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    addon_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    addon_price_label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    price_basis: Mapped[str | None] = mapped_column(String(120), nullable=True)
    yield_qty_per_board: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    thickness_mm: Mapped[Decimal | None] = mapped_column(Numeric(8, 3), nullable=True)
    moq: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    moq_unit_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    superseded_by_item_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("pricing_price_list_item.id", ondelete="RESTRICT", name="fk_pricing_price_list_item_superseded_by"),
        nullable=True,
    )
    source_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    source_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_sheet: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_row: Mapped[str | None] = mapped_column(String(40), nullable=True)
    #: the import job that created the row (Slice 2; the FK to the imports job table is added when imports land)
    import_job_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)

    __table_args__ = (
        CheckConstraint("unit_price >= 0", name="unit_price_non_negative"),
        CheckConstraint("final_price IS NULL OR final_price = unit_price", name="final_price_matches_unit_price"),
        CheckConstraint(
            "(base_price IS NULL OR base_price >= 0) AND (addon_price IS NULL OR addon_price >= 0)",
            name="breakdown_non_negative",
        ),
        CheckConstraint(
            "(yield_qty_per_board IS NULL OR yield_qty_per_board > 0) AND (moq IS NULL OR moq > 0) "
            "AND (thickness_mm IS NULL OR thickness_mm > 0)",
            name="quantities_positive",
        ),
        CheckConstraint("valid_to IS NULL OR valid_to >= valid_from", name="validity_order"),
        Index("ix_pricing_price_list_item_product", "company_id", "product_id"),
        Index("ix_pricing_price_list_item_list_product", "price_list_id", "product_id"),
    )


class PriceListItemHistory(IdMixin, TenantMixin, Base):
    """Append-only price history (who changed which price, when, and the before/after snapshot)."""

    __tablename__ = "pricing_price_list_item_history"
    __append_only__ = True

    item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("pricing_price_list_item.id", ondelete="RESTRICT", name="fk_pricing_price_list_item_history_item"),
        nullable=False,
    )
    price_list_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("pricing_price_list.id", ondelete="RESTRICT", name="fk_pricing_price_list_item_history_list"),
        nullable=False,
    )
    change_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=True
    )

    __table_args__ = (Index("ix_pricing_price_list_item_history_item", "item_id", "occurred_at"),)


class ProductCost(TenantEntity, Base):
    """Protected cost of record per product version (guard ``pricing.cost.read``; never sent to a model)."""

    __tablename__ = "pricing_product_cost"
    __append_only__ = True

    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("catalogue_product.id", ondelete="RESTRICT"), nullable=False
    )
    cost_version: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_cost_amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    unit_cost_currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    unit_code: Mapped[str] = mapped_column(String(20), nullable=False)
    cost_components: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    source_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    source_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("company_id", "product_id", "cost_version", name="uq_pricing_product_cost_version"),
        CheckConstraint("unit_cost_amount >= 0", name="unit_cost_non_negative"),
        CheckConstraint(f"unit_cost_currency IN {_CURRENCIES}", name="unit_cost_currency_enabled"),
        CheckConstraint("cost_version > 0", name="cost_version_positive"),
    )


class FxRate(TenantEntity, VersionMixin, Base):
    """A dated, sourced FX snapshot (1 ``base_currency`` = ``rate`` ``quote_currency``).

    Proposed by one person and approved by another through the approvals engine (``pricing.fx_rate.approve``); only
    an approved rate converts a price. One approved rate per (pair, date); rates are never invented or relabelled.
    """

    __tablename__ = "pricing_fx_rate"

    base_currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    quote_currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    rate: Mapped[Decimal] = mapped_column(Numeric(20, 10), nullable=False)
    rate_date: Mapped[date] = mapped_column(Date, nullable=False)
    source_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    source_reference: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="proposed")
    proposal_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    proposed_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=True
    )
    proposed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        CheckConstraint("rate > 0", name="rate_positive"),
        CheckConstraint("base_currency <> quote_currency", name="distinct_currencies"),
        CheckConstraint(f"base_currency IN {_CURRENCIES}", name="base_currency_enabled"),
        CheckConstraint(f"quote_currency IN {_CURRENCIES}", name="quote_currency_enabled"),
        CheckConstraint(
            "(status IN ('approved', 'rejected') AND decided_at IS NOT NULL) OR (status NOT IN ('approved', 'rejected'))",
            name="decision_recorded",
        ),
        CheckConstraint("decided_by IS NULL OR decided_by IS DISTINCT FROM proposed_by", name="separation_of_duties"),
        Index("ix_pricing_fx_rate_pair", "company_id", "base_currency", "quote_currency", "status", "rate_date"),
    )


#: one approved rate per pair and day (partial unique index; declared after the class to reference its columns)
Index(
    "uq_pricing_fx_rate_approved_day",
    FxRate.company_id,
    FxRate.base_currency,
    FxRate.quote_currency,
    FxRate.rate_date,
    unique=True,
    postgresql_where=FxRate.status == "approved",
)


class FxPolicyRow(TenantEntity, VersionMixin, Base):
    """The company FX policy (one row per company; absent means the defaults of ``schemas.FxPolicy``)."""

    __tablename__ = "pricing_fx_policy"

    conversion_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    conversion_source_currency: Mapped[str] = mapped_column(CHAR(3), nullable=False, default="EUR")
    max_rate_age_days: Mapped[int] = mapped_column(Integer, nullable=False, default=7)

    __table_args__ = (
        UniqueConstraint("company_id", name="uq_pricing_fx_policy_company"),
        CheckConstraint(f"conversion_source_currency IN {_CURRENCIES}", name="source_currency_enabled"),
        CheckConstraint("max_rate_age_days >= 0 AND max_rate_age_days <= 90", name="max_age_range"),
    )


__all__ = ["FxPolicyRow", "FxRate", "PriceList", "PriceListItem", "PriceListItemHistory", "ProductCost"]
