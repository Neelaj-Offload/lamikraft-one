"""IDOR / permission matrix for the finance routes over HTTP (SEC-03 / PERM-23 for Slice 5).

Finance records are company-level finance data: personas without finance keys (sales Meera, operations Ravi, the
warehouse assistant Kabir) get 403 on lists and 404 on records (existence is not disclosed); management (Sahil) reads
and approves but cannot draft, record, issue or export; finance (Ananya) cannot approve her own draft. Unknown ids are
404 on every detail route. Margin figures are redacted for sales on a quote they own."""

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
from app.seed.world import keys
from tests.integration.finance.world import ANANYA, MEERA, RAVI, SAHIL, FinWorld
from tests.integration.sales.http import api_app  # noqa: F401

pytestmark = pytest.mark.db
API = "/api/v1/finance"
KABIR = keys.USERS.KABIR


@pytest.fixture
def client(api_app: FastAPI, fin_world: FinWorld) -> Iterator[TestClient]:  # noqa: F811
    def resolve(request: Request) -> ActorContext:
        persona = request.headers.get("x-test-persona", ANANYA)
        actor = fin_world.actor(persona).with_(idempotency_key=request.headers.get("idempotency-key"))
        return actor.with_(auth_strength="mfa", recent_auth_at=fin_world.ctx.clock.now())

    api_app.dependency_overrides[get_actor] = resolve
    try:
        with TestClient(api_app, headers={"Origin": get_settings().public_origin}) as c:
            yield c
    finally:
        api_app.dependency_overrides.clear()


def _as(persona: str) -> dict[str, str]:
    return {"x-test-persona": persona, "Idempotency-Key": str(uuid.uuid7())}


def _code(r: Any) -> tuple[int, str | None]:
    body = r.json() if r.headers.get("content-type", "").startswith("application/") else {}
    return r.status_code, body.get("code") if isinstance(body, dict) else None


@pytest.fixture
def records(fin_world: FinWorld) -> dict[str, Any]:
    w = fin_world
    ids = w.delivered("10")
    d = w.draft(challan_id=ids["challan_id"])
    r = w.receipt("100")
    return {"invoice": d, "receipt": r, **ids}


def test_personas_without_finance_keys_see_nothing(client: TestClient, records: dict[str, Any]) -> None:
    inv, rec = records["invoice"], records["receipt"]
    for persona in (MEERA, RAVI, KABIR):
        for path in ("/invoices", "/credit-notes", "/receipts", "/summary", "/exceptions", "/ageing", "/tax-profiles",
                     "/invoice-suggestions", "/accounting/status", "/accounting/exports", "/invoices/export.csv"):
            assert client.get(API + path, headers=_as(persona)).status_code == 403, (persona, path)
        for path in (f"/invoices/{inv.id}", f"/invoices/{inv.id}/document.pdf", f"/receipts/{rec.id}"):
            assert client.get(API + path, headers=_as(persona)).status_code in (403, 404), (persona, path)
        r = client.post(f"{API}/invoices/{inv.id}/transitions", json={"action": "submit", "expected_version": inv.version}, headers=_as(persona))
        assert r.status_code in (403, 404)
        r = client.post(f"{API}/receipts/{rec.id}/allocations", json={"invoice_id": str(inv.id), "amount": "1"}, headers=_as(persona))
        assert r.status_code in (403, 404)
        r = client.post(f"{API}/receipts", json={"party_id": str(records["invoice"].party.id), "amount": "1", "currency": "EUR",
                                                 "received_on": "2026-10-12"}, headers=_as(persona))
        assert _code(r) == (403, "permission_denied")


def test_management_reads_and_approves_but_never_drafts_issues_or_exports(client: TestClient, records: dict[str, Any]) -> None:
    inv = records["invoice"]
    assert client.get(f"{API}/invoices/{inv.id}", headers=_as(SAHIL)).status_code == 200
    assert client.get(f"{API}/receipts", headers=_as(SAHIL)).status_code == 200
    assert client.get(f"{API}/ageing", headers=_as(SAHIL)).status_code == 200
    r = client.post(f"{API}/invoices", json={"challan_id": str(records["challan_id"])}, headers=_as(SAHIL))
    assert _code(r) == (403, "permission_denied")
    r = client.post(f"{API}/accounting/exports", json={"adapter": "demo"}, headers=_as(SAHIL))
    assert _code(r) == (403, "permission_denied")
    # submit (Ananya), approve by the creator refused, approve by Sahil allowed, issue by Sahil refused
    r = client.post(f"{API}/invoices/{inv.id}/transitions", json={"action": "submit", "expected_version": inv.version}, headers=_as(ANANYA))
    assert r.status_code == 200 and r.json()["issued"] is None
    version = r.json()["detail"]["version"]
    r = client.post(f"{API}/invoices/{inv.id}/transitions", json={"action": "approve", "expected_version": version}, headers=_as(ANANYA))
    assert r.status_code == 403
    r = client.post(f"{API}/invoices/{inv.id}/transitions", json={"action": "approve", "expected_version": version}, headers=_as(SAHIL))
    assert r.status_code == 200 and r.json()["detail"]["status"] == "approved"
    version = r.json()["detail"]["version"]
    r = client.post(f"{API}/invoices/{inv.id}/transitions", json={"action": "issue", "expected_version": version}, headers=_as(SAHIL))
    assert r.status_code == 403
    r = client.post(f"{API}/invoices/{inv.id}/transitions", json={"action": "issue", "expected_version": version}, headers=_as(ANANYA))
    assert r.status_code == 200 and r.json()["issued"] is False and r.json()["blockers"]


def test_unknown_and_mismatched_ids_are_not_found(client: TestClient, records: dict[str, Any]) -> None:
    inv = records["invoice"]
    for path in ("/invoices", "/credit-notes", "/receipts", "/accounting/exports"):
        assert client.get(f"{API}{path}/{uuid.uuid7()}", headers=_as(ANANYA)).status_code == 404
    # an invoice id on the credit-note routes is not found
    assert client.get(f"{API}/credit-notes/{inv.id}", headers=_as(ANANYA)).status_code == 404
    r = client.post(f"{API}/credit-notes/{inv.id}/transitions", json={"action": "submit", "expected_version": inv.version}, headers=_as(ANANYA))
    assert r.status_code == 404
    r = client.post(f"{API}/invoices", json={"challan_id": str(uuid.uuid7())}, headers=_as(ANANYA))
    assert r.status_code == 404


def test_http_documents_and_replay(client: TestClient, records: dict[str, Any]) -> None:
    inv = records["invoice"]
    pdf = client.get(f"{API}/invoices/{inv.id}/document.pdf", headers=_as(ANANYA))
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF") and pdf.headers["content-security-policy"] == "sandbox"
    csv_ = client.get(f"{API}/invoices/export.csv", headers=_as(ANANYA))
    assert csv_.status_code == 200 and "attachment" in csv_.headers["content-disposition"]
    key = str(uuid.uuid7())
    body = {"party_id": str(inv.party.id), "amount": "50", "currency": "EUR", "received_on": "2026-10-12"}
    first = client.post(f"{API}/receipts", json=body, headers={"x-test-persona": ANANYA, "Idempotency-Key": key})
    again = client.post(f"{API}/receipts", json=body, headers={"x-test-persona": ANANYA, "Idempotency-Key": key})
    assert first.status_code == 201 and again.json()["id"] == first.json()["id"]
    assert again.headers.get("Idempotent-Replayed") == "true"
    summary = client.get(f"{API}/summary", headers=_as(ANANYA)).json()
    assert summary["capabilities"]["create_invoice"]["allowed"] is True and summary["accounting_mode"] == "demo"
    assert client.get(f"{API}/summary", headers=_as(SAHIL)).json()["capabilities"]["create_invoice"]["allowed"] is False
