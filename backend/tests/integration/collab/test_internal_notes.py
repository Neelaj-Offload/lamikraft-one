"""PARITY LM-99 / API-69 / UI-66 backend: the autosaved internal note of any record (legacy: any login could
overwrite any note). Reads need the parent's read, writes its update; a stale version is a 409 with the server text."""

from __future__ import annotations

import pytest

from app.platform.authz.permissions import Scope
from app.seed.world import keys
from tests.integration.collab.conftest import PARENT_TYPE, make_parent
from tests.integration.org.platform_lane import ApiClient, member

pytestmark = pytest.mark.db

URL = "/api/v1/collab/notes"


def test_autosave_conflict_409_and_parent_update_required(api: ApiClient, company, parent_table) -> None:  # type: ignore[no-untyped-def]
    company_id, _ = company
    meera = member(company_id, keys.PEOPLE["MEERA"].name, "sales")
    neha = member(company_id, keys.PEOPLE["NEHA"].name, "sales")
    ravi = member(company_id, keys.PEOPLE["RAVI"].name, "employee", extra={"sales.quote.read": Scope.COMPANY})
    parent = make_parent(company_id, meera.user_id)
    params = {"resource_type": PARENT_TYPE, "resource_id": str(parent)}

    # owner saves (version 0 -> 1), then a second tab saves on top
    api.as_(meera.actor())
    first = api.put(URL, params=params, json={"body": "Call back Friday", "expected_version": 0})
    assert first.status_code == 200 and first.json()["version"] == 1
    second = api.put(URL, params=params, json={"body": "Call back Monday", "expected_version": 1})
    assert second.status_code == 200 and second.json()["version"] == 2

    # a stale autosave gets 409 with the server's text, author and version for the merge
    stale = api.put(URL, params=params, json={"body": "My older text", "expected_version": 1})
    assert stale.status_code == 409
    body = stale.json()
    assert body["code"] == "version_conflict" and body["current_version"] == 2
    assert body["current"]["body"] == "Call back Monday"

    # a reader without update right: sees the note, 403 on write; a peer who cannot see the record: 404 both ways
    api.as_(ravi.actor())
    seen = api.get(URL, params=params)
    assert seen.status_code == 200 and seen.json()["capabilities"]["update"]["allowed"] is False
    assert api.put(URL, params=params, json={"body": "overwrite", "expected_version": 2}).status_code == 403
    api.as_(neha.actor())
    assert api.get(URL, params=params).status_code == 404
    assert api.put(URL, params=params, json={"body": "overwrite", "expected_version": 2}).status_code == 404

    api.as_(meera.actor())
    assert api.get(URL, params=params).json()["body"] == "Call back Monday"
