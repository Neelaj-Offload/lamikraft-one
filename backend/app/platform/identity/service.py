"""Identity services: sign-in and sign-out, demo links, test sessions, the first admin, profile and preferences.

Sign-in spans several short transactions on purpose: rate-limit counters and failure state are committed
even when the request then fails, and argon2 verification runs outside any transaction. Every failure
returns the same generic 401 ``invalid_credentials``; throttling returns 429 ``rate_limited`` or
``account_locked`` with ``Retry-After``. Attempts are written to ``auth_attempt`` and, when the person has a
membership, to the company's audit log.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, or_, select, update
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.core.db.engine import session_factory
from app.core.errors import Conflict, Forbidden, NotFound, Unauthenticated, ValidationFailed, VersionConflict
from app.platform.authz.context import ActorContext
from app.platform.authz.permissions import Scope
from app.platform.identity import passwords, ratelimit, sessions
from app.platform.identity.actors import resolve_time_zone, tenant_scope
from app.platform.identity.auth_models import (
    AttemptKind,
    AttemptOutcome,
    AuthAttempt,
    AuthMethod,
    AuthSession,
    DemoSignInToken,
    DemoTokenSource,
    SessionStage,
)
from app.platform.identity.errors import (
    InvalidCredentials,
    LinkInvalidOrUsed,
    PasswordPolicyViolation,
    TooManyAttempts,
)
from app.platform.identity.models import (
    AppUser,
    Membership,
    MembershipBranch,
    MembershipRole,
    Role,
    UserPermissionOverride,
    UserPreference,
)
from app.platform.identity.preferences import Preferences, PreferencesPatch, apply_patch, read
from app.platform.identity.provisioning import CompanySpec
from app.platform.identity.schemas import (
    BranchRef,
    CompanyRef,
    ManagerRef,
    MembershipSummary,
    MembershipView,
    MeRead,
    PermissionGrant,
    PermissionOverrideList,
    PermissionOverridePut,
    PermissionOverrideView,
    PreferencesUpdated,
    ProfileView,
    RoleRef,
    SessionInfo,
    SessionProfile,
    SessionView,
    TeamRef,
    UserRef,
)
from app.platform.identity.sessions import ClientInfo, IssuedSession
from app.platform.identity.tokens import keyed_hash, new_token, normalize_email, sha256
from app.platform.org.models import Branch, Company
from app.platform.org.teams import Team, TeamMember
from app.platform.service import command, query
from app.platform.uow import UnitOfWork

DEMO_LINK_LIFETIME = timedelta(minutes=15)
_NO_USER = uuid.UUID(int=0)


def _member_actor(company_id: uuid.UUID, user_id: uuid.UUID, membership_id: uuid.UUID | None, name: str = "") -> ActorContext:
    """A bare user context for writing that user's own authentication records (no permissions)."""
    return ActorContext(
        actor_type="user",
        company_id=company_id,
        user_id=user_id,
        membership_id=membership_id,
        display_name=name,
        channel="web",
    )


def _attempt(
    uow: UnitOfWork,
    *,
    kind: AttemptKind,
    outcome: AttemptOutcome,
    client: ClientInfo,
    email_hmac: bytes | None = None,
    user_id: uuid.UUID | None = None,
    company_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
) -> None:
    uow.add(
        AuthAttempt(
            id=uuid.uuid7(),
            occurred_at=uow.now(),
            kind=kind.value,
            outcome=outcome.value,
            email_hmac=email_hmac,
            ip_hash=client.ip_hash,
            user_id=user_id,
            company_id=company_id,
            session_id=session_id,
        )
    )


def _ip_bucket(prefix: str, client: ClientInfo) -> str:
    return f"{prefix}:ip:{client.ip_hash.hex() if client.ip_hash else 'unknown'}"


# ---- membership lookup across tenants ------------------------------------------------------------
@dataclass(frozen=True)
class MemberRef:
    company_id: uuid.UUID
    membership_id: uuid.UUID
    status: str
    is_demo: bool = False


def _memberships_of(user_id: uuid.UUID) -> list[MemberRef]:
    """The user's memberships in active companies, the most recently used company first.

    ``membership`` is tenant-scoped and ``lk_app`` has no BYPASSRLS, so each company is bound in turn
    (``company`` is RLS-exempt). The cost grows with the number of tenants of one deployment (one company plus
    the demo company in practice).
    """
    out: list[MemberRef] = []
    with session_factory()() as s, s.begin():
        rows = s.execute(
            select(Company.id, Company.is_demo).where(Company.status == "active").order_by(Company.created_at, Company.id)
        ).all()
        demo = {company_id: bool(is_demo) for company_id, is_demo in rows}
        companies = [company_id for company_id, _ in rows]
        last = s.scalar(
            select(AuthSession.company_id)
            .where(AuthSession.user_id == user_id, AuthSession.company_id.is_not(None))
            .order_by(AuthSession.created_at.desc())
            .limit(1)
        )
        if last in companies:
            companies.remove(last)
            companies.insert(0, last)
        for company_id in companies:
            with tenant_scope(s, company_id):
                row = s.execute(
                    select(Membership.id, Membership.status).where(
                        Membership.company_id == company_id, Membership.user_id == user_id
                    )
                ).first()
            if row is not None:
                out.append(MemberRef(company_id, row[0], row[1], demo[company_id]))
    return out


# ---- sign-in ---------------------------------------------------------------------------------------
@dataclass(frozen=True)
class SignedIn:
    issued: IssuedSession
    info: SessionInfo
    preferences: Preferences


def login(email: str, password: str, client: ClientInfo) -> SignedIn:
    email_norm = normalize_email(email)[:254]
    email_hmac = keyed_hash("email", email_norm)
    email_key = email_hmac.hex()

    with UnitOfWork(ActorContext.system(None, reason="auth.login")) as uow:
        now = uow.now()
        verdicts = [
            ratelimit.hit(uow.session, _ip_bucket("login", client), limit=ratelimit.IP_LIMIT, now=now),
            ratelimit.hit(uow.session, f"login:email:{email_key}", limit=ratelimit.EMAIL_LIMIT, now=now),
            ratelimit.lock_state(uow.session, email_key, now=now),
        ]
        blocked = next((v for v in verdicts if not v.allowed), None)
        if blocked is not None:
            _attempt(uow, kind=AttemptKind.LOGIN, outcome=AttemptOutcome(blocked.code), client=client, email_hmac=email_hmac)
    if blocked is not None:
        raise TooManyAttempts(blocked.code or "rate_limited", blocked.retry_after_seconds)

    with session_factory()() as s:
        user = s.scalars(select(AppUser).where(AppUser.email_normalized == email_norm)).first()
        user_id = user.id if user else None
        stored_hash = user.password_hash if user else None
        user_active = bool(user and user.status == "active")
        display_name = user.display_name if user else ""
    ok = passwords.verify_password(stored_hash, password)
    # the same lookups run for unknown emails so the response time does not reveal whether an account exists
    memberships = _memberships_of(user_id or _NO_USER)
    # demo users sign in only through one-time links (api-conventions §7): a demo membership is never a target
    target = next((m for m in memberships if m.status == "active" and not m.is_demo), None) if ok and user_active else None
    rehash = passwords.hash_password(password) if target and stored_hash and passwords.needs_rehash(stored_hash) else None

    if target is None or user_id is None:
        with UnitOfWork(ActorContext.system(None, reason="auth.login")) as uow:
            failure = ratelimit.record_failure(uow.session, email_key, now=uow.now())
            _attempt(
                uow,
                kind=AttemptKind.LOGIN,
                outcome=AttemptOutcome.INVALID_CREDENTIALS,
                client=client,
                email_hmac=email_hmac,
                user_id=user_id,
            )
            if user_id is not None:
                row = uow.session.get(AppUser, user_id)
                if row is not None:
                    row.failed_login_count = row.failed_login_count + 1
                    if failure.locked_until is not None:
                        row.locked_until = failure.locked_until
                        row.lock_count = failure.lock_count
                        row.failed_login_count = 0
        if user_id is not None and memberships:
            home = memberships[0]
            with UnitOfWork(_member_actor(home.company_id, user_id, home.membership_id, display_name)) as uow:
                uow.audit("auth.login.failed", resource_type="identity.user", resource_id=user_id, outcome="failed", ip=client.audit_ip, user_agent=client.user_agent)
                if failure.locked_until is not None:
                    uow.audit(
                        "auth.login.locked",
                        resource_type="identity.user",
                        resource_id=user_id,
                        outcome="denied",
                        details={"locked_until": failure.locked_until.isoformat(), "lock_count": failure.lock_count},
                        ip=client.audit_ip,
                    )
        raise InvalidCredentials()

    with UnitOfWork(_member_actor(target.company_id, user_id, target.membership_id, display_name)) as uow:
        now = uow.now()
        ratelimit.clear_failures(uow.session, email_key)
        row = uow.session.get(AppUser, user_id)
        assert row is not None  # noqa: S101 - read above in this request
        row.failed_login_count = 0
        row.locked_until = None
        row.lock_count = 0
        row.last_login_at = now
        if rehash:
            row.password_hash = rehash
        issued = sessions.create_session(
            uow.session,
            user_id=user_id,
            company_id=target.company_id,
            membership_id=target.membership_id,
            method=AuthMethod.PASSWORD,
            client=client,
            now=now,
            stage=sign_in_stage(uow, user_id, target.membership_id),
        )
        _attempt(
            uow,
            kind=AttemptKind.LOGIN,
            outcome=AttemptOutcome.SUCCESS,
            client=client,
            email_hmac=email_hmac,
            user_id=user_id,
            company_id=target.company_id,
            session_id=issued.session_id,
        )
        uow.audit("auth.login.succeeded", resource_type="identity.user", resource_id=user_id, ip=client.audit_ip, user_agent=client.user_agent)
        return SignedIn(issued, _session_info(uow, issued), _preferences(uow, user_id))


def sign_in_stage(uow: UnitOfWork, user_id: uuid.UUID, membership_id: uuid.UUID) -> SessionStage:
    """After a correct password: verify a code when the user has an authenticator; enrol one first when the
    member's access requires MFA (security policy); otherwise the session is active at once."""
    from app.platform.identity import mfa

    if mfa.confirmed_factor(uow.session, user_id) is not None:
        return SessionStage.MFA_PENDING
    if mfa.member_requires_mfa(uow, membership_id, user_id):
        return SessionStage.MFA_ENROLLMENT_REQUIRED
    return SessionStage.ACTIVE


def _session_info(uow: UnitOfWork, issued: IssuedSession) -> SessionInfo:
    user = uow.session.get(AppUser, issued.user_id)
    company = uow.session.get(Company, issued.company_id)
    assert user is not None and company is not None  # noqa: S101 - referenced by the session just created
    return SessionInfo(
        user=UserRef(id=user.id, display_name=user.display_name, email=user.email),
        company=_company_ref(company),
        membership_id=issued.membership_id,
        session=SessionView(
            id=issued.session_id,
            auth_method=issued.auth_method,
            created_at=issued.created_at,
            idle_expires_at=issued.idle_expires_at,
            absolute_expires_at=issued.absolute_expires_at,
        ),
        csrf_token=issued.csrf_token,
        stage=issued.stage,
    )


def _company_ref(company: Company) -> CompanyRef:
    return CompanyRef(
        id=company.id,
        key=company.company_key,
        display_name=company.display_name,
        legal_name=company.legal_name,
        is_demo=company.is_demo,
        base_currency=company.base_currency,
    )


@command()
def logout(uow: UnitOfWork) -> bool:
    """Revoke the caller's current session (authenticated self-service)."""
    actor = uow.actor
    if actor.session_id is None:
        raise Unauthenticated()
    revoked = sessions.revoke(uow.session, actor.session_id, now=uow.now(), reason="logout")
    uow.audit("auth.logout", resource_type="identity.session", resource_id=actor.session_id)
    return revoked


# ---- demo sign-in links ----------------------------------------------------------------------------
@dataclass(frozen=True)
class DemoLink:
    token: str
    expires_at: datetime
    company_id: uuid.UUID
    user_id: uuid.UUID
    display_name: str


def issue_demo_link(
    *, company_key: str, email: str, via: DemoTokenSource = DemoTokenSource.CLI, issued_by: uuid.UUID | None = None
) -> DemoLink:
    """A one-time, 15-minute sign-in token for an active member of an ``is_demo`` company."""
    with UnitOfWork(ActorContext.system(None, reason="identity.demo_link")) as uow:
        company = uow.session.scalars(select(Company).where(Company.company_key == company_key)).first()
        if company is None:
            raise NotFound(f"No company with key {company_key!r}", code="not_found", resource_type="org.company")
        if not company.is_demo:
            raise Forbidden("Demo sign-in links exist only for demo companies", code="not_demo_company")
        company_id = company.id
    actor = ActorContext.system(company_id, reason="identity.demo_link").with_(actor_type="cli" if via == DemoTokenSource.CLI else "system")
    with UnitOfWork(actor) as uow:
        user = uow.session.scalars(select(AppUser).where(AppUser.email_normalized == normalize_email(email))).first()
        membership = (
            uow.session.scalars(
                select(Membership).where(Membership.company_id == company_id, Membership.user_id == user.id)
            ).first()
            if user
            else None
        )
        if user is None or membership is None:
            raise NotFound("No member with that email in this company", code="not_found", resource_type="identity.membership")
        if membership.status != "active" or user.status != "active":
            raise Conflict("This member is not active", code="membership_inactive")
        token = f"{company_id.hex}.{new_token()}"
        now = uow.now()
        uow.add(
            DemoSignInToken(
                id=uuid.uuid7(),
                company_id=company_id,
                user_id=user.id,
                membership_id=membership.id,
                token_hash=sha256(token),
                issued_via=via.value,
                issued_by=issued_by,
                created_at=now,
                expires_at=now + DEMO_LINK_LIFETIME,
            )
        )
        uow.audit("identity.demo_link.issued", resource_type="identity.membership", resource_id=membership.id, details={"via": via.value})
        return DemoLink(token, now + DEMO_LINK_LIFETIME, company_id, user.id, user.display_name)


def _company_of_token(token: str) -> uuid.UUID | None:
    prefix, sep, secret = token.partition(".")
    if not sep or len(prefix) != 32 or len(secret) < 20:
        return None
    try:
        return uuid.UUID(hex=prefix)
    except ValueError:
        return None


def demo_sign_in(token: str, client: ClientInfo) -> SignedIn:
    with UnitOfWork(ActorContext.system(None, reason="auth.demo_sign_in")) as uow:
        verdict = ratelimit.hit(uow.session, _ip_bucket("demo", client), limit=ratelimit.IP_LIMIT, now=uow.now())
        company_id = _company_of_token(token)
        if not verdict.allowed:
            _attempt(uow, kind=AttemptKind.DEMO_SIGN_IN, outcome=AttemptOutcome.RATE_LIMITED, client=client, company_id=company_id)
        company = uow.session.get(Company, company_id) if company_id else None
        demo_ok = company is not None and company.is_demo and company.status == "active"
        if verdict.allowed and not demo_ok:
            _attempt(uow, kind=AttemptKind.DEMO_SIGN_IN, outcome=AttemptOutcome.LINK_INVALID, client=client)
    if not verdict.allowed:
        raise TooManyAttempts("rate_limited", verdict.retry_after_seconds)
    if not demo_ok or company_id is None:
        raise LinkInvalidOrUsed()

    with session_factory()() as s, s.begin(), tenant_scope(s, company_id):
        peek = s.execute(
            select(DemoSignInToken.user_id, DemoSignInToken.membership_id).where(DemoSignInToken.token_hash == sha256(token))
        ).first()
    signed: SignedIn | None = None
    if peek is not None:
        with UnitOfWork(_member_actor(company_id, peek[0], peek[1])) as uow:
            signed = _consume_demo_token(uow, token, client)
    if signed is None:
        with UnitOfWork(ActorContext.system(None, reason="auth.demo_sign_in")) as uow:
            _attempt(uow, kind=AttemptKind.DEMO_SIGN_IN, outcome=AttemptOutcome.LINK_INVALID, client=client, company_id=company_id)
        raise LinkInvalidOrUsed()
    return signed


def _consume_demo_token(uow: UnitOfWork, token: str, client: ClientInfo) -> SignedIn | None:
    now = uow.now()
    row = uow.session.scalars(
        select(DemoSignInToken).where(DemoSignInToken.token_hash == sha256(token)).with_for_update()
    ).first()
    if row is None or row.used_at is not None or row.revoked_at is not None or row.expires_at <= now:
        return None
    membership = uow.session.get(Membership, row.membership_id)
    user = uow.session.get(AppUser, row.user_id)
    if membership is None or user is None or membership.status != "active" or user.status != "active":
        return None
    from app.platform.identity import mfa

    issued = sessions.create_session(
        uow.session,
        user_id=user.id,
        company_id=row.company_id,
        membership_id=membership.id,
        method=AuthMethod.DEMO_LINK,
        client=client,
        now=now,
        # demo members are fictional and passwordless: no forced enrolment, but an authenticator they set up is used
        stage=SessionStage.MFA_PENDING if mfa.confirmed_factor(uow.session, user.id) else SessionStage.ACTIVE,
    )
    row.used_at = now
    row.session_id = issued.session_id
    user.last_login_at = now
    _attempt(
        uow,
        kind=AttemptKind.DEMO_SIGN_IN,
        outcome=AttemptOutcome.SUCCESS,
        client=client,
        user_id=user.id,
        company_id=row.company_id,
        session_id=issued.session_id,
    )
    uow.audit("auth.demo_sign_in.succeeded", resource_type="identity.user", resource_id=user.id, ip=client.audit_ip, user_agent=client.user_agent)
    return SignedIn(issued, _session_info(uow, issued), _preferences(uow, user.id))


# ---- test-support sessions (LK_ENV=test only) ------------------------------------------------------
def test_sign_in(company_id: uuid.UUID, user_id: uuid.UUID, client: ClientInfo) -> SignedIn:
    if not get_settings().is_test:
        raise NotFound(code="not_found")
    with UnitOfWork(_member_actor(company_id, user_id, None)) as uow:
        membership = uow.session.scalars(
            select(Membership).where(Membership.company_id == company_id, Membership.user_id == user_id)
        ).first()
        user = uow.session.get(AppUser, user_id)
        if membership is None or user is None or membership.status != "active" or user.status != "active":
            raise NotFound("No active member with that id", code="not_found", resource_type="identity.membership")
        issued = sessions.create_session(
            uow.session,
            user_id=user_id,
            company_id=company_id,
            membership_id=membership.id,
            method=AuthMethod.TEST_SUPPORT,
            client=client,
            now=uow.now(),
        )
        _attempt(
            uow,
            kind=AttemptKind.TEST_SIGN_IN,
            outcome=AttemptOutcome.SUCCESS,
            client=client,
            user_id=user_id,
            company_id=company_id,
            session_id=issued.session_id,
        )
        return SignedIn(issued, _session_info(uow, issued), _preferences(uow, user_id))


test_sign_in.__test__ = False  # type: ignore[attr-defined]  # not a pytest test


def find_member_by_email(company_key: str, email: str) -> tuple[uuid.UUID, uuid.UUID]:
    """(company_id, user_id) for an email in a company (test support and CLI helpers)."""
    with UnitOfWork(ActorContext.system(None, reason="identity.lookup")) as uow:
        company_id = uow.session.scalar(select(Company.id).where(Company.company_key == company_key))
        user_id = uow.session.scalar(select(AppUser.id).where(AppUser.email_normalized == normalize_email(email)))
    if company_id is None or user_id is None:
        raise NotFound(code="not_found", resource_type="identity.membership")
    return company_id, user_id


# ---- first admin -----------------------------------------------------------------------------------
@dataclass(frozen=True)
class FirstAdmin:
    company_id: uuid.UUID
    user_id: uuid.UUID
    membership_id: uuid.UUID
    company_created: bool


def any_admin_membership() -> bool:
    """True when any company has a membership holding the ``admin`` role (invited or active)."""
    with session_factory()() as s, s.begin():
        companies = list(s.scalars(select(Company.id)))
        for company_id in companies:
            with tenant_scope(s, company_id):
                found = s.scalar(
                    select(Membership.id)
                    .join(MembershipRole, MembershipRole.membership_id == Membership.id)
                    .join(Role, Role.id == MembershipRole.role_id)
                    .where(Role.role_key == "admin", Membership.status.in_(("active", "invited")))
                    .limit(1)
                )
            if found is not None:
                return True
    return False


def create_first_admin(*, email: str, display_name: str, password: str, company: CompanySpec) -> FirstAdmin:
    """``lk admin create-first``: refuses when any admin membership exists; never reads secrets from argv."""
    from app.platform.identity import provisioning, roles

    email = email.strip()
    if "@" not in email or len(email) > 254:
        raise ValidationFailed("Enter a valid email address", code="validation_failed")
    violation = passwords.check_policy(
        password, email=email, company_names=(company.company_key, company.display_name, company.legal_name)
    )
    if violation is not None:
        raise PasswordPolicyViolation(violation.message, errors=[{"loc": ["password"], "msg": violation.message, "code": violation.code}])
    if any_admin_membership():
        raise Conflict("An administrator already exists; create-first can run only once", code="admin_exists")
    password_hash = passwords.hash_password(password)
    cli = ActorContext(actor_type="cli", company_id=None, is_system=True, display_name="lk admin create-first", channel="cli", auth_strength="system")
    with UnitOfWork(cli) as uow:
        roles.sync_permission_catalogue(uow)
        company_id, created = provisioning.ensure_company(uow, company)
        if uow.session.scalar(select(AppUser.id).where(AppUser.email_normalized == normalize_email(email))) is not None:
            raise Conflict("A user with this email already exists", code="user_exists")
    with UnitOfWork(cli.with_(company_id=company_id)) as uow:
        roles.ensure_system_roles(uow, company_id, origin="system")
        head_office = uow.session.scalar(
            select(Branch.id).where(Branch.company_id == company_id, Branch.is_head_office.is_(True), Branch.archived_at.is_(None))
        )
        if head_office is None:
            head_office = provisioning.ensure_branch(uow, code="HO", name="Head Office", is_head_office=True)
        user_id, _ = provisioning.ensure_user(uow, email=email, display_name=display_name, status="active", password_hash=password_hash)
        membership_id, _ = provisioning.provision_membership(
            uow, user_id=user_id, status="active", role_keys=["admin"], branch_ids=[head_office], default_branch_id=head_office
        )
        uow.audit(
            "identity.first_admin.created",
            resource_type="identity.membership",
            resource_id=membership_id,
            details={"company_created": created},
        )
    return FirstAdmin(company_id, user_id, membership_id, created)


# ---- profile, preferences and the session bootstrap ------------------------------------------------
def _preferences(uow: UnitOfWork, user_id: uuid.UUID) -> Preferences:
    row = uow.session.get(UserPreference, user_id)
    if row is None:
        return read({}, 0)
    return read({"ui": row.ui, "locale": row.locale, "briefing": row.briefing, "voice": row.voice, "assistant": row.assistant}, row.version)


def _require_member(uow: UnitOfWork) -> tuple[AppUser, Membership, Company]:
    actor = uow.actor
    if actor.user_id is None or actor.company_id is None:
        raise Unauthenticated()
    user = uow.session.get(AppUser, actor.user_id)
    membership = uow.session.get(Membership, actor.membership_id) if actor.membership_id else None
    company = uow.session.get(Company, actor.company_id)
    if user is None or membership is None or company is None:
        raise Unauthenticated()
    return user, membership, company


def _membership_view(uow: UnitOfWork, membership: Membership, company: Company) -> MembershipView:
    role_rows = uow.session.execute(
        select(Role.role_key, Role.name)
        .join(MembershipRole, MembershipRole.role_id == Role.id)
        .where(MembershipRole.membership_id == membership.id)
        .order_by(Role.role_key)
    ).all()
    branches = uow.session.scalars(
        select(Branch)
        .join(MembershipBranch, MembershipBranch.branch_id == Branch.id)
        .where(MembershipBranch.membership_id == membership.id, Branch.archived_at.is_(None))
        .order_by(Branch.branch_code)
    ).all()
    teams = uow.session.execute(
        select(Team.id, Team.team_key, Team.name, TeamMember.team_role)
        .join(TeamMember, TeamMember.team_id == Team.id)
        .where(TeamMember.membership_id == membership.id, Team.archived_at.is_(None))
        .order_by(Team.team_key)
    ).all()
    manager = None
    if membership.manager_membership_id is not None:
        name = uow.session.scalar(
            select(AppUser.display_name)
            .join(Membership, Membership.user_id == AppUser.id)
            .where(Membership.id == membership.manager_membership_id)
        )
        if name is not None:
            manager = ManagerRef(membership_id=membership.manager_membership_id, display_name=name)
    return MembershipView(
        id=membership.id,
        status=membership.status,
        job_title=membership.job_title,
        company=_company_ref(company),
        roles=[RoleRef(key=k, name=n) for k, n in role_rows],
        branches=[_branch_ref(b) for b in branches],
        teams=[TeamRef(id=i, key=k, name=n, team_role=r) for i, k, n, r in teams],
        manager=manager,
        joined_on=membership.joined_on.isoformat() if membership.joined_on else None,
    )


def _branch_ref(branch: Branch) -> BranchRef:
    return BranchRef(id=branch.id, code=branch.branch_code, name=branch.name, is_head_office=branch.is_head_office)


def _session_view(uow: UnitOfWork) -> SessionView | None:
    if uow.actor.session_id is None:
        return None
    row = uow.session.get(AuthSession, uow.actor.session_id)
    if row is None:
        return None
    return SessionView(
        id=row.id,
        auth_method=row.auth_method,
        created_at=row.created_at,
        idle_expires_at=row.idle_expires_at,
        absolute_expires_at=row.absolute_expires_at,
    )


@query()
def get_me(uow: UnitOfWork) -> MeRead:
    user, membership, company = _require_member(uow)
    return MeRead(
        user=ProfileView(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            full_name=user.full_name,
            locale=user.locale,
            time_zone=user.time_zone,
        ),
        membership=_membership_view(uow, membership, company),
        memberships=_membership_summaries(uow, user.id, membership.id),
        permissions=_grants(uow.actor),
        overrides=_open_overrides(uow, membership.id),
        preferences=_preferences(uow, user.id),
        session=_session_view(uow),
        time_zone=uow.actor.time_zone,
        locale=uow.actor.locale,
    )


def _grants(actor: ActorContext) -> list[PermissionGrant]:
    return [PermissionGrant(key=k, scope=s.label) for k, s in sorted(actor.permissions.items())]


def _override_view(row: UserPermissionOverride, now: datetime) -> PermissionOverrideView:
    return PermissionOverrideView(
        id=row.id,
        permission_key=row.permission_key,
        effect=row.effect,  # type: ignore[arg-type]
        scope=row.scope,
        reason=row.reason,
        expires_at=row.expires_at,
        in_effect=row.expires_at is None or row.expires_at > now,
        created_at=row.created_at,
        created_by=row.created_by,
    )


def _open_overrides(uow: UnitOfWork, membership_id: uuid.UUID) -> list[PermissionOverrideView]:
    rows = uow.session.scalars(
        select(UserPermissionOverride)
        .where(UserPermissionOverride.membership_id == membership_id, UserPermissionOverride.archived_at.is_(None))
        .order_by(UserPermissionOverride.permission_key)
    )
    now = uow.now()
    return [_override_view(r, now) for r in rows]


def _membership_summaries(uow: UnitOfWork, user_id: uuid.UUID, current_id: uuid.UUID) -> list[MembershipSummary]:
    refs = _memberships_of(user_id)
    companies = {c.id: c for c in uow.session.scalars(select(Company).where(Company.id.in_([r.company_id for r in refs])))}
    return [
        MembershipSummary(
            id=r.membership_id, status=r.status, company=_company_ref(companies[r.company_id]), is_current=r.membership_id == current_id
        )
        for r in sorted(refs, key=lambda r: (r.membership_id != current_id, companies[r.company_id].display_name))
        if r.company_id in companies
    ]


@command()
def update_preferences(uow: UnitOfWork, patch: PreferencesPatch) -> PreferencesUpdated:
    user, _membership, _company = _require_member(uow)
    row = uow.session.get(UserPreference, user.id, with_for_update=True)
    current_version = row.version if row is not None else 0
    if patch.expected_version != current_version:
        raise _preferences_conflict(uow, user.id, row)
    stored = (
        {"ui": row.ui, "locale": row.locale, "briefing": row.briefing, "voice": row.voice, "assistant": row.assistant}
        if row is not None
        else {}
    )
    sections, changed = apply_patch(stored, patch)
    if changed:
        if row is None:
            # first write: a concurrent first write for the same user loses with a 409 (the client re-reads)
            try:
                with uow.session.begin_nested():
                    uow.session.add(UserPreference(user_id=user.id, **sections))
            except IntegrityError:
                raise _preferences_conflict(uow, user.id, uow.session.get(UserPreference, user.id, populate_existing=True)) from None
        else:
            for name, value in sections.items():
                setattr(row, name, value)
            uow.flush()
        uow.audit("identity.preferences.updated", resource_type="identity.user", resource_id=user.id, details={"changed_fields": changed})
    return PreferencesUpdated(preferences=_preferences(uow, user.id), changed_fields=changed)


def _preferences_conflict(uow: UnitOfWork, user_id: uuid.UUID, row: UserPreference | None) -> VersionConflict:
    """409 ``version_conflict`` with the current representation (api-conventions §3): preferences are the user's
    own, so ``changed_by`` is that user (another tab or device)."""
    current = _preferences(uow, user_id)
    return VersionConflict(
        current_version=current.version,
        current=current.model_dump(mode="json"),
        changed_by=str(user_id) if row is not None else None,
        changed_at=row.updated_at.isoformat() if row is not None and row.updated_at else None,
    )


def session_profile(uow: UnitOfWork) -> SessionProfile:
    """The identity part of ``GET /api/v1/session/bootstrap`` for the signed-in actor."""
    user, membership, company = _require_member(uow)
    branches = uow.session.scalars(
        select(Branch).where(Branch.company_id == company.id, Branch.archived_at.is_(None)).order_by(
            Branch.is_head_office.desc(), Branch.branch_code
        )
    ).all()
    actor = uow.actor
    return SessionProfile(
        user=UserRef(id=user.id, display_name=user.display_name, email=user.email),
        membership=_membership_view(uow, membership, company),
        company=_company_ref(company),
        branches=[_branch_ref(b) for b in branches],
        time_zone=actor.time_zone or resolve_time_zone(company.default_time_zone),
        locale=actor.locale,
        permissions=_grants(actor),
        preferences=_preferences(uow, user.id),
        session=_session_view(uow),
    )


def rotate_csrf(uow: UnitOfWork) -> str:
    """A fresh CSRF secret for the caller's session (bootstrap rotation; the old value stops working)."""
    if uow.actor.session_id is None:
        raise Unauthenticated()
    return sessions.rotate_csrf(uow.session, uow.actor.session_id)


# ---- per-user permission overrides (PARITY API-08/API-09, LM-08) ---------------------------------------
PERMISSION_MANAGE = "identity.permission.manage"
USER_READ = "identity.user.read"


def _require_recent_auth(uow: UnitOfWork, key: str) -> None:
    """Enforce the ``MFA`` and ``RA`` flags of ``key`` (permissions.md §6) through :mod:`app.platform.authz.stepup`."""
    from app.platform.authz.stepup import require_step_up

    require_step_up(uow, key)


def _member_of_user(uow: UnitOfWork, user_id: uuid.UUID) -> Membership:
    from app.platform.identity import provisioning

    membership = provisioning.membership_for_user(uow, user_id)
    if membership is None:
        raise NotFound(code="not_found", resource_type="identity.membership")
    return membership


def _open_override(uow: UnitOfWork, membership_id: uuid.UUID, key: str) -> UserPermissionOverride | None:
    return uow.session.scalars(
        select(UserPermissionOverride).where(
            UserPermissionOverride.membership_id == membership_id,
            UserPermissionOverride.permission_key == key,
            UserPermissionOverride.archived_at.is_(None),
        )
    ).first()


@query()
def list_permission_overrides(uow: UnitOfWork, user_id: uuid.UUID) -> PermissionOverrideList:
    """A member's open overrides; needs ``identity.user.read`` or ``identity.permission.manage`` (company)."""
    actor = uow.actor
    if not (actor.can(USER_READ, Scope.COMPANY) or actor.can(PERMISSION_MANAGE, Scope.COMPANY)):
        raise Forbidden(code="permission_denied", permission=USER_READ)
    membership = _member_of_user(uow, user_id)
    return PermissionOverrideList(user_id=user_id, membership_id=membership.id, items=_open_overrides(uow, membership.id))


@command(PERMISSION_MANAGE, at_least=Scope.COMPANY, idempotent=True)
def put_permission_override(
    uow: UnitOfWork, user_id: uuid.UUID, permission_key: str, body: PermissionOverridePut
) -> PermissionOverrideView:
    """Grant or revoke one key for a member (replacing the open override for that key).

    Anti-escalation, the self-change ban, the last-admin guard, the epoch bump and the events are applied by
    :func:`app.platform.identity.provisioning.set_permission_override`. Repeating an identical PUT changes nothing.
    """
    from app.platform.identity import provisioning

    _require_recent_auth(uow, PERMISSION_MANAGE)
    membership = _member_of_user(uow, user_id)
    current = _open_override(uow, membership.id, permission_key)
    if (
        current is not None
        and current.effect == body.effect
        and current.scope == body.scope
        and current.reason == body.reason.strip()[:500]
        and current.expires_at == body.expires_at
    ):
        return _override_view(current, uow.now())
    provisioning.set_permission_override(
        uow,
        membership.id,
        permission_key=permission_key,
        effect=body.effect,
        reason=body.reason,
        scope=body.scope,
        expires_at=body.expires_at,
    )
    row = _open_override(uow, membership.id, permission_key)
    assert row is not None  # noqa: S101 - written just above
    return _override_view(row, uow.now())


@command(PERMISSION_MANAGE, at_least=Scope.COMPANY, idempotent=True)
def delete_permission_override(uow: UnitOfWork, user_id: uuid.UUID, permission_key: str) -> None:
    """Archive a member's open override for one key (404 when there is none)."""
    from app.platform.identity import provisioning

    _require_recent_auth(uow, PERMISSION_MANAGE)
    membership = _member_of_user(uow, user_id)
    row = _open_override(uow, membership.id, permission_key)
    if row is None:
        raise NotFound(code="not_found", resource_type="identity.permission_override")
    provisioning.archive_permission_override(uow, row.id)


# ---- self-service password change (PARITY LM-03/API-03) --------------------------------------------
PASSWORD_CHANGE_LIMIT = ratelimit.EMAIL_LIMIT


def change_password(actor: ActorContext, current_password: str, new_password: str, client: ClientInfo) -> SignedIn:
    """Change the caller's own password: the current password is required; the caller gets a new session (fresh
    cookies and CSRF) and every other session of the user, in every company, is revoked.

    Attempts are rate-limited per user (10 per 10 minutes, committed even when the request fails); argon2 runs
    outside any transaction.
    """
    if actor.session_id is None or actor.user_id is None or actor.company_id is None or actor.membership_id is None:
        raise Unauthenticated()
    user_id = actor.user_id
    with UnitOfWork(actor) as uow:
        verdict = ratelimit.hit(uow.session, f"password:user:{user_id.hex}", limit=PASSWORD_CHANGE_LIMIT, now=uow.now())
        user = uow.session.get(AppUser, user_id)
        company = uow.session.get(Company, actor.company_id)
        if user is None or company is None:
            raise Unauthenticated()
        stored_hash, email = user.password_hash, user.email
        company_names = (company.company_key, company.display_name, company.legal_name)
    if not verdict.allowed:
        raise TooManyAttempts("rate_limited", verdict.retry_after_seconds)
    if not passwords.verify_password(stored_hash, current_password):
        with UnitOfWork(actor) as uow:
            uow.audit(
                "auth.password.change_failed",
                resource_type="identity.user",
                resource_id=user_id,
                outcome="failed",
                ip=client.audit_ip,
                user_agent=client.user_agent,
            )
        msg = "The current password is not correct."
        raise ValidationFailed(
            msg, code="validation_failed", errors=[{"loc": ["body", "current_password"], "msg": msg, "code": "invalid_current_password"}]
        )
    violation = passwords.check_policy(new_password, email=email, company_names=company_names)
    if violation is None and new_password == current_password:
        violation = passwords.PolicyViolation("password_unchanged", "Choose a password different from the current one.")
    if violation is not None:
        raise PasswordPolicyViolation(
            violation.message, errors=[{"loc": ["body", "new_password"], "msg": violation.message, "code": violation.code}]
        )
    new_hash = passwords.hash_password(new_password)
    with UnitOfWork(actor) as uow:
        now = uow.now()
        row = uow.session.get(AppUser, user_id, with_for_update=True)
        if row is None:
            raise Unauthenticated()
        if row.password_hash != stored_hash:  # changed concurrently (another tab): make the caller retry
            raise Conflict("Your password was changed meanwhile. Sign in again.", code="password_changed")
        row.password_hash = new_hash
        row.password_changed_at = now
        issued = sessions.create_session(
            uow.session,
            user_id=user_id,
            company_id=actor.company_id,
            membership_id=actor.membership_id,
            method=AuthMethod.PASSWORD,
            client=client,
            now=now,
            mfa_verified=actor.auth_strength == "mfa",
        )
        others = sessions.revoke_all(uow.session, user_id=user_id, now=now, reason="password_changed", keep=issued.session_id)
        uow.audit(
            "auth.password.changed",
            resource_type="identity.user",
            resource_id=user_id,
            details={"other_sessions_revoked": others},
            ip=client.audit_ip,
            user_agent=client.user_agent,
        )
        return SignedIn(issued, _session_info(uow, issued), _preferences(uow, user_id))


# ---- maintenance -----------------------------------------------------------------------------------
ATTEMPT_RETENTION = timedelta(days=90)
SESSION_RETENTION = timedelta(days=30)


def purge_auth_state(uow: UnitOfWork) -> dict[str, int]:
    """Delete expired counters, attempts older than 90 days and sessions ended more than 30 days ago."""
    now = uow.now()
    counters = ratelimit.purge_expired(uow.session, now=now)
    attempts = uow.session.execute(delete(AuthAttempt).where(AuthAttempt.occurred_at < now - ATTEMPT_RETENTION)).rowcount  # type: ignore[attr-defined]
    cutoff = now - SESSION_RETENTION
    sessions_deleted = 0
    stale = list(
        uow.session.scalars(
            select(AuthSession.id).where(
                or_(AuthSession.revoked_at < cutoff, AuthSession.absolute_expires_at < cutoff)
            )
        )
    )
    if stale:
        uow.session.execute(update(AuthSession).where(AuthSession.rotated_from_id.in_(stale)).values(rotated_from_id=None))
        sessions_deleted = uow.session.execute(delete(AuthSession).where(AuthSession.id.in_(stale))).rowcount  # type: ignore[attr-defined]
    return {"counters": counters, "attempts": int(attempts or 0), "sessions": int(sessions_deleted or 0)}
