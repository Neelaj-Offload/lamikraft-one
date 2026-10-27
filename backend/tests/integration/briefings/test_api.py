"""HTTP surface: problem+json codes, route kinds, idempotent replays and the UI sections.

A test actor resolver stands in for identity's session resolver (``X-Test-User`` carries a fixture key).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.http import deps
from app.platform.bootstrap import build_sections
from app.seed.world import keys
from tests.integration.briefings.world import FakeWorld, d0

pytestmark = pytest.mark.db


@pytest.fixture
def client(world: FakeWorld) -> Iterator[TestClient]:
    previous = deps._resolver

    def resolve(request):  # type: ignore[no-untyped-def]
        person = request.headers.get("x-test-user")
        return world.actor(person, channel="web") if person else None

    deps.register_actor_resolver(resolve)
    from app.main import create_app

    try:
        yield TestClient(create_app(), headers={"Origin": get_settings().public_origin})
    finally:
        deps._resolver = previous


def as_(person: str, **extra: str) -> dict[str, str]:
    return {"X-Test-User": person, **extra}


def test_today_and_actions_over_http(client: TestClient) -> None:
    r = client.get("/api/v1/briefings/today", headers=as_(keys.USERS.MEERA))
    assert r.status_code == 200
    body = r.json()
    assert body["overview"]["sentence"] == keys.EXPECTED.MEERA_S1_SENTENCE and body["version"] == 1
    assert all(isinstance(m["amount"], str) for i in body["items"] for m in i["money"])
    first = body["items"][0]
    r = client.post(f"/api/v1/briefings/items/{first['issue_id']}/actions", json={"action": "explain"}, headers=as_(keys.USERS.MEERA))
    assert r.status_code == 200 and r.json()["explanation"]["score"] == 75
    r = client.post(f"/api/v1/briefings/items/{first['issue_id']}/actions", json={"action": "mark_handled"}, headers=as_(keys.USERS.MEERA))
    assert r.status_code == 409 and r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["code"] == "not_complete" and r.json()["remaining"] == ["reply_to_customer"]
    r = client.post(f"/api/v1/briefings/items/{first['issue_id']}/actions",
                    json={"action": "snooze", "until": d0(19, 0).isoformat()}, headers=as_(keys.USERS.MEERA))
    assert r.status_code == 422 and r.json()["code"] == "snooze_beyond_deadline" and "max_until" in r.json()
    r = client.post(f"/api/v1/briefings/items/{first['issue_id']}/actions", json={"action": "explain"}, headers=as_(keys.USERS.KABIR))
    assert r.status_code == 404
    r = client.post(f"/api/v1/briefings/{body['briefing_id']}/acknowledge", json={"version": 1}, headers=as_(keys.USERS.MEERA))
    assert r.status_code == 200 and r.json()["accepted"] is True


def test_stale_item_fingerprint_is_409_with_the_fresh_item(client: TestClient) -> None:
    body = client.get("/api/v1/briefings/today", headers=as_(keys.USERS.MEERA)).json()
    issue = body["items"][0]["issue_id"]
    r = client.post(f"/api/v1/briefings/items/{issue}/actions", json={"action": "explain", "item_fingerprint": "0" * 64},
                    headers=as_(keys.USERS.MEERA))
    assert r.status_code == 409 and r.json()["code"] == "item_changed" and r.json()["current"]["issue_id"] == issue


def test_scope_403_unauthenticated_401_and_reminder_404(client: TestClient, world: FakeWorld) -> None:
    assert client.get("/api/v1/tasks/inbox?scope=company", headers=as_(keys.USERS.KABIR)).status_code == 403
    assert client.get("/api/v1/tasks/inbox?scope=company", headers=as_(keys.USERS.SAHIL)).status_code == 200
    assert client.get("/api/v1/briefings/today").status_code == 401
    rid = world.refs[keys.REMINDERS.MEERA]
    assert client.get(f"/api/v1/tasks/reminders/{rid}", headers=as_(keys.USERS.NEHA)).status_code == 404
    assert client.get(f"/api/v1/tasks/reminders/{rid}", headers=as_(keys.USERS.MEERA)).status_code == 200


def test_idempotent_create_replays_the_stored_response(client: TestClient) -> None:
    body = {"text": "Send Berg the revised carton plan", "remind_at": d0(15, 0).isoformat()}
    headers = as_(keys.USERS.MEERA, **{"Idempotency-Key": "0192a3b4-0000-7000-8000-000000000001"})
    first = client.post("/api/v1/tasks/reminders", json=body, headers=headers)
    second = client.post("/api/v1/tasks/reminders", json=body, headers=headers)
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"] and second.headers.get("Idempotent-Replayed") == "true"
    changed = client.post("/api/v1/tasks/reminders", json={**body, "text": "Another"}, headers=headers)
    assert changed.status_code == 422 and changed.json()["code"] == "idempotency_key_reused"


def test_inbox_page_and_task_detail(client: TestClient, world: FakeWorld) -> None:
    page = client.get("/api/v1/tasks/inbox?tab=conversations&limit=1", headers=as_(keys.USERS.MEERA)).json()
    assert len(page["items"]) == 1 and page["next_cursor"]
    second = client.get(f"/api/v1/tasks/inbox?tab=conversations&limit=1&cursor={page['next_cursor']}", headers=as_(keys.USERS.MEERA)).json()
    assert second["items"][0]["id"] != page["items"][0]["id"]
    detail = client.get(f"/api/v1/tasks/tasks/{page['items'][0]['id']}", headers=as_(keys.USERS.MEERA)).json()
    assert detail["capabilities"]["complete"]["allowed"] is True and detail["allowed_transitions"]
    assert client.get(f"/api/v1/tasks/tasks/{page['items'][0]['id']}", headers=as_(keys.USERS.KABIR)).status_code == 404
    counts = client.get("/api/v1/tasks/inbox/counts", headers=as_(keys.USERS.MEERA)).json()
    assert counts == {"tasks": 1, "approvals": 0, "conversations": 2, "exceptions": 0}


def test_ui_sections_inbox_counts_and_briefing(world: FakeWorld) -> None:
    with world.uow(keys.USERS.MEERA) as uow:
        before = build_sections(uow, poll_only=True)
    assert before["briefing"]["status"] == "not_generated" and before["inbox_counts"]["conversations"] == 2
    from app.modules.briefings import service

    with world.uow(keys.USERS.MEERA) as uow:
        service.get_today(uow)
    with world.uow(keys.USERS.MEERA) as uow:
        after = build_sections(uow, poll_only=True)
    assert (after["briefing"]["version"], after["briefing"]["updates_available"]) == (1, 0)
    with world.uow(keys.USERS.KABIR) as uow:
        kabir = build_sections(uow)
    assert kabir["inbox_counts"] == {"tasks": 1, "approvals": 0, "conversations": 0, "exceptions": 0}
