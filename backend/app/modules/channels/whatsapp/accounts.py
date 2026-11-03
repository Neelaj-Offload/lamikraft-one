"""Channel accounts: the company's WhatsApp account from configuration, company resolution for the webhook (no
session at ingress: the phone number id is looked up per active company), the three verification checks and the
honest status label ("Demo — not connected" until live mode passes every check)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.core.errors import NotFound
from app.core.http.capabilities import Capability
from app.modules.channels import events as ev
from app.modules.channels.models import ChannelAccount
from app.modules.channels.policies import ACCOUNT_MANAGE
from app.modules.channels.schemas import AccountChecks, AccountRead, CheckResult, VerifyResult
from app.modules.channels.whatsapp.provider import AccountConfig, get_provider
from app.platform.authz.context import ActorContext
from app.platform.uow import UnitOfWork

DEMO_DISPLAY_PHONE = "+910000000000"
DEMO_LABEL = "Demo — not connected"
REQUIRED_LIVE_SETTINGS = (
    ("LK_WHATSAPP_PHONE_NUMBER_ID", lambda s: s.whatsapp_phone_number_id),
    ("LK_WHATSAPP_WABA_ID", lambda s: s.whatsapp_waba_id),
    ("LK_WHATSAPP_ACCESS_TOKEN", lambda s: s.whatsapp_access_token.get_secret_value()),
    ("LK_WHATSAPP_APP_SECRET", lambda s: s.whatsapp_app_secret.get_secret_value()),
    ("LK_WHATSAPP_VERIFY_TOKEN", lambda s: s.whatsapp_verify_token.get_secret_value()),
    ("LK_WHATSAPP_API_VERSION", lambda s: s.whatsapp_api_version),
)


def missing_settings(settings: Settings | None = None) -> list[str]:
    settings = settings or get_settings()
    if settings.whatsapp_mode != "live":
        return []
    return [name for name, getter in REQUIRED_LIVE_SETTINGS if not getter(settings)]


def demo_phone_number_id(company_id: uuid.UUID) -> str:
    return f"demo-{company_id.hex[:12]}"


def demo_waba_id(company_id: uuid.UUID) -> str:
    return f"demo-waba-{company_id.hex[:12]}"


def configured_phone_number_id(company_id: uuid.UUID, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    if settings.whatsapp_mode == "live" and settings.whatsapp_phone_number_id:
        return settings.whatsapp_phone_number_id
    return demo_phone_number_id(company_id)


def find_account(uow: UnitOfWork) -> ChannelAccount | None:
    return uow.session.scalars(
        select(ChannelAccount)
        .where(ChannelAccount.company_id == uow.actor.company_id, ChannelAccount.purpose == "employee_assistant")
        .order_by(ChannelAccount.created_at)
    ).first()


def ensure_account(uow: UnitOfWork, purpose: str = "employee_assistant") -> ChannelAccount:
    """The company's WhatsApp account, created from configuration on first use and kept in step with the
    configured mode (switching ``LK_WHATSAPP_MODE`` never silently keeps a verified live status).

    One number is configured (``LK_WHATSAPP_PHONE_NUMBER_ID``), so until owner decision 7 names a separate
    customer-service number, ``purpose="customer_service"`` resolves to the same account; customer and employee
    identities stay separate rows (``kind``) on it."""
    del purpose
    settings = get_settings()
    assert uow.actor.company_id is not None
    account = find_account(uow)
    mode = settings.whatsapp_mode
    pnid = configured_phone_number_id(uow.actor.company_id, settings)
    if account is None:
        account = ChannelAccount(
            id=uuid.uuid7(),
            purpose="employee_assistant",
            provider="whatsapp_cloud" if mode == "live" else "demo",
            mode=mode,
            phone_number_id=pnid,
            waba_id=(settings.whatsapp_waba_id or None) if mode == "live" else demo_waba_id(uow.actor.company_id),
            display_phone=DEMO_DISPLAY_PHONE if mode == "demo" else None,
            api_version=settings.whatsapp_api_version,
            status="configured_unverified" if mode == "demo" or not missing_settings(settings) else "not_configured",
            checks={},
        )
        uow.add(account)
        uow.flush()
        return account
    changed = False
    if account.mode != mode or account.phone_number_id != pnid:
        from app.modules.channels.whatsapp import enrolment

        # codes issued under the old mode (demo codes skip the step-up) must not survive the switch
        enrolment.cancel_pending(uow, account, reason=f"mode_switch:{account.mode}->{mode}")
        account.mode = mode
        account.provider = "whatsapp_cloud" if mode == "live" else "demo"
        account.phone_number_id = pnid
        account.checks = {}
        account.verified_at = None
        account.status = "configured_unverified" if (mode == "demo" or not missing_settings(settings)) else "not_configured"
        changed = True
    if account.api_version != settings.whatsapp_api_version:
        account.api_version = settings.whatsapp_api_version
        changed = True
    if mode == "live" and (account.waba_id or None) != (settings.whatsapp_waba_id or None):
        account.waba_id = settings.whatsapp_waba_id or None
        changed = True
    if mode == "live" and missing_settings(settings) and account.status != "not_configured":
        account.status = "not_configured"
        account.verified_at = None
        changed = True
    if mode == "demo" and account.display_phone is None:
        account.display_phone = DEMO_DISPLAY_PHONE
        changed = True
    if mode == "demo" and account.waba_id != demo_waba_id(uow.actor.company_id):
        account.waba_id = demo_waba_id(uow.actor.company_id)
        changed = True
    if changed:
        uow.flush()
    return account


def account_config(account: ChannelAccount, settings: Settings | None = None) -> AccountConfig:
    settings = settings or get_settings()
    return AccountConfig(
        account_id=account.id, company_id=account.company_id, mode=account.mode, phone_number_id=account.phone_number_id,
        waba_id=account.waba_id, display_phone=account.display_phone, api_version=account.api_version,
        access_token=settings.whatsapp_access_token.get_secret_value() if account.mode == "live" else "",
    )


def get_account(uow: UnitOfWork, account_id: uuid.UUID) -> ChannelAccount:
    row = uow.session.scalars(select(ChannelAccount).where(ChannelAccount.company_id == uow.actor.company_id, ChannelAccount.id == account_id)).first()
    if row is None:
        raise NotFound(code="not_found", resource_type="channels.account")
    return row


# ---- company resolution for the webhook (no session) ------------------------------------------------------------
def active_company_ids() -> list[uuid.UUID]:
    from app.core.db.engine import session_factory
    from app.platform.org.models import Company

    with session_factory()() as session:
        return list(session.scalars(select(Company.id).where(Company.status == "active").order_by(Company.id)))


def resolve_company(phone_number_id: str) -> tuple[uuid.UUID, uuid.UUID] | None:
    """(company id, account id) owning ``phone_number_id``; None for an unknown number (the delivery is ignored)."""
    for company_id in active_company_ids():
        with UnitOfWork(ActorContext.system(company_id, reason="channels.resolve")) as uow:
            row = uow.session.scalars(
                select(ChannelAccount).where(ChannelAccount.company_id == company_id, ChannelAccount.phone_number_id == phone_number_id)
            ).first()
            if row is not None:
                return company_id, row.id
    return None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _parse(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def mark_check(uow: UnitOfWork, account: ChannelAccount, name: str, at: datetime) -> None:
    checks = dict(account.checks or {})
    checks[name] = _iso(at)
    account.checks = checks
    _refresh_status(uow, account, at)


def mark_handshake(at: datetime) -> int:
    """Record ``handshake_ok_at`` on every company's account (the handshake carries no company)."""
    count = 0
    for company_id in active_company_ids():
        with UnitOfWork(ActorContext.system(company_id, reason="channels.handshake")) as uow:
            account = find_account(uow)
            if account is not None:
                mark_check(uow, account, "handshake_ok_at", at)
                count += 1
    return count


def _refresh_status(uow: UnitOfWork, account: ChannelAccount, now: datetime) -> None:
    checks = AccountChecks.model_validate({k: _parse(v) for k, v in (account.checks or {}).items()})
    complete = all((checks.graph_ok_at, checks.handshake_ok_at, checks.signed_event_ok_at))
    if account.mode == "live" and missing_settings():
        account.status = "not_configured"
        account.verified_at = None
        return
    if account.mode == "live" and complete:
        if account.status != "verified":
            account.status = "verified"
            account.verified_at = now
            uow.emit(ev.ACCOUNT_VERIFIED, aggregate_id=account.id, aggregate_version=account.version, payload={"account_id": str(account.id)})
        return
    if account.status in ("verified",) and not complete:
        account.status = "configured_unverified"
        account.verified_at = None
    elif account.status == "not_configured" and (account.mode == "demo" or not missing_settings()):
        account.status = "configured_unverified"


def label_text(account: ChannelAccount) -> str:
    if account.mode == "demo":
        return DEMO_LABEL
    return {
        "verified": "Connected",
        "configured_unverified": "Not connected",
        "not_configured": "Not configured",
        "error": "Error",
        "disabled": "Disabled",
    }.get(account.status, account.status)


def account_read(uow: UnitOfWork, account: ChannelAccount) -> AccountRead:
    settings = get_settings()
    checks = AccountChecks.model_validate({k: _parse(v) for k, v in (account.checks or {}).items()})
    can_manage = uow.actor.can(ACCOUNT_MANAGE)
    return AccountRead(
        id=account.id, purpose=account.purpose, provider=account.provider, mode=account.mode, status=account.status,  # type: ignore[arg-type]
        label_text=label_text(account), phone_number_id=account.phone_number_id if can_manage else None,
        waba_id=account.waba_id if can_manage else None, display_phone=account.display_phone, api_version=account.api_version,
        checks=checks, missing_settings=missing_settings(settings) if can_manage else [], live_outbound=bool(settings.whatsapp_live_outbound and account.mode == "live"),
        last_error=account.last_error if can_manage else None, verified_at=account.verified_at,
        capabilities={
            "verify": Capability(allowed=can_manage, reason_code=None if can_manage else "permission_denied"),
            "sync_templates": Capability(allowed=can_manage, reason_code=None if can_manage else "permission_denied"),
        },
    )


def company_label(uow: UnitOfWork) -> str:
    from app.platform.org.models import Company

    company = uow.session.get(Company, uow.actor.company_id)
    return company.display_name if company is not None else "Lamikraft"


def register_integration_def() -> None:
    """Attach the WhatsApp verification to the integration registry (ADR-040): live mode reports the missing
    settings, and verification passes only when all three checks have succeeded."""
    from app.platform.system.integrations import IntegrationDef, VerificationResult, register_integration
    from app.platform.system.models import IntegrationMode

    def verify(uow: UnitOfWork) -> VerificationResult:
        account = ensure_account(uow)
        result = run_checks(uow, account)
        failed = [c.name for c in result.checks if not c.ok]
        return VerificationResult(
            ok=account.status == "verified",
            error_code=None if not failed else ("demo_mode" if account.mode == "demo" else f"check_failed:{','.join(failed)}"),
            details={"api_version": account.api_version, "display_phone": account.display_phone, "mode": account.mode},
        )

    register_integration(IntegrationDef(
        key="channels.whatsapp",
        label="WhatsApp",
        configured_mode=lambda s: IntegrationMode.LIVE if s.whatsapp_mode == "live" else IntegrationMode.DEMO,
        missing_secrets=lambda s: missing_settings(s),
        verify=verify,
    ))


def run_checks(uow: UnitOfWork, account: ChannelAccount) -> VerifyResult:
    """Run the Graph API check now and report the two webhook-evidence checks; status becomes ``verified`` only
    when all three have passed in live mode. Demo mode reports honestly that no check can pass."""
    uow.actor.require(ACCOUNT_MANAGE)
    now = uow.now()
    results: list[CheckResult] = []
    if account.mode == "live" and not missing_settings():
        outcome = get_provider().check_phone_number(account_config(account))
        if outcome.ok:
            mark_check(uow, account, "graph_ok_at", now)
            if outcome.details.get("display_phone_number"):
                account.display_phone = str(outcome.details["display_phone_number"])
            account.last_error = None
        else:
            account.last_error = (outcome.detail or "graph_check_failed")[:200]
            account.status = "error" if account.status != "verified" else account.status
        results.append(CheckResult(name="graph_api", ok=outcome.ok, at=now if outcome.ok else None, detail=outcome.detail))
    else:
        detail = "Not configured: " + ", ".join(missing_settings()) if account.mode == "live" else "Demo provider — no Graph API check without live credentials"
        results.append(CheckResult(name="graph_api", ok=False, at=None, detail=detail))
    checks = AccountChecks.model_validate({k: _parse(v) for k, v in (account.checks or {}).items()})
    results.append(CheckResult(name="handshake", ok=checks.handshake_ok_at is not None, at=checks.handshake_ok_at, detail=None if checks.handshake_ok_at else "No webhook handshake received yet"))
    results.append(CheckResult(name="signed_event", ok=checks.signed_event_ok_at is not None, at=checks.signed_event_ok_at, detail=None if checks.signed_event_ok_at else "No signed webhook event received yet"))
    _refresh_status(uow, account, now)
    uow.flush()
    uow.audit("channels.account.verified", resource_type="channels.account", resource_id=account.id, outcome="success" if account.status == "verified" else "failed",
              details={"status": account.status, "mode": account.mode})
    return VerifyResult(account=account_read(uow, account), checks=results)


__all__ = [
    "DEMO_DISPLAY_PHONE", "DEMO_LABEL", "account_config", "account_read", "active_company_ids", "configured_phone_number_id",
    "demo_phone_number_id", "ensure_account", "find_account", "get_account", "label_text", "mark_check", "mark_handshake",
    "company_label", "missing_settings", "register_integration_def", "resolve_company", "run_checks",
]
