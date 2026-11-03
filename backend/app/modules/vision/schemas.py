"""Vision API models and the ``screen_capture`` company setting (ai-routing.md section 4.2).

``screen_capture.enabled`` defaults to true in demo and false in live (until the DPDP approval of BUILD_STATE §5
decision 6 is recorded); the personal preference ``assistant.screen_share`` (ask | auto) can never override it.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.modules.agents.schemas import ScreenContext
from app.modules.vision.contract import ExtractionKind
from app.platform.org.settings import SettingDef

ScreenShare = Literal["ask", "auto"]


class ScreenCaptureSetting(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: masked screenshots may be captured and sent to the vision model (mandatory control)
    enabled: bool = True


def _default(uow: Any) -> ScreenCaptureSetting:  # noqa: ARG001 - the default depends on the AI mode only
    from app.core.config import get_settings

    return ScreenCaptureSetting(enabled=get_settings().ai_mode == "demo")


SCREEN_CAPTURE_SETTING = SettingDef(
    key="screen_capture",
    model=ScreenCaptureSetting,
    description=(
        "Masked screenshots for the assistant. On by default in demo; off in live until the DPDP approval to send "
        "masked screenshots to Google is recorded."
    ),
    read_permission="org.settings.read",
    manage_permission="org.settings.manage",
    default=_default,
    owner_module="vision",
)


class VisionCapabilities(BaseModel):
    screen_capture_enabled: bool
    screen_share: ScreenShare
    provider_label: str
    mode: Literal["demo", "live"]
    #: live mode without GEMINI_API_KEY: vision fails visibly (no Demo fallback)
    configured: bool
    max_capture_bytes: int
    max_edge_px: int
    extraction_kinds: list[ExtractionKind]


class ScreenCaptureOut(BaseModel):
    id: uuid.UUID
    sha256: str
    width: int
    height: int
    size_bytes: int
    masked_count: int
    deduplicated: bool
    purge_at: datetime
    status: Literal["attached", "removed", "purged"]


class ScreenAnswerCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capture_id: uuid.UUID
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
    conversation_id: uuid.UUID | None = None
    context: ScreenContext | None = None


class ScreenAnswerOut(BaseModel):
    request_id: uuid.UUID
    status: Literal["answered", "handed_off", "unavailable"]
    text: str
    #: the question needs data or an action: the client sends it to the assistant as a normal turn
    handoff: bool
    handoff_reason: str | None
    provider_label: str
    tainted: bool = True
    capture_sha256: str


class ExtractionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_id: uuid.UUID
    kind: ExtractionKind | None = None
    conversation_id: uuid.UUID | None = None


class ExtractionField(BaseModel):
    key: str
    label: str
    type: str
    #: the confirmed or high-confidence value; None for a confirmation field until the person confirms it
    value: str | None
    #: what the model read for an uncertain field (shown as a hint, never used as a default)
    suggestion: str | None
    confidence: float
    needs_confirmation: bool


class ExtractionLine(BaseModel):
    index: int
    fields: list[ExtractionField]


class ExtractionCard(BaseModel):
    """The structured confirmation card (ai-routing.md section 3, ``visual_extraction``)."""

    kind: Literal["extraction"] = "extraction"
    request_id: uuid.UUID
    status: Literal["extracted", "confirmed", "unavailable"]
    extraction_kind: ExtractionKind
    provider_label: str
    tainted: bool = True
    header: list[ExtractionField]
    lines: list[ExtractionLine]
    pending_confirmations: int
    message: str | None = None
    version: int


ConfirmedValue = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None


class ExtractionConfirm(BaseModel):
    """Every confirmation field must be answered explicitly (a value, or null to leave it empty)."""

    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    header: dict[Annotated[str, StringConstraints(max_length=40)], ConfirmedValue] = Field(default_factory=dict)
    lines: list[dict[Annotated[str, StringConstraints(max_length=40)], ConfirmedValue]] = Field(default_factory=list, max_length=50)


__all__ = [
    "SCREEN_CAPTURE_SETTING",
    "ExtractionCard",
    "ExtractionConfirm",
    "ExtractionCreate",
    "ExtractionField",
    "ExtractionLine",
    "ScreenAnswerCreate",
    "ScreenAnswerOut",
    "ScreenCaptureOut",
    "ScreenCaptureSetting",
    "ScreenShare",
    "VisionCapabilities",
]
