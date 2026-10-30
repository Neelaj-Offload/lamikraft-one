"""Fixtures for the cutting lane's tests: personas, the catalogue world (parties, catalogue, pricing, commercial) at D0
and an HTTP client over the real app (persona from ``x-test-persona``; the identity lane owns sessions)."""

from collections.abc import Iterator

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.http.deps import get_actor
from app.platform.authz.context import ActorContext
from app.seed.world import keys
from tests.integration.catalogue.world import member_actors, personas  # noqa: F401
from tests.integration.sales.world import SalesWorld, world  # noqa: F401


@pytest.fixture(scope="module")
def api_app() -> FastAPI:
    from app.main import create_app

    return create_app()


@pytest.fixture
def client(api_app: FastAPI, world: SalesWorld) -> Iterator[TestClient]:  # noqa: F811
    """Default persona Ravi (operations, branch scope)."""

    def resolve(request: Request) -> ActorContext:
        persona = request.headers.get("x-test-persona", keys.USERS.RAVI)
        return world.actor(persona).with_(idempotency_key=request.headers.get("idempotency-key"))

    api_app.dependency_overrides[get_actor] = resolve
    try:
        with TestClient(api_app, headers={"Origin": get_settings().public_origin}) as c:
            yield c
    finally:
        api_app.dependency_overrides.clear()
