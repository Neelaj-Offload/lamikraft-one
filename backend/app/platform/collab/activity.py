"""Activity: a record's timeline and the company feed, read from the event stream and filtered by parent visibility.

Activity is not a second copy of the data: it is computed from ``domain_event`` (the transactional outbox), whose
payloads hold ids and changed-field names only (never restricted values or message text). An event belongs to a
record when its aggregate is that record, or when it is a collaboration event (note, attachment) whose payload
names that record. Every row is filtered through the registered ``ResourcePolicy`` of its record type (SEC-03):
the feed ORs ``aggregate_type = t AND aggregate_id IN visible_ids(t)`` over the top-level types, so an invisible
record never contributes a row, a label or a count. Needs ``collab.activity.read`` (employee base).
Paging is keyset on (occurred_at, seq), newest first.
"""

from __future__ import annotations

import base64
import binascii
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import ColumnElement, String, and_, cast, false, or_, select, tuple_

from app.core.errors import ValidationFailed
from app.platform.authz.policy import all_policies, scope_clause
from app.platform.collab.attachments import parent
from app.platform.collab.schemas import ActivityItem, ActivityPage
from app.platform.events.models import DomainEvent
from app.platform.identity.models import AppUser
from app.platform.service import query

if TYPE_CHECKING:
    from app.platform.uow import UnitOfWork

ACTIVITY_READ = "collab.activity.read"
COLLAB_EVENTS = ("collab.note.updated", "collab.comment.added", "collab.attachment.added", "collab.attachment.archived")
MAX_LIMIT = 100


def _cursor(at: datetime, seq: int) -> str:
    return base64.urlsafe_b64encode(f"{at.isoformat()}|{seq}".encode()).decode().rstrip("=")


def _parse_cursor(value: str) -> tuple[datetime, int]:
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode()
        at, seq = raw.rsplit("|", 1)
        return datetime.fromisoformat(at), int(seq)
    except (ValueError, binascii.Error, UnicodeDecodeError):
        raise ValidationFailed(errors=[{"loc": ["query", "before"], "msg": "invalid cursor", "code": "invalid_cursor"}]) from None


def _payload_resource(resource_type: str) -> ColumnElement[bool]:
    return and_(DomainEvent.event_type.in_(COLLAB_EVENTS), DomainEvent.payload["resource_type"].astext == resource_type)


def _visible_clause(uow: UnitOfWork) -> ColumnElement[bool]:
    actor = uow.actor
    terms: list[ColumnElement[bool]] = []
    for resource_type, policy in sorted(all_policies().items()):
        if policy.parent is not None or not actor.is_system and not actor.can(policy.permission("read")):
            continue
        ids = select(cast(policy.model.id, String)).where(scope_clause(actor, policy, "read"))  # type: ignore[attr-defined]
        terms.append(and_(DomainEvent.aggregate_type == resource_type, cast(DomainEvent.aggregate_id, String).in_(ids)))
        terms.append(and_(_payload_resource(resource_type), DomainEvent.payload["resource_id"].astext.in_(ids)))
    return or_(*terms) if terms else false()


def _humanize(event_type: str) -> tuple[str, str]:
    _module, entity, verb = event_type.split(".")
    noun = entity.replace("_", " ")
    return verb, f"{noun[:1].upper()}{noun[1:]} {verb.replace('_', ' ')}"


def _labels(uow: UnitOfWork, refs: set[tuple[str, uuid.UUID]]) -> dict[tuple[str, uuid.UUID], tuple[str | None, str | None]]:
    """(label, canonical path) per visible record, from the owning policy (records loaded in one query per type)."""
    out: dict[tuple[str, uuid.UUID], tuple[str | None, str | None]] = {}
    by_type: dict[str, set[uuid.UUID]] = {}
    for t, i in refs:
        by_type.setdefault(t, set()).add(i)
    policies = all_policies()
    for t, ids in by_type.items():
        policy = policies.get(t)
        if policy is None:
            continue
        model: Any = policy.model
        for obj in uow.session.scalars(select(model).where(model.id.in_(ids), scope_clause(uow.actor, policy, "read"))):
            label = policy.label(obj) if policy.label else (getattr(obj, policy.business_key_column) if policy.business_key_column else None)
            path = policy.canonical_path(obj) if policy.canonical_path else None
            out[(t, obj.id)] = (str(label) if label is not None else None, path)
    return out


def _record_of(evt: DomainEvent) -> tuple[str, uuid.UUID] | None:
    if evt.event_type in COLLAB_EVENTS:
        try:
            return str(evt.payload["resource_type"]), uuid.UUID(str(evt.payload["resource_id"]))
        except (KeyError, ValueError):
            return None
    return (evt.aggregate_type, evt.aggregate_id) if evt.aggregate_id else None


@query(ACTIVITY_READ)
def list_activity(
    uow: UnitOfWork,
    *,
    resource_type: str | None = None,
    resource_id: uuid.UUID | None = None,
    before: str | None = None,
    limit: int = 30,
) -> ActivityPage:
    """A record's timeline (``resource_type`` + ``resource_id``; 404 unless the record is visible) or the feed."""
    if (resource_type is None) != (resource_id is None):
        raise ValidationFailed(errors=[{"loc": ["query"], "msg": "Give both resource_type and resource_id", "code": "incomplete"}])
    limit = max(1, min(limit, MAX_LIMIT))
    stmt = select(DomainEvent).where(DomainEvent.company_id == uow.actor.company_id)
    if resource_type is not None and resource_id is not None:
        parent(uow, resource_type, resource_id)  # 404 when not visible
        stmt = stmt.where(
            or_(
                and_(DomainEvent.aggregate_type == resource_type, DomainEvent.aggregate_id == resource_id),
                and_(_payload_resource(resource_type), DomainEvent.payload["resource_id"].astext == str(resource_id)),
            )
        )
    else:
        stmt = stmt.where(_visible_clause(uow))
    if before:
        at, seq = _parse_cursor(before)
        stmt = stmt.where(tuple_(DomainEvent.occurred_at, DomainEvent.seq) < tuple_(at, seq))
    rows = list(uow.session.scalars(stmt.order_by(DomainEvent.occurred_at.desc(), DomainEvent.seq.desc()).limit(limit + 1)))
    page, more = rows[:limit], len(rows) > limit
    refs = {r for r in (_record_of(e) for e in page) if r is not None}
    labels = _labels(uow, refs)
    actors = {e.actor_user_id for e in page if e.actor_user_id}
    names = dict(uow.session.execute(select(AppUser.id, AppUser.display_name).where(AppUser.id.in_(actors))).all()) if actors else {}
    items = []
    for e in page:
        ref = _record_of(e)
        verb, summary = _humanize(e.event_type)
        label, path = labels.get(ref, (None, None)) if ref else (None, None)
        changed = e.payload.get("changed_fields") if isinstance(e.payload, dict) else None
        items.append(
            ActivityItem(
                id=e.id,
                occurred_at=e.occurred_at,
                event_type=e.event_type,
                verb=verb,
                summary=summary,
                actor_name=names.get(e.actor_user_id) if e.actor_user_id else ("System" if e.actor_type == "system" else None),
                actor_type=e.actor_type,
                resource_type=ref[0] if ref else e.aggregate_type,
                resource_id=ref[1] if ref else None,
                resource_label=label,
                path=path,
                changed_fields=[str(c) for c in changed] if isinstance(changed, list) else [],
            )
        )
    last = page[-1] if page else None
    return ActivityPage(items=items, next_cursor=_cursor(last.occurred_at, last.seq) if more and last else None)
