"""The 24-hour customer service window and template eligibility (design §15 "Outbound")."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from app.modules.channels.models import ChannelIdentity, WaTemplate
from app.platform.uow import UnitOfWork

WINDOW = timedelta(hours=24)
#: template statuses that may be sent; anything else blocks with the status as the reason
SENDABLE_TEMPLATE_STATUSES = frozenset({"approved"})


def window_open(identity: ChannelIdentity, now: datetime) -> bool:
    return identity.last_inbound_at is not None and now - identity.last_inbound_at < WINDOW


def window_closes_at(identity: ChannelIdentity) -> datetime | None:
    return identity.last_inbound_at + WINDOW if identity.last_inbound_at else None


def template_check(uow: UnitOfWork, template_id: uuid.UUID | None) -> tuple[WaTemplate | None, str | None]:
    """(template, block reason). A missing template or one that is paused, disabled, rejected or pending blocks."""
    if template_id is None:
        return None, "template_missing"
    template = uow.session.get(WaTemplate, template_id)
    if template is None or template.company_id != uow.actor.company_id:
        return None, "template_missing"
    if template.status not in SENDABLE_TEMPLATE_STATUSES:
        return template, f"template_{template.status}"
    return template, None


__all__ = ["SENDABLE_TEMPLATE_STATUSES", "WINDOW", "template_check", "window_closes_at", "window_open"]
