"""Route declarations and the test-support boundary.

``app.core.http.authz_decl.validate_routes`` walks ``app.routes`` for ``APIRoute`` objects, but FastAPI 0.143 wraps
included routers in ``_IncludedRouter``, so the startup check sees no API route at all. Until the integrator fixes
the kernel check, this contract test proves from the OpenAPI document that every mounted ``/api`` operation
declares exactly one valid kind and only registered permission keys.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings, reset_settings_cache
from app.core.http.authz_decl import KINDS
from app.registry import get_registry

EXPECTED = {
    ("POST", "/api/v1/identity/session"): ("identity_create_session", "public"),
    ("DELETE", "/api/v1/identity/session"): ("identity_delete_session", "authenticated"),
    ("POST", "/api/v1/identity/demo-sign-in"): ("identity_create_demo_session", "public"),
    ("GET", "/api/v1/identity/me"): ("identity_get_me", "authenticated"),
    ("PATCH", "/api/v1/identity/me/preferences"): ("identity_update_preferences", "authenticated"),
    ("POST", "/api/v1/identity/me/password"): ("identity_update_password", "authenticated"),
    ("GET", "/api/v1/identity/users/{user_id}/permission-overrides"): ("identity_list_permission_overrides", "permission"),
    ("PUT", "/api/v1/identity/users/{user_id}/permission-overrides/{permission_key}"): (
        "identity_set_permission_override",
        "permission",
    ),
    ("DELETE", "/api/v1/identity/users/{user_id}/permission-overrides/{permission_key}"): (
        "identity_delete_permission_override",
        "permission",
    ),
    ("GET", "/api/v1/session/bootstrap"): ("ui_get_session_bootstrap", "authenticated"),
    ("GET", "/api/v1/ui/poll"): ("ui_poll_sections", "authenticated"),
    ("POST", "/api/v1/_test/sign-in"): ("identity_create_test_session", "test_support"),
    ("GET", "/api/v1/_test/fixtures"): ("identity_get_test_fixtures", "test_support"),
    ("POST", "/api/v1/_test/clock"): ("identity_update_test_clock", "test_support"),
}


def _operations(spec: dict) -> dict[tuple[str, str], dict]:  # type: ignore[type-arg]
    return {
        (method.upper(), path): op
        for path, item in spec["paths"].items()
        for method, op in item.items()
        if method in {"get", "post", "put", "patch", "delete"}
    }


@pytest.fixture
def development_env() -> Iterator[None]:
    previous = os.environ.get("LK_ENV")
    os.environ["LK_ENV"] = "development"
    reset_settings_cache()
    try:
        yield
    finally:
        os.environ["LK_ENV"] = previous or "test"
        reset_settings_cache()


def test_every_api_operation_declares_a_valid_authz_kind() -> None:
    from app.main import create_app

    assert get_settings().is_test  # test-support routes are part of this document
    operations = _operations(create_app().openapi())
    known = set(get_registry().permissions)
    problems = []
    for (method, path), op in operations.items():
        if not path.startswith("/api/"):
            continue
        decl = op.get("x-authz")
        if not isinstance(decl, dict) or decl.get("kind") not in KINDS:
            problems.append(f"{method} {path}: missing or invalid x-authz")
        elif decl["kind"] == "permission":
            problems += [f"{method} {path}: unknown permission {k}" for k in decl.get("permissions", []) if k not in known]
        if path.startswith("/api/v1/_test/") and decl and decl.get("kind") != "test_support":
            problems.append(f"{method} {path}: test-support paths must be test_support routes")
    assert problems == []


def test_identity_and_ui_operations() -> None:
    from app.main import create_app

    operations = _operations(create_app().openapi())
    for (method, path), (operation_id, kind) in EXPECTED.items():
        op = operations[(method, path)]
        assert op["operationId"] == operation_id
        assert op["x-authz"]["kind"] == kind


def test_test_support_is_absent_outside_the_test_environment(development_env: None) -> None:
    from app.main import create_app

    assert not get_settings().is_test
    app = create_app()
    assert not [p for p in app.openapi()["paths"] if p.startswith("/api/v1/_test")]
    origin = {"Origin": get_settings().public_origin}
    with TestClient(app) as client:
        assert client.post("/api/v1/_test/sign-in", json={"user_key": "MEERA"}, headers=origin).status_code == 404
        assert client.get("/api/v1/_test/fixtures").status_code == 404
        assert client.post("/api/v1/_test/clock", json={"at": "2026-10-12T03:25:00Z"}, headers=origin).status_code == 404


def test_test_support_handlers_refuse_outside_the_test_environment(development_env: None) -> None:
    from app.core.errors import NotFound
    from app.platform.identity import testsupport

    with pytest.raises(NotFound):
        testsupport.fixtures()
    with pytest.raises(NotFound):
        testsupport.set_clock(testsupport.ClockRequest(at="2026-10-12T03:25:00Z"))  # type: ignore[arg-type]


def test_auth_tokens_are_never_query_parameters() -> None:
    from app.main import create_app

    for (method, path), op in _operations(create_app().openapi()).items():
        if path.startswith(("/api/v1/identity", "/api/v1/session", "/api/v1/ui", "/api/v1/_test")):
            assert not [p for p in op.get("parameters", []) if p.get("in") == "query"], f"{method} {path}"
