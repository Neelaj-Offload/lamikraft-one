"""Live mode (design §15 "Live mode") against a fake Graph API transport — no call ever leaves the machine.

``not_configured`` while any required setting is missing; "Connected" only after the Graph API check, the webhook
handshake and a signed event all succeeded (``channels.account.verified``); outbound needs the live-outbound flag
and, outside production, the development allowlist; real statuses (not simulated) are the only delivery evidence.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core import config as app_config
from app.modules.channels.whatsapp import accounts, signature
from app.modules.channels.whatsapp.cloud_api import CloudApiProvider
from app.modules.channels.whatsapp.provider import set_provider_override
from app.platform.events.models import DomainEvent
from app.platform.uow import UnitOfWork
from tests.integration.channels.conftest import API, WhatsApp, unix
from tests.support import drain

pytestmark = pytest.mark.db

PNID = "109876543210"
LIVE = {
    "LK_WHATSAPP_MODE": "live", "LK_WHATSAPP_PHONE_NUMBER_ID": PNID, "LK_WHATSAPP_WABA_ID": "2000000001",
    "LK_WHATSAPP_ACCESS_TOKEN": "fake-token", "LK_WHATSAPP_APP_SECRET": "live-app-secret", "LK_WHATSAPP_VERIFY_TOKEN": "live-verify",
    "LK_WHATSAPP_API_VERSION": "v26.0",
}


class FakeGraph:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.counter = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert request.headers["authorization"] == "Bearer fake-token"
        if request.method == "GET" and request.url.path == f"/v26.0/{PNID}":
            return httpx.Response(200, json={"display_phone_number": "+91 22 4000 1234", "verified_name": "Lamikraft", "quality_rating": "GREEN", "id": PNID})
        if request.method == "POST" and request.url.path == f"/v26.0/{PNID}/messages":
            self.counter += 1
            return httpx.Response(200, json={"messaging_product": "whatsapp", "messages": [{"id": f"wamid.LIVE.{self.counter}"}]})
        return httpx.Response(404, json={"error": {"code": 100, "message": "unexpected"}})

    def sends(self) -> list[dict]:
        return [json.loads(r.content) for r in self.requests if r.method == "POST"]


@pytest.fixture
def live(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeGraph]:
    for name, value in LIVE.items():
        monkeypatch.setenv(name, value)
    app_config.reset_settings_cache()
    graph = FakeGraph()
    set_provider_override(CloudApiProvider(transport=httpx.MockTransport(graph)))
    try:
        yield graph
    finally:
        set_provider_override(None)
        monkeypatch.undo()
        app_config.reset_settings_cache()


def _account_status(wa: WhatsApp) -> tuple[str, str]:
    with UnitOfWork(wa.actor("PRIYA")) as uow:
        account = accounts.ensure_account(uow)
        return account.status, accounts.label_text(account)


def test_live_mode_is_not_configured_while_a_setting_is_missing(wa: WhatsApp, live: FakeGraph, monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    monkeypatch.setenv("LK_WHATSAPP_ACCESS_TOKEN", "")
    app_config.reset_settings_cache()
    response = client.get(f"{API}/channels/whatsapp/account", headers={"x-test-persona": "PRIYA"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "not_configured" and body["label_text"] == "Not configured"
    assert body["missing_settings"] == ["LK_WHATSAPP_ACCESS_TOKEN"]
    sales_view = client.get(f"{API}/channels/whatsapp/account", headers={"x-test-persona": "MEERA"}).json()
    assert sales_view["missing_settings"] == [] and sales_view["phone_number_id"] is None  # admin details only


def test_connected_only_after_graph_handshake_and_signed_event(wa: WhatsApp, live: FakeGraph, client: TestClient) -> None:
    headers = {"x-test-persona": "PRIYA"}
    first = client.post(f"{API}/channels/whatsapp/account/verify", headers=headers)
    assert first.status_code == 200, first.text
    result = first.json()
    assert [c["ok"] for c in result["checks"]] == [True, False, False]
    assert result["account"]["status"] == "configured_unverified" and result["account"]["label_text"] == "Not connected"
    assert result["account"]["display_phone"] == "+91 22 4000 1234"
    handshake = client.get(f"{API}/webhooks/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "live-verify", "hub.challenge": "42"})
    assert handshake.status_code == 200 and handshake.text == "42"
    assert _account_status(wa)[0] == "configured_unverified"
    # a signed event (any status for an unknown message) completes the third check
    wa.statuses("wamid.SOMETHING", "919800000001", [("sent", unix(wa.now()))])
    assert _account_status(wa) == ("verified", "Connected")
    with UnitOfWork(wa.system()) as uow:
        assert uow.session.scalar(select(func.count()).select_from(DomainEvent).where(DomainEvent.event_type == "channels.account.verified")) == 1
    again = client.post(f"{API}/channels/whatsapp/account/verify", headers=headers).json()
    assert [c["ok"] for c in again["checks"]] == [True, True, True]


def test_verify_needs_a_recent_sign_in_and_the_admin_key(wa: WhatsApp, live: FakeGraph, client: TestClient) -> None:
    stale = client.post(f"{API}/channels/whatsapp/account/verify", headers={"x-test-persona": "PRIYA", "x-test-recent-auth": "0"})
    assert stale.status_code == 401 and stale.json()["code"] == "reauth_required"
    sales = client.post(f"{API}/channels/whatsapp/account/verify", headers={"x-test-persona": "MEERA"})
    assert sales.status_code == 403


def test_live_outbound_needs_the_flag_and_the_allowlist_and_statuses_are_real(wa: WhatsApp, live: FakeGraph, monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.integration.channels.test_scenario_k import _outbox, _queue

    identity = wa.enrol("MEERA")
    link_reply = wa.messages(identity.id, "outbound")[-1]
    assert link_reply["outbox_state"] == "blocked" and link_reply["blocked_reason"] == "live_outbound_disabled"
    monkeypatch.setenv("LK_WHATSAPP_LIVE_OUTBOUND", "true")
    app_config.reset_settings_cache()
    no_list = _queue(wa, identity.id, "hello")
    drain()
    assert _outbox(wa, no_list).blocked_reason == "not_in_dev_allowlist" and live.sends() == []
    monkeypatch.setenv("LK_WHATSAPP_DEV_ALLOWLIST", "+" + wa.wa_id("MEERA"))
    app_config.reset_settings_cache()
    ok = _queue(wa, identity.id, "hello again")
    drain()
    row = _outbox(wa, ok)
    assert row.state == "accepted" and row.provider_message_id == "wamid.LIVE.1"
    sent = live.sends()[0]
    assert sent["to"] == wa.wa_id("MEERA") and sent["biz_opaque_callback_data"] == str(ok) and sent["text"]["body"] == "hello again"
    message = next(m for m in wa.messages(identity.id, "outbound") if m["outbox_id"] == ok)
    assert message["status"] == "accepted" and message["simulated"] is False  # accepted, not delivered
    wa.statuses("wamid.LIVE.1", wa.wa_id("MEERA"), [("sent", unix(wa.now()) + 1), ("delivered", unix(wa.now()) + 2)])
    message = next(m for m in wa.messages(identity.id, "outbound") if m["outbox_id"] == ok)
    assert message["status"] == "delivered" and message["simulated"] is False
    assert signature.verify_token() == "live-verify"
