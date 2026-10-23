"""Briefing problem codes (api-conventions §3)."""

from __future__ import annotations

from app.core.errors import AppError, Conflict


class PinEnded(AppError):
    status, code, title = 410, "pin_ended", "This listening session has ended"


class ItemChanged(Conflict):
    code, title = "item_changed", "This item changed since you opened it"
