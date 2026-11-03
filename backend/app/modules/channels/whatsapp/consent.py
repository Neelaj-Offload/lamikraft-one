"""Consent (append-only log). STOP, UNSUBSCRIBE or "band karo" opts the sender out of every proactive purpose and
earns a confirmation (a reply to a message the user sent is always allowed); START opts back in. Daily-briefing
pushes need ``opted_in`` plus an open window or an approved utility template (checked by the sender)."""

from __future__ import annotations

import re
import uuid
from datetime import datetime

from sqlalchemy import select

from app.modules.channels import events as ev
from app.modules.channels.models import ChannelConsent, ChannelIdentity
from app.modules.channels.schemas import PROACTIVE_PURPOSES, ConsentPurpose, ConsentStatus
from app.platform.uow import UnitOfWork

OPT_OUT_PATTERNS = (
    re.compile(r"^\s*(stop|unsubscribe|cancel|opt\s*out)\s*[.!]*\s*$", re.IGNORECASE),
    re.compile(r"^\s*band\s+karo\s*[.!]*\s*$", re.IGNORECASE),
    re.compile(r"^\s*बंद\s+करो\s*[.!।]*\s*$"),
)
OPT_IN_PATTERNS = (
    re.compile(r"^\s*(start|subscribe|opt\s*in|resume)\s*[.!]*\s*$", re.IGNORECASE),
    re.compile(r"^\s*(chalu|shuru)\s+karo\s*[.!]*\s*$", re.IGNORECASE),
)


def is_opt_out(text: str) -> bool:
    return any(p.match(text or "") for p in OPT_OUT_PATTERNS)


def is_opt_in(text: str) -> bool:
    return any(p.match(text or "") for p in OPT_IN_PATTERNS)


def record(
    uow: UnitOfWork, identity: ChannelIdentity, purpose: ConsentPurpose | str, status: ConsentStatus | str, *, source: str,
    evidence_ref: str | None = None, now: datetime | None = None,
) -> ChannelConsent:
    now = now or uow.now()
    row = ChannelConsent(
        id=uuid.uuid7(), identity_id=identity.id, purpose=str(purpose), status=str(status), source=source[:40],
        evidence_ref=(evidence_ref or None) and evidence_ref[:200], recorded_by=uow.actor.user_id, recorded_at=now,
    )
    uow.add(row)
    uow.flush()
    uow.emit(ev.CONSENT_CHANGED, aggregate_id=identity.id, payload=ev.payload(ev.ConsentChangedPayload(identity_id=identity.id, purpose=str(purpose), status=str(status))))
    uow.audit("channels.consent.changed", resource_type="channels.identity", resource_id=identity.id, details={"purpose": str(purpose), "status": str(status), "source": source})
    return row


def current(uow: UnitOfWork, identity_id: uuid.UUID) -> dict[str, str]:
    """purpose -> latest status. Unlisted purposes have no explicit consent."""
    rows = uow.session.scalars(
        select(ChannelConsent).where(ChannelConsent.identity_id == identity_id).order_by(ChannelConsent.recorded_at, ChannelConsent.id)
    )
    out: dict[str, str] = {}
    for row in rows:
        out[row.purpose] = row.status
    return out


def allows(uow: UnitOfWork, identity_id: uuid.UUID, purpose: ConsentPurpose | str) -> tuple[bool, str | None]:
    """Whether a message for ``purpose`` may go out: proactive purposes need an explicit opt-in; replies and
    transactional messages are allowed unless the person opted out of that purpose."""
    state = current(uow, identity_id)
    status = state.get(str(purpose))
    if str(purpose) in {p.value for p in PROACTIVE_PURPOSES}:
        return (status == "opted_in", None if status == "opted_in" else ("consent_opted_out" if status == "opted_out" else "consent_missing"))
    return (status != "opted_out", None if status != "opted_out" else "consent_opted_out")


def opt_out_all(uow: UnitOfWork, identity: ChannelIdentity, *, evidence_ref: str, now: datetime) -> list[str]:
    changed = []
    for purpose in PROACTIVE_PURPOSES:
        record(uow, identity, purpose, ConsentStatus.OPTED_OUT, source="whatsapp_keyword", evidence_ref=evidence_ref, now=now)
        changed.append(purpose.value)
    return changed


def opt_in_all(uow: UnitOfWork, identity: ChannelIdentity, *, evidence_ref: str, now: datetime) -> list[str]:
    changed = []
    for purpose in PROACTIVE_PURPOSES:
        record(uow, identity, purpose, ConsentStatus.OPTED_IN, source="whatsapp_keyword", evidence_ref=evidence_ref, now=now)
        changed.append(purpose.value)
    return changed


__all__ = ["allows", "current", "is_opt_in", "is_opt_out", "opt_in_all", "opt_out_all", "record"]
