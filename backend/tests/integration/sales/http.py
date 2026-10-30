"""HTTP fixtures for the sales lane: the real FastAPI app with the authenticated-actor dependency resolving the persona
named in ``x-test-persona`` (the identity lane owns sessions; see tests/integration/catalogue/test_lane_api.py)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.http.deps import get_actor
from app.platform.authz.context import ActorContext
from app.seed.world import keys
from tests.integration.sales.world import SalesWorld

API = "/api/v1"


@pytest.fixture(scope="module")
def api_app() -> FastAPI:
    from app.main import create_app

    return create_app()


@pytest.fixture
def sales_client(api_app: FastAPI, sales_world: SalesWorld) -> Iterator[TestClient]:
    """A client over the full Slice-1 sales world at D0 (default persona Meera)."""

    def resolve(request: Request) -> ActorContext:
        persona = request.headers.get("x-test-persona", keys.USERS.MEERA)
        return sales_world.actor(persona).with_(idempotency_key=request.headers.get("idempotency-key"))

    api_app.dependency_overrides[get_actor] = resolve
    try:
        with TestClient(api_app, headers={"Origin": get_settings().public_origin}) as client:
            yield client
    finally:
        api_app.dependency_overrides.clear()


def as_(persona: str, **extra: str) -> dict[str, str]:
    return {"x-test-persona": persona, **extra}


def problem(response: Any, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    body: dict[str, Any] = response.json()
    assert body["code"] == code, body
    return body
