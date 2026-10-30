"""Product media (LM-23..27, FG-MED-*): images, documents and packaging photos linked to ``platform/files`` objects.

Upload is two steps on the same origin: the browser streams the bytes to ``POST /api/v1/files`` (sniffed, size
limited, content-addressed, deduplicated by sha256) and then attaches the returned file id here. Downloads go through
``GET /api/v1/files/{id}/content`` (cookie session, no tokens in URLs), authorised by the file-access checker this
module registers: a file is readable when the actor can read a product that links it.

Rules: one live primary image per product (partial unique index; images only), the first stored image becomes
primary automatically, deleting the primary promotes the next image by (sort_order, uploaded_at), soft delete keeps
the object (quote snapshots stay renderable) and restore brings the link back. ``catalogue.media.manage`` at own
scope may change only media the actor uploaded; at company scope any.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import exists, select, update

from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.core.http.capabilities import Capability
from app.modules.catalogue import events as ev
from app.modules.catalogue.models import Product, ProductMedia
from app.platform.authz.permissions import Scope
from app.platform.service import query
from app.platform.uow import UnitOfWork

MANAGE = "catalogue.media.manage"
READ = "catalogue.product.read"
M = ProductMedia


class MediaType(StrEnum):
    IMAGE = "image"
    DOCUMENT = "document"
    PACKAGING_PHOTO = "packaging_photo"


class MediaAttach(BaseModel):
    """Attach a stored file (from ``POST /api/v1/files``) to the product."""

    model_config = ConfigDict(extra="forbid")

    file_id: uuid.UUID
    media_type: MediaType
    alt_text: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None
    is_primary: bool = False
    source_catalog_page: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None


class MediaUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    alt_text: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None
    sort_order: int | None = Field(default=None, ge=0, le=100000)
    file_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)] | None = None


class MediaDelete(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class MediaVersion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)


class MediaRead(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    media_type: MediaType
    file_id: uuid.UUID | None
    file_name: str | None
    original_filename: str | None
    content_type: str | None
    size_bytes: int | None
    alt_text: str | None
    is_primary: bool
    sort_order: int
    source_kind: str
    source_url_key: str | None
    ingest_status: str
    ingest_error: str | None
    uploaded_by_name: str | None
    uploaded_at: datetime
    deleted_at: datetime | None
    delete_reason: str | None
    content_url: str | None
    #: images and PDFs may be shown inline (preview); everything else is a download
    previewable: bool
    version: int
    capabilities: dict[str, Capability]


class MediaGroups(BaseModel):
    product_id: uuid.UUID
    image: list[MediaRead]
    packaging_photo: list[MediaRead]
    document: list[MediaRead]
    deleted: list[MediaRead]


# ---- helpers --------------------------------------------------------------------------------------------------------
def _product_for_media(uow: UnitOfWork, product_id: uuid.UUID) -> Product:
    """The product, visible to the actor (404 otherwise), live, with ``catalogue.media.manage`` (403 otherwise)."""
    product = uow.repo(Product).get(product_id)
    if not uow.actor.can(MANAGE):
        raise Forbidden(code="permission_denied", permission=MANAGE)
    if product.archived_at is not None:
        raise Conflict("The product is archived", code="product_archived")
    return product


def _may_change(uow: UnitOfWork, media: ProductMedia) -> Capability:
    scope = uow.actor.scope_for(MANAGE)
    if scope is None:
        return Capability(allowed=False, reason_code="permission_denied")
    if scope < Scope.COMPANY and media.uploaded_by != uow.actor.user_id:
        return Capability(allowed=False, reason_code="not_owner")
    return Capability(allowed=True)


def _media_for_change(uow: UnitOfWork, media_id: uuid.UUID, expected_version: int | None) -> ProductMedia:
    media = uow.session.scalars(
        select(M).where(M.id == media_id, M.company_id == uow.actor.company_id).with_for_update()
    ).first()
    if media is None:
        raise NotFound(code="not_found", resource_type="catalogue.media")
    product = uow.repo(Product).get(media.product_id)  # 404 when the parent product is not visible
    decision = _may_change(uow, media)
    if not decision.allowed:
        raise Forbidden(code=decision.reason_code or "permission_denied", permission=MANAGE)
    if product.archived_at is not None:
        raise Conflict("The product is archived", code="product_archived")
    if expected_version is not None:
        uow.expect_version(media, expected_version)
    return media


def _emit(uow: UnitOfWork, name: str, media: ProductMedia) -> None:
    uow.emit(
        name,
        aggregate_id=media.id,
        aggregate_version=media.version,
        payload=ev.payload(ev.MediaPayload(media_id=media.id, product_id=media.product_id, media_type=media.media_type)),
    )


def _names(uow: UnitOfWork, ids: set[uuid.UUID | None]) -> dict[uuid.UUID, str]:
    from app.platform.identity.models import AppUser

    clean = {i for i in ids if i is not None}
    if not clean:
        return {}
    return dict(uow.session.execute(select(AppUser.id, AppUser.display_name).where(AppUser.id.in_(clean))).all())


def _read(uow: UnitOfWork, media: ProductMedia, names: dict[uuid.UUID, str]) -> MediaRead:
    change = _may_change(uow, media)
    previewable = bool(media.content_type) and (
        str(media.content_type).startswith("image/") or media.content_type == "application/pdf"
    )
    return MediaRead(
        id=media.id,
        product_id=media.product_id,
        media_type=MediaType(media.media_type),
        file_id=media.file_id,
        file_name=media.file_name,
        original_filename=media.original_filename,
        content_type=media.content_type,
        size_bytes=media.size_bytes,
        alt_text=media.alt_text,
        is_primary=media.is_primary,
        sort_order=media.sort_order,
        source_kind=media.source_kind,
        source_url_key=media.source_url_key,
        ingest_status=media.ingest_status,
        ingest_error=media.ingest_error,
        uploaded_by_name=names.get(media.uploaded_by) if media.uploaded_by else None,
        uploaded_at=media.uploaded_at,
        deleted_at=media.deleted_at,
        delete_reason=media.delete_reason,
        content_url=f"/api/v1/files/{media.file_id}/content" if media.file_id else None,
        previewable=previewable and media.file_id is not None,
        version=media.version,
        capabilities={
            "update": change if media.deleted_at is None else Capability(allowed=False, reason_code="deleted"),
            "delete": change if media.deleted_at is None else Capability(allowed=False, reason_code="deleted"),
            "restore": change if media.deleted_at is not None else Capability(allowed=False, reason_code="not_deleted"),
            "make_primary": (
                Capability(allowed=False, reason_code="not_an_image")
                if media.media_type != MediaType.IMAGE
                else Capability(allowed=False, reason_code="deleted")
                if media.deleted_at is not None
                else Capability(allowed=False, reason_code="already_primary")
                if media.is_primary
                else Capability(allowed=False, reason_code="not_stored")
                if media.ingest_status != "stored"
                else change
            ),
        },
    )


def _live_images(uow: UnitOfWork, product_id: uuid.UUID) -> list[ProductMedia]:
    return list(
        uow.session.scalars(
            select(M)
            .where(
                M.product_id == product_id,
                M.deleted_at.is_(None),
                M.media_type == MediaType.IMAGE.value,
                M.ingest_status == "stored",
            )
            .order_by(M.sort_order, M.uploaded_at, M.id)
        )
    )


def _set_primary(uow: UnitOfWork, media: ProductMedia) -> None:
    """Make ``media`` the only live primary image of its product (one transaction; siblings first)."""
    uow.session.execute(
        update(M)
        .where(M.product_id == media.product_id, M.is_primary.is_(True), M.id != media.id)
        .values(is_primary=False, version=M.version + 1, updated_at=uow.now())
        .execution_options(synchronize_session=False)
    )
    media.is_primary = True


def _promote_next(uow: UnitOfWork, product_id: uuid.UUID, *, exclude: uuid.UUID) -> ProductMedia | None:
    for candidate in _live_images(uow, product_id):
        if candidate.id != exclude:
            candidate.is_primary = True
            return candidate
    return None


# ---- commands ------------------------------------------------------------------------------------------------------
def attach_media(uow: UnitOfWork, product_id: uuid.UUID, data: MediaAttach) -> MediaRead:
    """Link an uploaded file to the product. The same bytes on the same product are a 409 ``media_duplicate``;
    images must be image files; the first image becomes primary."""
    from app.platform.files import service as files
    from app.platform.files.sniff import IMAGE_KINDS

    product = _product_for_media(uow, product_id)
    obj = files.get_readable(uow, data.file_id)  # 404 unless this actor may read the file
    if data.media_type in (MediaType.IMAGE, MediaType.PACKAGING_PHOTO) and obj.kind not in {k.value for k in IMAGE_KINDS}:
        raise ValidationFailed(
            "Images and packaging photos must be JPEG, PNG, GIF or WebP files",
            errors=[{"loc": ["body", "file_id"], "msg": "not an image", "code": "not_an_image"}],
        )
    if data.is_primary and data.media_type != MediaType.IMAGE:
        raise ValidationFailed(
            "Only images can be primary",
            errors=[{"loc": ["body", "is_primary"], "msg": "only images", "code": "primary_must_be_image"}],
        )
    duplicate = uow.session.scalar(
        select(exists().where(M.product_id == product.id, M.file_id == obj.id, M.deleted_at.is_(None)))
    )
    if duplicate:
        raise Conflict("This file is already attached to the product", code="media_duplicate")
    next_order = (
        uow.session.scalar(select(M.sort_order).where(M.product_id == product.id).order_by(M.sort_order.desc()).limit(1))
        or 0
    ) + 10
    media = ProductMedia(
        id=uuid.uuid7(),
        company_id=uow.actor.company_id,
        product_id=product.id,
        file_id=obj.id,
        media_type=data.media_type.value,
        file_name=obj.original_name,
        original_filename=obj.original_name,
        content_type=obj.content_type,
        size_bytes=int(obj.size_bytes),
        alt_text=data.alt_text,
        is_primary=False,
        sort_order=next_order,
        source_kind="upload",
        source_catalog_page=data.source_catalog_page,
        ingest_status="stored",
        uploaded_by=uow.actor.user_id,
        uploaded_at=uow.now(),
    )
    uow.add(media)
    uow.flush()
    first_image = data.media_type == MediaType.IMAGE and len(_live_images(uow, product.id)) == 1
    if data.is_primary or first_image:
        _set_primary(uow, media)
        uow.flush()
    _emit(uow, ev.MEDIA_UPLOADED, media)
    uow.audit("catalogue.media.uploaded", resource_type="catalogue.product", resource_id=product.id,
              resource_label=product.product_key, details={"media_id": str(media.id), "media_type": media.media_type})
    return _read(uow, media, _names(uow, {media.uploaded_by}))


def update_media(uow: UnitOfWork, media_id: uuid.UUID, data: MediaUpdate) -> MediaRead:
    media = _media_for_change(uow, media_id, data.expected_version)
    if media.deleted_at is not None:
        raise Conflict("The media item is deleted", code="media_deleted")
    for name in ("alt_text", "sort_order", "file_name"):
        if name in data.model_fields_set:
            value = getattr(data, name)
            if name in ("sort_order", "file_name") and value is None:
                continue
            setattr(media, name, value)
    media.updated_at = uow.now()
    uow.flush()
    return _read(uow, media, _names(uow, {media.uploaded_by}))


def make_primary(uow: UnitOfWork, media_id: uuid.UUID, data: MediaVersion) -> MediaRead:
    media = _media_for_change(uow, media_id, data.expected_version)
    if media.deleted_at is not None or media.media_type != MediaType.IMAGE.value or media.ingest_status != "stored":
        raise Conflict("Only a live stored image can be primary", code="primary_must_be_image")
    if not media.is_primary:
        _set_primary(uow, media)
        media.updated_at = uow.now()
        uow.flush()
        _emit(uow, ev.MEDIA_PRIMARY_CHANGED, media)
    return _read(uow, media, _names(uow, {media.uploaded_by}))


def delete_media(uow: UnitOfWork, media_id: uuid.UUID, data: MediaDelete) -> MediaRead:
    """Soft delete with a reason; the stored object is kept. A deleted primary hands over to the next image."""
    media = _media_for_change(uow, media_id, data.expected_version)
    if media.deleted_at is not None:
        raise Conflict("The media item is already deleted", code="media_deleted")
    was_primary = media.is_primary
    media.deleted_at, media.deleted_by, media.delete_reason = uow.now(), uow.actor.user_id, data.reason
    media.is_primary = False
    uow.flush()
    _emit(uow, ev.MEDIA_DELETED, media)
    if was_primary:
        promoted = _promote_next(uow, media.product_id, exclude=media.id)
        if promoted is not None:
            uow.flush()
            _emit(uow, ev.MEDIA_PRIMARY_CHANGED, promoted)
    uow.audit("catalogue.media.deleted", resource_type="catalogue.product", resource_id=media.product_id,
              reason=data.reason, details={"media_id": str(media.id)})
    return _read(uow, media, _names(uow, {media.uploaded_by}))


def restore_media(uow: UnitOfWork, media_id: uuid.UUID, data: MediaVersion) -> MediaRead:
    media = _media_for_change(uow, media_id, data.expected_version)
    if media.deleted_at is None:
        raise Conflict("The media item is not deleted", code="media_not_deleted")
    if media.file_id is not None and uow.session.scalar(
        select(exists().where(M.product_id == media.product_id, M.file_id == media.file_id, M.deleted_at.is_(None)))
    ):
        raise Conflict("The same file is attached again already", code="media_duplicate")
    media.deleted_at, media.deleted_by, media.delete_reason = None, None, None
    uow.flush()
    if media.media_type == MediaType.IMAGE.value and media.ingest_status == "stored" and not any(
        m.is_primary for m in _live_images(uow, media.product_id)
    ):
        _set_primary(uow, media)
        uow.flush()
    _emit(uow, ev.MEDIA_RESTORED, media)
    return _read(uow, media, _names(uow, {media.uploaded_by}))


# ---- reads ---------------------------------------------------------------------------------------------------------
@query(READ)
def list_media(uow: UnitOfWork, product_id: uuid.UUID, *, include_deleted: bool = False) -> MediaGroups:
    """Live media grouped by type (primary first, then sort order); deleted items only when asked."""
    product = uow.repo(Product).get(product_id)
    stmt = select(M).where(M.product_id == product.id)
    if not include_deleted:
        stmt = stmt.where(M.deleted_at.is_(None))
    rows = list(uow.session.scalars(stmt.order_by(M.is_primary.desc(), M.sort_order, M.uploaded_at, M.id)))
    names = _names(uow, {r.uploaded_by for r in rows})
    reads = [_read(uow, r, names) for r in rows]
    live = [r for r in reads if r.deleted_at is None]
    return MediaGroups(
        product_id=product.id,
        image=[r for r in live if r.media_type == MediaType.IMAGE],
        packaging_photo=[r for r in live if r.media_type == MediaType.PACKAGING_PHOTO],
        document=[r for r in live if r.media_type == MediaType.DOCUMENT],
        deleted=[r for r in reads if r.deleted_at is not None],
    )


def file_access(uow: UnitOfWork, obj: object) -> bool | None:
    """Download authorisation for ``platform/files``: readable when the actor can read a product linking the file
    (deleted links included, so restored history stays downloadable to product readers)."""
    file_id = getattr(obj, "id", None)
    product_ids = list(
        uow.session.scalars(select(M.product_id).where(M.company_id == uow.actor.company_id, M.file_id == file_id))
    )
    if not product_ids:
        return None
    if not uow.actor.can(READ):
        return False
    visible = uow.session.scalar(
        select(exists().where(Product.id.in_(product_ids), uow.repo(Product).clause("read")))
    )
    return bool(visible)
