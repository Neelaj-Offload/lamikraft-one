"""Files service: store uploads and generated files, authorise and prepare downloads.

Upload pipeline (api-conventions §11): the router streams the body to a staging file with the per-purpose
limit while hashing it; here the bytes are sniffed (``sniff.py``), checked against the purpose, deduplicated
on (company, sha256) and moved into storage under a random key. A blob written by a unit of work that does not
commit is deleted again, so storage never keeps bytes without a row.

Dedupe shares the row and the blob, never the authorisation: every caller who stores the bytes is recorded as
a claimant (``FileObject.claims``) for the purpose they stored them for, and the result they get back shows
their own name and purpose. Downloads are authorised through the parents registered with
``register_file_access``; without a parent, an export is readable by everyone who generated it and an upload
nothing references yet by everyone who uploaded it. Downloads are streamed by the router after the unit of
work has closed.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import unicodedata
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import event, func, select, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.errors import NotFound, ValidationFailed
from app.platform.files.access import registered_file_access
from app.platform.files.errors import PayloadTooLarge
from app.platform.files.models import FileKind, FileObject, FilePurpose
from app.platform.files.schemas import FileRead
from app.platform.files.sniff import CONTENT_TYPES, HEAD_BYTES, INLINE_KINDS, reject, sanitize_filename, sniff
from app.platform.files.storage import StorageBackend, get_storage, new_storage_key, staging_dir
from app.platform.service import command, query

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, SessionTransaction

    from app.platform.authz.context import ActorContext
    from app.platform.files.upload import ReceivedUpload
    from app.platform.uow import UnitOfWork

MIB = 1024 * 1024
PURPOSE_LIMITS: dict[FilePurpose, int] = {
    FilePurpose.IMAGE: 15 * MIB,
    FilePurpose.DOCUMENT: 25 * MIB,
    FilePurpose.IMPORT: 50 * MIB,
    FilePurpose.EXPORT: 50 * MIB,
    FilePurpose.SCREEN_CAPTURE: 3 * MIB // 2,
}
PURPOSE_KINDS: dict[FilePurpose, frozenset[FileKind]] = {
    FilePurpose.IMAGE: frozenset({FileKind.PNG, FileKind.JPEG, FileKind.GIF, FileKind.WEBP}),
    FilePurpose.DOCUMENT: frozenset(FileKind),
    FilePurpose.IMPORT: frozenset({FileKind.XLSX, FileKind.CSV, FileKind.TXT}),
    FilePurpose.EXPORT: frozenset({FileKind.PDF, FileKind.XLSX, FileKind.CSV, FileKind.TXT}),
    #: WebP from the client; PNG where the browser cannot encode WebP (Safari)
    FilePurpose.SCREEN_CAPTURE: frozenset({FileKind.WEBP, FileKind.PNG}),
}
LOGO_KINDS = frozenset({FileKind.PNG, FileKind.JPEG})
CHUNK = 64 * 1024


def limit_for(purpose: FilePurpose | str) -> int:
    return PURPOSE_LIMITS[FilePurpose(purpose)]


def content_url(file_id: uuid.UUID) -> str:
    return f"/api/v1/files/{file_id}/content"


def _read(obj: FileObject, *, purpose: FilePurpose, name: str, deduplicated: bool = False) -> FileRead:
    """The caller's view of a stored file: their own name and purpose, never another claimant's."""
    return FileRead(
        id=obj.id,
        sha256=obj.sha256,
        size_bytes=obj.size_bytes,
        kind=obj.kind,
        content_type=obj.content_type,
        original_name=name,
        purpose=purpose.value,
        restricted=obj.restricted,
        created_at=obj.created_at,
        deduplicated=deduplicated,
        content_url=content_url(obj.id),
    )


def _existing(uow: UnitOfWork, sha256: str) -> FileObject | None:
    return uow.session.scalars(
        select(FileObject).where(FileObject.company_id == uow.actor.company_id, FileObject.sha256 == sha256)
    ).first()


# ---- claims -----------------------------------------------------------------------------------------------
def _claim(user_id: uuid.UUID, purpose: FilePurpose, name: str) -> dict[str, str]:
    return {"user_id": str(user_id), "purpose": purpose.value, "name": name}


def _claims_of(obj: FileObject, actor: ActorContext) -> list[dict[str, Any]]:
    if actor.user_id is None:
        return []
    uid = str(actor.user_id)
    return [c for c in (obj.claims or []) if isinstance(c, dict) and c.get("user_id") == uid]


def _add_claim(uow: UnitOfWork, obj: FileObject, purpose: FilePurpose, name: str, *, restricted: bool) -> None:
    """Record the actor as a claimant of ``obj`` (once per purpose) and tighten ``restricted`` if asked.

    Both are single UPDATE statements: the row lock and the re-checked WHERE make concurrent claims of the same
    bytes safe. ``restricted`` describes the content, so it only ever goes from false to true.
    """
    company_id = uow.actor.company_id
    if restricted and not obj.restricted:
        uow.session.execute(
            update(FileObject)
            .where(FileObject.id == obj.id, FileObject.company_id == company_id)
            .values(restricted=True)
            .execution_options(synchronize_session=False)
        )
    user_id = uow.actor.user_id
    if user_id is not None:
        entry = _claim(user_id, purpose, name)
        uow.session.execute(
            update(FileObject)
            .where(
                FileObject.id == obj.id,
                FileObject.company_id == company_id,
                ~FileObject.claims.contains([{"user_id": entry["user_id"], "purpose": entry["purpose"]}]),
            )
            .values(
                claims=FileObject.claims.op("||", return_type=JSONB)(
                    func.jsonb_build_array(
                        func.jsonb_build_object(
                            "user_id", entry["user_id"], "purpose", entry["purpose"], "name", entry["name"]
                        )
                    )
                )
            )
            .execution_options(synchronize_session=False)
        )
    uow.session.refresh(obj)


# ---- storage hygiene --------------------------------------------------------------------------------------
def _delete_unless_committed(uow: UnitOfWork, storage: StorageBackend, key: str) -> None:
    """Delete the blob at ``key`` when the unit of work's transaction ends without committing.

    Covers a rollback after ``_store`` returned (a caller composing ``store_generated`` raises later) and a
    failed commit. Nested savepoints (search providers, idempotency) are ignored; only the unit of work's own
    transaction decides.
    """
    session = uow.session
    root = session.get_transaction()
    if root is None:  # pragma: no cover - a unit of work always has an open transaction
        return
    outcome = {"committed": False, "done": False}

    # The listeners stay attached (removing them while the session dispatches the event is not allowed); they
    # act once and live only as long as the unit of work's session.
    def on_commit(sess: Session) -> None:
        # after_commit also fires for savepoints; the unit of work's transaction commits with none open
        if not outcome["done"] and sess.get_nested_transaction() is None and sess.get_transaction() is root:
            outcome["committed"] = True

    def on_end(sess: Session, transaction: SessionTransaction) -> None:
        if transaction is not root or outcome["done"]:
            return
        outcome["done"] = True
        if not outcome["committed"]:
            storage.delete(key)

    event.listen(session, "after_commit", on_commit)
    event.listen(session, "after_transaction_end", on_end)


# ---- storing ----------------------------------------------------------------------------------------------
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
        _add_claim(uow, existing, purpose, name, restricted=restricted)
        return _read(existing, purpose=purpose, name=name, deduplicated=True)

    storage = get_storage()
    key = new_storage_key(actor.company_id)
    storage.put_file(key, path)
    _delete_unless_committed(uow, storage, key)
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
                claims=[_claim(actor.user_id, purpose, name)] if actor.user_id is not None else [],
                created_at=now,
                updated_at=now,
                created_by=actor.user_id,
                updated_by=actor.user_id,
            )
            .on_conflict_do_nothing(index_elements=["company_id", "sha256"])
            .returning(FileObject.id)
        ).scalar()
        if new_id is None:  # a concurrent upload of the same bytes won: claim it, drop our copy
            storage.delete(key)
            winner = _existing(uow, sha256)
            assert winner is not None
            _add_claim(uow, winner, purpose, name, restricted=restricted)
            return _read(winner, purpose=purpose, name=name, deduplicated=True)
        obj = uow.session.get(FileObject, new_id)
        assert obj is not None
        return _read(obj, purpose=purpose, name=name)
    except BaseException:
        storage.delete(key)
        raise


@command("files.file.create")
def create_from_upload(uow: UnitOfWork, received: ReceivedUpload, *, purpose: FilePurpose | str) -> FileRead:
    purpose = FilePurpose(purpose)
    if purpose in (FilePurpose.EXPORT, FilePurpose.SCREEN_CAPTURE):
        raise ValidationFailed(
            "Exports and screen captures are created through their own services.",
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
@dataclass(frozen=True)
class _Grant:
    """Read access to a file and the name it is served under for this actor."""

    name: str


def _grant(uow: UnitOfWork, obj: FileObject) -> _Grant | None:
    actor = uow.actor
    if obj.company_id != actor.company_id:
        return None
    mine = _claims_of(obj, actor)
    # a claimant sees the name they gave the file; everyone else the first name it was stored under
    name = next((c["name"] for c in mine if c.get("purpose") == FilePurpose.EXPORT.value), None) or (
        mine[0]["name"] if mine else obj.original_name
    )
    if actor.is_system:
        return _Grant(name)
    if any(c.get("purpose") == FilePurpose.EXPORT.value for c in mine):
        return _Grant(name)  # exports have no parent: whoever generated these bytes may read them
    verdicts = [checker(uow, obj) for checker in registered_file_access().values()]
    if any(v is True for v in verdicts):
        return _Grant(name)
    if mine and all(v is None for v in verdicts):
        return _Grant(name)  # nothing references the file yet: only the people who uploaded it
    return None


def can_read(uow: UnitOfWork, obj: FileObject) -> bool:
    return _grant(uow, obj) is not None


def _readable(uow: UnitOfWork, file_id: uuid.UUID) -> tuple[FileObject, _Grant]:
    obj = uow.session.scalars(
        select(FileObject).where(FileObject.id == file_id, FileObject.company_id == uow.actor.company_id)
    ).first()
    grant = _grant(uow, obj) if obj is not None else None
    if obj is None or grant is None:
        raise NotFound(code="not_found", resource_type="files.file")
    return obj, grant


def get_readable(uow: UnitOfWork, file_id: uuid.UUID) -> FileObject:
    """The file if the actor may read it; 404 otherwise (no existence leak)."""
    return _readable(uow, file_id)[0]


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


def _audited(obj: FileObject, actor: ActorContext) -> bool:
    """Restricted content and exports are audited on every download."""
    return obj.restricted or obj.purpose == FilePurpose.EXPORT.value or any(
        c.get("purpose") == FilePurpose.EXPORT.value for c in _claims_of(obj, actor)
    )


@query()
def open_download(uow: UnitOfWork, file_id: uuid.UUID, variant: str | None = None) -> DownloadTicket:
    """The ticket to stream a file (or its ``thumb``/``medium`` image variant, authorised exactly like the file)."""
    obj, grant = _readable(uow, file_id)
    if variant is not None:
        from app.platform.files.variants import variant_of

        row = variant_of(uow, obj.id, variant)
        if row is None:
            raise NotFound(code="not_found", resource_type="files.file_variant")
        stem = grant.name.rsplit(".", 1)[0]
        return DownloadTicket(
            file_id=obj.id,
            storage_key=row.storage_key,
            content_type=row.content_type,
            kind=FileKind.JPEG if row.content_type == "image/jpeg" else FileKind.PNG,
            original_name=f"{stem}-{variant}.{'jpg' if row.content_type == 'image/jpeg' else 'png'}",
            sha256=row.sha256,
            size_bytes=row.size_bytes,
            restricted=obj.restricted,
        )
    if _audited(obj, uow.actor):
        uow.audit(
            "files.file.downloaded",
            resource_type="files.file",
            resource_id=obj.id,
            resource_label=grant.name,
            details={"purpose": obj.purpose, "restricted": obj.restricted},
        )
    return DownloadTicket(
        file_id=obj.id,
        storage_key=obj.storage_key,
        content_type=obj.content_type,
        kind=FileKind(obj.kind),
        original_name=grant.name,
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
