"""Attachments on any record (SEC-03): a polymorphic child authorised only through its parent.

- Listing needs the parent's ``read`` (404 when the parent is not visible, also for unknown resource types).
- Attaching, renaming and removing need the parent's ``update`` (403 when visible but not editable).
- Files go through ``platform/files`` first (``POST /api/v1/files``: per-purpose size limits, magic-byte sniffing,
  no SVG/HTML/macros, dedupe); only files the actor may read (normally ones they uploaded) can be attached, and
  only images and documents (not import sheets or exports).
- Downloads of an attached file are authorised by the parent's ``read`` through the files access registry.
- Removal archives the attachment (the file object stays for history); events ``collab.attachment.added|archived``.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.http.capabilities import Capability
from app.platform.authz.policy import ResourcePolicy, get_policy
from app.platform.authz.repository import ScopedRepository
from app.platform.collab.models import Attachment
from app.platform.collab.schemas import AttachmentList, AttachmentRead
from app.platform.files.models import FileObject, FilePurpose, FileVariant
from app.platform.identity.models import AppUser
from app.platform.service import command, query

if TYPE_CHECKING:
    from app.platform.uow import UnitOfWork

ATTACHABLE_PURPOSES = frozenset({FilePurpose.IMAGE.value, FilePurpose.DOCUMENT.value})
IMAGE_KINDS = frozenset({"png", "jpeg", "gif", "webp"})


def parent(uow: UnitOfWork, resource_type: str, resource_id: uuid.UUID) -> tuple[ScopedRepository[Any], Any]:
    """The parent record when the actor may read it (404 otherwise, including unknown or child resource types)."""
    try:
        policy: ResourcePolicy = get_policy(resource_type)
    except KeyError:
        raise NotFound(code="not_found", resource_type=resource_type) from None
    repo: ScopedRepository[Any] = ScopedRepository(uow, policy)
    return repo, repo.get(resource_id, "read")


def _views(uow: UnitOfWork, rows: list[Attachment], can_update: bool) -> list[AttachmentRead]:
    if not rows:
        return []
    files = {f.id: f for f in uow.session.scalars(select(FileObject).where(FileObject.id.in_([r.file_id for r in rows])))}
    variants: dict[uuid.UUID, set[str]] = {}
    for file_id, variant in uow.session.execute(
        select(FileVariant.file_id, FileVariant.variant).where(FileVariant.file_id.in_(list(files)))
    ).all():
        variants.setdefault(file_id, set()).add(variant)
    names = dict(
        uow.session.execute(select(AppUser.id, AppUser.display_name).where(AppUser.id.in_({r.created_by for r in rows if r.created_by}))).all()
    )
    out = []
    for r in rows:
        f = files[r.file_id]
        base = f"/api/v1/files/{f.id}/content"
        out.append(
            AttachmentRead(
                id=r.id,
                resource_type=r.resource_type,
                resource_id=r.resource_id,
                file_id=f.id,
                title=r.title,
                role=r.role,  # type: ignore[arg-type]
                kind=f.kind,
                content_type=f.content_type,
                size_bytes=f.size_bytes,
                content_url=base,
                thumbnail_url=f"{base}?variant=thumb" if "thumb" in variants.get(f.id, set()) else None,
                created_at=r.created_at,
                created_by_name=names.get(r.created_by) if r.created_by else None,
                version=r.version,
                capabilities={"update": Capability(allowed=can_update, reason_code=None if can_update else "permission_denied")},
            )
        )
    return out


@query()
def list_attachments(uow: UnitOfWork, resource_type: str, resource_id: uuid.UUID) -> AttachmentList:
    repo, record = parent(uow, resource_type, resource_id)
    rows = list(
        uow.session.scalars(
            select(Attachment)
            .where(
                Attachment.company_id == uow.actor.company_id,
                Attachment.resource_type == resource_type,
                Attachment.resource_id == resource_id,
                Attachment.archived_at.is_(None),
            )
            .order_by(Attachment.created_at, Attachment.id)
        )
    )
    can_update = repo.can(record, "update")
    return AttachmentList(
        items=_views(uow, rows, can_update),
        capabilities={"add": Capability(allowed=can_update, reason_code=None if can_update else "permission_denied")},
    )


def _payload(row: Attachment) -> dict[str, object]:
    return {
        "resource_type": row.resource_type,
        "resource_id": str(row.resource_id),
        "attachment_id": str(row.id),
        "file_id": str(row.file_id),
        "role": row.role,
    }


@command()
def add_attachment(uow: UnitOfWork, resource_type: str, resource_id: uuid.UUID, *, file_id: uuid.UUID, title: str | None) -> AttachmentRead:
    from app.platform.files.service import get_readable

    repo, record = parent(uow, resource_type, resource_id)
    repo.require_action(record, "update")
    try:
        file = get_readable(uow, file_id)
    except NotFound:
        raise ValidationFailed(errors=[{"loc": ["body", "file_id"], "msg": "Upload the file first", "code": "file_not_found"}]) from None
    purposes = {file.purpose} | {c.get("purpose") for c in (file.claims or []) if isinstance(c, dict) and c.get("user_id") == str(uow.actor.user_id)}
    if not purposes & ATTACHABLE_PURPOSES:
        raise ValidationFailed(errors=[{"loc": ["body", "file_id"], "msg": "Only images and documents can be attached", "code": "purpose_not_attachable"}])
    uow.advisory_xact_lock("collab.attachment", f"{resource_type}:{resource_id}")
    existing = uow.session.scalar(
        select(Attachment.id).where(
            Attachment.company_id == uow.actor.company_id,
            Attachment.resource_type == resource_type,
            Attachment.resource_id == resource_id,
            Attachment.file_id == file.id,
            Attachment.archived_at.is_(None),
        )
    )
    if existing is not None:
        raise Conflict("This file is already attached here.", code="already_attached", attachment_id=str(existing))
    mine = next((c.get("name") for c in (file.claims or []) if isinstance(c, dict) and c.get("user_id") == str(uow.actor.user_id)), None)
    row = Attachment(
        id=uuid.uuid7(),
        company_id=uow.actor.company_id,
        resource_type=resource_type,
        resource_id=resource_id,
        file_id=file.id,
        role="image" if file.kind in IMAGE_KINDS else "document",
        title=((title or "").strip() or mine or file.original_name)[:200],
    )
    uow.add(row)
    uow.flush()
    if file.kind in IMAGE_KINDS:
        from app.platform.files.variants import ensure_variants

        ensure_variants(uow, file)
    uow.emit("collab.attachment.added", aggregate_id=row.id, aggregate_version=row.version, payload=_payload(row))
    uow.audit("collab.attachment.added", resource_type=resource_type, resource_id=resource_id, resource_label=row.title, details={"file_id": str(file.id)})
    return _views(uow, [row], True)[0]


def _attachment(uow: UnitOfWork, attachment_id: uuid.UUID) -> tuple[Attachment, ScopedRepository[Any], Any]:
    row = uow.session.scalars(
        select(Attachment).where(Attachment.id == attachment_id, Attachment.company_id == uow.actor.company_id, Attachment.archived_at.is_(None))
    ).first()
    if row is None:
        raise NotFound(code="not_found", resource_type="collab.attachment")
    try:
        repo, record = parent(uow, row.resource_type, row.resource_id)
    except NotFound:
        raise NotFound(code="not_found", resource_type="collab.attachment") from None
    return row, repo, record


@command()
def rename_attachment(uow: UnitOfWork, attachment_id: uuid.UUID, *, title: str, expected_version: int) -> AttachmentRead:
    row, repo, record = _attachment(uow, attachment_id)
    repo.require_action(record, "update")
    uow.expect_version(row, expected_version)
    title = title.strip()
    if not title:
        raise ValidationFailed(errors=[{"loc": ["body", "title"], "msg": "A title is required", "code": "missing"}])
    if title != row.title:
        uow.audit("collab.attachment.renamed", resource_type=row.resource_type, resource_id=row.resource_id, changes={"title": {"from": row.title, "to": title}})
        row.title = title[:200]
        uow.flush()
    return _views(uow, [row], True)[0]


@command()
def remove_attachment(uow: UnitOfWork, attachment_id: uuid.UUID) -> None:
    row, repo, record = _attachment(uow, attachment_id)
    repo.require_action(record, "update")
    row.archived_at = uow.now()
    row.archived_by = uow.actor.user_id
    uow.flush()
    uow.emit("collab.attachment.archived", aggregate_id=row.id, aggregate_version=row.version, payload=_payload(row))
    uow.audit("collab.attachment.archived", resource_type=row.resource_type, resource_id=row.resource_id, resource_label=row.title)


def attachment_file_access(uow: UnitOfWork, file: FileObject) -> bool | None:
    """Files access checker: True when an open attachment of the file has a parent the actor may read."""
    refs = uow.session.execute(
        select(Attachment.resource_type, Attachment.resource_id).where(
            Attachment.company_id == uow.actor.company_id, Attachment.file_id == file.id, Attachment.archived_at.is_(None)
        )
    ).all()
    if not refs:
        return None
    for resource_type, resource_id in refs:
        try:
            policy = get_policy(resource_type)
        except KeyError:
            continue
        if ScopedRepository(uow, policy).exists(policy.model.id == resource_id):  # type: ignore[attr-defined]
            return True
    return False
