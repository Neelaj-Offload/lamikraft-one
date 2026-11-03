"""Invitations and password resets: single-use, expiring links whose tokens live only in URL fragments.

Invitations (``identity.user.manage``, MFA + recent auth): an administrator invites a person by email with roles and
branches. The person gets an ``invited`` membership (a new ``app_user`` unless the email already has one) and a
7-day link ``/invite#t=<company>.<secret>``. Resending replaces the token (the old link stops working); revoking
closes it. Accepting sets the password (or confirms the existing one), activates the user and the membership
(``identity.membership.activated``) and signs the person in; members whose access requires MFA must enrol next.

Password resets: self-service requests always answer 202 (no account enumeration) and create a 30-minute link only
for an active member with a password; administrators issue a 24-hour link (never a password). Completing a reset
sets the new password, revokes every session and every other open reset, keeps MFA, and emits
``identity.user.credentials_changed``.

Delivery: ``LK_EMAIL_MODE=demo`` writes ``.eml`` files to the demo outbox after commit; the administrator sees the
link once ("Email delivery: Demo, not sent"). Public endpoints are rate-limited per address.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select, update

from app.core.db.engine import session_factory
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.platform.authz.context import ActorContext
from app.platform.authz.permissions import Scope
from app.platform.authz.stepup import require_step_up
from app.platform.identity import mail, passwords, provisioning, ratelimit, sessions
from app.platform.identity.actors import tenant_scope
from app.platform.identity.auth_models import AttemptKind, AttemptOutcome, AuthMethod
from app.platform.identity.credential_models import Invitation, InvitationDelivery, PasswordReset, ResetKind
from app.platform.identity.errors import LinkInvalidOrUsed, PasswordPolicyViolation, TooManyAttempts
from app.platform.identity.models import AppUser, Membership
from app.platform.identity.schemas import (
    Delivery,
    InvitationCreate,
    InvitationIssued,
    InvitationPreview,
    InvitationView,
    PasswordResetIssued,
)
from app.platform.identity.sessions import ClientInfo
from app.platform.identity.tokens import keyed_hash, new_token, normalize_email, sha256
from app.platform.org.models import Company
from app.platform.service import command, query
from app.platform.uow import UnitOfWork

INVITATION_LIFETIME = timedelta(days=7)
SELF_RESET_LIFETIME = timedelta(minutes=30)
ADMIN_RESET_LIFETIME = timedelta(hours=24)
USER_MANAGE = "identity.user.manage"
DEMO_LABEL = "Email delivery: Demo, not sent"


# ---- shared helpers -----------------------------------------------------------------------------------------
def _attempt(uow: UnitOfWork, kind: AttemptKind, outcome: AttemptOutcome, client: ClientInfo, **ids: object) -> None:
    from app.platform.identity.service import _attempt as record

    record(uow, kind=kind, outcome=outcome, client=client, **ids)  # type: ignore[arg-type]


def _ip_limit(prefix: str, client: ClientInfo) -> None:
    from app.platform.identity.service import _ip_bucket

    with UnitOfWork(ActorContext.system(None, reason=f"identity.{prefix}")) as uow:
        verdict = ratelimit.hit(uow.session, _ip_bucket(prefix, client), limit=ratelimit.IP_LIMIT, now=uow.now())
    if not verdict.allowed:
        raise TooManyAttempts("rate_limited", verdict.retry_after_seconds)


def _deliver(uow: UnitOfWork, message: mail.Outgoing, token_link: str) -> Delivery:
    """Queue the message for after commit; in demo mode the link is also returned once to the caller."""
    mail.require_delivery()
    now = uow.now()
    name = mail.outbox_name(message, now)
    uow.after_commit(lambda: mail.write_demo(message, now=now, name=name))
    return Delivery(mode="demo_outbox", label=DEMO_LABEL, manual_link=token_link, outbox_file=name)


def _check_policy(password: str, *, email: str | None, company: Company | None) -> None:
    names = (company.company_key, company.display_name, company.legal_name) if company else ()
    violation = passwords.check_policy(password, email=email, company_names=names)
    if violation is not None:
        raise PasswordPolicyViolation(
            violation.message, errors=[{"loc": ["body", "password"], "msg": violation.message, "code": violation.code}]
        )


def _company_of_token(token: str) -> uuid.UUID | None:
    from app.platform.identity.service import _company_of_token as parse

    return parse(token)


# ---- invitations ----------------------------------------------------------------------------------------------
def _invitation_status(row: Invitation, now: datetime) -> str:
    if row.accepted_at is not None:
        return "accepted"
    if row.revoked_at is not None:
        return "revoked"
    if row.expires_at <= now:
        return "expired"
    return "open"


def invitation_view(uow: UnitOfWork, row: Invitation) -> InvitationView:
    name = (
        uow.session.scalar(select(AppUser.display_name).where(AppUser.id == row.invited_by)) if row.invited_by else None
    )
    return InvitationView(
        id=row.id,
        user_id=row.user_id,
        membership_id=row.membership_id,
        email=row.email_normalized,
        status=_invitation_status(row, uow.now()),  # type: ignore[arg-type]
        created_at=row.created_at,
        expires_at=row.expires_at,
        send_count=row.send_count,
        last_sent_at=row.last_sent_at,
        invited_by_name=name,
    )


def _invitation_message(uow: UnitOfWork, email: str, display_name: str, token: str) -> tuple[mail.Outgoing, str]:
    company = uow.session.get(Company, uow.actor.company_id)
    company_name = company.display_name if company else "Lamikraft One"
    url = mail.link("/invite", token)
    inviter = uow.actor.display_name or "An administrator"
    body = (
        f"Hello {display_name},\n\n{inviter} invited you to {company_name} on Lamikraft One.\n\n"
        f"Open this link within 7 days to choose your password and sign in:\n{url}\n\n"
        "If you were not expecting this invitation, ignore this message.\n"
    )
    return mail.Outgoing("invitation", email, f"Your invitation to {company_name}", body), url


def _issue_invitation_token(uow: UnitOfWork) -> str:
    return f"{uow.actor.company_id.hex}.{new_token()}"  # type: ignore[union-attr]


@command(USER_MANAGE, at_least=Scope.COMPANY)
def invite(uow: UnitOfWork, body: InvitationCreate) -> InvitationIssued:
    require_step_up(uow, USER_MANAGE)
    provisioning.lock_access(uow)
    email = body.email.strip()
    normalized = normalize_email(email)
    existing = uow.session.scalars(select(AppUser).where(AppUser.email_normalized == normalized)).first()
    if existing is not None:
        if existing.status in ("historical", "disabled"):
            raise Conflict("This email belongs to an account that cannot be invited.", code="user_not_invitable")
        if provisioning.membership_for_user(uow, existing.id) is not None:
            raise Conflict(
                "This person is already a member of the company (open their page to resend or reactivate).",
                code="already_member",
                user_id=str(existing.id),
            )
    manager_membership_id = None
    if body.manager_user_id is not None:
        manager = provisioning.membership_for_user(uow, body.manager_user_id)
        if manager is None:
            raise ValidationFailed(errors=[{"loc": ["body", "manager_user_id"], "msg": "Unknown member", "code": "unknown_member"}])
        manager_membership_id = manager.id
    user_id, _created = provisioning.ensure_user(
        uow, email=email, display_name=body.display_name.strip(), full_name=body.full_name, status="invited"
    )
    default_branch = body.default_branch_id or (body.branch_ids[0] if body.branch_ids else None)
    membership_id, _ = provisioning.provision_membership(
        uow,
        user_id=user_id,
        status="invited",
        role_keys=body.role_keys,
        branch_ids=body.branch_ids,
        default_branch_id=default_branch,
        manager_membership_id=manager_membership_id,
        job_title=body.job_title,
        origin="invitation",
    )
    now = uow.now()
    token = _issue_invitation_token(uow)
    row = Invitation(
        id=uuid.uuid7(),
        company_id=uow.actor.company_id,
        user_id=user_id,
        membership_id=membership_id,
        email_normalized=normalized,
        token_hash=sha256(token),
        invited_by=uow.actor.user_id,
        delivery=InvitationDelivery.DEMO_OUTBOX.value if mail.is_demo() else InvitationDelivery.EMAIL.value,
        created_at=now,
        expires_at=now + INVITATION_LIFETIME,
        send_count=1,
        last_sent_at=now,
    )
    uow.add(row)
    uow.flush()
    message, url = _invitation_message(uow, email, body.display_name, token)
    delivery = _deliver(uow, message, url)
    uow.emit(
        "identity.invitation.sent",
        aggregate_id=row.id,
        payload={"invitation_id": str(row.id), "membership_id": str(membership_id), "delivery": row.delivery},
    )
    uow.audit(
        "identity.invitation.sent",
        resource_type="identity.membership",
        resource_id=membership_id,
        resource_label=email,
        details={"roles": sorted(set(body.role_keys)), "delivery": row.delivery, "expires_at": row.expires_at.isoformat()},
    )
    return InvitationIssued(invitation=invitation_view(uow, row), delivery=delivery)


def _invitation(uow: UnitOfWork, invitation_id: uuid.UUID, *, for_update: bool = True) -> Invitation:
    stmt = select(Invitation).where(Invitation.id == invitation_id, Invitation.company_id == uow.actor.company_id)
    if for_update:
        stmt = stmt.with_for_update()
    row = uow.session.scalars(stmt).first()
    if row is None:
        raise NotFound(code="not_found", resource_type="identity.invitation")
    return row


@command(USER_MANAGE, at_least=Scope.COMPANY)
def resend_invitation(uow: UnitOfWork, invitation_id: uuid.UUID) -> InvitationIssued:
    require_step_up(uow, USER_MANAGE)
    row = _invitation(uow, invitation_id)
    if row.accepted_at is not None or row.revoked_at is not None:
        raise Conflict("This invitation is closed; invite the person again.", code="invitation_closed")
    now = uow.now()
    token = _issue_invitation_token(uow)
    row.token_hash = sha256(token)
    row.expires_at = now + INVITATION_LIFETIME
    row.send_count = row.send_count + 1
    row.last_sent_at = now
    uow.flush()
    user = uow.session.get(AppUser, row.user_id)
    message, url = _invitation_message(uow, row.email_normalized, user.display_name if user else row.email_normalized, token)
    delivery = _deliver(uow, message, url)
    uow.emit(
        "identity.invitation.sent",
        aggregate_id=row.id,
        payload={"invitation_id": str(row.id), "membership_id": str(row.membership_id), "delivery": row.delivery},
    )
    uow.audit("identity.invitation.resent", resource_type="identity.membership", resource_id=row.membership_id, details={"send_count": row.send_count})
    return InvitationIssued(invitation=invitation_view(uow, row), delivery=delivery)


@command(USER_MANAGE, at_least=Scope.COMPANY)
def revoke_invitation(uow: UnitOfWork, invitation_id: uuid.UUID) -> InvitationView:
    require_step_up(uow, USER_MANAGE)
    row = _invitation(uow, invitation_id)
    if row.accepted_at is not None:
        raise Conflict("This invitation was already accepted.", code="invitation_closed")
    if row.revoked_at is None:
        row.revoked_at = uow.now()
        row.revoked_by = uow.actor.user_id
        row.token_hash = None
        uow.flush()
        uow.emit(
            "identity.invitation.revoked",
            aggregate_id=row.id,
            payload={"invitation_id": str(row.id), "membership_id": str(row.membership_id), "delivery": row.delivery},
        )
        uow.audit("identity.invitation.revoked", resource_type="identity.membership", resource_id=row.membership_id)
    return invitation_view(uow, row)


@query()
def invitations_of(uow: UnitOfWork, membership_id: uuid.UUID) -> list[InvitationView]:
    rows = uow.session.scalars(
        select(Invitation)
        .where(Invitation.company_id == uow.actor.company_id, Invitation.membership_id == membership_id)
        .order_by(Invitation.created_at.desc())
    )
    return [invitation_view(uow, r) for r in rows]


@dataclass(frozen=True)
class _OpenInvitation:
    company_id: uuid.UUID
    invitation_id: uuid.UUID
    user_id: uuid.UUID
    membership_id: uuid.UUID
    email: str
    display_name: str
    company_name: str
    expires_at: datetime
    password_hash: str | None
    company: Company


def _open_invitation(token: str) -> _OpenInvitation:
    company_id = _company_of_token(token)
    if company_id is None:
        raise LinkInvalidOrUsed()
    with session_factory()() as s, s.begin(), tenant_scope(s, company_id):
        company = s.get(Company, company_id)
        row = s.scalars(select(Invitation).where(Invitation.token_hash == sha256(token))).first()
        from app.core.clock import get_clock

        now = get_clock(company_id).now()
        if company is None or company.status != "active" or row is None or _invitation_status(row, now) != "open":
            raise LinkInvalidOrUsed()
        user = s.get(AppUser, row.user_id)
        membership = s.get(Membership, row.membership_id)
        if user is None or membership is None or membership.status != "invited":
            raise LinkInvalidOrUsed()
        s.expunge(company)
        return _OpenInvitation(
            company_id, row.id, user.id, membership.id, user.email or row.email_normalized, user.display_name,
            company.display_name, row.expires_at, user.password_hash, company,
        )


def preview_invitation(token: str, client: ClientInfo) -> InvitationPreview:
    _ip_limit("invite", client)
    inv = _open_invitation(token)
    return InvitationPreview(
        email=inv.email,
        display_name=inv.display_name,
        company_name=inv.company_name,
        expires_at=inv.expires_at,
        has_password=inv.password_hash is not None,
    )


def accept_invitation(token: str, password: str, display_name: str | None, client: ClientInfo):  # type: ignore[no-untyped-def]
    """Accept: choose a password (or confirm the existing one), activate, sign in. Returns ``service.SignedIn``."""
    from app.platform.identity.service import SignedIn, _preferences, _session_info, sign_in_stage

    _ip_limit("invite", client)
    inv = _open_invitation(token)
    if inv.password_hash is not None:
        if not passwords.verify_password(inv.password_hash, password):
            raise ValidationFailed(
                "Enter the password you already use for Lamikraft One.",
                errors=[{"loc": ["body", "password"], "msg": "not your current password", "code": "invalid_password"}],
            )
        new_hash = None
    else:
        _check_policy(password, email=inv.email, company=inv.company)
        new_hash = passwords.hash_password(password)
    actor = ActorContext.system(inv.company_id, reason="identity.invitation.accept").with_(
        user_id=inv.user_id, membership_id=inv.membership_id, actor_type="user", display_name=inv.display_name, channel="web"
    )
    with UnitOfWork(actor) as uow:
        row = uow.session.scalars(
            select(Invitation).where(Invitation.id == inv.invitation_id, Invitation.token_hash == sha256(token)).with_for_update()
        ).first()
        now = uow.now()
        if row is None or _invitation_status(row, now) != "open":
            raise LinkInvalidOrUsed()
        user = uow.session.get(AppUser, inv.user_id, with_for_update=True)
        assert user is not None  # noqa: S101
        if new_hash is not None:
            if user.password_hash is not None:  # set concurrently through another invitation
                raise LinkInvalidOrUsed()
            user.password_hash = new_hash
            user.password_changed_at = now
        if display_name:
            user.display_name = display_name.strip()
        if user.status == "invited":
            user.status = "active"
        row.accepted_at = now
        row.token_hash = None
        uow.flush()
        provisioning.activate_membership(uow, inv.membership_id, origin="invitation")
        user.last_login_at = now
        issued = sessions.create_session(
            uow.session,
            user_id=user.id,
            company_id=inv.company_id,
            membership_id=inv.membership_id,
            method=AuthMethod.PASSWORD,
            client=client,
            now=now,
            stage=sign_in_stage(uow, user.id, inv.membership_id),
        )
        _attempt(uow, AttemptKind.INVITE_ACCEPT, AttemptOutcome.SUCCESS, client, user_id=user.id, company_id=inv.company_id, session_id=issued.session_id)
        uow.emit(
            "identity.invitation.accepted",
            aggregate_id=row.id,
            payload={"invitation_id": str(row.id), "membership_id": str(inv.membership_id), "delivery": row.delivery},
        )
        uow.audit("identity.invitation.accepted", resource_type="identity.membership", resource_id=inv.membership_id, ip=client.audit_ip)
        return SignedIn(issued, _session_info(uow, issued), _preferences(uow, user.id))


# ---- password resets ------------------------------------------------------------------------------------------
def _reset_message(email: str, display_name: str, token: str, lifetime: timedelta, *, admin: bool) -> tuple[mail.Outgoing, str]:
    url = mail.link("/reset-password", token)
    minutes = int(lifetime.total_seconds() // 60)
    when = f"{minutes} minutes" if minutes < 120 else f"{minutes // 60} hours"
    who = "An administrator asked for" if admin else "Someone (hopefully you) asked for"
    body = (
        f"Hello {display_name},\n\n{who} a new Lamikraft One password for this account.\n\n"
        f"Open this link within {when} to choose a new password:\n{url}\n\n"
        "If you did not ask for this, ignore this message: your password stays as it is.\n"
    )
    return mail.Outgoing("password_reset", email, "Choose a new Lamikraft One password", body), url


def _home_company(user_id: uuid.UUID) -> uuid.UUID | None:
    from app.platform.identity.service import _memberships_of

    target = next((m for m in _memberships_of(user_id) if m.status == "active" and not m.is_demo), None)
    return target.company_id if target else None


def request_reset(email: str, client: ClientInfo) -> None:
    """Always accepted (202) whether or not the email belongs to someone; only the per-address limit shows."""
    _ip_limit("reset", client)
    normalized = normalize_email(email)[:254]
    email_hmac = keyed_hash("email", normalized)
    with UnitOfWork(ActorContext.system(None, reason="identity.reset.request")) as uow:
        now = uow.now()
        verdict = ratelimit.hit(uow.session, f"reset:email:{email_hmac.hex()}", limit=5, now=now)
        user = uow.session.scalars(select(AppUser).where(AppUser.email_normalized == normalized)).first()
        _attempt(uow, AttemptKind.RESET_REQUEST, AttemptOutcome.SUCCESS if verdict.allowed else AttemptOutcome.RATE_LIMITED, client, email_hmac=email_hmac, user_id=user.id if user else None)
        eligible = verdict.allowed and user is not None and user.status == "active" and user.password_hash is not None
        user_id = user.id if user else None
        display = user.display_name if user else ""
        user_email = user.email if user else None
    if not eligible or user_id is None or user_email is None or not mail.is_demo():
        return
    company_id = _home_company(user_id)
    if company_id is None:
        return
    token = new_token()
    actor = ActorContext.system(company_id, reason="identity.reset.request").with_(user_id=user_id, actor_type="user", channel="web")
    with UnitOfWork(actor) as uow:
        now = uow.now()
        uow.add(
            PasswordReset(
                id=uuid.uuid7(), user_id=user_id, company_id=company_id, token_hash=sha256(token), kind=ResetKind.SELF_SERVICE.value,
                created_at=now, expires_at=now + SELF_RESET_LIFETIME,
            )
        )
        message, url = _reset_message(user_email, display, token, SELF_RESET_LIFETIME, admin=False)
        _deliver(uow, message, url)
        uow.audit("auth.password_reset.requested", resource_type="identity.user", resource_id=user_id, ip=client.audit_ip)


@command(USER_MANAGE, at_least=Scope.COMPANY)
def issue_reset(uow: UnitOfWork, user_id: uuid.UUID) -> PasswordResetIssued:
    """An administrator-issued one-time reset link (24 h). Never a password."""
    require_step_up(uow, USER_MANAGE)
    membership = provisioning.membership_for_user(uow, user_id)
    if membership is None:
        raise NotFound(code="not_found", resource_type="identity.membership")
    if user_id == uow.actor.user_id:
        raise Forbidden("Change your own password on your security page.", code="self_access_change")
    company = uow.session.get(Company, uow.actor.company_id)
    if company is not None and company.is_demo:
        raise Conflict("Demo members sign in with one-time demo links and have no password.", code="not_available_in_demo")
    user = uow.session.get(AppUser, user_id)
    if user is None or membership.status != "active" or user.status != "active" or not user.email:
        raise Conflict("Only active members can get a password reset link.", code="membership_inactive")
    now = uow.now()
    token = new_token()
    uow.add(
        PasswordReset(
            id=uuid.uuid7(), user_id=user_id, company_id=uow.actor.company_id, token_hash=sha256(token),
            kind=ResetKind.ADMIN_ISSUED.value, requested_by=uow.actor.user_id, created_at=now, expires_at=now + ADMIN_RESET_LIFETIME,
        )
    )
    message, url = _reset_message(user.email, user.display_name, token, ADMIN_RESET_LIFETIME, admin=True)
    delivery = _deliver(uow, message, url)
    uow.audit("identity.password_reset.issued", resource_type="identity.membership", resource_id=membership.id)
    return PasswordResetIssued(user_id=user_id, expires_at=now + ADMIN_RESET_LIFETIME, delivery=delivery)


def complete_reset(token: str, password: str, client: ClientInfo) -> None:
    _ip_limit("reset", client)
    with session_factory()() as s, s.begin():
        row = s.scalars(select(PasswordReset).where(PasswordReset.token_hash == sha256(token))).first()
        from app.core.clock import get_clock

        now = get_clock(row.company_id if row else None).now()
        if row is None or row.used_at is not None or row.revoked_at is not None or row.expires_at <= now:
            raise LinkInvalidOrUsed()
        user = s.get(AppUser, row.user_id)
        if user is None or user.status != "active":
            raise LinkInvalidOrUsed()
        reset_id, user_id, company_id, email = row.id, user.id, row.company_id, user.email
        company = s.get(Company, company_id) if company_id else None
        if company is not None:
            s.expunge(company)
    _check_policy(password, email=email, company=company)
    new_hash = passwords.hash_password(password)
    actor = ActorContext.system(company_id, reason="identity.reset.complete").with_(user_id=user_id, actor_type="user", channel="web")
    with UnitOfWork(actor) as uow:
        now = uow.now()
        row = uow.session.get(PasswordReset, reset_id, with_for_update=True)
        if row is None or row.used_at is not None or row.revoked_at is not None or row.expires_at <= now:
            raise LinkInvalidOrUsed()
        user = uow.session.get(AppUser, user_id, with_for_update=True)
        assert user is not None  # noqa: S101
        user.password_hash = new_hash
        user.password_changed_at = now
        user.failed_login_count = 0
        user.locked_until = None
        row.used_at = now
        uow.session.execute(
            update(PasswordReset)
            .where(PasswordReset.user_id == user_id, PasswordReset.id != reset_id, PasswordReset.used_at.is_(None), PasswordReset.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        revoked = sessions.revoke_all(uow.session, user_id=user_id, now=now, reason="password_reset")
        _attempt(uow, AttemptKind.RESET_COMPLETE, AttemptOutcome.SUCCESS, client, user_id=user_id, company_id=company_id)
        if company_id is not None:
            uow.emit("identity.user.credentials_changed", aggregate_id=user_id, payload={"user_id": str(user_id), "kind": "password_reset"})
            uow.audit("auth.password_reset.completed", resource_type="identity.user", resource_id=user_id, details={"sessions_revoked": revoked}, ip=client.audit_ip)

