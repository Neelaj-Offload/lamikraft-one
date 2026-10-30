"""Self-service and administrator session management (api-conventions §7: revocation applies on the next request).

- Your own sessions (``authenticated``): list them, end one, or end every other one.
- Another member's sessions (``identity.session.manage``, MFA + recent auth): list them or end them all.

Only open (not revoked, not expired) sessions of the current company are listed; addresses and user agents are
stored as keyed hashes, so the list shows times and sign-in methods only.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.core.errors import Forbidden, NotFound, Unauthenticated
from app.platform.authz.permissions import Scope
from app.platform.authz.stepup import require_step_up
from app.platform.identity import provisioning, sessions
from app.platform.identity.auth_models import AuthSession, SessionStage
from app.platform.identity.schemas import RevokedCount, SessionList, SessionListItem
from app.platform.service import command, query
from app.platform.uow import UnitOfWork

SESSION_MANAGE = "identity.session.manage"


def _open_sessions(uow: UnitOfWork, user_id: uuid.UUID) -> list[AuthSession]:
    now = uow.now()
    rows = uow.session.scalars(
        select(AuthSession)
        .where(
            AuthSession.user_id == user_id,
            AuthSession.company_id == uow.actor.company_id,
            AuthSession.revoked_at.is_(None),
            AuthSession.stage == SessionStage.ACTIVE.value,
        )
        .order_by(AuthSession.last_seen_at.desc())
    )
    return [r for r in rows if sessions.is_live(r, now)]


def _items(uow: UnitOfWork, rows: list[AuthSession]) -> SessionList:
    return SessionList(
        items=[
            SessionListItem(
                id=r.id,
                auth_method=r.auth_method,
                created_at=r.created_at,
                last_seen_at=r.last_seen_at,
                idle_expires_at=r.idle_expires_at,
                absolute_expires_at=r.absolute_expires_at,
                mfa_verified=r.mfa_verified_at is not None,
                current=r.id == uow.actor.session_id,
            )
            for r in rows
        ]
    )


def _me(uow: UnitOfWork) -> uuid.UUID:
    if uow.actor.user_id is None or uow.actor.session_id is None:
        raise Unauthenticated()
    return uow.actor.user_id


@query()
def my_sessions(uow: UnitOfWork) -> SessionList:
    return _items(uow, _open_sessions(uow, _me(uow)))


@command()
def end_my_session(uow: UnitOfWork, session_id: uuid.UUID) -> None:
    user_id = _me(uow)
    row = uow.session.get(AuthSession, session_id)
    if row is None or row.user_id != user_id or row.company_id != uow.actor.company_id or row.revoked_at is not None:
        raise NotFound(code="not_found", resource_type="identity.session")
    sessions.revoke(uow.session, session_id, now=uow.now(), reason="ended_by_user")
    uow.audit("auth.session.ended", resource_type="identity.session", resource_id=session_id)


@command()
def end_my_other_sessions(uow: UnitOfWork) -> RevokedCount:
    user_id = _me(uow)
    count = sessions.revoke_all(uow.session, user_id=user_id, now=uow.now(), reason="ended_by_user", keep=uow.actor.session_id)
    uow.audit("auth.session.others_ended", resource_type="identity.user", resource_id=user_id, details={"revoked": count})
    return RevokedCount(revoked=count)


@query(SESSION_MANAGE, at_least=Scope.COMPANY)
def member_sessions(uow: UnitOfWork, user_id: uuid.UUID) -> SessionList:
    if provisioning.membership_for_user(uow, user_id) is None:
        raise NotFound(code="not_found", resource_type="identity.membership")
    return _items(uow, _open_sessions(uow, user_id))


@command(SESSION_MANAGE, at_least=Scope.COMPANY)
def end_member_sessions(uow: UnitOfWork, user_id: uuid.UUID) -> RevokedCount:
    require_step_up(uow, SESSION_MANAGE)
    membership = provisioning.membership_for_user(uow, user_id)
    if membership is None:
        raise NotFound(code="not_found", resource_type="identity.membership")
    if user_id == uow.actor.user_id:
        raise Forbidden("End your own sessions from your security page.", code="self_access_change")
    count = sessions.revoke_all(uow.session, membership_id=membership.id, now=uow.now(), reason="ended_by_admin")
    uow.audit("identity.sessions.ended", resource_type="identity.membership", resource_id=membership.id, details={"revoked": count})
    return RevokedCount(revoked=count)
