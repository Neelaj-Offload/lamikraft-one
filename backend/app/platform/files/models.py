"""``file_object``: one content-addressed row per (company, sha256).

The storage key is random and never derived from the user's filename. The sniffed content type, not the
declared one, decides how a download is served. Parents (quote documents, product media, the company logo)
reference files by id and authorise downloads through ``register_file_access``.

Dedupe keeps one row (and one stored blob) per company and content, but ownership is per person: ``claims``
lists every user who stored these bytes, once per purpose, with the name that user gave them. The creator-only
fallbacks (exports, files nothing references yet) authorise each claimant, so a second person who uploads or
exports identical bytes can read what they stored, and nobody else can through that path.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import ActorStampMixin, Base, IdMixin, TenantMixin, TimestampMixin, enum_column


class FilePurpose(StrEnum):
    IMAGE = "image"
    DOCUMENT = "document"
    IMPORT = "import"
    EXPORT = "export"


class FileKind(StrEnum):
    PNG = "png"
    JPEG = "jpeg"
    GIF = "gif"
    WEBP = "webp"
    PDF = "pdf"
    XLSX = "xlsx"
    CSV = "csv"
    TXT = "txt"


class FileObject(IdMixin, TenantMixin, TimestampMixin, ActorStampMixin, Base):
    __tablename__ = "file_object"

    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    kind: Mapped[str] = enum_column(FileKind, length=10)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    declared_content_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    purpose: Mapped[str] = enum_column(FilePurpose, length=20)
    storage_backend: Mapped[str] = mapped_column(String(20), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(200), nullable=False)
    #: restricted content (e.g. an export containing costing): downloads are never cached and are audited
    restricted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: ``[{"user_id", "purpose", "name"}]``: everyone who stored these bytes, once per (user, purpose); appended
    #: atomically by ``files.service`` and never shown to other users
    claims: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )

    __table_args__ = (
        Index("uq_file_object_company_sha256", "company_id", "sha256", unique=True),
        Index("uq_file_object_storage_key", "storage_key", unique=True),
        Index("ix_file_object_creator", "company_id", "created_by", "created_at"),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="sha256_format"),
        CheckConstraint("size_bytes >= 0", name="size_non_negative"),
        CheckConstraint("purpose IN ('image','document','import','export')", name="purpose_values"),
        CheckConstraint("kind IN ('png','jpeg','gif','webp','pdf','xlsx','csv','txt')", name="kind_values"),
        CheckConstraint("storage_backend IN ('local_fs','s3')", name="storage_backend_values"),
        CheckConstraint("jsonb_typeof(claims) = 'array'", name="claims_array"),
    )
