"""Parties (minimal Slice-1 master): party, contacts, addresses, tax identifiers.

Tax identifiers are optional and never marked verified (no fabricated GSTIN/VAT numbers in the world).
Customer agreements are price lists with ``scope_kind='customer'`` (pricing module), not a party table.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

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
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import ArchivableMixin, Base, BranchMixin, TenantEntity, VersionMixin

#: the lead pipeline (spec 2026-11-25-leads-module-design.md); won and lost are closed
LEAD_STAGES = ("new", "contacted", "qualified", "negotiating", "won", "lost")
OPEN_LEAD_STAGES = ("new", "contacted", "qualified", "negotiating")
#: what a lead is interested in: Crown's product lines (fixed list)
INTERESTS = ("lamikraft", "table_top", "standard_decorative", "standard_compact")
PRIORITIES = ("A", "B", "C")
TEMPERATURES = ("hot", "warm", "cold")
ACTIVITY_KINDS = ("call", "email", "whatsapp", "meeting", "visit", "note")
#: built-in lead sources every company has (provisioned on first use; never deleted, only deactivated)
SYSTEM_LEAD_SOURCES = (
    ("website", "Website", 10),
    ("visiting_card", "Visiting card", 20),
    ("trade_show", "Trade show", 30),
    ("referral", "Referral", 40),
    ("other", "Other", 90),
)

ROLE_VALUES = ("customer", "vendor", "fabricator", "job_worker")
#: built-in customer types every company has (provisioned on first use; never deleted, only deactivated)
SYSTEM_CUSTOMER_TYPES = (("standard", "Standard", 10), ("dealer", "Dealer", 20), ("distributor", "Distributor", 30))


class CustomerTypeRecord(TenantEntity, VersionMixin, Base):
    """The customer-type reference table (SC-13): parties reference it by (company, code)."""

    __tablename__ = "parties_customer_type"

    code: Mapped[str] = mapped_column(String(20), nullable=False)
    label: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        UniqueConstraint("company_id", "code", name="uq_parties_customer_type_code"),
        CheckConstraint("code ~ '^[a-z][a-z0-9_]{1,19}$'", name="code_format"),
        CheckConstraint("btrim(label) <> ''", name="label_not_blank"),
    )


class Party(TenantEntity, VersionMixin, ArchivableMixin, BranchMixin, Base):
    __tablename__ = "parties_party"

    party_number: Mapped[str] = mapped_column(String(20), nullable=False)
    legal_name: Mapped[str] = mapped_column(String(200), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    name_key: Mapped[str] = mapped_column(String(200), nullable=False)
    country_code: Mapped[str] = mapped_column(CHAR(2), nullable=False)
    default_currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    customer_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    roles: Mapped[list[str]] = mapped_column(ARRAY(String(20)), nullable=False)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=False
    )
    #: normalised number, names and contact names for tokenised escaped-ILIKE search
    search_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # ---- lead pipeline (NULL for parties without the customer role) ----
    website: Mapped[str | None] = mapped_column(String(200), nullable=True)
    lead_source_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    interests: Mapped[list[str] | None] = mapped_column(ARRAY(String(30)), nullable=True)
    requirement: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_contact_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    lead_stage: Mapped[str | None] = mapped_column(String(20), nullable=True)
    lost_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    priority: Mapped[str | None] = mapped_column(CHAR(1), nullable=True)
    temperature: Mapped[str | None] = mapped_column(String(10), nullable=True)
    #: copied from the latest activity; drives the follow-up task and list sorting
    next_follow_up_on: Mapped[date | None] = mapped_column(Date, nullable=True)

    __table_args__ = (
        Index("uq_parties_party_number", "company_id", "party_number", unique=True),
        Index("ix_parties_party_owner", "company_id", "owner_user_id"),
        Index("ix_parties_party_name_key", "company_id", "name_key"),
        Index("ix_parties_party_roles", "roles", postgresql_using="gin"),
        Index(
            "ix_parties_party_search_trgm",
            "search_text",
            postgresql_using="gin",
            postgresql_ops={"search_text": "gin_trgm_ops"},
        ),
        CheckConstraint("party_number ~ '^P-[0-9]{5,}$'", name="party_number_format"),
        CheckConstraint("country_code ~ '^[A-Z]{2}$'", name="country_code_format"),
        CheckConstraint("default_currency IN ('INR','EUR','USD','GBP')", name="default_currency_enabled"),
        CheckConstraint(
            "cardinality(roles) > 0 AND roles <@ ARRAY['customer','vendor','fabricator','job_worker']::varchar[]",
            name="roles_values",
        ),
        CheckConstraint("btrim(legal_name) <> '' AND btrim(display_name) <> ''", name="names_not_blank"),
        ForeignKeyConstraint(
            ["company_id", "customer_type"],
            ["parties_customer_type.company_id", "parties_customer_type.code"],
            name="fk_parties_party_customer_type",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "lead_source_code"],
            ["parties_lead_source.company_id", "parties_lead_source.code"],
            name="fk_parties_party_lead_source",
            ondelete="RESTRICT",
        ),
        Index("ix_parties_party_lead_stage", "company_id", "lead_stage"),
        Index("ix_parties_party_lead_source", "company_id", "lead_source_code"),
        Index("ix_parties_party_follow_up", "company_id", "owner_user_id", "next_follow_up_on"),
        CheckConstraint(
            "lead_stage IS NULL OR lead_stage IN ('new','contacted','qualified','negotiating','won','lost')",
            name="lead_stage_values",
        ),
        CheckConstraint("(lead_stage IS NOT DISTINCT FROM 'lost') = (lost_reason IS NOT NULL)", name="lost_reason_when_lost"),
        CheckConstraint("priority IS NULL OR priority IN ('A', 'B', 'C')", name="priority_values"),
        CheckConstraint("temperature IS NULL OR temperature IN ('hot', 'warm', 'cold')", name="temperature_values"),
        CheckConstraint(
            "interests IS NULL OR interests <@ "
            "ARRAY['lamikraft','table_top','standard_decorative','standard_compact']::varchar[]",
            name="interests_values",
        ),
        CheckConstraint("requirement IS NULL OR char_length(requirement) <= 2000", name="requirement_length"),
    )


class LeadSourceRecord(TenantEntity, VersionMixin, Base):
    """Where a lead came from (website, a trade show, a visiting card): a per-company managed list."""

    __tablename__ = "parties_lead_source"

    code: Mapped[str] = mapped_column(String(20), nullable=False)
    label: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        UniqueConstraint("company_id", "code", name="uq_parties_lead_source_code"),
        CheckConstraint("code ~ '^[a-z][a-z0-9_]{1,19}$'", name="code_format"),
        CheckConstraint("btrim(label) <> ''", name="label_not_blank"),
    )


class PartyActivity(TenantEntity, Base):
    """One logged touch with a lead or customer. Append-only: a wrong entry is corrected by a new one."""

    __tablename__ = "parties_activity"

    party_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("parties_party.id", ondelete="RESTRICT"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    outcome: Mapped[str | None] = mapped_column(String(200), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_follow_up_on: Mapped[date | None] = mapped_column(Date, nullable=True)

    __table_args__ = (
        Index("ix_parties_activity_party_time", "company_id", "party_id", "occurred_at"),
        CheckConstraint("kind IN ('call','email','whatsapp','meeting','visit','note')", name="kind_values"),
        CheckConstraint("char_length(notes) <= 4000", name="notes_length"),
        CheckConstraint("outcome IS NOT NULL OR notes IS NOT NULL", name="has_content"),
    )


class PartyContact(TenantEntity, ArchivableMixin, Base):
    __tablename__ = "parties_party_contact"

    party_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("parties_party.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    job_title: Mapped[str | None] = mapped_column(String(120), nullable=True)
    email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)



class PartyAddress(TenantEntity, ArchivableMixin, Base):
    __tablename__ = "parties_party_address"

    party_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("parties_party.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    line1: Mapped[str] = mapped_column(String(200), nullable=False)
    line2: Mapped[str | None] = mapped_column(String(200), nullable=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    region: Mapped[str | None] = mapped_column(String(120), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    country_code: Mapped[str] = mapped_column(CHAR(2), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (CheckConstraint("country_code ~ '^[A-Z]{2}$'", name="country_code_format"),)


class PartyTaxIdentifier(TenantEntity, ArchivableMixin, Base):
    __tablename__ = "parties_party_tax_identifier"

    party_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("parties_party.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    scheme: Mapped[str] = mapped_column(String(10), nullable=False)
    value: Mapped[str] = mapped_column(String(40), nullable=False)
    country_code: Mapped[str | None] = mapped_column(CHAR(2), nullable=True)
    verification_status: Mapped[str] = mapped_column(String(20), nullable=False, default="unverified")

    __table_args__ = (
        CheckConstraint("verification_status = 'unverified'", name="never_claimed_verified"),
        CheckConstraint("scheme <> 'gstin' OR value ~ '^[0-9]{2}[A-Z0-9]{13}$'", name="gstin_format"),
        CheckConstraint("scheme <> 'pan' OR value ~ '^[A-Z]{5}[0-9]{4}[A-Z]$'", name="pan_format"),
    )


#: one live primary contact and one live default address per kind; tax identifiers unique among live rows
Index(
    "uq_parties_party_contact_primary",
    PartyContact.party_id,
    unique=True,
    postgresql_where=PartyContact.is_primary & PartyContact.archived_at.is_(None),
)
Index(
    "uq_parties_party_address_default",
    PartyAddress.party_id,
    PartyAddress.kind,
    unique=True,
    postgresql_where=PartyAddress.is_default & PartyAddress.archived_at.is_(None),
)
Index(
    "uq_parties_party_tax_identifier_value",
    PartyTaxIdentifier.company_id,
    PartyTaxIdentifier.scheme,
    PartyTaxIdentifier.value,
    unique=True,
    postgresql_where=PartyTaxIdentifier.archived_at.is_(None),
)

__all__ = [
    "ACTIVITY_KINDS", "INTERESTS", "LEAD_STAGES", "OPEN_LEAD_STAGES", "PRIORITIES", "ROLE_VALUES", "SYSTEM_LEAD_SOURCES",
    "TEMPERATURES", "LeadSourceRecord", "Party", "PartyActivity", "PartyAddress", "PartyContact", "PartyTaxIdentifier",
]
