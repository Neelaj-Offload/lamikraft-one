"""PARITY PERM-19 / PERM-23 / PERM-24 / SEC-01 (route level): every non-public route on this branch refuses a
caller without a session, for every method, before any input is read; record-level denial (404/403 per persona)
is covered by tests/integration/security/test_isolation_matrix.py and the module IDOR suites."""

from __future__ import annotations

import re
import uuid

from fastapi.routing import APIRoute, iter_route_contexts
from fastapi.testclient import TestClient

from app.core.config import get_settings

OPEN_KINDS = {"public", "webhook", "test_support"}


def _routes(app):  # type: ignore[no-untyped-def]
    for ctx in iter_route_contexts(app.routes):
        route = ctx.original_route
        path = str(ctx.path)
        if not isinstance(route, APIRoute) or not path.startswith("/api/"):
            continue
        kind = ((route.openapi_extra or {}).get("x-authz") or {}).get("kind")
        for method in sorted(ctx.methods or ()):
            yield method, path, kind


def test_every_route_denies_unauthorised_personas() -> None:
    from app.main import create_app

    app = create_app()
    client = TestClient(app, base_url="http://testserver")  # no lifespan, no session cookie
    origin = {"Origin": get_settings().public_origin}
    checked, problems = 0, []
    for method, path, kind in _routes(app):
        if kind in OPEN_KINDS:
            continue
        concrete = re.sub(r"{[^}]+}", str(uuid.uuid7()), path)
        r = client.request(method, concrete, headers=origin, json={} if method in {"POST", "PUT", "PATCH", "DELETE"} else None)
        checked += 1
        if r.status_code != 401:
            problems.append(f"{method} {path}: {r.status_code}")
        elif "application/problem+json" not in r.headers.get("content-type", ""):
            problems.append(f"{method} {path}: 401 without problem+json")
    assert problems == []
    assert checked > 100
