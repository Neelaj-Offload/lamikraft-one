"""GET /api/v1/ui/poll: poll-only sections with ETag / 304."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.platform.bootstrap import _SECTIONS, UiSection, register_ui_section
from app.seed.context import SeedContext
from app.seed.world import keys
from tests.integration.identity.fixtures import test_sign_in

pytestmark = pytest.mark.db

POLL = "/api/v1/ui/poll"
_counter = {"n": 1}


@pytest.fixture
def sections() -> Iterator[None]:
    saved = dict(_SECTIONS)
    register_ui_section(UiSection("probe_inbox", lambda uow: {"open": _counter["n"]}, in_poll=True))
    register_ui_section(UiSection("probe_static", lambda uow: {"x": 1}, in_poll=False))
    yield
    _SECTIONS.clear()
    _SECTIONS.update(saved)


def test_poll_etag_and_not_modified(client: TestClient, world: SeedContext, sections: None) -> None:
    test_sign_in(client, keys.USERS.MEERA)
    _counter["n"] = 1
    first = client.get(POLL)
    assert first.status_code == 200
    assert first.json()["sections"]["probe_inbox"] == {"open": 1}
    assert "probe_static" not in first.json()["sections"]  # bootstrap-only sections are not polled
    etag = first.headers["ETag"]
    again = client.get(POLL, headers={"If-None-Match": etag})
    assert again.status_code == 304 and again.headers["ETag"] == etag and again.content == b""
    assert client.get(POLL, headers={"If-None-Match": f"W/{etag}"}).status_code == 304
    _counter["n"] = 2
    changed = client.get(POLL, headers={"If-None-Match": etag})
    assert changed.status_code == 200 and changed.headers["ETag"] != etag
    assert changed.json()["sections"]["probe_inbox"] == {"open": 2}


def test_poll_needs_a_session(client: TestClient, world: SeedContext) -> None:
    r = client.get(POLL)
    assert r.status_code == 401 and r.json()["code"] == "unauthenticated"
