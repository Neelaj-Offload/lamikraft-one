"""Leave (absences) and access requests.

Leave: a member records their own absence (``requested``); their manager or a holder of
``identity.absence.approve`` approves or rejects it; the member (or an approver) may cancel it. Events
``identity.absence.requested|approved|cancelled`` let the Inbox and briefings suggest owner reassignment; the
``identity.absence`` reader gives them the dates and the cover person. No medical detail is ever stored.

Access requests: a member asks for one permission (key, scope, reason, up to 90 days). An approver holding
``identity.access_request.approve`` (MFA + recent auth) grants it as an expiring per-user override (anti-escalation
applies: the approver must hold the key at that scope) or rejects it; the requester may withdraw a pending one.
Events ``identity.access_request.submitted|decided``; every step is audited.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import select

from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.platform.authz.context import ActorContext
from app.platform.authz.permissions import Scope
from app.platform.authz.stepup import require_step_up
from app.platform.identity import provisioning
from app.platform.identity.availability_models import (
    AbsenceStatus,
    AccessRequest,
    AccessRequestStatus,
    UserAbsence,
)
from app.platform.identity.models import AppUser, Membership, Permission
from app.platform.identity.schemas import (
    AbsenceCreate,
    AbsenceDecision,
    AbsenceList,
    AbsenceView,
    AccessRequestCreate,
    AccessRequestDecision,
    AccessRequestList,
    AccessRequestView,
    CapabilityView,
)
from app.platform.service import command, query
from app.platform.sources import SourceFacts
from app.platform.uow import UnitOfWork

ABSENCE_APPROVE = "identity.absence.approve"
ACCESS_APPROVE = "identity.access_request.approve"
MAX_ABSENCE_DAYS = 366


def _cap(allowed: bool, reason: str = "permission_denied") -> CapabilityView:
    return CapabilityView(allowed=allowed, reason_code=None if allowed else reason)


def _self(uow: UnitOfWork) -> Membership:
    actor = uow.actor
    membership = uow.session.get(Membership, actor.membership_id) if actor.membership_id else None
    if membership is None or membership.status != "active":
        raise Forbidden(code="permission_denied")
    return membership


def _people(uow: UnitOfWork, membership_ids: set[uuid.UUID]) -> dict[uuid.UUID, tuple[uuid.UUID, str]]:
    if not membership_ids:
        return {}
    rows = uow.session.execute(
        select(Membership.id, Membership.user_id, AppUser.display_name, Membership.status)
        .join(AppUser, AppUser.id == Membership.user_id)
        .where(Membership.id.in_(membership_ids))
    ).all()
    return {mid: (uid, f"{name} (inactive)" if status == "deactivated" else name) for mid, uid, name, status in rows}


def _user_names(uow: UnitOfWork, user_ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not user_ids:
        return {}
    return dict(uow.session.execute(select(AppUser.id, AppUser.display_name).where(AppUser.id.in_(user_ids))).all())  # type: ignore[arg-type]


# ---- leave -----------------------------------------------------------------------------------------------------
def _is_approver(uow: UnitOfWork, row: UserAbsence) -> bool:
    actor = uow.actor
    if actor.can(ABSENCE_APPROVE, Scope.COMPANY):
        return True
    member = uow.session.get(Membership, row.membership_id)
    return member is not None and member.manager_membership_id is not None and member.manager_membership_id == actor.membership_id


def _absence_views(uow: UnitOfWork, rows: list[UserAbsence]) -> list[AbsenceView]:
    people = _people(uow, {r.membership_id for r in rows} | {r.cover_membership_id for r in rows if r.cover_membership_id})
    deciders = _user_names(uow, {r.decided_by for r in rows if r.decided_by})
    today = uow.now().date()
    out = []
    for r in rows:
        approver = _is_approver(uow, r)
        mine = r.membership_id == uow.actor.membership_id
        open_ = r.status in (AbsenceStatus.REQUESTED.value, AbsenceStatus.APPROVED.value) and r.ends_on >= today
        cover = people.get(r.cover_membership_id) if r.cover_membership_id else None
        person = people.get(r.membership_id, (None, "?"))
        out.append(
            AbsenceView(
                id=r.id,
                user_id=person[0],  # type: ignore[arg-type]
                display_name=person[1],
                kind=r.kind,  # type: ignore[arg-type]
                starts_on=r.starts_on,
                ends_on=r.ends_on,
                status=r.status,  # type: ignore[arg-type]
                note=r.note,
                cover_user_id=cover[0] if cover else None,
                cover_name=cover[1] if cover else None,
                decided_by_name=deciders.get(r.decided_by) if r.decided_by else None,
                decided_at=r.decided_at,
                decision_note=r.decision_note,
                version=r.version,
                capabilities={
                    "decide": _cap(approver and not mine and r.status == AbsenceStatus.REQUESTED.value, "invalid_transition" if approver else "permission_denied"),
                    "cancel": _cap((mine or approver) and open_, "invalid_transition" if (mine or approver) else "permission_denied"),
                },
            )
        )
    return out


def _absence_payload(row: UserAbsence) -> dict[str, object]:
    return {
        "absence_id": str(row.id),
        "membership_id": str(row.membership_id),
        "starts_on": row.starts_on.isoformat(),
        "ends_on": row.ends_on.isoformat(),
    }


@command()
def request_absence(uow: UnitOfWork, body: AbsenceCreate) -> AbsenceView:
    me = _self(uow)
    if body.ends_on < body.starts_on:
        raise ValidationFailed(errors=[{"loc": ["body", "ends_on"], "msg": "Ends on or after the start", "code": "ends_before_start"}])
    if (body.ends_on - body.starts_on).days >= MAX_ABSENCE_DAYS:
        raise ValidationFailed(errors=[{"loc": ["body", "ends_on"], "msg": "At most one year", "code": "too_long"}])
    if body.ends_on < uow.now().date():
        raise ValidationFailed(errors=[{"loc": ["body", "ends_on"], "msg": "Already over", "code": "in_the_past"}])
    cover_id = None
    if body.cover_user_id is not None:
        cover = provisioning.membership_for_user(uow, body.cover_user_id)
        if cover is None or cover.status != "active" or cover.id == me.id:
            raise ValidationFailed(errors=[{"loc": ["body", "cover_user_id"], "msg": "Choose another active member", "code": "invalid_cover"}])
        cover_id = cover.id
    overlap = uow.session.scalar(
        select(UserAbsence.id).where(
            UserAbsence.company_id == me.company_id,
            UserAbsence.membership_id == me.id,
            UserAbsence.status.in_((AbsenceStatus.REQUESTED.value, AbsenceStatus.APPROVED.value)),
            UserAbsence.starts_on <= body.ends_on,
            UserAbsence.ends_on >= body.starts_on,
        )
    )
    if overlap is not None:
        raise Conflict("You already have leave recorded for some of these days.", code="absence_overlap")
    row = UserAbsence(
        id=uuid.uuid7(),
        company_id=me.company_id,
        membership_id=me.id,
        kind=body.kind,
        starts_on=body.starts_on,
        ends_on=body.ends_on,
        status=AbsenceStatus.REQUESTED.value,
        note=(body.note or "").strip() or None,
        cover_membership_id=cover_id,
    )
    uow.add(row)
    uow.flush()
    uow.emit("identity.absence.requested", aggregate_id=row.id, aggregate_version=row.version, payload=_absence_payload(row))
    uow.audit("identity.absence.requested", resource_type="identity.absence", resource_id=row.id, details={"kind": body.kind})
    return _absence_views(uow, [row])[0]


def _absence(uow: UnitOfWork, absence_id: uuid.UUID) -> UserAbsence:
    row = uow.session.scalars(
        select(UserAbsence).where(UserAbsence.id == absence_id, UserAbsence.company_id == uow.actor.company_id).with_for_update()
    ).first()
    if row is None or not (row.membership_id == uow.actor.membership_id or _is_approver(uow, row)):
        raise NotFound(code="not_found", resource_type="identity.absence")
    return row


@command()
def decide_absence(uow: UnitOfWork, absence_id: uuid.UUID, body: AbsenceDecision) -> AbsenceView:
    row = _absence(uow, absence_id)
    if not _is_approver(uow, row) or row.membership_id == uow.actor.membership_id:
        raise Forbidden("Leave is approved by the manager or a leave approver, never by the person.", code="permission_denied", permission=ABSENCE_APPROVE)
    uow.expect_version(row, body.expected_version)
    if row.status != AbsenceStatus.REQUESTED.value:
        raise Conflict("This leave was already decided.", code="invalid_transition")
    row.status = AbsenceStatus.APPROVED.value if body.decision == "approve" else AbsenceStatus.REJECTED.value
    row.decided_by = uow.actor.user_id
    row.decided_at = uow.now()
    row.decision_note = (body.note or "").strip() or None
    uow.flush()
    if body.decision == "approve":
        uow.emit("identity.absence.approved", aggregate_id=row.id, aggregate_version=row.version, payload=_absence_payload(row))
    uow.audit(f"identity.absence.{'approved' if body.decision == 'approve' else 'rejected'}", resource_type="identity.absence", resource_id=row.id, reason=row.decision_note)
    return _absence_views(uow, [row])[0]


@command()
def cancel_absence(uow: UnitOfWork, absence_id: uuid.UUID) -> AbsenceView:
    row = _absence(uow, absence_id)
    if row.status not in (AbsenceStatus.REQUESTED.value, AbsenceStatus.APPROVED.value) or row.ends_on < uow.now().date():
        raise Conflict("This leave can no longer be cancelled.", code="invalid_transition")
    row.status = AbsenceStatus.CANCELLED.value
    uow.flush()
    uow.emit("identity.absence.cancelled", aggregate_id=row.id, aggregate_version=row.version, payload=_absence_payload(row))
    uow.audit("identity.absence.cancelled", resource_type="identity.absence", resource_id=row.id)
    return _absence_views(uow, [row])[0]


@query()
def list_absences(uow: UnitOfWork, *, scope: str = "mine", include_past: bool = False) -> AbsenceList:
    """``mine``: your own; ``team``: people you approve for (your reports, or everyone with the approve key)."""
    actor = uow.actor
    stmt = select(UserAbsence).where(UserAbsence.company_id == actor.company_id)
    if scope == "team":
        if not actor.can(ABSENCE_APPROVE, Scope.COMPANY):
            reports = select(Membership.id).where(Membership.manager_membership_id == actor.membership_id)
            stmt = stmt.where(UserAbsence.membership_id.in_(reports))
    else:
        stmt = stmt.where(UserAbsence.membership_id == actor.membership_id)
    if not include_past:
        stmt = stmt.where(UserAbsence.ends_on >= uow.now().date())
    rows = list(uow.session.scalars(stmt.order_by(UserAbsence.starts_on, UserAbsence.id)))
    return AbsenceList(items=_absence_views(uow, rows))


def read_absence_facts(uow: UnitOfWork, absence_id: uuid.UUID) -> SourceFacts | None:
    """``identity.absence`` reader: dates, status and the cover person, for owner-reassignment hints. Visible to
    the system, the person, their manager, the cover and leave approvers; never a medical detail (none is kept)."""
    actor = uow.actor
    row = uow.session.scalars(select(UserAbsence).where(UserAbsence.id == absence_id, UserAbsence.company_id == actor.company_id)).first()
    if row is None:
        return None
    member = uow.session.get(Membership, row.membership_id)
    allowed = actor.is_system or actor.membership_id in (row.membership_id, row.cover_membership_id) or (
        member is not None and member.manager_membership_id == actor.membership_id
    ) or actor.can(ABSENCE_APPROVE, Scope.COMPANY)
    if not allowed or member is None:
        return None
    people = _people(uow, {row.membership_id} | ({row.cover_membership_id} if row.cover_membership_id else set()))
    cover = people.get(row.cover_membership_id) if row.cover_membership_id else None
    return SourceFacts(
        source_type="identity.absence",
        source_id=row.id,
        version=row.version,
        label=f"{people.get(row.membership_id, (None, '?'))[1]} away {row.starts_on.isoformat()} to {row.ends_on.isoformat()}",
        status=row.status,
        owner_user_id=member.user_id,
        branch_id=member.default_branch_id,
        required_permission=ABSENCE_APPROVE,
        canonical_path="/settings/leave",
        is_closed=row.status in (AbsenceStatus.CANCELLED.value, AbsenceStatus.REJECTED.value),
        updated_at=row.updated_at,
        facts={
            "membership_id": str(row.membership_id),
            "starts_on": row.starts_on.isoformat(),
            "ends_on": row.ends_on.isoformat(),
            "kind": row.kind,
            "cover_membership_id": str(row.cover_membership_id) if row.cover_membership_id else None,
            "cover_user_id": str(cover[0]) if cover else None,
            "cover_name": cover[1] if cover else None,
        },
    )


# ---- access requests -------------------------------------------------------------------------------------------------
def _request_views(uow: UnitOfWork, rows: list[AccessRequest]) -> list[AccessRequestView]:
    people = _people(uow, {r.requester_membership_id for r in rows})
    deciders = _user_names(uow, {r.decided_by for r in rows if r.decided_by})
    approver = uow.actor.can(ACCESS_APPROVE, Scope.COMPANY)
    out = []
    for r in rows:
        mine = r.requester_membership_id == uow.actor.membership_id
        pending = r.status == AccessRequestStatus.PENDING.value
        person = people.get(r.requester_membership_id, (None, "?"))
        out.append(
            AccessRequestView(
                id=r.id,
                requester_user_id=person[0],  # type: ignore[arg-type]
                requester_name=person[1],
                permission_key=r.permission_key,
                scope=r.scope,  # type: ignore[arg-type]
                reason=r.reason,
                duration_days=r.duration_days,
                status=r.status,  # type: ignore[arg-type]
                decided_by_name=deciders.get(r.decided_by) if r.decided_by else None,
                decided_at=r.decided_at,
                decision_note=r.decision_note,
                grant_expires_at=r.grant_expires_at,
                created_at=r.created_at,
                version=r.version,
                capabilities={
                    "decide": _cap(approver and pending and not mine, "permission_denied" if not approver else ("self_access_change" if mine else "invalid_transition")),
                    "withdraw": _cap(mine and pending, "invalid_transition" if mine else "permission_denied"),
                },
            )
        )
    return out


def _request_payload(row: AccessRequest, decision: str | None) -> dict[str, object]:
    return {"access_request_id": str(row.id), "requester_membership_id": str(row.requester_membership_id), "decision": decision}


@command()
def submit_access_request(uow: UnitOfWork, body: AccessRequestCreate) -> AccessRequestView:
    me = _self(uow)
    perm = uow.session.get(Permission, body.permission_key)
    if perm is None or perm.deprecated_at is not None:
        raise ValidationFailed(errors=[{"loc": ["body", "permission_key"], "msg": "Unknown permission", "code": "unknown_permission"}])
    if body.scope not in perm.allowed_scopes:
        raise ValidationFailed(errors=[{"loc": ["body", "scope"], "msg": f"Allowed: {', '.join(perm.allowed_scopes)}", "code": "scope_not_allowed"}])
    held = uow.actor.permissions.get(body.permission_key)
    if held is not None and held >= Scope.parse(body.scope):
        raise Conflict("You already have this permission at that scope.", code="already_granted")
    open_ = uow.session.scalar(
        select(AccessRequest.id).where(
            AccessRequest.company_id == me.company_id,
            AccessRequest.requester_membership_id == me.id,
            AccessRequest.permission_key == body.permission_key,
            AccessRequest.status == AccessRequestStatus.PENDING.value,
        )
    )
    if open_ is not None:
        raise Conflict("You already asked for this permission; wait for the decision or withdraw it.", code="request_pending")
    row = AccessRequest(
        id=uuid.uuid7(),
        company_id=me.company_id,
        requester_membership_id=me.id,
        permission_key=body.permission_key,
        scope=body.scope,
        reason=body.reason.strip(),
        duration_days=body.duration_days,
        status=AccessRequestStatus.PENDING.value,
    )
    uow.add(row)
    uow.flush()
    uow.emit("identity.access_request.submitted", aggregate_id=row.id, aggregate_version=row.version, payload=_request_payload(row, None))
    uow.audit("identity.access_request.submitted", resource_type="identity.access_request", resource_id=row.id, reason=row.reason, details={"permission_key": row.permission_key, "scope": row.scope, "duration_days": row.duration_days})
    return _request_views(uow, [row])[0]


def _request(uow: UnitOfWork, request_id: uuid.UUID) -> AccessRequest:
    row = uow.session.scalars(
        select(AccessRequest).where(AccessRequest.id == request_id, AccessRequest.company_id == uow.actor.company_id).with_for_update()
    ).first()
    if row is None or not (row.requester_membership_id == uow.actor.membership_id or uow.actor.can(ACCESS_APPROVE, Scope.COMPANY)):
        raise NotFound(code="not_found", resource_type="identity.access_request")
    return row


@command()
def decide_access_request(uow: UnitOfWork, request_id: uuid.UUID, body: AccessRequestDecision) -> AccessRequestView:
    actor: ActorContext = uow.actor
    row = _request(uow, request_id)
    actor.require(ACCESS_APPROVE, Scope.COMPANY)
    require_step_up(uow, ACCESS_APPROVE)
    if row.requester_membership_id == actor.membership_id:
        raise Forbidden("Someone else decides your own request.", code="self_access_change")
    uow.expect_version(row, body.expected_version)
    if row.status != AccessRequestStatus.PENDING.value:
        raise Conflict("This request was already decided.", code="invalid_transition")
    now = uow.now()
    if body.decision == "approve":
        days = min(body.duration_days or row.duration_days, row.duration_days)
        expires = now + timedelta(days=days)
        # the grant runs as the approver, so anti-escalation applies to them
        override_id = provisioning.set_permission_override(
            uow,
            row.requester_membership_id,
            permission_key=row.permission_key,
            effect="grant",
            reason=f"Access request: {row.reason}"[:500],
            scope=row.scope,
            expires_at=expires,
            origin="access_request",
        )
        row.status = AccessRequestStatus.APPROVED.value
        row.grant_expires_at = expires
        row.override_id = override_id
    else:
        row.status = AccessRequestStatus.REJECTED.value
    row.decided_by = actor.user_id
    row.decided_at = now
    row.decision_note = (body.note or "").strip() or None
    uow.flush()
    uow.emit("identity.access_request.decided", aggregate_id=row.id, aggregate_version=row.version, payload=_request_payload(row, body.decision))
    uow.audit(
        f"identity.access_request.{'approved' if body.decision == 'approve' else 'rejected'}",
        resource_type="identity.access_request",
        resource_id=row.id,
        reason=row.decision_note,
        details={"permission_key": row.permission_key, "scope": row.scope, "grant_expires_at": row.grant_expires_at.isoformat() if row.grant_expires_at else None},
    )
    return _request_views(uow, [row])[0]


@command()
def withdraw_access_request(uow: UnitOfWork, request_id: uuid.UUID) -> AccessRequestView:
    row = _request(uow, request_id)
    if row.requester_membership_id != uow.actor.membership_id:
        raise Forbidden(code="permission_denied")
    if row.status != AccessRequestStatus.PENDING.value:
        raise Conflict("Only a pending request can be withdrawn.", code="invalid_transition")
    row.status = AccessRequestStatus.WITHDRAWN.value
    uow.flush()
    uow.emit("identity.access_request.decided", aggregate_id=row.id, aggregate_version=row.version, payload=_request_payload(row, "withdrawn"))
    uow.audit("identity.access_request.withdrawn", resource_type="identity.access_request", resource_id=row.id)
    return _request_views(uow, [row])[0]


@query()
def list_access_requests(uow: UnitOfWork, *, scope: str = "mine", status: str | None = None) -> AccessRequestList:
    """``mine``: your requests; ``all``: everyone's (``identity.access_request.approve``)."""
    actor = uow.actor
    stmt = select(AccessRequest).where(AccessRequest.company_id == actor.company_id)
    if scope == "all":
        actor.require(ACCESS_APPROVE, Scope.COMPANY)
    else:
        stmt = stmt.where(AccessRequest.requester_membership_id == actor.membership_id)
    if status:
        stmt = stmt.where(AccessRequest.status == status)
    rows = list(uow.session.scalars(stmt.order_by(AccessRequest.status != "pending", AccessRequest.created_at.desc()).limit(200)))
    return AccessRequestList(items=_request_views(uow, rows))
