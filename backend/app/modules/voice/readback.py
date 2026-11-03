"""Deterministic read-back text (design section 14): customer, quantity with UOM, unit price with currency, total
and dates in the user's time zone — built from the re-read record through the owning service, never from model
text. A voice confirm or approve requires a presented, unexpired read-back of the unchanged record
(``require_presented_readback``).

Example (scenario C): "Nordhaus Möbel GmbH. Quote LK-QT-2026-0009, draft, not sent. 240 pcs Oak serving tray 450 at
EUR 24.00 each. Total EUR 5,760.00. Prepared 12 Oct 2026."
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.core.documents.format import format_date, format_quantity, group_digits
from app.core.errors import Conflict, ValidationFailed
from app.core.money import CURRENCY_EXPONENT
from app.modules.voice.models import VoiceReadback
from app.platform.uow import UnitOfWork

READBACK_TTL = timedelta(minutes=10)
SUPPORTED_SUBJECTS = ("sales.quote",)
MAX_LINES_READ = 5
STATUS_WORDS = {
    "draft": "draft, not sent", "internal_review": "in internal review, not sent", "sent": "sent", "revised": "revised",
    "won": "won", "lost": "lost", "cancelled": "cancelled", "archived": "archived",
}


@dataclass(frozen=True)
class Readback:
    subject_type: str
    subject_id: uuid.UUID
    subject_version: int | None
    text: str
    content_hash: str


def money_words(amount: Decimal | str | None, currency: str, *, unit_price: bool = False) -> str:
    """``EUR 5,760.00`` (ISO code, not a symbol, so it reads aloud the same everywhere); unit prices keep up to four
    decimals but never fewer than the currency's minor unit; INR uses Indian grouping."""
    if amount is None:
        return "not priced"
    value = Decimal(str(amount))
    places = CURRENCY_EXPONENT.get(currency, 2)
    text = format(value.quantize(Decimal(1).scaleb(-(4 if unit_price else places))), "f")
    if unit_price and "." in text:
        whole, fraction = text.split(".")
        fraction = fraction.rstrip("0").ljust(places, "0")
        text = f"{whole}.{fraction}" if fraction else whole
    negative = text.startswith("-")
    whole, _, fraction = text.lstrip("-").partition(".")
    grouped = group_digits(whole, indian=currency == "INR") + (f".{fraction}" if fraction else "")
    return f"{currency} {'-' if negative else ''}{grouped}"


def _hash(facts: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(facts, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def _user_zone(uow: UnitOfWork) -> str:
    from app.platform.identity.models import UserPreference
    from app.platform.org.models import Company

    row = uow.session.get(UserPreference, uow.actor.user_id) if uow.actor.user_id else None
    zone = (row.locale or {}).get("time_zone") if row is not None else None
    if zone:
        return str(zone)
    company_zone = uow.session.scalar(select(Company.default_time_zone).where(Company.id == uow.actor.company_id))
    return company_zone or "Asia/Kolkata"


def quote_readback(uow: UnitOfWork, quote_id: uuid.UUID) -> Readback:
    """Read back a quote through ``sales.quotes.get_quote`` (which authorises; another user's quote is a 404)."""
    from app.modules.sales.quotes import get_quote

    quote = get_quote(uow, quote_id)
    zone = _user_zone(uow)
    currency = quote.currency
    party = quote.party_snapshot.display_name if quote.party_snapshot else quote.party.display_name  # type: ignore[union-attr]
    sentences = [f"{party}.", f"Quote {quote.quote_number}, {STATUS_WORDS.get(str(quote.status), str(quote.status))}."]
    lines = sorted(quote.lines, key=lambda line: line.line_no)
    facts_lines = []
    for line in lines[:MAX_LINES_READ]:
        quantity = format_quantity(Decimal(str(line.quantity)), line.unit_code)
        price = money_words(line.unit_price, line.currency or currency, unit_price=True)
        sentences.append(f"{quantity} {line.description} at {price} each.")
        facts_lines.append([str(line.line_key), str(line.quantity), line.unit_code, str(line.unit_price), line.currency])
    if len(lines) > MAX_LINES_READ:
        sentences.append(f"And {len(lines) - MAX_LINES_READ} more lines.")
    total = quote.totals.grand_total if quote.totals else None
    if total is not None and quote.totals.totals_complete:
        sentences.append(f"Total {money_words(total.amount, total.currency)}.")
    else:
        sentences.append("Total not complete yet.")
    if quote.totals is not None and quote.totals.surcharge_applied:
        sentences.append(f"Includes {quote.totals.surcharge_label} of {money_words(quote.totals.surcharge.amount, currency)}.")
    if quote.valid_until is not None:
        sentences.append(f"Valid until {format_date(quote.valid_until)}.")
    if quote.issued_at is not None:
        sentences.append(f"Issued {format_date(quote.issued_at, zone)}.")
    else:
        sentences.append(f"Prepared {format_date(quote.created_at, zone)}.")
    facts = {
        "quote": str(quote.id), "version": quote.version, "status": str(quote.status), "party": party,
        "currency": currency, "lines": facts_lines, "total": str(total.amount) if total else None,
        "valid_until": quote.valid_until.isoformat() if quote.valid_until else None, "zone": zone,
    }
    return Readback(subject_type="sales.quote", subject_id=quote.id, subject_version=quote.version,
                    text=" ".join(sentences), content_hash=_hash(facts))


def build(uow: UnitOfWork, subject_type: str, subject_id: uuid.UUID) -> Readback:
    if subject_type == "sales.quote":
        return quote_readback(uow, subject_id)
    raise ValidationFailed(
        f"Read-back is available for {', '.join(SUPPORTED_SUBJECTS)}.", code="readback_unsupported",
        errors=[{"loc": ["body", "subject_type"], "msg": "unsupported", "type": "readback_unsupported"}],
    )


def present(uow: UnitOfWork, subject_type: str, subject_id: uuid.UUID) -> VoiceReadback:
    """Build the read-back and record that it was presented to the person (shown and, if enabled, spoken)."""
    readback = build(uow, subject_type, subject_id)
    now = uow.now()
    row = VoiceReadback(
        id=uuid.uuid7(), user_id=uow.actor.user_id, subject_type=readback.subject_type, subject_id=readback.subject_id,
        subject_version=readback.subject_version, content_hash=readback.content_hash, text=readback.text,
        presented_at=now, expires_at=now + READBACK_TTL,
    )
    uow.add(row)
    uow.flush()
    return row


def require_presented_readback(uow: UnitOfWork, subject_type: str, subject_id: uuid.UUID, *, action: str) -> VoiceReadback:
    """The voice confirm/approve guard: the latest read-back of this subject for this person must be unexpired,
    unconsumed and match the record as it is now. Raises 409 ``readback_required`` otherwise; consumes it on success.

    Integrator request: agents/approvals call this before executing a confirm or approve whose channel is voice."""
    row = uow.session.scalars(
        select(VoiceReadback).where(
            VoiceReadback.company_id == uow.actor.company_id, VoiceReadback.user_id == uow.actor.user_id,
            VoiceReadback.subject_type == subject_type, VoiceReadback.subject_id == subject_id,
        ).order_by(VoiceReadback.presented_at.desc()).limit(1).with_for_update()
    ).first()
    now = uow.now()
    if row is None or row.consumed_at is not None:
        raise Conflict("Read the details back before confirming by voice.", code="readback_required", reason="missing")
    if row.expires_at <= now:
        raise Conflict("The read-back expired; read the details back again.", code="readback_required", reason="expired")
    if build(uow, subject_type, subject_id).content_hash != row.content_hash:
        raise Conflict("The record changed since it was read back; read it back again.", code="readback_required",
                       reason="changed")
    row.consumed_at = now
    row.consumed_by = action[:80]
    return row


__all__ = ["READBACK_TTL", "Readback", "build", "money_words", "present", "quote_readback", "require_presented_readback"]
