"""Fixtures for the agents lane: the seeded fixture world (catalogue lane's personas), the fake sales tools
(``fake_sales.py`` — the single switch point for the real tools) and an API client that resolves the persona from
the ``x-test-persona`` header exactly as a session would."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.http.deps import get_actor
from app.platform.authz.context import ActorContext
from app.platform.uow import UnitOfWork
from app.seed.world import keys
from tests.integration.agents import fake_sales
from tests.integration.catalogue.world import World, member_actors, personas, world  # noqa: F401
from tests.support import drain

API = "/api/v1"


@pytest.fixture
def sales_tools(world: World) -> Iterator[fake_sales.FakeSalesStore]:
    """Register the fake sales tools and readers and seed the prior won quote (LK-QT-2026-0003)."""
    fake_sales.register()
    try:
        with UnitOfWork(world.actor(keys.USERS.MEERA)) as uow:
            fake_sales.seed_prior_won_quote(
                uow, party_id=world.ref("NORDHAUS"), owner_user_id=world.user_id(keys.USERS.MEERA),
                party_name=keys.PARTY_NAMES["NORDHAUS"],
            )
        yield fake_sales.STORE
    finally:
        fake_sales.unregister()


@pytest.fixture(scope="module")
def app() -> FastAPI:
    from app.main import create_app

    return create_app()


@pytest.fixture
def client(app: FastAPI, world: World) -> Iterator[TestClient]:
    def resolve(request: Request) -> ActorContext:
        persona = request.headers.get("x-test-persona", keys.USERS.MEERA)
        return world.actor(persona).with_(idempotency_key=request.headers.get("idempotency-key"), channel="web")

    app.dependency_overrides[get_actor] = resolve
    try:
        with TestClient(app, headers={"Origin": get_settings().public_origin}) as c:
            yield c
    finally:
        app.dependency_overrides.clear()


class Assistant:
    """Drive the agents API as a persona: create a conversation, post a turn, drain the worker, poll the run."""

    def __init__(self, client: TestClient, persona: str = keys.USERS.MEERA) -> None:
        self.client = client
        self.persona = persona
        self.headers = {"x-test-persona": persona}
        self.conversation_id: uuid.UUID | None = None

    def start(self, channel: str = "web") -> dict[str, Any]:
        response = self.client.post(f"{API}/agents/conversations", json={"channel": channel}, headers=self.headers)
        assert response.status_code == 201, response.text
        body = response.json()
        self.conversation_id = uuid.UUID(body["id"])
        return body

    def post_turn(self, text: str = "", **extra: Any) -> Any:
        if self.conversation_id is None:
            self.start()
        body: dict[str, Any] = {"text": text, **extra}
        return self.client.post(f"{API}/agents/conversations/{self.conversation_id}/turns", json=body, headers=self.headers)

    def poll(self, run_id: str, after_seq: int = 0) -> dict[str, Any]:
        response = self.client.get(f"{API}/agents/runs/{run_id}", params={"after_seq": after_seq}, headers=self.headers)
        assert response.status_code == 200, response.text
        return response.json()

    def say(self, text: str = "", **extra: Any) -> dict[str, Any]:
        """Post a turn (202), drain the job inline, return the finished run detail with all steps."""
        response = self.post_turn(text, **extra)
        assert response.status_code == 202, response.text
        run_id = response.json()["run_id"]
        drain()
        detail = self.poll(run_id)
        assert detail["done"], detail
        return detail

    def conversation(self) -> dict[str, Any]:
        response = self.client.get(f"{API}/agents/conversations/{self.conversation_id}", headers=self.headers)
        assert response.status_code == 200, response.text
        return response.json()


@pytest.fixture
def meera(client: TestClient, sales_tools: fake_sales.FakeSalesStore) -> Assistant:
    return Assistant(client, keys.USERS.MEERA)


def tool_calls(detail: dict[str, Any]) -> list[str]:
    return [s["name"] for s in detail["steps"] if s["kind"] == "tool_call"]


def cards_of(detail: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    return [c for c in detail["cards"] if c["kind"] == kind]
