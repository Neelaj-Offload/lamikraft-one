"""Files service: store uploads and generated files, authorise and prepare downloads.

Upload pipeline (api-conventions §11): the router streams the body to a staging file with the per-purpose
limit while hashing it; here the bytes are sniffed (``sniff.py``), checked against the purpose, deduplicated
on (company, sha256) and moved into storage under a random key. Downloads are authorised through the parents
registered with ``register_file_access`` (creator-only fallback for exports and for files nothing references
yet) and are streamed by the router after the unit of work has closed.
"""

from __future__ import annotations

import os
import tempfile
import unicodedata
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.errors import NotFound, ValidationFailed
from app.platform.files.access import registered_file_access
from app.platform.files.errors import PayloadTooLarge
from app.platform.files.models import FileKind, FileObject, FilePurpose
from app.platform.files.schemas import FileRead
from app.platform.files.sniff import CONTENT_TYPES, HEAD_BYTES, INLINE_KINDS, reject, sanitize_filename, sniff
from app.platform.files.storage import get_storage, new_storage_key, staging_dir
from app.platform.service import command, query

if TYPE_CHECKING:
    from app.platform.files.upload import ReceivedUpload
    from app.platform.uow import UnitOfWork

MIB = 1024 * 1024
PURPOSE_LIMITS: dict[FilePurpose, int] = {
    FilePurpose.IMAGE: 15 * MIB,
    FilePurpose.DOCUMENT: 25 * MIB,
    FilePurpose.IMPORT: 50 * MIB,
    FilePurpose.EXPORT: 50 * MIB,
}
PURPOSE_KINDS: dict[FilePurpose, frozenset[FileKind]] = {
    FilePurpose.IMAGE: frozenset({FileKind.PNG, FileKind.JPEG, FileKind.GIF, FileKind.WEBP}),
    FilePurpose.DOCUMENT: frozenset(FileKind),
    FilePurpose.IMPORT: frozenset({FileKind.XLSX, FileKind.CSV, FileKind.TXT}),
    FilePurpose.EXPORT: frozenset({FileKind.PDF, FileKind.XLSX, FileKind.CSV, FileKind.TXT}),
}
LOGO_KINDS = frozenset({FileKind.PNG, FileKind.JPEG})
CHUNK = 64 * 1024


def limit_for(purpose: FilePurpose | str) -> int:
    return PURPOSE_LIMITS[FilePurpose(purpose)]


def content_url(file_id: uuid.UUID) -> str:
    return f"/api/v1/files/{file_id}/content"


def _read(obj: FileObject, *, deduplicated: bool = False, shown_name: str | None = None) -> FileRead:
    return FileRead(
        id=obj.id,
        sha256=obj.sha256,
        size_bytes=obj.size_bytes,
        kind=obj.kind,
        content_type=obj.content_type,
        original_name=shown_name or obj.original_name,
        purpose=obj.purpose,
        restricted=obj.restricted,
        created_at=obj.created_at,
        deduplicated=deduplicated,
        content_url=content_url(obj.id),
    )


def _existing(uow: UnitOfWork, sha256: str) -> FileObject | None:
    return uow.session.scalars(
        select(FileObject).where(FileObject.company_id == uow.actor.company_id, FileObject.sha256 == sha256)
    ).first()


def _store(
    uow: UnitOfWork,
    *,
    path: Path,
    size: int,
    sha256: str,
    head: bytes,
    filename: str | None,
    declared_content_type: str | None,
    purpose: FilePurpose,
    restricted: bool,
) -> FileRead:
    actor = uow.actor
    if actor.company_id is None:
        raise NotFound(code="not_found", resource_type="files.file")
    limit = PURPOSE_LIMITS[purpose]
    if size > limit:
        raise PayloadTooLarge(f"The file is larger than the {limit // MIB} MB allowed here.", limit_bytes=limit)
    name = sanitize_filename(filename)
    kind = sniff(path, head, name)
    if kind not in PURPOSE_KINDS[purpose]:
        raise reject("type_not_allowed_for_purpose", f"A {kind.value} file cannot be used as {purpose.value}.")

    existing = _existing(uow, sha256)
    if existing is not None:
        if restricted and not existing.restricted:
            existing.restricted = True  # never downgrade; restricted content stays restricted
            uow.flush()
        return _read(existing, deduplicated=True, shown_name=name)

    storage = get_storage()
    key = new_storage_key(actor.company_id)
    storage.put_file(key, path)
    try:
        now = uow.now()
        new_id = uow.session.execute(
            pg_insert(FileObject)
            .values(
                id=uuid.uuid7(),
                company_id=actor.company_id,
                sha256=sha256,
                size_bytes=size,
                kind=kind.value,
                content_type=CONTENT_TYPES[kind],
                declared_content_type=(declared_content_type or None),
                original_name=name,
                purpose=purpose.value,
                storage_backend=storage.name,
                storage_key=key,
                restricted=restricted,
                created_at=now,
                updated_at=now,
                created_by=actor.user_id,
                updated_by=actor.user_id,
            )
            .on_conflict_do_nothing(index_elements=["company_id", "sha256"])
            .returning(FileObject.id)
        ).scalar()
        if new_id is None:  # a concurrent upload of the same bytes won: reuse it, drop our copy
            storage.delete(key)
            winner = _existing(uow, sha256)
            assert winner is not None
            return _read(winner, deduplicated=True, shown_name=name)
        obj = uow.session.get(FileObject, new_id)
        assert obj is not None
        return _read(obj)
    except BaseException:
        storage.delete(key)
        raise


@command("files.file.create")
def create_from_upload(uow: UnitOfWork, received: ReceivedUpload, *, purpose: FilePurpose | str) -> FileRead:
    purpose = FilePurpose(purpose)
    if purpose == FilePurpose.EXPORT:
        raise ValidationFailed(
            "Exports are created by the system.",
            errors=[{"loc": ["query", "purpose"], "msg": "not an upload purpose", "code": "invalid_choice"}],
        )
    return _store(
        uow,
        path=received.path,
        size=received.size,
        sha256=received.sha256,
        head=received.head,
        filename=received.filename,
        declared_content_type=received.declared_content_type,
        purpose=purpose,
        restricted=False,
    )


@command()
def store_generated(
    uow: UnitOfWork,
    data: bytes,
    *,
    filename: str,
    purpose: FilePurpose | str = FilePurpose.EXPORT,
    restricted: bool = False,
) -> FileRead:
    """Store bytes produced by a service (PDF documents, CSV/XLSX exports) under the same rules as uploads."""
    import hashlib

    fd, tmp = tempfile.mkstemp(prefix="generated-", suffix=".part", dir=staging_dir())
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        return _store(
            uow,
            path=Path(tmp),
            size=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            head=data[:HEAD_BYTES],
            filename=filename,
            declared_content_type=None,
            purpose=FilePurpose(purpose),
            restricted=restricted,
        )
    finally:
        Path(tmp).unlink(missing_ok=True)


# ---- authorisation ----------------------------------------------------------------------------------------
def can_read(uow: UnitOfWork, obj: FileObject) -> bool:
    actor = uow.actor
    if obj.company_id != actor.company_id:
        return False
    if actor.is_system:
        return True
    verdicts = [checker(uow, obj) for checker in registered_file_access().values()]
    if any(v is True for v in verdicts):
        return True
    unreferenced = all(v is None for v in verdicts)
    is_creator = obj.created_by is not None and obj.created_by == actor.user_id
    return is_creator and (obj.purpose == FilePurpose.EXPORT.value or unreferenced)


def get_readable(uow: UnitOfWork, file_id: uuid.UUID) -> FileObject:
    """The file if the actor may read it; 404 otherwise (no existence leak)."""
    obj = uow.session.scalars(
        select(FileObject).where(FileObject.id == file_id, FileObject.company_id == uow.actor.company_id)
    ).first()
    if obj is None or not can_read(uow, obj):
        raise NotFound(code="not_found", resource_type="files.file")
    return obj


def require_logo_image(uow: UnitOfWork, file_id: uuid.UUID) -> None:
    """Validation for ``company_identity.logo_file_id``: a readable PNG or JPEG of this company."""
    try:
        obj = get_readable(uow, file_id)
    except NotFound:
        raise ValidationFailed(
            errors=[{"loc": ["body", "value", "logo_file_id"], "msg": "file not found", "code": "file_not_found"}]
        ) from None
    if FileKind(obj.kind) not in LOGO_KINDS:
        raise ValidationFailed(
            errors=[{"loc": ["body", "value", "logo_file_id"], "msg": "the logo must be PNG or JPEG", "code": "logo_not_image"}]
        )


# ---- downloads --------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class DownloadTicket:
    """Everything the router needs to stream a file after the unit of work has closed."""

    file_id: uuid.UUID
    storage_key: str
    content_type: str
    kind: FileKind
    original_name: str
    sha256: str
    size_bytes: int
    restricted: bool

    @property
    def etag(self) -> str:
        return f'"{self.sha256}"'

    @property
    def inline(self) -> bool:
        return self.kind in INLINE_KINDS

    def iter_bytes(self) -> Iterator[bytes]:
        with get_storage().open(self.storage_key) as fh:
            while chunk := fh.read(CHUNK):
                yield chunk


@query()
def open_download(uow: UnitOfWork, file_id: uuid.UUID) -> DownloadTicket:
    obj = get_readable(uow, file_id)
    if obj.restricted or obj.purpose == FilePurpose.EXPORT.value:
        uow.audit(
            "files.file.downloaded",
            resource_type="files.file",
            resource_id=obj.id,
            resource_label=obj.original_name,
            details={"purpose": obj.purpose, "restricted": obj.restricted},
        )
    return DownloadTicket(
        file_id=obj.id,
        storage_key=obj.storage_key,
        content_type=obj.content_type,
        kind=FileKind(obj.kind),
        original_name=obj.original_name,
        sha256=obj.sha256,
        size_bytes=obj.size_bytes,
        restricted=obj.restricted,
    )


def ascii_fallback(name: str) -> str:
    """The legacy ``filename`` parameter: diacritics folded (case kept), other non-ASCII and quoting characters
    replaced by ``_``; the exact name travels in ``filename*``."""
    folded = "".join(ch for ch in unicodedata.normalize("NFKD", name) if not unicodedata.combining(ch))
    safe = "".join(ch if 32 <= ord(ch) < 127 and ch not in '"\\;' else "_" for ch in folded)
    return safe or "download"


def content_disposition(name: str, *, inline: bool) -> str:
    """RFC 6266: an ASCII ``filename`` fallback plus the exact UTF-8 name in ``filename*`` (RFC 8187)."""
    from urllib.parse import quote

    kind = "inline" if inline else "attachment"
    return f"{kind}; filename=\"{ascii_fallback(name)}\"; filename*=UTF-8''{quote(name, safe='')}"
