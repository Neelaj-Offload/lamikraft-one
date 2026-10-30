"""The sales HTTP surface end to end: operationIds and route declarations, problem+json, DecimalStr money, Page shape,
Idempotency-Key (required on issue-like transitions, replay header), optimistic versions, the BUG-01 409 for
Slice-2 actions, scope (404 invisible / 403 forbidden), the engine preview, enquiries and customer messages."""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.seed.world import keys
from tests.integration.sales.http import API, as_, problem
from tests.integration.sales.world import SalesWorld

pytestmark = pytest.mark.db
MEERA, NEHA, SAHIL, RAVI = keys.USERS.MEERA, keys.USERS.NEHA, keys.USERS.SAHIL, keys.USERS.RAVI
Q = "/sales/quotes"
EXPECTED_OPERATIONS = {
    ("get", Q): ("sales_list_quotes", ["sales.quote.read"]),
    ("post", Q): ("sales_create_quote", ["sales.quote.create"]),
    ("get", f"{Q}/{{quote_id}}"): ("sales_get_quote", ["sales.quote.read"]),
    ("patch", f"{Q}/{{quote_id}}"): ("sales_update_quote", ["sales.quote.update"]),
    ("delete", f"{Q}/{{quote_id}}"): ("sales_delete_quote", ["sales.quote.delete"]),
    ("post", f"{Q}/{{quote_id}}/lines"): ("sales_create_quote_line", ["sales.quote.update"]),
    ("patch", f"{Q}/{{quote_id}}/lines/{{line_id}}"): ("sales_update_quote_line", ["sales.quote.update"]),
    ("delete", f"{Q}/{{quote_id}}/lines/{{line_id}}"): ("sales_delete_quote_line", ["sales.quote.update"]),
    ("post", f"{Q}/{{quote_id}}/transitions"): ("sales_transition_quote", ["sales.quote.transition", "sales.quote.issue"]),
    ("get", f"{Q}/{{quote_id}}/revisions"): ("sales_list_quote_revisions", ["sales.quote.read"]),
    ("get", f"{Q}/{{quote_id}}/revisions/{{revision_no}}"): ("sales_get_quote_revision", ["sales.quote.read"]),
    ("get", f"{Q}/{{quote_id}}/revisions/{{revision_no}}/document.pdf"): ("sales_download_quote_revision_pdf", ["sales.quote.export"]),
    ("get", f"{Q}/{{quote_id}}/history"): ("sales_list_quote_history", ["sales.quote.read"]),
    ("post", f"{Q}/calculate"): ("sales_calculate_quote_preview", ["pricing.price.read"]),
    ("get", "/sales/enquiries"): ("sales_list_enquiries", ["sales.enquiry.read"]),
    ("post", "/sales/enquiries"): ("sales_create_enquiry", ["sales.enquiry.create"]),
    ("get", "/sales/enquiries/{enquiry_id}"): ("sales_get_enquiry", ["sales.enquiry.read"]),
    ("patch", "/sales/enquiries/{enquiry_id}"): ("sales_update_enquiry", ["sales.enquiry.update"]),
    ("get", "/sales/customer-messages"): ("sales_list_customer_messages", ["sales.customer_message.read"]),
    ("post", "/sales/customer-messages"): ("sales_create_customer_message", ["sales.customer_message.create"]),
    ("get", "/sales/customer-messages/{message_id}"): ("sales_get_customer_message", ["sales.customer_message.read"]),
    ("patch", "/sales/customer-messages/{message_id}"): ("sales_update_customer_message", ["sales.customer_message.update"]),
    ("post", "/sales/customer-messages/{message_id}/replied"): ("sales_transition_customer_message", ["sales.customer_message.update"]),
}


def _key() -> dict[str, str]:
    return {"Idempotency-Key": str(uuid.uuid7())}


def test_operation_ids_and_route_declarations(api_app: FastAPI) -> None:
    spec = api_app.openapi()
    sales_ops = {(m, p.removeprefix(API)) for p, ops in spec["paths"].items() if p.startswith(f"{API}/sales/") for m in ops}
    assert set(EXPECTED_OPERATIONS) <= sales_ops
    for (method, path), (operation_id, permissions) in EXPECTED_OPERATIONS.items():
        op = spec["paths"][f"{API}{path}"][method]
        assert op["operationId"] == operation_id
        assert op["x-authz"] == {"kind": "permission", "permissions": permissions}, operation_id
    for method, path in sales_ops:  # every sales route: <module>_<verb>_<noun> and a permission declaration
        op = spec["paths"][f"{API}{path}"][method]
        assert op["operationId"].startswith("sales_") and op["x-authz"]["kind"] == "permission", (method, path)
    pdf = spec["paths"][f"{API}{Q}/{{quote_id}}/revisions/{{revision_no}}/document.pdf"]["get"]
    assert "application/pdf" in pdf["responses"]["200"]["content"]


def test_quote_lifecycle_over_http(sales_client: TestClient, sales_world: SalesWorld) -> None:
    c = sales_client
    key = _key()
    body = {"party_id": str(sales_world.ref("NORDHAUS")), "remarks": "via API"}
    created = c.post(f"{API}{Q}", json=body, headers=key)
    assert created.status_code == 201, created.text
    quote = created.json()
    assert quote["quote_number"] == keys.QUOTES.SCENARIO_C_NEW and quote["status"] == "draft" and quote["currency"] == "EUR"
    replay = c.post(f"{API}{Q}", json=body, headers=key)
    assert replay.status_code == 201 and replay.headers.get("Idempotent-Replayed") == "true" and replay.json()["id"] == quote["id"]

    qid = quote["id"]
    line = c.post(f"{API}{Q}/{qid}/lines", json={"expected_version": quote["version"], "product_id": str(sales_world.ref("OAK_TRAY")),
                                                 "quantity": "240"})
    assert line.status_code == 201, line.text
    detail = line.json()
    assert detail["totals"]["grand_total"] == {"amount": keys.EXPECTED.SCENARIO_C_TOTAL, "currency": "EUR"}
    assert isinstance(detail["lines"][0]["unit_price"], str) and detail["lines"][0]["unit_price"] == keys.PRICES.OAK_TRAY_EUR
    line_id = detail["lines"][0]["id"]
    problem(c.patch(f"{API}{Q}/{qid}/lines/{line_id}", json={"expected_version": quote["version"], "quantity": "250"}), 409, "version_conflict")
    problem(c.post(f"{API}{Q}/{qid}/lines", json={"expected_version": detail["version"], "product_id": str(sales_world.ref("OAK_TRAY")),
                                                  "quantity": 1.5}), 422, "validation_failed")  # floats are refused
    patched = c.patch(f"{API}{Q}/{qid}/lines/{line_id}", json={"expected_version": detail["version"], "quantity": "250"}).json()
    assert patched["totals"]["grand_total"]["amount"] == "6000.00"

    # Slice-2 actions are a 409 with the allowed transitions (BUG-01), issue needs an Idempotency-Key
    archive = problem(c.post(f"{API}{Q}/{qid}/transitions", json={"action": "archive", "expected_version": patched["version"]}),
                      409, "invalid_transition")
    assert [t["action"] for t in archive["allowed_transitions"]] == ["submit_review", "mark_sent", "cancel"]
    problem(c.post(f"{API}{Q}/{qid}/transitions", json={"action": "mark_sent", "expected_version": patched["version"]}),
            422, "idempotency_key_required")
    send_key = _key()
    sent = c.post(f"{API}{Q}/{qid}/transitions", json={"action": "mark_sent", "expected_version": patched["version"],
                                                       "dispatch_channel": "email"}, headers=send_key)
    assert sent.status_code == 200, sent.text
    assert sent.json()["status"] == "sent" and sent.json()["revision_no"] == 1 and sent.json()["valid_until"] == "2026-11-11"
    again = c.post(f"{API}{Q}/{qid}/transitions", json={"action": "mark_sent", "expected_version": patched["version"],
                                                        "dispatch_channel": "email"}, headers=send_key)
    assert again.status_code == 200 and again.headers.get("Idempotent-Replayed") == "true"
    history = c.get(f"{API}{Q}/{qid}/history").json()
    assert [(h["action"], h["to_status"]) for h in history] == [("mark_sent", "sent")]
    revisions = c.get(f"{API}{Q}/{qid}/revisions").json()
    assert [r["revision_no"] for r in revisions] == [1]
    revision = c.get(f"{API}{Q}/{qid}/revisions/1").json()
    assert revision["snapshot"]["totals"]["grand_total"] == "6000.0000"
    problem(c.delete(f"{API}{Q}/{qid}", params={"expected_version": sent.json()["version"]}, headers=as_(SAHIL)), 403, "permission_denied")
    problem(c.delete(f"{API}{Q}/{qid}", params={"expected_version": sent.json()["version"]}, headers=as_(keys.USERS.PRIYA)),
            403, "issued_documents_cannot_be_deleted")


def test_list_preview_and_scope_over_http(sales_client: TestClient, sales_world: SalesWorld) -> None:
    c = sales_client
    page = c.get(f"{API}{Q}", params={"limit": 2}).json()
    assert set(page) == {"items", "total", "limit", "offset"} and page["total"] == 5 and len(page["items"]) == 2
    assert all(isinstance(item["grand_total"]["amount"], str) for item in page["items"])
    sahil = c.get(f"{API}{Q}", params={"status": ["sent"], "q": "berg"}, headers=as_(SAHIL)).json()
    assert [q["quote_number"] for q in sahil["items"]] == [keys.QUOTES.BERG_EXPIRING]
    problem(c.get(f"{API}{Q}", params={"status": ["bogus"]}), 422, "validation_failed")
    problem(c.get(f"{API}{Q}/{sales_world.ref('Q_THORNBURY_EXPIRING')}"), 404, "not_found")  # Neha's quote
    problem(c.get(f"{API}{Q}/{uuid.uuid7()}", headers=as_(SAHIL)), 404, "not_found")
    ravi = c.get(f"{API}{Q}/{sales_world.ref('Q_NORDHAUS_DRAFT')}", headers=as_(RAVI)).json()
    problem(c.patch(f"{API}{Q}/{sales_world.ref('Q_NORDHAUS_DRAFT')}", json={"expected_version": ravi["version"], "remarks": "x"},
                    headers=as_(RAVI)), 403, "permission_denied")
    preview = c.post(f"{API}{Q}/calculate", json={
        "currency": "EUR", "party_id": str(sales_world.ref("NORDHAUS")), "surcharge_requested": True,
        "lines": [{"product_id": str(sales_world.ref("OAK_TRAY")), "quantity": "100"}],
    })
    assert preview.status_code == 200, preview.text
    calc = preview.json()["calculation"]
    assert calc["grand_total"] == {"amount": "2800.00", "currency": "EUR"}  # 100 x 24.00 + 400.00 surcharge (below 5,000)
    assert calc["surcharge"]["applied"] is True and calc["minimum"]["status"] == "BELOW"
    with sales_world.uow(SAHIL) as uow:  # the preview persisted nothing
        from app.modules.sales import service as sales
        from app.modules.sales.schemas import QuoteFilters

        assert sales.list_quotes(uow, QuoteFilters()).total == 8


def test_enquiries_and_messages_over_http(sales_client: TestClient, sales_world: SalesWorld) -> None:
    c = sales_client
    enquiries = c.get(f"{API}/sales/enquiries").json()
    assert [e["enquiry_number"] for e in enquiries["items"]] == [keys.ENQUIRIES.MAISON]  # Meera sees her own
    created = c.post(f"{API}/sales/enquiries", json={"party_id": str(sales_world.ref("BERG")), "channel": "web", "subject": "Trivets"},
                     headers=_key())
    assert created.status_code == 201, created.text
    enquiry = created.json()
    assert enquiry["enquiry_number"] == "ENQ-2026-0003" and enquiry["status"] == "received"
    problem(c.patch(f"{API}/sales/enquiries/{enquiry['id']}", json={"expected_version": enquiry["version"],
                                                                   "owner_user_id": str(sales_world.user_id(NEHA))}), 403, "permission_denied")
    assigned = c.patch(f"{API}/sales/enquiries/{enquiry['id']}", headers=as_(SAHIL),
                       json={"expected_version": enquiry["version"], "owner_user_id": str(sales_world.user_id(NEHA))})
    assert assigned.status_code == 200 and assigned.json()["status"] == "assigned"
    problem(c.get(f"{API}/sales/enquiries/{enquiry['id']}"), 404, "not_found")

    messages = c.get(f"{API}/sales/customer-messages", params={"status": ["received"]}).json()
    assert {m["id"] for m in messages["items"]} == {str(sales_world.ref(keys.MESSAGES.NORDHAUS)), str(sales_world.ref(keys.MESSAGES.BERG))}
    msg = c.get(f"{API}/sales/customer-messages/{sales_world.ref(keys.MESSAGES.BERG)}").json()
    replied = c.post(f"{API}/sales/customer-messages/{msg['id']}/replied", json={"expected_version": msg["version"], "reply_ref_type": "email"},
                     headers=_key())
    assert replied.status_code == 200, replied.text
    assert replied.json()["status"] == "replied" and replied.json()["replied_at"] is not None
    problem(c.get(f"{API}/sales/customer-messages/{msg['id']}", headers=as_(NEHA)), 404, "not_found")
    new = c.post(f"{API}/sales/customer-messages", json={"party_id": str(sales_world.ref("MAISON")), "channel": "whatsapp", "body": "Bonjour"},
                 headers=_key())
    assert new.status_code == 201 and new.json()["status"] == "received" and new.json()["assignee"]["id"] == str(sales_world.user_id(MEERA))
