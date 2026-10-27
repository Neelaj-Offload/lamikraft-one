"""Parties (minimal Slice-1 master): party, contacts, addresses, tax identifiers.

Tax identifiers are optional and never marked verified (no fabricated GSTIN/VAT numbers in the world).
Customer agreements are price lists with ``scope_kind='customer'`` (pricing module), not a party table.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    CHAR,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import ArchivableMixin, Base, BranchMixin, TenantEntity, VersionMixin

ROLE_VALUES = ("customer", "vendor", "fabricator", "job_worker")


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

__all__ = ["ROLE_VALUES", "Party", "PartyAddress", "PartyContact", "PartyTaxIdentifier"]
