"""System API models."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel


class IntegrationRead(BaseModel):
    key: str
    label: str
    mode: Literal["demo", "live"]
    state: Literal["not_connected", "connected", "error"]
    #: UI label: "Demo" in demo mode, otherwise the state ("Connected", "Not connected", "Error")
    label_text: str
    verified_at: datetime | None
    last_checked_at: datetime | None
    last_error_code: str | None
    details: dict[str, Any] | None
