"""Typed personal preference sections (ADR-039): ui, locale, briefing, voice, assistant.

Read models ignore unknown stored keys (forward compatible) and fill defaults; patch models forbid unknown
fields. Preferences choose presentation only: a field that would weaken a company policy (snooze bounds,
mandatory families, retention, session lifetimes, MFA ...) is refused with 422 ``mandatory_control``.
"""

from __future__ import annotations

from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.errors import AppError

#: keys owned by company policy; a preference may never set them (briefing design §15, ADR-039)
MANDATORY_CONTROL_KEYS: frozenset[str] = frozenset(
    {
        "snooze_max_days",
        "snooze_bounds",
        "unsnoozable_kinds",
        "undismissable_kinds",
        "mandatory_families",
        "exclude_families",
        "include_families",
        "ack_on_view_seconds",
        "sla_workdays",
        "high_value_thresholds",
        "company_quiet_hours",
        "retention_days",
        "channel_sensitivity",
        "mfa_required",
        "session_idle_hours",
        "session_absolute_days",
        "screenshots_disabled",
        "approval_required",
        "permissions",
        "role",
        "roles",
    }
)


class MandatoryControl(AppError):
    status, code, title = 422, "mandatory_control", "Preferences cannot change company policy"


class _Read(BaseModel):
    model_config = ConfigDict(extra="ignore")


class _Patch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _no_policy_keys(cls, data: Any) -> Any:
        if isinstance(data, dict):
            blocked = sorted(k for k in data if isinstance(k, str) and k in MANDATORY_CONTROL_KEYS)
            if blocked:
                raise MandatoryControl(
                    "These settings are company policy, not personal preferences.", fields=blocked
                )
        return data


Theme = Literal["system", "light", "dark"]
Motion = Literal["full", "reduced"]
Density = Literal["comfortable", "compact"]
LocaleCode = Literal["en-IN", "en-GB", "en-US", "hi-IN"]
BriefingLanguage = Literal["en", "hi"]
DetailLevel = Literal["brief", "standard", "detailed"]
#: hi-IN and Hinglish are labelled "Untested" until a recorded phrase set passes (BUILD_STATE section 5 #5)
SpeechLanguage = Literal["en-IN", "hi-IN", "hinglish"]
#: masked screenshots: ask before each one, or attach for router-classified visual requests (ai-routing.md 4.2)
ScreenShare = Literal["ask", "auto"]
ResponseStyle = Literal["concise", "detailed"]


def _zone(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError("unknown IANA time zone") from None
    return value


# ---- read models (defaults filled) -----------------------------------------------------------------
class UiPreferences(_Read):
    theme: Theme = "system"
    motion: Motion = "full"
    sidebar_collapsed: bool = False
    context_rail_open: bool = True
    density: Density = "comfortable"
    shortcuts_enabled: bool = True


class LocalePreferences(_Read):
    locale: LocaleCode | None = None
    time_zone: str | None = None


class BriefingPreferences(_Read):
    language: BriefingLanguage = "en"
    detail_level: DetailLevel = "standard"


class VoicePreferences(_Read):
    speech_language: SpeechLanguage = "en-IN"
    speak_responses: bool = False
    read_back_values: bool = True


class AssistantPreferences(_Read):
    proactive_suggestions: bool = True
    response_style: ResponseStyle = "concise"
    screen_share: ScreenShare = "ask"


SECTIONS: dict[str, type[_Read]] = {
    "ui": UiPreferences,
    "locale": LocalePreferences,
    "briefing": BriefingPreferences,
    "voice": VoicePreferences,
    "assistant": AssistantPreferences,
}


class Preferences(BaseModel):
    version: int
    ui: UiPreferences
    locale: LocalePreferences
    briefing: BriefingPreferences
    voice: VoicePreferences
    assistant: AssistantPreferences


# ---- patch models (dirty fields only) --------------------------------------------------------------
class UiPreferencesPatch(_Patch):
    theme: Theme | None = None
    motion: Motion | None = None
    sidebar_collapsed: bool | None = None
    context_rail_open: bool | None = None
    density: Density | None = None
    shortcuts_enabled: bool | None = None


class LocalePreferencesPatch(_Patch):
    locale: LocaleCode | None = None
    time_zone: str | None = Field(default=None, max_length=64)

    @field_validator("time_zone")
    @classmethod
    def _valid_zone(cls, value: str | None) -> str | None:
        return _zone(value)


class BriefingPreferencesPatch(_Patch):
    language: BriefingLanguage | None = None
    detail_level: DetailLevel | None = None


class VoicePreferencesPatch(_Patch):
    speech_language: SpeechLanguage | None = None
    speak_responses: bool | None = None
    read_back_values: bool | None = None


class AssistantPreferencesPatch(_Patch):
    proactive_suggestions: bool | None = None
    response_style: ResponseStyle | None = None
    screen_share: ScreenShare | None = None


class PreferencesPatch(_Patch):
    """Dirty sections plus ``expected_version`` (api-conventions §6): the version the client read (0 before the
    first save). A mismatch is 409 ``version_conflict`` carrying the current preferences."""

    expected_version: int = Field(ge=0)
    ui: UiPreferencesPatch | None = None
    locale: LocalePreferencesPatch | None = None
    briefing: BriefingPreferencesPatch | None = None
    voice: VoicePreferencesPatch | None = None
    assistant: AssistantPreferencesPatch | None = None


#: fields that may be cleared with an explicit null (everything else treats null as "unchanged")
NULLABLE_FIELDS = {("locale", "locale"), ("locale", "time_zone")}


def read(stored: dict[str, dict[str, Any] | None], version: int) -> Preferences:
    return Preferences(
        version=version,
        **{name: model.model_validate(stored.get(name) or {}) for name, model in SECTIONS.items()},  # type: ignore[arg-type]
    )


def apply_patch(stored: dict[str, dict[str, Any] | None], patch: PreferencesPatch) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Merge a patch into stored sections. Returns (new sections, changed ``section.field`` names)."""
    out: dict[str, dict[str, Any]] = {}
    changed: list[str] = []
    for name, model in SECTIONS.items():
        current = model.model_validate(stored.get(name) or {}).model_dump(mode="json")
        section_patch = getattr(patch, name)
        if section_patch is not None:
            for field, value in section_patch.model_dump(mode="json", exclude_unset=True).items():
                if value is None and (name, field) not in NULLABLE_FIELDS:
                    continue
                if current.get(field) != value:
                    current[field] = value
                    changed.append(f"{name}.{field}")
        out[name] = current
    return out, changed


def ui_cookie_value(ui: UiPreferences) -> str:
    """The ``lk_ui`` cookie mirrors theme and motion for server rendering (apps/web/src/lib/ui-preferences.ts)."""
    return f"theme={ui.theme}&motion={ui.motion}"
