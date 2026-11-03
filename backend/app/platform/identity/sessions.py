"""Opaque server-side sessions (ADR-008, api-conventions §7).

A session token is 256 random bits sent only in the HttpOnly ``lk_session`` cookie (``__Host-lk_session`` in
production); the database keeps its SHA-256. A separate CSRF secret is delivered in the readable ``lk_csrf``
cookie and checked against ``csrf_hash`` on unsafe requests. Idle lifetime 12 h (extended at most once a
minute), absolute lifetime 7 days; a new session is issued on every sign-in (the previous one in the same
browser is revoked and linked through ``rotated_from_id``); revocation applies on the next request.
"""

from __future__ import annotations

import ipaddress
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.platform.identity.auth_models import AuthMethod, AuthSession, SessionStage
from app.platform.identity.tokens import keyed_hash, new_token, sha256

IDLE_LIFETIME = timedelta(hours=12)
ABSOLUTE_LIFETIME = timedelta(days=7)
RECENT_AUTH_WINDOW = timedelta(minutes=10)
TOUCH_INTERVAL = timedelta(minutes=1)

CSRF_COOKIE = "lk_csrf"
UI_COOKIE = "lk_ui"
CSRF_HEADER = "x-csrf-token"


def session_cookie_name() -> str:
    return "__Host-lk_session" if get_settings().is_production else "lk_session"


@dataclass(frozen=True)
class ClientInfo:
    ip: str | None = None
    user_agent: str | None = None
    #: the session cookie presented with the request (rotated on sign-in)
    session_token: str | None = None

    @property
    def ip_hash(self) -> bytes | None:
        return keyed_hash("ip", self.ip) if self.ip else None

    @property
    def user_agent_hash(self) -> bytes | None:
        return keyed_hash("ua", self.user_agent) if self.user_agent else None

    @property
    def audit_ip(self) -> str | None:
        if not self.ip:
            return None
        try:
            return str(ipaddress.ip_address(self.ip))
        except ValueError:
            return None


@dataclass(frozen=True)
class IssuedSession:
    session_id: uuid.UUID
    token: str
    csrf_token: str
    user_id: uuid.UUID
    company_id: uuid.UUID
    membership_id: uuid.UUID
    created_at: datetime
    idle_expires_at: datetime
    absolute_expires_at: datetime
    auth_method: str
    stage: str = SessionStage.ACTIVE.value


def find_by_token(session: Session, token: str | None) -> AuthSession | None:
    if not token or len(token) > 512:
        return None
    return session.scalars(select(AuthSession).where(AuthSession.token_hash == sha256(token))).first()


def is_open(row: AuthSession, now: datetime) -> bool:
    """Not revoked and not expired, whatever its stage (a pending MFA session is open but not live)."""
    return row.revoked_at is None and now < row.idle_expires_at and now < row.absolute_expires_at


def is_live(row: AuthSession, now: datetime) -> bool:
    return is_open(row, now) and row.stage == SessionStage.ACTIVE.value


def create_session(
    session: Session,
    *,
    user_id: uuid.UUID,
    company_id: uuid.UUID,
    membership_id: uuid.UUID,
    method: AuthMethod,
    client: ClientInfo,
    now: datetime,
    stage: SessionStage = SessionStage.ACTIVE,
    mfa_verified: bool = False,
    recent_auth: bool | None = None,
) -> IssuedSession:
    """Insert a new session, revoking the one this browser presented (rotation).

    The presented session may belong to another person or company (or be expired but unrevoked), so it is
    revoked with a Core UPDATE (``auth_session`` is RLS-exempt), never through the ORM unit of work, whose tenant
    stamp rejects a dirty row of another company. ``rotated_from_id`` links only the same user in the same company.
    """
    rotated_from: uuid.UUID | None = None
    previous = find_by_token(session, client.session_token)
    if previous is not None and previous.revoked_at is None:
        same = previous.user_id == user_id and previous.company_id == company_id
        revoke(session, previous.id, now=now, reason="rotated" if same else "replaced")
        if same:
            rotated_from = previous.id
    token, csrf = new_token(), new_token()
    absolute = now + ABSOLUTE_LIFETIME
    row = AuthSession(
        id=uuid.uuid7(),
        user_id=user_id,
        company_id=company_id,
        membership_id=membership_id,
        token_hash=sha256(token),
        csrf_hash=sha256(csrf),
        stage=stage.value,
        auth_method=method.value,
        created_at=now,
        last_seen_at=now,
        idle_expires_at=min(now + IDLE_LIFETIME, absolute),
        absolute_expires_at=absolute,
        # test-support sessions stand in for password sign-ins (same strength); demo links are not re-authentication;
        # a session waiting for its MFA code has not authenticated yet
        recent_auth_at=now
        if (recent_auth if recent_auth is not None else method in (AuthMethod.PASSWORD, AuthMethod.TEST_SUPPORT))
        and stage != SessionStage.MFA_PENDING
        else None,
        mfa_verified_at=now if mfa_verified else None,
        rotated_from_id=rotated_from,
        ip_hash=client.ip_hash,
        user_agent_hash=client.user_agent_hash,
    )
    session.add(row)
    session.flush()
    return IssuedSession(
        session_id=row.id,
        token=token,
        csrf_token=csrf,
        user_id=user_id,
        company_id=company_id,
        membership_id=membership_id,
        created_at=now,
        idle_expires_at=row.idle_expires_at,
        absolute_expires_at=absolute,
        auth_method=method.value,
        stage=stage.value,
    )


def touch(row: AuthSession, now: datetime) -> bool:
    """Extend the idle expiry (at most once per minute). Returns True when the row changed."""
    if now - row.last_seen_at < TOUCH_INTERVAL:
        return False
    row.last_seen_at = now
    row.idle_expires_at = min(now + IDLE_LIFETIME, row.absolute_expires_at)
    return True


def revoke(session: Session, session_id: uuid.UUID, *, now: datetime, reason: str) -> bool:
    result = session.execute(
        update(AuthSession)
        .where(AuthSession.id == session_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=now, revoked_reason=reason[:40])
    )
    return bool(result.rowcount)  # type: ignore[attr-defined]


def revoke_all(
    session: Session,
    *,
    now: datetime,
    reason: str,
    user_id: uuid.UUID | None = None,
    membership_id: uuid.UUID | None = None,
    keep: uuid.UUID | None = None,
) -> int:
    """Revoke every open session of a user (all companies) or of one membership, except ``keep``."""
    if user_id is None and membership_id is None:
        raise ValueError("revoke_all needs a user or a membership")
    stmt = update(AuthSession).where(AuthSession.revoked_at.is_(None))
    if user_id is not None:
        stmt = stmt.where(AuthSession.user_id == user_id)
    if membership_id is not None:
        stmt = stmt.where(AuthSession.membership_id == membership_id)
    if keep is not None:
        stmt = stmt.where(AuthSession.id != keep)
    result = session.execute(stmt.values(revoked_at=now, revoked_reason=reason[:40]))
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


def rotate_csrf(session: Session, session_id: uuid.UUID) -> str:
    """Issue a fresh CSRF secret for a live session (the previous value stops working)."""
    csrf = new_token()
    session.execute(update(AuthSession).where(AuthSession.id == session_id).values(csrf_hash=sha256(csrf)))
    return csrf
