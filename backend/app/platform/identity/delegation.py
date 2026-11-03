"""Delegation: time-bounded, scoped, audited hand-over of record reach (permissions.md §10).

A delegator lets a delegate act on the delegator's records for some delegable keys (``D`` flag) for at most 90
days. Delegation never adds keys: each key counts only while the delegate *and* the delegator hold it, so a
delegate without ``sales.quote.update`` gains nothing for it. Effects: ``ActorContext.delegated[key]`` lists the
delegators, and ``scope_clause`` lets an own/team/branch-scoped delegate reach the delegators' owned records.

- Members delegate their own access (self-service, ``authenticated``); ``identity.delegation.manage`` (recent auth)
  lets an administrator arrange or cancel a delegation for anyone.
- Creating or cancelling bumps the company's authz epoch; resolution caches also expire at the next start or end.
- ``identity.delegation.created|cancelled`` are emitted at once; ``started|ended`` by the boundary job, once each.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import datetime, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.platform.authz.permissions import Scope
from app.platform.identity import provisioning
from app.platform.identity.availability_models import MAX_DELEGATION_DAYS, Delegation, DelegationReason
from app.platform.identity.models import AppUser, Membership
from app.platform.identity.schemas import DelegationCreate, DelegationList, DelegationView
from app.platform.service import command, query
from app.platform.uow import UnitOfWork

DELEGATION_MANAGE = "identity.delegation.manage"


def delegable_keys() -> frozenset[str]:
    from app.registry import get_registry

    return frozenset(p.key for p in get_registry().permissions.values() if p.delegable)


# ---- resolution (called from actors.load_access) -------------------------------------------------------------
def active_delegations_for(
    session: Session, company_id: uuid.UUID, membership_id: uuid.UUID, permissions: Mapping[str, Scope], *, now: datetime
) -> tuple[dict[str, set[uuid.UUID]], datetime | None]:
    """(key -> delegator user ids, next boundary) for a delegate at ``now``."""
    from app.platform.identity.actors import load_access

    rows = list(
        session.scalars(
            select(Delegation).where(
                Delegation.company_id == company_id,
                Delegation.delegate_membership_id == membership_id,
                Delegation.cancelled_at.is_(None),
                Delegation.ends_at > now,
            )
        )
    )
    boundary: datetime | None = None
    delegated: dict[str, set[uuid.UUID]] = {}
    allowed = delegable_keys()
    for row in rows:
        edge = row.starts_at if row.starts_at > now else row.ends_at
        boundary = edge if boundary is None or edge < boundary else boundary
        if row.starts_at > now:
            continue
        delegator = session.get(Membership, row.delegator_membership_id)
        if delegator is None or delegator.status != "active":
            continue
        held = load_access(session, company_id, delegator.id, delegator.user_id, now=now, with_delegations=False).permissions
        for key in row.permission_keys:
            if key in allowed and key in permissions and key in held:
                delegated.setdefault(key, set()).add(delegator.user_id)
    return delegated, boundary


# ---- views -----------------------------------------------------------------------------------------------------
def _status(row: Delegation, now: datetime) -> str:
    if row.cancelled_at is not None:
        return "cancelled"
    if now < row.starts_at:
        return "scheduled"
    if now < row.ends_at:
        return "active"
    return "ended"


def _names(uow: UnitOfWork, membership_ids: set[uuid.UUID]) -> dict[uuid.UUID, tuple[uuid.UUID, str]]:
    rows = uow.session.execute(
        select(Membership.id, Membership.user_id, AppUser.display_name, Membership.status)
        .join(AppUser, AppUser.id == Membership.user_id)
        .where(Membership.id.in_(membership_ids))
    ).all()
    return {mid: (uid, name if status != "deactivated" else f"{name} (inactive)") for mid, uid, name, status in rows}


def _view(uow: UnitOfWork, row: Delegation, names: dict[uuid.UUID, tuple[uuid.UUID, str]]) -> DelegationView:
    delegator = names.get(row.delegator_membership_id, (None, "?"))
    delegate = names.get(row.delegate_membership_id, (None, "?"))
    now = uow.now()
    can_cancel = row.cancelled_at is None and row.ends_at > now and (
        uow.actor.membership_id in (row.delegator_membership_id,) or uow.actor.can(DELEGATION_MANAGE, Scope.COMPANY)
    )
    return DelegationView(
        id=row.id,
        delegator_user_id=delegator[0],  # type: ignore[arg-type]
        delegator_name=delegator[1],
        delegate_user_id=delegate[0],  # type: ignore[arg-type]
        delegate_name=delegate[1],
        permission_keys=sorted(row.permission_keys),
        include_approvals=row.include_approvals,
        starts_at=row.starts_at,
        ends_at=row.ends_at,
        reason=row.reason,  # type: ignore[arg-type]
        note=row.note,
        status=_status(row, now),  # type: ignore[arg-type]
        cancelled_at=row.cancelled_at,
        version=row.version,
        capabilities={"cancel": {"allowed": can_cancel, "reason_code": None if can_cancel else "permission_denied"}},
    )


def _views(uow: UnitOfWork, rows: list[Delegation]) -> list[DelegationView]:
    ids = {r.delegator_membership_id for r in rows} | {r.delegate_membership_id for r in rows}
    names = _names(uow, ids) if ids else {}
    return [_view(uow, r, names) for r in rows]


def _payload(row: Delegation) -> dict[str, object]:
    return {
        "delegation_id": str(row.id),
        "delegator_membership_id": str(row.delegator_membership_id),
        "delegate_membership_id": str(row.delegate_membership_id),
        "include_approvals": row.include_approvals,
        "starts_at": row.starts_at.isoformat(),
        "ends_at": row.ends_at.isoformat(),
    }


# ---- commands --------------------------------------------------------------------------------------------------
def _member_by_user(uow: UnitOfWork, user_id: uuid.UUID, field: str) -> Membership:
    membership = provisioning.membership_for_user(uow, user_id)
    if membership is None or membership.status != "active":
        raise ValidationFailed(errors=[{"loc": ["body", field], "msg": "Not an active member", "code": "inactive_member"}])
    return membership


@command()
def create_delegation(uow: UnitOfWork, body: DelegationCreate) -> DelegationView:
    """Delegate your own record reach (or, with ``identity.delegation.manage``, someone else's)."""
    from app.platform.authz.stepup import require_step_up

    actor = uow.actor
    if actor.membership_id is None or actor.user_id is None:
        raise Forbidden(code="permission_denied")
    delegator_user = body.delegator_user_id or actor.user_id
    if delegator_user != actor.user_id:
        actor.require(DELEGATION_MANAGE, Scope.COMPANY)
        require_step_up(uow, DELEGATION_MANAGE)
    delegator = _member_by_user(uow, delegator_user, "delegator_user_id")
    delegate = _member_by_user(uow, body.delegate_user_id, "delegate_user_id")
    if delegator.id == delegate.id:
        raise ValidationFailed(errors=[{"loc": ["body", "delegate_user_id"], "msg": "Choose someone else", "code": "self_delegation"}])
    now = uow.now()
    starts = body.starts_at or now
    if body.ends_at <= starts:
        raise ValidationFailed(errors=[{"loc": ["body", "ends_at"], "msg": "Ends after it starts", "code": "ends_before_start"}])
    if body.ends_at - starts > timedelta(days=MAX_DELEGATION_DAYS):
        raise ValidationFailed(errors=[{"loc": ["body", "ends_at"], "msg": f"At most {MAX_DELEGATION_DAYS} days", "code": "too_long"}])
    if body.ends_at <= now:
        raise ValidationFailed(errors=[{"loc": ["body", "ends_at"], "msg": "Already over", "code": "in_the_past"}])
    keys = sorted(set(body.permission_keys))
    allowed = delegable_keys()
    unknown = [k for k in keys if k not in allowed]
    if unknown:
        raise ValidationFailed(
            errors=[{"loc": ["body", "permission_keys"], "msg": f"Not delegable: {', '.join(unknown)}", "code": "not_delegable"}]
        )
    from app.platform.identity.actors import load_access

    delegator_perms = load_access(uow.session, uow.actor.company_id, delegator.id, delegator.user_id, now=now, with_delegations=False).permissions  # type: ignore[arg-type]
    missing = [k for k in keys if k not in delegator_perms]
    if missing:
        raise ValidationFailed(
            errors=[{"loc": ["body", "permission_keys"], "msg": f"The delegator does not hold: {', '.join(missing)}", "code": "not_held"}]
        )
    provisioning.lock_access(uow)
    row = Delegation(
        id=uuid.uuid7(),
        company_id=uow.actor.company_id,
        delegator_membership_id=delegator.id,
        delegate_membership_id=delegate.id,
        permission_keys=keys,
        include_approvals=body.include_approvals,
        starts_at=starts,
        ends_at=body.ends_at,
        reason=body.reason,
        note=(body.note or "").strip() or None,
        started_notified_at=now if starts <= now else None,
    )
    uow.add(row)
    uow.flush()
    uow.emit("identity.delegation.created", aggregate_id=row.id, aggregate_version=row.version, payload=_payload(row))
    if starts <= now:
        uow.emit("identity.delegation.started", aggregate_id=row.id, aggregate_version=row.version, payload=_payload(row))
    provisioning.access_changed(uow, [delegate.id], ["delegations"])
    uow.audit(
        "identity.delegation.created",
        resource_type="identity.delegation",
        resource_id=row.id,
        details={"permission_keys": keys, "starts_at": starts.isoformat(), "ends_at": body.ends_at.isoformat(), "reason": body.reason},
    )
    return _views(uow, [row])[0]


@command()
def cancel_delegation(uow: UnitOfWork, delegation_id: uuid.UUID) -> DelegationView:
    actor = uow.actor
    row = uow.session.scalars(
        select(Delegation).where(Delegation.id == delegation_id, Delegation.company_id == actor.company_id).with_for_update()
    ).first()
    visible = row is not None and (
        actor.membership_id in (row.delegator_membership_id, row.delegate_membership_id) or actor.can(DELEGATION_MANAGE, Scope.COMPANY)
    )
    if row is None or not visible:
        raise NotFound(code="not_found", resource_type="identity.delegation")
    if actor.membership_id != row.delegator_membership_id:
        from app.platform.authz.stepup import require_step_up

        actor.require(DELEGATION_MANAGE, Scope.COMPANY)
        require_step_up(uow, DELEGATION_MANAGE)
    now = uow.now()
    if row.cancelled_at is not None or row.ends_at <= now:
        raise Conflict("This delegation is already over.", code="invalid_transition")
    provisioning.lock_access(uow)
    row.cancelled_at = now
    row.cancelled_by = actor.user_id
    uow.flush()
    uow.emit("identity.delegation.cancelled", aggregate_id=row.id, aggregate_version=row.version, payload=_payload(row))
    provisioning.access_changed(uow, [row.delegate_membership_id], ["delegations"])
    uow.audit("identity.delegation.cancelled", resource_type="identity.delegation", resource_id=row.id)
    return _views(uow, [row])[0]


@query()
def list_delegations(uow: UnitOfWork, *, scope: str = "mine", include_past: bool = False) -> DelegationList:
    """``mine``: given and received by you; ``all``: every delegation (``identity.delegation.manage``)."""
    actor = uow.actor
    stmt = select(Delegation).where(Delegation.company_id == actor.company_id)
    if scope == "all":
        actor.require(DELEGATION_MANAGE, Scope.COMPANY)
    else:
        stmt = stmt.where(
            or_(Delegation.delegator_membership_id == actor.membership_id, Delegation.delegate_membership_id == actor.membership_id)
        )
    if not include_past:
        stmt = stmt.where(Delegation.cancelled_at.is_(None), Delegation.ends_at > uow.now())
    rows = list(uow.session.scalars(stmt.order_by(Delegation.starts_at.desc(), Delegation.id)))
    return DelegationList(items=_views(uow, rows), delegable_keys=sorted(delegable_keys()))


# ---- boundary job ------------------------------------------------------------------------------------------------
def notify_boundaries(uow: UnitOfWork) -> dict[str, int]:
    """Emit ``started`` / ``ended`` once per delegation whose start or end has passed (system job, per company)."""
    now = uow.now()
    started = list(
        uow.session.scalars(
            select(Delegation)
            .where(
                Delegation.company_id == uow.actor.company_id,
                Delegation.cancelled_at.is_(None),
                Delegation.started_notified_at.is_(None),
                Delegation.starts_at <= now,
            )
            .with_for_update(skip_locked=True)
        )
    )
    for row in started:
        row.started_notified_at = now
        uow.emit("identity.delegation.started", aggregate_id=row.id, payload=_payload(row))
    ended = list(
        uow.session.scalars(
            select(Delegation)
            .where(
                Delegation.company_id == uow.actor.company_id,
                Delegation.ended_notified_at.is_(None),
                or_(Delegation.ends_at <= now, and_(Delegation.cancelled_at.is_not(None), Delegation.cancelled_at <= now)),
            )
            .with_for_update(skip_locked=True)
        )
    )
    for row in ended:
        row.ended_notified_at = now
        if row.cancelled_at is None:
            uow.emit("identity.delegation.ended", aggregate_id=row.id, payload=_payload(row))
    uow.flush()
    return {"started": len(started), "ended": sum(1 for r in ended if r.cancelled_at is None)}


REASONS = tuple(r.value for r in DelegationReason)
