"""Fixtures for the challans lane's tests: personas, the catalogue world, the challan world at D0 and the HTTP client."""

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
from tests.integration.catalogue.world import member_actors, personas  # noqa: F401
from tests.integration.challans.world import ChallanWorld, challan_world, world  # noqa: F401
from tests.integration.inventory.world import inv_world  # noqa: F401
from tests.integration.sales.http import api_app  # noqa: F401

API = "/api/v1"
CHALLANS = f"{API}/challans/challans"


@pytest.fixture
def challan_client(api_app: FastAPI, challan_world: ChallanWorld) -> Iterator[TestClient]:  # noqa: F811
    """A client over the challan world at D0 (default persona Ravi, operations)."""

    def resolve(request: Request) -> ActorContext:
        persona = request.headers.get("x-test-persona", keys.USERS.RAVI)
        return challan_world.actor(persona).with_(idempotency_key=request.headers.get("idempotency-key"))

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
