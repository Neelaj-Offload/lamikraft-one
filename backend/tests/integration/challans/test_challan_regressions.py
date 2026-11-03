"""Named regressions for the legacy challan defects (PLAN §10.1 #13 and #14; SEC-06) and global search (LM-96).

- BUG-14: the legacy ``PUT /challans/{id}`` accepted any status string, and the builder saved the quantity on every
  keystroke with errors swallowed. Now a status changes only through the transition table (an unknown or disallowed
  action is a 409 ``invalid_transition`` naming the allowed ones, and the header has no ``status`` field at all), and a
  line edit is versioned and validated: a bad quantity is a 422 that leaves the stored line as it was, and a stale
  edit is a 409 instead of a silent overwrite.
- BUG-13: the legacy number was ``max(existing) + 1``; a deleted draft's number is never handed out again.
- SEC-06: search terms are literal (escaped ILIKE), never a pattern.
"""

from __future__ import annotations

import uuid

import pytest

from app.seed.world import keys
from tests.integration.challans.conftest import CHALLANS, as_, problem
from tests.integration.challans.world import ChallanWorld

pytestmark = pytest.mark.db
RAVI, MEERA, ADMIN = keys.USERS.RAVI, keys.USERS.MEERA, keys.USERS.PRIYA


def _key() -> dict[str, str]:
    return {"Idempotency-Key": str(uuid.uuid7())}


def test_bug_14_status_only_through_transitions_and_line_edits_never_silent(challan_client, challan_world: ChallanWorld) -> None:  # type: ignore[no-untyped-def]
    w = challan_world
    ravi = as_(RAVI)
    draft_id = w.ref(keys.CHALLAN_REFS.OUTWARD_DRAFT)
    before = challan_client.get(f"{CHALLANS}/{draft_id}", headers=ravi).json()
    assert before["status"] == "draft"
    # any status string through the header is refused outright (the field does not exist)
    r = challan_client.patch(f"{CHALLANS}/{draft_id}", json={"expected_version": before["version"], "status": "closed"}, headers=ravi)
    assert r.status_code == 422, r.text
    # unknown and disallowed actions are 409 invalid_transition with the allowed ones listed
    for action in ("archived", "closed", "close", "sent", "draft"):
        body = problem(
            challan_client.post(f"{CHALLANS}/{draft_id}/transitions", json={"action": action, "expected_version": before["version"]}, headers={**ravi, **_key()}),
            409,
            "invalid_transition",
        )
        assert {t["action"] for t in body["allowed_transitions"]} == {"issue", "cancel"}, action
    # a terminal challan offers nothing at all
    issued_id = w.ref(keys.CHALLAN_REFS.SAMPLE_MAISON)
    issued = challan_client.get(f"{CHALLANS}/{issued_id}", headers=ravi).json()
    closed = challan_client.post(f"{CHALLANS}/{issued_id}/transitions", json={"action": "close", "expected_version": issued["version"]}, headers={**ravi, **_key()})
    assert closed.status_code == 200 and closed.json()["status"] == "closed" and closed.json()["allowed_transitions"] == []
    body = problem(
        challan_client.post(f"{CHALLANS}/{issued_id}/transitions", json={"action": "issue", "expected_version": closed.json()["version"]}, headers={**ravi, **_key()}),
        409,
        "invalid_transition",
    )
    assert body["allowed_transitions"] == []
    # the quantity edit: invalid values are 422 and change nothing; a stale version is 409, never an overwrite
    line = before["lines"][0]
    url = f"{CHALLANS}/{draft_id}/lines/{line['id']}"
    for bad in ("0", "-3", "abc", "1.5"):  # 1.5 pcs: whole numbers only for an integer unit
        r = challan_client.patch(url, json={"expected_version": before["version"], "quantity": bad}, headers=ravi)
        assert r.status_code == 422, (bad, r.text)
        assert r.headers["content-type"].startswith("application/problem+json")
    unchanged = challan_client.get(f"{CHALLANS}/{draft_id}", headers=ravi).json()
    assert unchanged["version"] == before["version"] and unchanged["lines"][0]["quantity"] == line["quantity"]
    ok = challan_client.patch(url, json={"expected_version": before["version"], "quantity": "41"}, headers=ravi)
    assert ok.status_code == 200 and ok.json()["lines"][0]["quantity"] == "41" and ok.json()["version"] == before["version"] + 1
    problem(challan_client.patch(url, json={"expected_version": before["version"], "quantity": "42"}, headers=ravi), 409, "version_conflict")
    assert challan_client.get(f"{CHALLANS}/{draft_id}", headers=ravi).json()["lines"][0]["quantity"] == "41"


def test_bug_13_deleted_draft_number_is_never_reused(challan_client, challan_world: ChallanWorld) -> None:  # type: ignore[no-untyped-def]
    w = challan_world
    created = challan_client.post(
        CHALLANS, json={"destination_type": "customer", "party_id": str(w.ref("NORDHAUS"))}, headers={**as_(ADMIN), **_key()}
    )
    assert created.status_code == 201, created.text
    number, version = created.json()["challan_number"], created.json()["version"]
    assert number == "DC-2026-0004"
    deleted = challan_client.delete(f"{CHALLANS}/{created.json()['id']}", params={"expected_version": version}, headers={**as_(ADMIN), **_key()})
    assert deleted.status_code == 200 and deleted.json()["deleted_at"] is not None
    nxt = challan_client.post(CHALLANS, json={"destination_type": "customer", "party_id": str(w.ref("NORDHAUS"))}, headers={**as_(ADMIN), **_key()})
    assert nxt.json()["challan_number"] == "DC-2026-0005"  # legacy max + 1 would have handed out 0004 again


def test_sec_06_search_terms_are_literal_and_global_search_is_scoped(challan_client, challan_world: ChallanWorld) -> None:  # type: ignore[no-untyped-def]
    ravi = as_(RAVI)
    for pattern in (".*", "DC-2026-000%", "DC_2026", "(a+)+$", "%"):
        r = challan_client.get(CHALLANS, params={"q": pattern}, headers=ravi)
        assert r.status_code == 200 and r.json()["total"] == 0, pattern
    assert challan_client.get(CHALLANS, params={"q": "dc-2026-0001"}, headers=ravi).json()["total"] == 1
    # global search: Ravi finds the challans; the exact number ranks first; Meera (own scope) sees no challan group
    found = challan_client.get("/api/v1/search", params={"q": "DC-2026-0002"}, headers=ravi)
    assert found.status_code == 200, found.text
    groups = {g["resource_type"]: g for g in found.json()["groups"]}
    hits = groups["challans.challan"]["hits"]
    assert hits[0]["title"].startswith(keys.CHALLANS.SAMPLE_MAISON) and hits[0]["path"].startswith("/operations/challans/")
    assert groups["challans.challan"]["group"] == "Challans"
    by_party = challan_client.get("/api/v1/search", params={"q": "Precision"}, headers=ravi).json()
    assert any(h["title"] == f"{keys.CHALLANS.JOB_WORK} · {keys.PARTY_NAMES['PRECISION_EDGE']}" for g in by_party["groups"] for h in g["hits"])
    meera = challan_client.get("/api/v1/search", params={"q": "DC-2026"}, headers=as_(MEERA)).json()
    assert all(g["resource_type"] != "challans.challan" or g["hits"] == [] for g in meera["groups"])
