"""Recent records: remember the detail records a user opens, and the ``ui.recent_record`` SourceReader.

``POST /api/v1/ui/recent-records`` is called by the web shell when a detail route opens. Only records the actor
can see are remembered (the resource type's ResourcePolicy decides; an invisible or unknown record is 404, so the
endpoint never confirms that a record exists). A repeat moves the record to the top; the newest
``RECENT_KEEP`` per user are kept.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import delete, exists, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.errors import Forbidden, NotFound, ValidationFailed
from app.platform.service import command
from app.platform.sources import SourceFacts

from .models import RECENT_KEEP, RecentRecord
from .schemas import RecentRecordCreate, RecentRecordRead

if TYPE_CHECKING:
    from app.platform.uow import UnitOfWork


def _visible(uow: UnitOfWork, resource_type: str, resource_id: uuid.UUID) -> bool:
    from app.platform.authz.policy import get_policy, scope_clause

    try:
        policy = get_policy(resource_type)
    except KeyError:
        policy = None
    if policy is None:
        raise ValidationFailed(
            errors=[{"loc": ["body", "resource_type"], "msg": "not a recordable resource type", "code": "unsupported"}]
        )
    model = policy.model
    return bool(
        uow.session.scalar(
            select(exists().where(model.id == resource_id, scope_clause(uow.actor, policy, "read")))  # type: ignore[attr-defined]
        )
    )


@command()
def record_recent_record(uow: UnitOfWork, body: RecentRecordCreate) -> RecentRecordRead:
    actor = uow.actor
    if actor.user_id is None or actor.company_id is None or actor.is_system:
        raise Forbidden(code="permission_denied")
    if not _visible(uow, body.resource_type, body.resource_id):
        raise NotFound(code="not_found", resource_type=body.resource_type)
    now = uow.now()
    stmt = pg_insert(RecentRecord).values(
        id=uuid.uuid7(),
        company_id=actor.company_id,
        user_id=actor.user_id,
        resource_type=body.resource_type,
        resource_id=body.resource_id,
        opened_at=now,
    )
    uow.session.execute(
        stmt.on_conflict_do_update(
            index_elements=["company_id", "user_id", "resource_type", "resource_id"],
            set_={"opened_at": stmt.excluded.opened_at},
        )
    )
    keep = (
        select(RecentRecord.id)
        .where(RecentRecord.company_id == actor.company_id, RecentRecord.user_id == actor.user_id)
        .order_by(RecentRecord.opened_at.desc(), RecentRecord.id.desc())
        .limit(RECENT_KEEP)
    )
    uow.session.execute(
        delete(RecentRecord).where(
            RecentRecord.company_id == actor.company_id,
            RecentRecord.user_id == actor.user_id,
            RecentRecord.id.not_in(keep.scalar_subquery()),
        )
    )
    return RecentRecordRead(resource_type=body.resource_type, resource_id=body.resource_id, opened_at=now)


def read_recent_record_facts(uow: UnitOfWork, user_id: uuid.UUID) -> SourceFacts | None:
    """``ui.recent_record`` (source id = user id): how many records the user opened lately, by type. Personal:
    only the system and the user themself get facts."""
    actor = uow.actor
    if not (actor.is_system or actor.user_id == user_id) or actor.company_id is None:
        return None
    rows = uow.session.execute(
        select(RecentRecord.resource_type, func.count(), func.max(RecentRecord.opened_at))
        .where(RecentRecord.company_id == actor.company_id, RecentRecord.user_id == user_id)
        .group_by(RecentRecord.resource_type)
    ).all()
    by_type = {resource_type: int(count) for resource_type, count, _last in rows}
    last = max((last for _t, _c, last in rows), default=None)
    return SourceFacts(
        source_type="ui.recent_record",
        source_id=user_id,
        version=None,
        label="Recently opened records",
        status="active",
        owner_user_id=user_id,
        branch_id=None,
        required_permission="org.directory.read",
        canonical_path="/today",
        updated_at=last,
        facts={"count": sum(by_type.values()), "by_type": by_type},
    )
