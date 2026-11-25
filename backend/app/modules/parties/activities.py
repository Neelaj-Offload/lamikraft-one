"""The activity log: every call, email, WhatsApp, meeting, visit or note with a lead or customer.

Append-only (a DB trigger rejects UPDATE/DELETE): a wrong entry is corrected by logging a new one. Logging copies the
entry's ``next_follow_up_on`` onto the party (the latest activity decides the next follow-up; none clears it) and
moves a ``new`` lead to ``contacted``. ``parties.activity.logged`` drives the follow-up task (``parties.rules``).
"""

from __future__ import annotations

import base64
import uuid
from datetime import datetime, timedelta

from sqlalchemy import and_, or_, select

from app.core.clock import local_date
from app.core.db.base import new_id
from app.core.errors import Conflict, ValidationFailed
from app.modules.parties import events as ev
from app.modules.parties.models import Party, PartyActivity
from app.modules.parties.schemas import (
    ActivityCreate,
    ActivityKind,
    ActivityRead,
    LeadStage,
    PartyActivityPage,
    UserRef,
)
from app.modules.parties.service import _owner_names
from app.platform.service import query
from app.platform.uow import UnitOfWork

CREATE = "parties.activity.create"
READ = "parties.party.read"
MAX_PAGE = 100


def _invalid(msg: str, code: str, field: str) -> ValidationFailed:
    return ValidationFailed(msg, errors=[{"loc": ["body", field], "msg": msg, "code": code}])


def _read(row: PartyActivity, names: dict[uuid.UUID, str]) -> ActivityRead:
    return ActivityRead(
        id=row.id,
        party_id=row.party_id,
        kind=ActivityKind(row.kind),
        occurred_at=row.occurred_at,
        outcome=row.outcome,
        notes=row.notes,
        next_follow_up_on=row.next_follow_up_on,
        created_by=UserRef(id=row.created_by, display_name=names.get(row.created_by)) if row.created_by else
        UserRef(id=uuid.UUID(int=0), display_name=None),
        created_at=row.created_at,
    )


def log_activity(uow: UnitOfWork, party_id: uuid.UUID, data: ActivityCreate) -> ActivityRead:
    actor = uow.actor
    actor.require(CREATE)
    party = uow.repo(Party).get(party_id, "read", for_update=True)  # 404 outside the caller's scope
    if party.archived_at is not None:
        raise Conflict("Restore this record before logging activity on it", code="archived")
    if data.outcome is None and data.notes is None:
        raise _invalid("Add an outcome or a note", "activity_empty", "notes")
    now = uow.now()
    occurred_at = data.occurred_at or now
    if occurred_at > now + timedelta(minutes=5):
        raise _invalid("An activity cannot be logged in the future", "occurred_in_future", "occurred_at")
    today = local_date(now, actor.time_zone)
    if data.next_follow_up_on is not None and data.next_follow_up_on < today:
        raise _invalid("Pick today or a later date for the next follow-up", "follow_up_in_past", "next_follow_up_on")
    row = PartyActivity(
        id=new_id(),
        company_id=actor.company_id,
        party_id=party.id,
        kind=data.kind.value,
        occurred_at=occurred_at,
        outcome=data.outcome,
        notes=data.notes,
        next_follow_up_on=data.next_follow_up_on,
    )
    uow.add(row)
    previous_stage = party.lead_stage
    closed = party.lead_stage in (LeadStage.WON.value, LeadStage.LOST.value)
    party.next_follow_up_on = None if closed else data.next_follow_up_on
    if party.lead_stage == LeadStage.NEW.value:
        party.lead_stage = LeadStage.CONTACTED.value
        party.stage_changed_at = now
    party.updated_at = now
    uow.flush()
    if previous_stage != party.lead_stage:
        uow.emit(
            ev.LEAD_STAGE_CHANGED,
            aggregate_id=party.id,
            aggregate_version=party.version,
            payload=ev.payload(
                ev.LeadStageChangedPayload(party_id=party.id, from_stage=previous_stage, to_stage=party.lead_stage)
            ),
        )
    uow.emit(
        ev.ACTIVITY_LOGGED,
        aggregate_id=party.id,
        aggregate_version=party.version,
        payload=ev.payload(
            ev.ActivityLoggedPayload(
                party_id=party.id,
                activity_id=row.id,
                kind=row.kind,
                next_follow_up_on=row.next_follow_up_on.isoformat() if row.next_follow_up_on else None,
            )
        ),
    )
    uow.audit(
        "parties.activity.logged",
        resource_type="parties.party",
        resource_id=party.id,
        resource_label=f"{party.party_number} · {party.display_name}",
        details={"kind": row.kind, "activity_id": str(row.id)},
    )
    return _read(row, _owner_names(uow, [row.created_by] if row.created_by else []))


def _encode(row: PartyActivity) -> str:
    return base64.urlsafe_b64encode(f"{row.occurred_at.isoformat()}|{row.id}".encode()).decode()


def _decode(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        at, _, rid = base64.urlsafe_b64decode(cursor.encode()).decode().partition("|")
        return datetime.fromisoformat(at), uuid.UUID(rid)
    except (ValueError, UnicodeDecodeError) as exc:
        raise _invalid("The page cursor is not valid", "invalid_cursor", "cursor") from exc


@query(READ)
def list_activities(uow: UnitOfWork, party_id: uuid.UUID, *, cursor: str | None = None, limit: int = 30) -> PartyActivityPage:
    """Newest first; ``next_cursor`` continues after the last item."""
    party = uow.repo(Party).get(party_id)
    limit = max(1, min(limit, MAX_PAGE))
    stmt = select(PartyActivity).where(
        PartyActivity.company_id == uow.actor.company_id, PartyActivity.party_id == party.id
    )
    if cursor:
        at, rid = _decode(cursor)
        stmt = stmt.where(
            or_(PartyActivity.occurred_at < at, and_(PartyActivity.occurred_at == at, PartyActivity.id < rid))
        )
    rows = list(
        uow.session.scalars(stmt.order_by(PartyActivity.occurred_at.desc(), PartyActivity.id.desc()).limit(limit + 1))
    )
    more = len(rows) > limit
    rows = rows[:limit]
    names = _owner_names(uow, [r.created_by for r in rows if r.created_by])
    return PartyActivityPage(items=[_read(r, names) for r in rows], next_cursor=_encode(rows[-1]) if more and rows else None)
