"""Responsibility rules: who owns, does or decides a piece of work.

Order of resolution (briefing design §4 step 5):
1. the person the source names (message assignee, quote owner, enquiry owner, party owner), if active;
2. the next named person (e.g. the party's account owner when the message assignee left);
3. team-lead fallback: the manager of the first named person (``membership.manager_membership_id``);
4. otherwise the family's queue (``tasks_queue``) and a ``responsibility:{queue}`` issue for admins.
Approvals use candidates: active members (minus the initiator) whom the approvals engine finds eligible,
evaluated as each member through ``actor_for_member``.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from sqlalchemy import select

from app.core.errors import NotFound
from app.platform.authz.actors import actor_for_member
from app.platform.authz.context import ActorContext
from app.platform.identity.models import AppUser, Membership
from app.platform.org.workcal import CalendarView, resolve_view
from app.platform.uow import UnitOfWork

QUEUE_BY_FAMILY_PREFIX = {"sales": "sales", "common": "admin", "ops": "operations", "admin": "admin"}


@dataclass(frozen=True)
class Responsible:
    owner_user_id: uuid.UUID | None
    assignee_user_id: uuid.UUID | None
    queue_code: str | None = None


def active_member_ids(uow: UnitOfWork) -> list[uuid.UUID]:
    rows = uow.session.scalars(
        select(Membership.user_id)
        .where(Membership.company_id == uow.actor.company_id, Membership.status == "active")
        .order_by(Membership.user_id)
    )
    return list(rows)


def is_active(uow: UnitOfWork, user_id: uuid.UUID | None) -> bool:
    if user_id is None:
        return False
    return bool(
        uow.session.scalar(
            select(Membership.id).where(
                Membership.company_id == uow.actor.company_id,
                Membership.user_id == user_id,
                Membership.status == "active",
            )
        )
    )


def membership_user(uow: UnitOfWork, membership_id: uuid.UUID | None) -> uuid.UUID | None:
    if membership_id is None:
        return None
    return uow.session.scalar(
        select(Membership.user_id).where(Membership.company_id == uow.actor.company_id, Membership.id == membership_id)
    )


def manager_of(uow: UnitOfWork, user_id: uuid.UUID | None) -> uuid.UUID | None:
    if user_id is None:
        return None
    manager_membership = uow.session.scalar(
        select(Membership.manager_membership_id).where(
            Membership.company_id == uow.actor.company_id, Membership.user_id == user_id
        )
    )
    return membership_user(uow, manager_membership)


def default_branch_of(uow: UnitOfWork, user_id: uuid.UUID | None) -> uuid.UUID | None:
    if user_id is None:
        return None
    return uow.session.scalar(
        select(Membership.default_branch_id).where(
            Membership.company_id == uow.actor.company_id, Membership.user_id == user_id
        )
    )


def display_names(uow: UnitOfWork, user_ids: Iterable[uuid.UUID | None]) -> dict[uuid.UUID, str]:
    ids = sorted({u for u in user_ids if u is not None})
    if not ids:
        return {}
    rows = uow.session.execute(select(AppUser.id, AppUser.display_name).where(AppUser.id.in_(ids)))
    return {r[0]: r[1] for r in rows}


def first_name(name: str | None) -> str:
    return (name or "").strip().split(" ")[0] if name else ""


def resolve(uow: UnitOfWork, family: str, named: Sequence[uuid.UUID | None]) -> Responsible:
    """First active named person, else the first named person's manager, else the family queue."""
    for user_id in named:
        if is_active(uow, user_id):
            return Responsible(owner_user_id=user_id, assignee_user_id=user_id)
    first = next((u for u in named if u is not None), None)
    lead = manager_of(uow, first)
    if is_active(uow, lead):
        return Responsible(owner_user_id=lead, assignee_user_id=lead)
    prefix = family.split(".", 1)[0]
    return Responsible(owner_user_id=None, assignee_user_id=None, queue_code=QUEUE_BY_FAMILY_PREFIX.get(prefix, "admin"))


def member_actor(uow: UnitOfWork, user_id: uuid.UUID) -> ActorContext | None:
    """The member's effective context (None when the membership is inactive)."""
    try:
        return actor_for_member(uow.actor.company_id, user_id, channel="job")  # type: ignore[arg-type]
    except NotFound:
        return None


def eligible_approvers(uow: UnitOfWork, proposal: object) -> list[uuid.UUID]:
    """Active members except the initiator whom the approvals engine finds eligible for ``proposal``."""
    from app.modules.approvals import service as approvals
    from app.modules.tasks.visibility import view_as

    initiator = getattr(proposal, "requested_by", None)
    out: list[uuid.UUID] = []
    for user_id in active_member_ids(uow):
        if user_id == initiator:
            continue
        actor = member_actor(uow, user_id)
        if actor is None:
            continue
        if approvals.is_eligible(view_as(uow, actor), proposal):  # type: ignore[arg-type]
            out.append(user_id)
    return out


def company_calendar(uow: UnitOfWork) -> CalendarView:
    """The company's default calendar: business deadlines (SLA, approvals, expiry) are company time."""
    return resolve_view(uow, None)


def user_calendar(uow: UnitOfWork, user_id: uuid.UUID | None) -> CalendarView:
    """The calendar a person works to, in their zone (conventions §7: user → membership → calendar).

    A work-assignment zone override wins; otherwise the user's or membership's zone replaces the
    calendar zone, so a Berlin-based member's work date, windows and labels are Berlin time.
    """
    view = resolve_view(uow, user_id)
    if user_id is None:
        return view
    from app.platform.org.workcal import WorkAssignment

    has_override = uow.session.scalar(
        select(WorkAssignment.id).where(
            WorkAssignment.company_id == uow.actor.company_id,
            WorkAssignment.user_id == user_id,
            WorkAssignment.time_zone_override.is_not(None),
        )
    )
    if has_override:
        return view
    zone = uow.session.scalar(select(AppUser.time_zone).where(AppUser.id == user_id)) or uow.session.scalar(
        select(Membership.work_time_zone).where(
            Membership.company_id == uow.actor.company_id, Membership.user_id == user_id
        )
    )
    if zone and zone != view.time_zone:
        from dataclasses import replace

        return replace(view, time_zone=zone)
    return view
