"""Typed preference sections: merge rules, nullable clears, unknown fields and mandatory controls."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.platform.identity.preferences import (
    MANDATORY_CONTROL_KEYS,
    MandatoryControl,
    PreferencesPatch,
    UiPreferences,
    apply_patch,
    read,
    ui_cookie_value,
)


def test_defaults_fill_every_section() -> None:
    prefs = read({}, 0)
    assert prefs.ui.theme == "system" and prefs.ui.motion == "full" and prefs.ui.shortcuts_enabled
    assert prefs.locale.locale is None and prefs.locale.time_zone is None
    assert prefs.briefing.detail_level == "standard" and prefs.voice.speech_language == "en-IN"
    assert prefs.assistant.response_style == "concise"


def test_stored_unknown_keys_are_ignored_on_read() -> None:
    prefs = read({"ui": {"theme": "dark", "retired_field": 1}}, 4)
    assert prefs.version == 4 and prefs.ui.theme == "dark"


def test_patch_changes_only_dirty_fields() -> None:
    stored = {"ui": {"theme": "dark", "density": "compact"}}
    patch = PreferencesPatch.model_validate({"ui": {"motion": "reduced"}, "voice": {"speak_responses": True}})
    sections, changed = apply_patch(stored, patch)
    assert sections["ui"]["theme"] == "dark" and sections["ui"]["density"] == "compact"
    assert sections["ui"]["motion"] == "reduced" and sections["voice"]["speak_responses"] is True
    assert changed == ["ui.motion", "voice.speak_responses"]


def test_null_means_unchanged_except_for_clearable_fields() -> None:
    stored = {"ui": {"theme": "dark"}, "locale": {"time_zone": "Europe/Berlin", "locale": "en-GB"}}
    patch = PreferencesPatch.model_validate({"ui": {"theme": None}, "locale": {"time_zone": None}})
    sections, changed = apply_patch(stored, patch)
    assert sections["ui"]["theme"] == "dark"
    assert sections["locale"] == {"locale": "en-GB", "time_zone": None}
    assert changed == ["locale.time_zone"]


def test_unknown_fields_and_bad_values_are_rejected() -> None:
    with pytest.raises(ValidationError):
        PreferencesPatch.model_validate({"ui": {"font": "comic"}})
    with pytest.raises(ValidationError):
        PreferencesPatch.model_validate({"ui": {"theme": "neon"}})
    with pytest.raises(ValidationError):
        PreferencesPatch.model_validate({"locale": {"time_zone": "Mars/Olympus"}})
    with pytest.raises(ValidationError):
        PreferencesPatch.model_validate({"briefing": {"detail_level": 3.5}})


@pytest.mark.parametrize("key", sorted(MANDATORY_CONTROL_KEYS))
def test_policy_keys_are_mandatory_controls(key: str) -> None:
    for payload in ({"briefing": {key: 1}}, {"ui": {key: True}}, {key: "x"}):
        with pytest.raises(MandatoryControl) as exc:
            PreferencesPatch.model_validate(payload)
        assert exc.value.status == 422 and exc.value.code == "mandatory_control"


def test_ui_cookie_mirrors_theme_and_motion() -> None:
    assert ui_cookie_value(UiPreferences(theme="dark", motion="reduced")) == "theme=dark&motion=reduced"
