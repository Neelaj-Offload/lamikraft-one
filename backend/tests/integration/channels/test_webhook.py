"""The public webhook route (design §15; scenario K: signature rejection and replay).

GET handshake (constant-time verify token, challenge echoed, ``handshake_ok_at`` recorded); POST with a missing,
wrong or previous-secret signature; byte-exact HMAC (re-serialised JSON fails); body limit; unknown phone number
ids ignored; a replayed delivery has one business effect.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core import config as app_config
from app.modules.channels.models import ChannelMessage, InboundEvent, WebhookInbox, WebhookRejection
from app.modules.channels.whatsapp import signature
from app.modules.channels.whatsapp.demo_provider import signed_webhook_body
from app.platform.authz.context import ActorContext
from app.platform.uow import UnitOfWork
from tests.integration.channels.conftest import API, WhatsApp
from tests.support import drain

pytestmark = pytest.mark.db


def _count(model: type, *where: object) -> int:
    with UnitOfWork(ActorContext.system(None, reason="test")) as uow:
        return int(uow.session.scalar(select(func.count()).select_from(model).where(*where)) or 0)


def test_handshake_echoes_the_challenge_only_for_the_verify_token(client: TestClient, wa: WhatsApp) -> None:
    wa.account()
    token = signature.verify_token()
    assert token
    ok = client.get(f"{API}/webhooks/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": token, "hub.challenge": "1158201444"})
    assert ok.status_code == 200 and ok.text == "1158201444"
    assert wa.account().checks.get("handshake_ok_at")
    bad = client.get(f"{API}/webhooks/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": token + "x", "hub.challenge": "1"})
    assert bad.status_code == 403
    wrong_mode = client.get(f"{API}/webhooks/whatsapp", params={"hub.mode": "unsubscribe", "hub.verify_token": token, "hub.challenge": "1"})
    assert wrong_mode.status_code == 403


def test_k_signature_rejection_writes_a_rejection_row_without_the_payload(client: TestClient, wa: WhatsApp) -> None:
    payload = wa.message_payload(wa.wa_id("MEERA"), {"id": wa.wamid(), "type": "text", "text": {"body": "hello"}})
    body, good = signed_webhook_body(payload)
    before = _count(WebhookRejection)
    missing = client.post(f"{API}/webhooks/whatsapp", content=body, headers={"content-type": "application/json"})
    wrong = client.post(f"{API}/webhooks/whatsapp", content=body, headers={"content-type": "application/json", "x-hub-signature-256": "sha256=" + "0" * 64})
    # re-serialising the JSON changes the bytes: the original signature no longer matches
    reserialised = json.dumps(payload, indent=2).encode()
    altered = client.post(f"{API}/webhooks/whatsapp", content=reserialised, headers={"content-type": "application/json", "x-hub-signature-256": good})
    assert (missing.status_code, wrong.status_code, altered.status_code) == (403, 403, 403)
    assert _count(WebhookRejection) == before + 3
    with UnitOfWork(ActorContext.system(None, reason="test")) as uow:
        reasons = sorted(uow.session.scalars(select(WebhookRejection.reason).order_by(WebhookRejection.received_at.desc()).limit(3)))
        columns = set(WebhookRejection.__table__.c.keys())
    assert reasons == ["signature_invalid", "signature_invalid", "signature_missing"]
    assert "payload" not in columns
    assert _count(WebhookInbox) == 0
    accepted = client.post(f"{API}/webhooks/whatsapp", content=body, headers={"content-type": "application/json", "x-hub-signature-256": good})
    assert accepted.status_code == 200 and accepted.json() == {"status": "accepted"}
    assert _count(WebhookInbox) == 1


def test_previous_secret_is_accepted_during_rotation(wa: WhatsApp, monkeypatch: pytest.MonkeyPatch) -> None:
    current = signature.app_secrets()[0]
    monkeypatch.setenv("LK_WHATSAPP_APP_SECRET", "new-secret-after-rotation")
    monkeypatch.setenv("LK_WHATSAPP_APP_SECRET_PREVIOUS", current)
    app_config.reset_settings_cache()
    try:
        payload = wa.message_payload(wa.wa_id("MEERA"), {"id": wa.wamid(), "type": "text", "text": {"body": "hi"}})
        assert wa.deliver(payload, secret=current, process=False).status_code == 200
        assert wa.deliver(payload, secret="new-secret-after-rotation", process=False).status_code == 200
        assert wa.deliver(payload, secret="some-other-secret", process=False).status_code == 403
    finally:
        monkeypatch.undo()
        app_config.reset_settings_cache()


def test_oversized_body_is_refused(client: TestClient, wa: WhatsApp) -> None:
    big = b"{" + b" " * (4 * 1024 * 1024 + 10) + b"}"
    response = client.post(f"{API}/webhooks/whatsapp", content=big, headers={"content-type": "application/json", "x-hub-signature-256": signature.sign(big, signature.app_secrets()[0])})
    assert response.status_code == 413
    assert _count(WebhookInbox) == 0


def test_unknown_phone_number_id_is_ignored(wa: WhatsApp) -> None:
    payload = wa.message_payload(wa.wa_id("MEERA"), {"id": wa.wamid(), "type": "text", "text": {"body": "hello"}})
    payload["entry"][0]["changes"][0]["value"]["metadata"]["phone_number_id"] = "999000111"
    assert wa.deliver(payload).status_code == 200
    with UnitOfWork(ActorContext.system(None, reason="test")) as uow:
        inbox = uow.session.scalars(select(WebhookInbox)).one()
    assert inbox.status == "ignored" and inbox.company_id is None
    assert _count(InboundEvent) == 0


def test_k_replay_of_a_delivery_has_one_business_effect(wa: WhatsApp) -> None:
    identity = wa.enrol("MEERA")
    wamid = wa.wamid()
    payload = wa.message_payload(wa.wa_id("MEERA"), {"id": wamid, "type": "text", "text": {"body": "STOP"}})
    for _ in range(3):  # Meta retries for up to 7 days: duplicates are normal
        assert wa.deliver(payload).status_code == 200
    drain()
    with UnitOfWork(wa.system()) as uow:
        inbound = uow.session.scalar(select(func.count()).select_from(ChannelMessage).where(ChannelMessage.provider_message_id == wamid))
        events = uow.session.scalar(select(func.count()).select_from(InboundEvent).where(InboundEvent.provider_event_key == wamid))
    assert inbound == 1 and events == 1
    confirmations = [r for r in wa.replies(identity.id) if "Proactive messages are off" in r]
    assert len(confirmations) == 1
    assert _count(WebhookInbox) >= 3
