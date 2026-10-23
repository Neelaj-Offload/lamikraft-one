"""Integration status: configured mode, truthful state, 'connected' only through a verification routine."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.config import reset_settings_cache
from app.core.errors import Forbidden, NotConfigured
from app.platform.authz.context import ActorContext
from app.platform.bootstrap import build_sections, registered_sections
from app.platform.system import service as status
from app.platform.system.integrations import (
    IntegrationDef,
    VerificationResult,
    integration_def,
    register_integration,
)
from app.platform.system.models import IntegrationMode, IntegrationStatus
from app.platform.uow import UnitOfWork
from app.seed.world import keys
from tests.integration.org.platform_lane import ApiClient, audit_rows, events, member, problem

pytestmark = pytest.mark.db
URL = "/api/v1/system/integrations"
KEYS = ["accounting", "ai.anthropic", "ai.gemini", "channels.whatsapp", "email", "storage"]


@pytest.fixture
def people(company):  # type: ignore[no-untyped-def]
    company_id, _ = company
    return {
        "company_id": company_id,
        "priya": member(company_id, keys.PEOPLE["PRIYA"].name, "admin"),
        "meera": member(company_id, keys.PEOPLE["MEERA"].name, "sales"),
    }


@pytest.fixture
def live_ai(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("LK_AI_MODE", "live")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEY", "test-only-not-a-real-key")
    reset_settings_cache()
    yield
    monkeypatch.undo()
    reset_settings_cache()


def _by_key(rows: list[dict]) -> dict[str, dict]:  # type: ignore[type-arg]
    return {r["key"]: r for r in rows}


def test_everything_is_demo_and_not_connected_by_default(api: ApiClient, people) -> None:  # type: ignore[no-untyped-def]
    r = api.as_(people["priya"].actor()).get(URL)
    assert r.status_code == 200, r.text
    rows = r.json()
    assert [row["key"] for row in rows] == KEYS
    assert {(row["mode"], row["state"], row["label_text"]) for row in rows} == {("demo", "not_connected", "Demo")}
    assert all(row["verified_at"] is None for row in rows)


def test_integration_status_is_admin_only(api: ApiClient, people) -> None:  # type: ignore[no-untyped-def]
    r = api.as_(people["meera"].actor()).get(URL)
    assert r.status_code == 403 and problem(r)["code"] == "permission_denied"


def test_live_mode_with_a_missing_secret_fails_visibly(api: ApiClient, people, live_ai) -> None:  # type: ignore[no-untyped-def]
    rows = _by_key(api.as_(people["priya"].actor()).get(URL).json())
    anthropic = rows["ai.anthropic"]
    assert (anthropic["mode"], anthropic["state"], anthropic["label_text"]) == ("live", "error", "Error")
    assert anthropic["last_error_code"] == "secret_missing"
    assert anthropic["details"] == {"missing": ["ANTHROPIC_API_KEY"]}
    gemini = rows["ai.gemini"]  # configured but never verified: not connected, never "connected" by config
    assert (gemini["mode"], gemini["state"], gemini["label_text"]) == ("live", "not_connected", "Not connected")
    assert "test-only-not-a-real-key" not in api.get(URL).text


def test_connected_only_after_verification(people, live_ai) -> None:  # type: ignore[no-untyped-def]
    company_id = people["company_id"]
    admin = people["priya"].actor()
    ok = status.record_verification(admin, "ai.gemini", VerificationResult(ok=True, details={"api_version": "v1"}))
    assert (ok.state, ok.label_text, ok.details) == ("connected", "Connected", {"api_version": "v1"})
    assert ok.verified_at is not None
    failed = status.record_verification(admin, "ai.gemini", VerificationResult(ok=False, error_code="auth_failed"))
    assert (failed.state, failed.last_error_code, failed.verified_at) == ("error", "auth_failed", None)
    changes = [e.payload for e in events(company_id, "system.integration.status_changed")]
    assert changes == [
        {"integration_key": "ai.gemini", "mode": "live", "state_from": "not_connected", "state_to": "connected",
         "origin": "user"},
        {"integration_key": "ai.gemini", "mode": "live", "state_from": "connected", "state_to": "error",
         "origin": "user"},
    ]
    outcomes = [r.outcome for r in audit_rows(company_id, "system.integration.verified")]
    assert outcomes == ["success", "failed"]


def test_a_verification_for_another_mode_does_not_count(people, live_ai, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    admin = people["priya"].actor()
    status.record_verification(admin, "ai.gemini", VerificationResult(ok=True))
    monkeypatch.setenv("LK_AI_MODE", "demo")
    reset_settings_cache()
    row = {r.key: r for r in status.list_integrations(admin)}["ai.gemini"]
    assert (row.mode, row.state, row.label_text) == ("demo", "not_connected", "Demo")


def test_the_database_refuses_connected_without_verification(people) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(IntegrityError, match="connected_requires_verification"):
        with UnitOfWork(ActorContext.system(people["company_id"])) as uow:
            uow.add(IntegrationStatus(integration_key="email", mode=IntegrationMode.DEMO.value, state="connected"))


def test_verification_routines_drive_the_state(people, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    admin = people["priya"].actor()
    with pytest.raises(NotConfigured):
        status.run_verification(admin, "email")
    original = integration_def("email")
    assert original is not None
    register_integration(
        IntegrationDef(key="email", label=original.label, configured_mode=original.configured_mode,
                       verify=lambda _uow: VerificationResult(ok=True, details={"transport": "demo-eml"}))
    )
    try:
        result = status.run_verification(admin, "email")
        assert (result.state, result.label_text) == ("connected", "Demo")  # demo mode is always labelled Demo
    finally:
        register_integration(original)


def test_recording_needs_manage_permission(people) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(Forbidden):
        status.record_verification(people["meera"].actor(), "email", VerificationResult(ok=True))


def test_ui_section_exposes_modes_to_every_member(people) -> None:  # type: ignore[no-untyped-def]
    section = {s.key: s for s in registered_sections()}["integrations"]
    assert section.in_poll is False
    with UnitOfWork(people["meera"].actor()) as uow:
        built = build_sections(uow)["integrations"]
    assert [i["key"] for i in built["integrations"]] == KEYS
    assert set(built["integrations"][0]) == {"key", "label", "mode", "state", "label_text"}
