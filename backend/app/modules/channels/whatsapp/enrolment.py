"""Enrolment (design §15 "Enrolment and sessions").

The web app, after a recent authentication, issues an 8-digit code (stored as a keyed hash, valid 10 minutes)
and a wa.me link prefilled with "LINK <code>". A matching inbound code from WhatsApp activates the sender's
identity for that user and starts a channel session (7 days idle, 30 days absolute). Wrong codes count against
the sender: five failed codes within ten minutes refuse further attempts from that sender until the window ends
(``channels_enrolment.attempts`` counts the failures against the enrolment a sender eventually used). A phone
number alone never carries authority.
"""

from __future__ import annotations

import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import quote

from sqlalchemy import select, update

from app.core.errors import Forbidden
from app.modules.channels.models import ChannelAccount, ChannelEnrolment, ChannelIdentity
from app.modules.channels.policies import IDENTITY_MANAGE
from app.modules.channels.schemas import ConsentPurpose, ConsentStatus, EnrolmentRead
from app.modules.channels.whatsapp import accounts, consent
from app.modules.channels.whatsapp import identity as identities
from app.platform.identity.tokens import keyed_hash
from app.platform.uow import UnitOfWork

CODE_TTL = timedelta(minutes=10)
MAX_ATTEMPTS = 5
LINK_PATTERN = re.compile(r"^\s*LINK\s+(\d{8})\s*$", re.IGNORECASE)
ASSISTANT_USE = "agents.assistant.use"
DEMO_MODE = "demo"


def _hash(account: ChannelAccount, code: str) -> bytes:
    return keyed_hash("channels.whatsapp.enrolment", f"{account.id}:{code}")


def link_text(code: str) -> str:
    return f"LINK {code}"


def wa_me_link(account: ChannelAccount, code: str) -> str | None:
    number = identities.digits(account.display_phone)
    if not number:
        return None
    return f"https://wa.me/{number}?text={quote(link_text(code))}"


def create(uow: UnitOfWork) -> EnrolmentRead:
    """A new code for the signed-in user (earlier pending codes of the user are cancelled)."""
    from app.platform.org.stepup import require_recent_auth

    actor = uow.actor
    if actor.user_id is None or actor.is_system:
        raise Forbidden(code="permission_denied", permission=ASSISTANT_USE)
    if not (actor.can(ASSISTANT_USE) or actor.can(IDENTITY_MANAGE)):
        raise Forbidden(code="permission_denied", permission=ASSISTANT_USE)
    account = accounts.ensure_account(uow)
    if account.mode != DEMO_MODE:
        # fail closed: only the explicit demo mode (whose only "phone" is the simulator's synthetic number) skips
        # the step-up; live and any unknown or future mode need a recent sign-in (RA on channels.identity.manage)
        require_recent_auth(uow, IDENTITY_MANAGE)
    now = uow.now()
    uow.session.execute(
        update(ChannelEnrolment)
        .where(ChannelEnrolment.company_id == actor.company_id, ChannelEnrolment.user_id == actor.user_id, ChannelEnrolment.status == "pending")
        .values(status="cancelled", updated_at=now)
    )
    code = f"{secrets.randbelow(10**8):08d}"
    row = ChannelEnrolment(
        id=uuid.uuid7(), user_id=actor.user_id, account_id=account.id, code_hash=_hash(account, code), expires_at=now + CODE_TTL,
        attempts=0, status="pending", mode=account.mode,
    )
    uow.add(row)
    uow.flush()
    uow.audit("channels.enrolment.created", resource_type="channels.enrolment", resource_id=row.id)
    return EnrolmentRead(
        id=row.id, code=code, expires_at=row.expires_at, wa_me_link=wa_me_link(account, code), message_text=link_text(code),
        status="pending", mode=account.mode,  # type: ignore[arg-type]
    )


@dataclass(frozen=True)
class LinkOutcome:
    #: linked | expired | invalid | locked
    outcome: str
    identity: ChannelIdentity | None = None
    user_name: str | None = None


def cancel_pending(uow: UnitOfWork, account: ChannelAccount, *, reason: str) -> int:
    """Invalidate every outstanding code of the account (a mode switch: codes issued under the old mode die)."""
    now = uow.now()
    result = uow.session.execute(
        update(ChannelEnrolment)
        .where(ChannelEnrolment.company_id == uow.actor.company_id, ChannelEnrolment.account_id == account.id, ChannelEnrolment.status == "pending")
        .values(status="cancelled", updated_at=now)
    )
    count = int(result.rowcount or 0)  # type: ignore[attr-defined]
    if count:
        uow.audit("channels.enrolment.cancelled", resource_type="channels.account", resource_id=account.id, details={"reason": reason, "count": count})
    return count


def parse_code(text: str | None) -> str | None:
    match = LINK_PATTERN.match(text or "")
    return match.group(1) if match else None


def _sender_bucket(account: ChannelAccount, wa_id: str | None, bsuid: str | None) -> str:
    sender = bsuid or wa_id or "-"
    return "channels.link:" + keyed_hash("channels.whatsapp.link_sender", f"{account.id}:{sender}").hex()[:40]


def _failures(uow: UnitOfWork, bucket: str, *, count: bool) -> int:
    from app.platform.identity.auth_models import RateLimitCounter
    from app.platform.identity.ratelimit import WINDOW, hit

    if count:
        hit(uow.session, bucket, limit=MAX_ATTEMPTS, now=uow.now())
    now = uow.now()
    row = uow.session.scalars(
        select(RateLimitCounter).where(RateLimitCounter.bucket_key == bucket, RateLimitCounter.expires_at > now)
        .order_by(RateLimitCounter.window_start.desc()).limit(1)
    ).first()
    if row is None or row.window_start + WINDOW <= now:
        return 0
    return int(row.count)


def try_link(
    uow: UnitOfWork, account: ChannelAccount, code: str, *, wa_id: str | None, bsuid: str | None, username: str | None,
    simulated: bool,
) -> LinkOutcome:
    from app.platform.identity.models import AppUser

    bucket = _sender_bucket(account, wa_id, bsuid)
    if _failures(uow, bucket, count=False) >= MAX_ATTEMPTS:
        return LinkOutcome("locked")
    now = uow.now()
    row = uow.session.scalars(
        select(ChannelEnrolment)
        .where(ChannelEnrolment.company_id == uow.actor.company_id, ChannelEnrolment.account_id == account.id,
               ChannelEnrolment.code_hash == _hash(account, code))
        .with_for_update()
    ).first()
    if row is None or row.status != "pending":
        failures = _failures(uow, bucket, count=True)
        return LinkOutcome("locked" if failures >= MAX_ATTEMPTS else "invalid")
    if row.expires_at <= now:
        row.status = "expired"
        _failures(uow, bucket, count=True)
        return LinkOutcome("expired")
    if row.mode == DEMO_MODE and not (account.mode == DEMO_MODE and simulated):
        # a code issued without step-up (demo) never links a number outside the demo/simulator path
        row.status = "cancelled"
        _failures(uow, bucket, count=True)
        uow.audit("channels.enrolment.rejected", resource_type="channels.enrolment", resource_id=row.id, outcome="denied",
                  details={"reason": "demo_code_outside_demo", "account_mode": account.mode})
        return LinkOutcome("invalid")
    row.attempts = min(_failures(uow, bucket, count=False), MAX_ATTEMPTS)
    identity = identities.activate_employee(uow, account, user_id=row.user_id, wa_id=wa_id, bsuid=bsuid, username=username, now=now)
    row.status = "used"
    row.used_at = now
    row.identity_id = identity.id
    # replies to messages the user starts are allowed by default; the linked user may opt in to proactive purposes
    consent.record(uow, identity, ConsentPurpose.ASSISTANT_REPLIES, ConsentStatus.OPTED_IN, source="enrolment", evidence_ref=f"enrolment:{row.id}", now=now)
    user = uow.session.get(AppUser, row.user_id)
    return LinkOutcome("linked", identity, user.display_name if user is not None else None)


__all__ = ["DEMO_MODE", "cancel_pending", "CODE_TTL", "LINK_PATTERN", "MAX_ATTEMPTS", "LinkOutcome", "create", "link_text", "parse_code", "try_link", "wa_me_link"]
