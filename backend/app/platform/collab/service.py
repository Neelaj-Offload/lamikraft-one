"""Internal notes: one autosaved note per record, authorised strictly through the parent record.

The parent's ``ResourcePolicy`` (``get_policy(resource_type)``) decides: a parent the actor cannot read is
404 (also for unknown resource types — no existence leak), reading a note needs the parent's ``read`` and
writing it the parent's ``update`` (403 when the parent is visible but not editable). Saves are optimistic:
a stale ``expected_version`` is 409 ``version_conflict`` carrying the current note for a three-way merge.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from app.core.errors import NotFound, VersionConflict
from app.platform.authz.policy import ResourcePolicy, get_policy
from app.platform.authz.repository import ScopedRepository
from app.platform.collab.models import Note
from app.platform.collab.schemas import Capability, NoteRead
from app.platform.identity.models import AppUser
from app.platform.service import command, query

if TYPE_CHECKING:
    from app.platform.uow import UnitOfWork


def _parent(uow: UnitOfWork, resource_type: str, resource_id: uuid.UUID) -> tuple[ScopedRepository[Any], Any]:
    try:
        policy: ResourcePolicy = get_policy(resource_type)
    except KeyError:
        raise NotFound(code="not_found", resource_type=resource_type) from None
    repo: ScopedRepository[Any] = ScopedRepository(uow, policy)
    return repo, repo.get(resource_id, "read")  # 404 when the parent is not visible


def _note(uow: UnitOfWork, resource_type: str, resource_id: uuid.UUID, *, for_update: bool = False) -> Note | None:
    stmt = select(Note).where(
        Note.company_id == uow.actor.company_id,
        Note.resource_type == resource_type,
        Note.resource_id == resource_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    return uow.session.scalars(stmt).first()


def _read(
    uow: UnitOfWork, resource_type: str, resource_id: uuid.UUID, note: Note | None, can_update: bool
) -> NoteRead:
    name = None
    if note is not None and note.updated_by is not None:
        name = uow.session.scalar(select(AppUser.display_name).where(AppUser.id == note.updated_by))
    return NoteRead(
        resource_type=resource_type,
        resource_id=resource_id,
        note_id=note.id if note is not None else None,
        body=note.body if note is not None else "",
        version=note.version if note is not None else 0,
        updated_at=note.updated_at if note is not None else None,
        updated_by=note.updated_by if note is not None else None,
        updated_by_name=name,
        capabilities={
            "update": Capability(allowed=can_update, reason_code=None if can_update else "permission_denied")
        },
    )


@query()
def get_note(uow: UnitOfWork, resource_type: str, resource_id: uuid.UUID) -> NoteRead:
    repo, parent = _parent(uow, resource_type, resource_id)
    return _read(uow, resource_type, resource_id, _note(uow, resource_type, resource_id), repo.can(parent, "update"))


@command()
def save_note(
    uow: UnitOfWork, resource_type: str, resource_id: uuid.UUID, *, body: str, expected_version: int
) -> NoteRead:
    """Save the internal note. The parent is authorised before the idempotent part, so a replayed
    ``Idempotency-Key`` is answered only while the actor may still edit the parent."""
    repo, parent = _parent(uow, resource_type, resource_id)
    repo.require_action(parent, "update")  # 403: visible parent, no right to edit it
    result = _write_note(uow, resource_type, resource_id, body=body, expected_version=expected_version)
    return result if isinstance(result, NoteRead) else NoteRead.model_validate(result)


@command(idempotent=True)
def _write_note(
    uow: UnitOfWork, resource_type: str, resource_id: uuid.UUID, *, body: str, expected_version: int
) -> NoteRead:
    uow.advisory_xact_lock("collab.note", f"{uow.actor.company_id}:{resource_type}:{resource_id}")
    note = _note(uow, resource_type, resource_id, for_update=True)
    current_version = note.version if note is not None else 0
    if expected_version != current_version:
        current = _read(uow, resource_type, resource_id, note, True).model_dump(mode="json")
        raise VersionConflict(
            "Someone else changed this note while you were editing.",
            current_version=current_version,
            current=current,
            changed_by=str(note.updated_by) if note is not None and note.updated_by else None,
            changed_at=note.updated_at.isoformat() if note is not None else None,
        )
    if note is not None and note.body == body:
        return _read(uow, resource_type, resource_id, note, True)
    if note is None:
        note = uow.add(Note(company_id=uow.actor.company_id, resource_type=resource_type, resource_id=resource_id, body=body))
    else:
        note.body = body
    uow.flush()
    uow.emit(
        "collab.note.updated",
        aggregate_id=note.id,
        aggregate_version=note.version,
        payload={
            "resource_type": resource_type,
            "resource_id": str(resource_id),
            "note_id": str(note.id),
            "version": note.version,
        },
    )
    return _read(uow, resource_type, resource_id, note, True)
