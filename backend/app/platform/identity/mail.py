"""Outbound identity mail (invitations, password resets).

``LK_EMAIL_MODE=demo`` (the default) never sends anything: each message is written as an RFC 5322 ``.eml`` file to
``<LK_STORAGE_DIR>/mail/`` so a developer can open it, and the UI labels the delivery "Demo, not sent". SMTP
delivery is not configured in this build (``smtp`` mode answers 409 ``not_configured``).

Messages are written after the unit of work commits, so a rolled-back invitation never leaves a link behind.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path

from app.core.config import get_settings
from app.core.errors import NotConfigured

SENDER = "Lamikraft One <no-reply@lamikraft.invalid>"


@dataclass(frozen=True)
class Outgoing:
    kind: str  # invitation | password_reset
    to: str
    subject: str
    body: str


def outbox_dir() -> Path:
    return Path(get_settings().storage_dir) / "mail"


def is_demo() -> bool:
    return get_settings().email_mode == "demo"


def require_delivery() -> None:
    if not is_demo():
        raise NotConfigured("Email delivery (SMTP) is not configured in this build.", code="not_configured")


def outbox_name(message: Outgoing, now: datetime) -> str:
    safe_kind = re.sub(r"[^a-z_]", "", message.kind) or "mail"
    return f"{now.strftime('%Y%m%dT%H%M%S')}-{safe_kind}-{uuid.uuid4().hex[:12]}.eml"


def write_demo(message: Outgoing, *, now: datetime, name: str | None = None) -> Path:
    """Write ``message`` to the demo outbox and return the file path."""
    msg = EmailMessage()
    msg["From"] = SENDER
    msg["To"] = message.to
    msg["Subject"] = message.subject
    msg["Date"] = format_datetime(now)
    msg["X-Lamikraft-Delivery"] = "demo (not sent)"
    msg.set_content(message.body)
    folder = outbox_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (name or outbox_name(message, now))
    path.write_bytes(bytes(msg))
    return path


def link(path: str, token: str) -> str:
    """An absolute link carrying the token in the URL fragment (never sent to a server by the browser)."""
    return f"{get_settings().public_origin}{path}#t={token}"
