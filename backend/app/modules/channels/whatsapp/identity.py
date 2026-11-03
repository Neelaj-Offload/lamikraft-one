"""Channel identities and sessions: matching (BSUID first, then wa_id), employee activation on a successful
enrolment (a reassigned number revokes the previous holder first), suspension on a BSUID change, revocation on
unlink, deactivation or credential reset (sessions revoked, armed buttons voided). A phone number alone never
carries authority: authority comes from the active identity's ``user_id`` and a live channel session."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select, update

from app.modules.channels import events as ev
from app.modules.channels.models import ChannelAccount, ChannelIdentity, ChannelSession
from app.platform.uow import UnitOfWork

SESSION_IDLE = timedelta(days=7)
SESSION_ABSOLUTE = timedelta(days=30)
GENERIC_REPLY_INTERVAL = timedelta(hours=1)


def digits(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


def mask(value: str | None) -> str | None:
    d = digits(value)
    if not d:
        return None
    return f"{'•' * max(len(d) - 4, 0)}{d[-4:]}"


def find_identity(uow: UnitOfWork, account: ChannelAccount, *, bsuid: str | None, wa_id: str | None) -> ChannelIdentity | None:
    if bsuid:
        row = uow.session.scalars(
            select(ChannelIdentity).where(ChannelIdentity.account_id == account.id, ChannelIdentity.bsuid == bsuid).with_for_update()
        ).first()
        if row is not None:
            return row
    if wa_id:
        row = uow.session.scalars(
            select(ChannelIdentity).where(ChannelIdentity.account_id == account.id, ChannelIdentity.wa_id == wa_id).with_for_update()
        ).first()
        if row is not None:
            if bsuid and row.bsuid is None:
                row.bsuid = bsuid  # learn the BSUID the first time Meta sends it
            return row
    return None


def ensure_unknown_identity(uow: UnitOfWork, account: ChannelAccount, *, wa_id: str | None, bsuid: str | None) -> ChannelIdentity:
    row = find_identity(uow, account, bsuid=bsuid, wa_id=wa_id)
    if row is not None:
        return row
    row = ChannelIdentity(id=uuid.uuid7(), account_id=account.id, kind="unknown", status="pending", wa_id=wa_id or None, bsuid=bsuid or None)
    uow.add(row)
    uow.flush()
    return row


def employee_identities_for_user(uow: UnitOfWork, user_id: uuid.UUID, *, active_only: bool = True) -> list[ChannelIdentity]:
    stmt = select(ChannelIdentity).where(ChannelIdentity.company_id == uow.actor.company_id, ChannelIdentity.user_id == user_id, ChannelIdentity.kind == "employee")
    if active_only:
        stmt = stmt.where(ChannelIdentity.status == "active")
    return list(uow.session.scalars(stmt.order_by(ChannelIdentity.created_at)))


def active_session(uow: UnitOfWork, identity: ChannelIdentity, now: datetime) -> ChannelSession | None:
    row = uow.session.scalars(
        select(ChannelSession)
        .where(ChannelSession.identity_id == identity.id, ChannelSession.revoked_at.is_(None))
        .order_by(ChannelSession.created_at.desc())
    ).first()
    if row is None or row.idle_expires_at <= now or row.absolute_expires_at <= now:
        return None
    return row


def is_authorised(uow: UnitOfWork, identity: ChannelIdentity, now: datetime) -> bool:
    return identity.kind == "employee" and identity.status == "active" and identity.user_id is not None and active_session(uow, identity, now) is not None


def touch_session(uow: UnitOfWork, identity: ChannelIdentity, now: datetime) -> None:
    session = active_session(uow, identity, now)
    if session is not None:
        session.idle_expires_at = min(now + SESSION_IDLE, session.absolute_expires_at)


def start_session(uow: UnitOfWork, identity: ChannelIdentity, now: datetime) -> ChannelSession:
    assert identity.user_id is not None
    row = ChannelSession(
        id=uuid.uuid7(), identity_id=identity.id, user_id=identity.user_id,
        idle_expires_at=now + SESSION_IDLE, absolute_expires_at=now + SESSION_ABSOLUTE,
    )
    uow.add(row)
    uow.flush()
    return row


def revoke_sessions(uow: UnitOfWork, identity: ChannelIdentity, now: datetime, reason: str) -> int:
    result = uow.session.execute(
        update(ChannelSession)
        .where(ChannelSession.identity_id == identity.id, ChannelSession.revoked_at.is_(None))
        .values(revoked_at=now, reason=reason[:80], updated_at=now)
    )
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


def _identity_payload(identity: ChannelIdentity) -> dict[str, object]:
    return ev.payload(ev.IdentityPayload(identity_id=identity.id, kind=identity.kind, user_id=identity.user_id))


def revoke_identity(uow: UnitOfWork, identity: ChannelIdentity, *, reason: str, now: datetime | None = None) -> None:
    from app.modules.channels import action_refs

    now = now or uow.now()
    if identity.status != "revoked":
        identity.status = "revoked"
        identity.revoked_at = now
        identity.suspended_reason = reason[:80]
    revoke_sessions(uow, identity, now, reason)
    action_refs.void_for_identity(uow, identity.id, reason=reason)
    uow.emit(ev.IDENTITY_REVOKED, aggregate_id=identity.id, aggregate_version=identity.version, payload=_identity_payload(identity))
    uow.audit("channels.identity.revoked", resource_type="channels.identity", resource_id=identity.id, reason=reason)


def suspend_identity(uow: UnitOfWork, identity: ChannelIdentity, *, reason: str, now: datetime | None = None) -> None:
    from app.modules.channels import action_refs

    now = now or uow.now()
    identity.status = "suspended"
    identity.suspended_reason = reason[:80]
    revoke_sessions(uow, identity, now, reason)
    action_refs.void_for_identity(uow, identity.id, reason=reason)
    uow.emit(ev.IDENTITY_SUSPENDED, aggregate_id=identity.id, aggregate_version=identity.version, payload=_identity_payload(identity))
    uow.audit("channels.identity.suspended", resource_type="channels.identity", resource_id=identity.id, reason=reason)


def revoke_for_user(uow: UnitOfWork, user_id: uuid.UUID, *, reason: str, event_id: uuid.UUID | None = None) -> int:
    """Deactivation or credential reset: every active or suspended identity of the user is revoked once."""
    from app.platform.events.service import once

    if event_id is not None and not once(uow, ev.REVOKE_HANDLER, event_id):
        return 0
    count = 0
    for identity in employee_identities_for_user(uow, user_id, active_only=False):
        if identity.status in ("active", "suspended", "pending"):
            revoke_identity(uow, identity, reason=reason)
            count += 1
    return count


def activate_employee(
    uow: UnitOfWork, account: ChannelAccount, *, user_id: uuid.UUID, wa_id: str | None, bsuid: str | None, username: str | None, now: datetime
) -> ChannelIdentity:
    """Link ``user_id`` to the sender. A number held by another user is reassigned: the previous identity is
    revoked (sessions, buttons) before the new one is activated. The user's other active identities stay."""
    existing = find_identity(uow, account, bsuid=bsuid, wa_id=wa_id)
    if existing is not None and existing.kind == "employee" and existing.user_id not in (None, user_id):
        revoke_identity(uow, existing, reason="number_reassigned", now=now)
    if existing is not None and (existing.kind == "unknown" or existing.user_id in (None, user_id)):
        identity = existing
        identity.kind = "employee"
        identity.user_id = user_id
        identity.party_id = None
        identity.contact_id = None
    elif existing is not None:  # reassigned: a fresh identity row for the new holder, the old keeps its history
        existing.wa_id = None if wa_id else existing.wa_id
        existing.bsuid = None if bsuid else existing.bsuid
        uow.flush()
        identity = ChannelIdentity(id=uuid.uuid7(), account_id=account.id, kind="employee", user_id=user_id)
        uow.add(identity)
    else:
        identity = ChannelIdentity(id=uuid.uuid7(), account_id=account.id, kind="employee", user_id=user_id)
        uow.add(identity)
    identity.wa_id = wa_id or identity.wa_id
    identity.bsuid = bsuid or identity.bsuid
    identity.username = username or identity.username
    identity.phone_e164 = f"+{digits(wa_id)}" if wa_id else identity.phone_e164
    identity.status = "active"
    identity.revoked_at = None
    identity.suspended_reason = None
    identity.last_inbound_at = now
    uow.flush()
    start_session(uow, identity, now)
    uow.emit(ev.IDENTITY_LINKED, aggregate_id=identity.id, aggregate_version=identity.version, payload=_identity_payload(identity))
    uow.audit("channels.identity.linked", resource_type="channels.identity", resource_id=identity.id, resource_label=mask(wa_id) or "WhatsApp")
    return identity


def match_customer(uow: UnitOfWork, account: ChannelAccount, *, wa_id: str | None) -> tuple[uuid.UUID, uuid.UUID] | None:
    """(party id, contact id) of a party contact whose phone matches the sender; None when nobody matches."""
    from app.modules.parties.models import PartyContact

    number = digits(wa_id)
    if len(number) < 8:
        return None
    rows = uow.session.scalars(
        select(PartyContact).where(PartyContact.company_id == uow.actor.company_id, PartyContact.phone.is_not(None), PartyContact.archived_at.is_(None))
    )
    for contact in rows:
        if digits(contact.phone).endswith(number[-10:]) and len(digits(contact.phone)) >= 10:
            return contact.party_id, contact.id
    return None


def ensure_customer_identity(uow: UnitOfWork, account: ChannelAccount, *, wa_id: str | None, bsuid: str | None, party_id: uuid.UUID, contact_id: uuid.UUID | None) -> ChannelIdentity:
    identity = find_identity(uow, account, bsuid=bsuid, wa_id=wa_id)
    if identity is None:
        identity = ChannelIdentity(id=uuid.uuid7(), account_id=account.id, kind="customer", status="active", wa_id=wa_id or None, bsuid=bsuid or None)
        uow.add(identity)
    if identity.kind == "unknown":
        identity.kind = "customer"
        identity.status = "active"
    identity.party_id = party_id
    identity.contact_id = contact_id
    identity.phone_e164 = f"+{digits(wa_id)}" if wa_id else identity.phone_e164
    uow.flush()
    return identity


__all__ = [
    "GENERIC_REPLY_INTERVAL", "SESSION_ABSOLUTE", "SESSION_IDLE", "activate_employee", "active_session", "digits", "employee_identities_for_user",
    "ensure_customer_identity", "ensure_unknown_identity", "find_identity", "is_authorised", "mask", "match_customer", "revoke_for_user",
    "revoke_identity", "revoke_sessions", "start_session", "suspend_identity", "touch_session",
]
