"""MFA flows: the sign-in code step, step-up re-authentication, self-service enrolment and the admin reset.

- ``verify_sign_in_code``: a ``mfa_pending`` session (password already checked) becomes an active, MFA-verified
  session after a TOTP or recovery code; the token rotates. Five wrong codes revoke the pending session.
- ``reauth``: refreshes ``recent_auth_at`` with the password or a code; a code also marks the session MFA-verified
  (how a demo-link session or a password-only session reaches MFA-flagged actions).
- Enrolment: ``enroll`` (seed + QR, pending until confirmed) → ``confirm`` (first code; ten recovery codes shown
  once; an enrolment-required session becomes active). Disabling is refused while the member's access requires
  MFA. Recovery codes can be regenerated with a current code.
- ``admin_reset``: an administrator (``identity.mfa.manage``, MFA + recent auth) removes another member's
  authenticator and ends their sessions; their next sign-in asks them to enrol again when required.

Every flow writes an ``auth_attempt`` row where a code is checked and an audit entry; credential changes emit
``identity.user.credentials_changed``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.core.db.engine import session_factory
from app.core.errors import Conflict, Forbidden, NotFound, Unauthenticated, ValidationFailed
from app.platform.authz.context import ActorContext
from app.platform.authz.permissions import Scope
from app.platform.identity import mfa, passwords, ratelimit, sessions
from app.platform.identity.auth_models import (
    AttemptKind,
    AttemptOutcome,
    AuthMethod,
    AuthSession,
    SessionStage,
)
from app.platform.identity.credential_models import MfaFactor
from app.platform.identity.errors import InvalidCode, SessionExpired, TooManyAttempts
from app.platform.identity.models import AppUser, Membership
from app.platform.identity.schemas import (
    MfaConfirmed,
    MfaEnrollment,
    MfaStatus,
    ReauthResult,
    RecoveryCodes,
)
from app.platform.identity.sessions import ClientInfo
from app.platform.service import command, query
from app.platform.uow import UnitOfWork

MFA_MANAGE = "identity.mfa.manage"
REAUTH_LIMIT = ratelimit.EMAIL_LIMIT


def _attempt(uow: UnitOfWork, kind: AttemptKind, outcome: AttemptOutcome, client: ClientInfo, **ids: object) -> None:
    from app.platform.identity.service import _attempt as record

    record(uow, kind=kind, outcome=outcome, client=client, **ids)  # type: ignore[arg-type]


def _bare_actor(row: AuthSession) -> ActorContext:
    from app.platform.identity.service import _member_actor

    assert row.company_id is not None  # noqa: S101 - sessions always carry a company
    return _member_actor(row.company_id, row.user_id, row.membership_id).with_(session_id=row.id)


def _pending_row(token: str | None) -> AuthSession:
    """The open ``mfa_pending`` session presented by the browser (detached), else 401."""
    with session_factory()() as s, s.begin():
        row = sessions.find_by_token(s, token)
        if row is None or row.company_id is None:
            raise SessionExpired()
        from app.core.clock import get_clock

        if not sessions.is_open(row, get_clock(row.company_id).now()) or row.stage != SessionStage.MFA_PENDING.value:
            raise SessionExpired()
        s.expunge(row)
        return row


# ---- sign-in code step ------------------------------------------------------------------------------------
def verify_sign_in_code(code: str, client: ClientInfo):  # type: ignore[no-untyped-def]  # -> service.SignedIn
    from app.platform.identity.service import SignedIn, _preferences, _session_info

    pending = _pending_row(client.session_token)
    session_id, company_id, user_id = pending.id, pending.company_id, pending.user_id
    assert company_id is not None  # noqa: S101 - checked by _pending_row
    failed = False
    revoked = False
    with UnitOfWork(_bare_actor(pending)) as uow:
        row = uow.session.get(AuthSession, session_id, with_for_update=True)
        if row is None or row.revoked_at is not None or row.stage != SessionStage.MFA_PENDING.value:
            raise SessionExpired()
        now = uow.now()
        factor = mfa.confirmed_factor(uow.session, user_id, for_update=True)
        method = mfa.verify_any(uow.session, factor, code, now) if factor is not None else None
        if method is None:
            row.mfa_attempts = row.mfa_attempts + 1
            failed = True
            if row.mfa_attempts >= mfa.MAX_PENDING_ATTEMPTS:
                sessions.revoke(uow.session, row.id, now=now, reason="mfa_attempts")
                revoked = True
            _attempt(uow, AttemptKind.MFA, AttemptOutcome.INVALID_CODE, client, user_id=user_id, company_id=company_id, session_id=row.id)
            uow.audit("auth.mfa.failed", resource_type="identity.user", resource_id=user_id, outcome="failed", details={"revoked": revoked})
        else:
            assert row.membership_id is not None  # noqa: S101
            issued = sessions.create_session(
                uow.session,
                user_id=user_id,
                company_id=company_id,
                membership_id=row.membership_id,
                method=AuthMethod(row.auth_method),
                client=client,
                now=now,
                mfa_verified=True,
                recent_auth=True,
            )
            _attempt(uow, AttemptKind.MFA, AttemptOutcome.SUCCESS, client, user_id=user_id, company_id=company_id, session_id=issued.session_id)
            uow.audit("auth.mfa.verified", resource_type="identity.user", resource_id=user_id, details={"method": method})
            return SignedIn(issued, _session_info(uow, issued), _preferences(uow, user_id))
    if revoked:
        raise SessionExpired()
    assert failed  # noqa: S101
    raise InvalidCode()


# ---- step-up re-authentication ------------------------------------------------------------------------------
def reauth(actor: ActorContext, *, password: str | None, code: str | None, client: ClientInfo) -> ReauthResult:
    """Confirm identity again: the password refreshes recent authentication; a code also verifies MFA."""
    if actor.session_id is None or actor.user_id is None:
        raise Unauthenticated()
    if (password is None) == (code is None):
        raise ValidationFailed(
            "Give your password or a code from your authenticator.",
            errors=[{"loc": ["body"], "msg": "password or code", "code": "one_of"}],
        )
    with UnitOfWork(actor) as uow:
        verdict = ratelimit.hit(uow.session, f"reauth:user:{actor.user_id.hex}", limit=REAUTH_LIMIT, now=uow.now())
        user = uow.session.get(AppUser, actor.user_id)
        stored_hash = user.password_hash if user else None
    if not verdict.allowed:
        raise TooManyAttempts("rate_limited", verdict.retry_after_seconds)
    ok_password = password is not None and passwords.verify_password(stored_hash, password)
    with UnitOfWork(actor) as uow:
        now = uow.now()
        row = uow.session.get(AuthSession, actor.session_id, with_for_update=True)
        if row is None or row.revoked_at is not None:
            raise SessionExpired()
        method: str | None = "password" if ok_password else None
        if code is not None:
            factor = mfa.confirmed_factor(uow.session, actor.user_id, for_update=True)
            method = mfa.verify_any(uow.session, factor, code, now) if factor is not None else None
        outcome = AttemptOutcome.SUCCESS if method else (AttemptOutcome.INVALID_CODE if code else AttemptOutcome.INVALID_CREDENTIALS)
        _attempt(uow, AttemptKind.REAUTH, outcome, client, user_id=actor.user_id, company_id=actor.company_id, session_id=row.id)
        if method is None:
            uow.audit("auth.reauth.failed", resource_type="identity.user", resource_id=actor.user_id, outcome="failed")
        else:
            row.recent_auth_at = now
            if method != "password":
                row.mfa_verified_at = now
            uow.audit("auth.reauth.succeeded", resource_type="identity.user", resource_id=actor.user_id, details={"method": method})
            return ReauthResult(
                recent_auth_at=now,
                auth_strength="mfa" if row.mfa_verified_at is not None else ("demo_link" if row.auth_method == "demo_link" else "password"),
            )
    if code is not None:
        raise InvalidCode()
    raise ValidationFailed(
        "That password is not correct.",
        errors=[{"loc": ["body", "password"], "msg": "That password is not correct.", "code": "invalid_password"}],
    )


# ---- self-service enrolment ---------------------------------------------------------------------------------
def _self(uow: UnitOfWork) -> tuple[AppUser, Membership]:
    actor = uow.actor
    if actor.user_id is None or actor.membership_id is None:
        raise Unauthenticated()
    user = uow.session.get(AppUser, actor.user_id)
    membership = uow.session.get(Membership, actor.membership_id)
    if user is None or membership is None:
        raise Unauthenticated()
    return user, membership


@query()
def status(uow: UnitOfWork) -> MfaStatus:
    user, membership = _self(uow)
    factor = mfa.active_factor(uow.session, user.id)
    confirmed = factor is not None and factor.confirmed_at is not None
    return MfaStatus(
        enrolled=confirmed,
        pending=factor is not None and not confirmed,
        confirmed_at=factor.confirmed_at if confirmed and factor else None,
        recovery_codes_remaining=mfa.remaining_recovery_codes(uow.session, factor) if confirmed and factor else 0,
        required=mfa.member_requires_mfa(uow, membership.id, user.id),
        session_verified=uow.actor.auth_strength == "mfa",
    )


@command()
def enroll(uow: UnitOfWork) -> MfaEnrollment:
    """Start (or restart) an enrolment: a fresh seed, shown once as a QR code and as text for manual entry."""
    user, _membership = _self(uow)
    now = uow.now()
    uow.advisory_xact_lock("identity.mfa", str(user.id))
    factor = mfa.active_factor(uow.session, user.id, for_update=True)
    if factor is not None and factor.confirmed_at is not None:
        raise Conflict("Two-step sign-in is already set up. Remove it first to use another device.", code="mfa_already_enrolled")
    if factor is not None:
        mfa.disable(uow.session, factor, now=now, by=user.id, reason="replaced_before_confirmation")
        uow.flush()
    secret = mfa.new_secret()
    sealed = mfa.seal_secret(user.id, secret)
    factor = MfaFactor(
        id=uuid.uuid7(), user_id=user.id, secret_ciphertext=sealed.blob, key_id=sealed.key_id, created_at=now
    )
    uow.add(factor)
    uow.flush()
    uri = mfa.provisioning_uri(secret, user.email or user.display_name)
    uow.audit("auth.mfa.enrolment_started", resource_type="identity.user", resource_id=user.id)
    return MfaEnrollment(factor_id=factor.id, secret=secret, otpauth_uri=uri, qr_svg=mfa.qr_svg(uri))


@dataclass(frozen=True)
class ConfirmedEnrolment:
    result: MfaConfirmed
    signed: object | None  # service.SignedIn when the session rotated


def confirm(actor: ActorContext, code: str, client: ClientInfo) -> ConfirmedEnrolment:
    """Confirm the pending factor with its first code; the session becomes MFA-verified (token rotated)."""
    from app.platform.identity.service import SignedIn, _preferences, _session_info

    with UnitOfWork(actor) as uow:
        user, membership = _self(uow)
        now = uow.now()
        uow.advisory_xact_lock("identity.mfa", str(user.id))
        factor = mfa.active_factor(uow.session, user.id, for_update=True)
        if factor is None or factor.confirmed_at is not None:
            raise Conflict("Start the set-up again: there is no authenticator waiting for confirmation.", code="mfa_not_pending")
        if not mfa.verify_totp(factor, code, now):
            _attempt(uow, AttemptKind.MFA, AttemptOutcome.INVALID_CODE, client, user_id=user.id, company_id=actor.company_id, session_id=actor.session_id)
            ok = False
        else:
            ok = True
            factor.confirmed_at = now
            codes = mfa.new_recovery_codes(uow.session, factor, now)
            assert actor.session_id is not None and actor.company_id is not None  # noqa: S101
            issued = sessions.create_session(
                uow.session,
                user_id=user.id,
                company_id=actor.company_id,
                membership_id=membership.id,
                method=AuthMethod(_auth_method(uow, actor.session_id)),
                client=client,
                now=now,
                mfa_verified=True,
                recent_auth=True,
            )
            _attempt(uow, AttemptKind.MFA, AttemptOutcome.SUCCESS, client, user_id=user.id, company_id=actor.company_id, session_id=issued.session_id)
            uow.emit("identity.user.credentials_changed", aggregate_id=user.id, payload={"user_id": str(user.id), "kind": "mfa_enrolled"})
            uow.audit("auth.mfa.enrolled", resource_type="identity.user", resource_id=user.id)
            return ConfirmedEnrolment(
                MfaConfirmed(recovery_codes=codes, confirmed_at=now),
                SignedIn(issued, _session_info(uow, issued), _preferences(uow, user.id)),
            )
    assert not ok  # noqa: S101
    raise InvalidCode()


def _auth_method(uow: UnitOfWork, session_id: uuid.UUID) -> str:
    row = uow.session.get(AuthSession, session_id)
    return row.auth_method if row is not None else AuthMethod.PASSWORD.value


@command()
def disable_own(uow: UnitOfWork, code: str) -> MfaStatus:
    """Remove your own authenticator with a current code; refused while your access requires MFA."""
    user, membership = _self(uow)
    now = uow.now()
    factor = mfa.confirmed_factor(uow.session, user.id, for_update=True)
    if factor is None:
        raise NotFound("Two-step sign-in is not set up.", code="not_found", resource_type="identity.mfa_factor")
    if mfa.member_requires_mfa(uow, membership.id, user.id):
        raise Conflict("Your role requires two-step sign-in, so it cannot be removed.", code="mfa_required_by_policy")
    if mfa.verify_any(uow.session, factor, code, now) is None:
        raise InvalidCode()
    mfa.disable(uow.session, factor, now=now, by=user.id, reason="self_service")
    uow.flush()
    uow.emit("identity.user.credentials_changed", aggregate_id=user.id, payload={"user_id": str(user.id), "kind": "mfa_disabled"})
    uow.audit("auth.mfa.disabled", resource_type="identity.user", resource_id=user.id)
    return status(uow)


@command()
def regenerate_codes(uow: UnitOfWork, code: str) -> RecoveryCodes:
    """New recovery codes (the old ones stop working) after a current TOTP code."""
    user, _membership = _self(uow)
    now = uow.now()
    factor = mfa.confirmed_factor(uow.session, user.id, for_update=True)
    if factor is None:
        raise NotFound("Two-step sign-in is not set up.", code="not_found", resource_type="identity.mfa_factor")
    if not mfa.verify_totp(factor, code, now):
        raise InvalidCode()
    codes = mfa.new_recovery_codes(uow.session, factor, now)
    uow.audit("auth.mfa.recovery_codes_regenerated", resource_type="identity.user", resource_id=user.id)
    return RecoveryCodes(recovery_codes=codes)


# ---- administrator reset --------------------------------------------------------------------------------------
@command(MFA_MANAGE, at_least=Scope.COMPANY)
def admin_reset(uow: UnitOfWork, user_id: uuid.UUID, reason: str) -> None:
    from app.platform.authz.stepup import require_step_up
    from app.platform.identity import provisioning

    require_step_up(uow, MFA_MANAGE)
    membership = provisioning.membership_for_user(uow, user_id)
    if membership is None:
        raise NotFound(code="not_found", resource_type="identity.membership")
    if user_id == uow.actor.user_id:
        raise Forbidden("Use your own security page to change your authenticator.", code="self_access_change")
    now = uow.now()
    factor = mfa.active_factor(uow.session, user_id, for_update=True)
    if factor is None:
        raise NotFound("This member has no authenticator set up.", code="not_found", resource_type="identity.mfa_factor")
    mfa.disable(uow.session, factor, now=now, by=uow.actor.user_id, reason="admin_reset")
    revoked = sessions.revoke_all(uow.session, user_id=user_id, now=now, reason="mfa_reset")
    uow.emit("identity.user.credentials_changed", aggregate_id=user_id, payload={"user_id": str(user_id), "kind": "mfa_reset"})
    uow.audit(
        "identity.mfa.reset",
        resource_type="identity.membership",
        resource_id=membership.id,
        reason=reason.strip()[:500] or None,
        details={"sessions_revoked": revoked},
    )


__all__ = [
    "ConfirmedEnrolment",
    "admin_reset",
    "confirm",
    "disable_own",
    "enroll",
    "reauth",
    "regenerate_codes",
    "status",
    "verify_sign_in_code",
]
