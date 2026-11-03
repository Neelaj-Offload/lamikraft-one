"""Pure WhatsApp units: signature (byte-exact, both secrets, constant-time shape), typed payload parsing (messages,
statuses, template updates, groups, BSUID), the versioned error-code table, the Cloud API adapter over an httpx mock
transport (request shape, outcomes: accepted / unknown / throttle / failed / blocked), card rendering (figures
from the card, Demo prefix, button limits), consent keywords and the 24-hour window."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest

from app.modules.channels import error_codes
from app.modules.channels.whatsapp import consent, payloads, render, signature, window
from app.modules.channels.whatsapp.cloud_api import CloudApiProvider, to_cloud_body
from app.modules.channels.whatsapp.provider import AccountConfig, MediaError, MediaInfo

ACCOUNT = AccountConfig(account_id=None, company_id=None, mode="live", phone_number_id="123456", waba_id="999", display_phone="+91 22 0000 0000",
                        api_version="v26.0", access_token="token-xyz")


# ---- signature ---------------------------------------------------------------------------------------------------------
def test_signature_is_byte_exact_and_accepts_either_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    body = b'{"object":"whatsapp_business_account","entry":[]}'
    settings = SimpleNamespace(
        whatsapp_app_secret=SimpleNamespace(get_secret_value=lambda: "current"),
        whatsapp_app_secret_previous=SimpleNamespace(get_secret_value=lambda: "previous"),
        whatsapp_mode="live",
    )
    assert signature.verify_signature(body, signature.sign(body, "current"), settings)  # type: ignore[arg-type]
    assert signature.verify_signature(body, signature.sign(body, "previous"), settings)  # type: ignore[arg-type]
    assert not signature.verify_signature(body, signature.sign(body, "other"), settings)  # type: ignore[arg-type]
    assert not signature.verify_signature(body + b" ", signature.sign(body, "current"), settings)  # type: ignore[arg-type]
    assert not signature.verify_signature(body, None, settings)  # type: ignore[arg-type]
    assert not signature.verify_signature(body, "sha1=abc", settings)  # type: ignore[arg-type]
    assert not signature.verify_signature(body, "sha256=short", settings)  # type: ignore[arg-type]
    upper = "sha256=" + signature.sign(body, "current").removeprefix("sha256=").upper()
    assert signature.verify_signature(body, upper, settings)  # type: ignore[arg-type]


def test_live_mode_without_a_secret_verifies_nothing() -> None:
    settings = SimpleNamespace(
        whatsapp_app_secret=SimpleNamespace(get_secret_value=lambda: ""),
        whatsapp_app_secret_previous=SimpleNamespace(get_secret_value=lambda: ""),
        whatsapp_mode="live",
        whatsapp_verify_token=SimpleNamespace(get_secret_value=lambda: ""),
    )
    assert signature.app_secrets(settings) == []  # type: ignore[arg-type]
    assert not signature.verify_handshake("subscribe", "anything", settings)  # type: ignore[arg-type]


# ---- payloads ----------------------------------------------------------------------------------------------------------
def _messages_change(**value: object) -> dict:
    return {"object": "whatsapp_business_account", "entry": [{"id": "999", "changes": [{"field": "messages", "value": {
        "messaging_product": "whatsapp", "metadata": {"display_phone_number": "91220000", "phone_number_id": "123456"}, **value}}]}]}


def test_payload_parsing_covers_messages_statuses_and_unknown_types() -> None:
    raw = _messages_change(
        contacts=[{"wa_id": "919800000001", "user_id": "IN.BSUID.1", "profile": {"name": "Meera"}}],
        messages=[
            {"from": "919800000001", "from_user_id": "IN.BSUID.1", "id": "wamid.A", "timestamp": "1760239500", "type": "text", "text": {"body": "hi"}},
            {"from": "919800000001", "id": "wamid.B", "timestamp": "1760239501", "type": "audio", "audio": {"id": "m1", "mime_type": "audio/ogg", "sha256": "abc", "voice": True}},
            {"from": "919800000001", "id": "wamid.C", "timestamp": "1760239502", "type": "interactive",
             "interactive": {"type": "button_reply", "button_reply": {"id": "a:nonce", "title": "Review"}}, "context": {"from": "91220000", "id": "wamid.OUT"}},
            {"from": "919800000001", "id": "wamid.D", "timestamp": "1760239503", "type": "sticker", "sticker": {"id": "s"}},
            {"from": "919800000001", "id": "wamid.E", "timestamp": "1760239504", "type": "system", "system": {"type": "user_changed_user_id", "user_id": "IN.BSUID.2"}},
            {"from": "120363000000000000@g.us", "id": "wamid.G", "timestamp": "1760239505", "type": "text", "text": {"body": "group"}},
        ],
        statuses=[{"id": "wamid.OUT", "status": "delivered", "timestamp": "1760239600", "recipient_id": "919800000001", "biz_opaque_callback_data": "x"}],
    )
    (waba, value), = payloads.messages_changes(payloads.parse_payload(raw))
    assert waba == "999" and value.metadata.phone_number_id == "123456"
    kinds = [payloads.classify_message(m) for m in value.messages]
    assert kinds == ["text", "audio", "interactive", "unsupported", "system", "text"]
    assert value.messages[0].from_user_id == "IN.BSUID.1" and value.contacts[0].user_id == "IN.BSUID.1"
    assert value.messages[2].interactive.reply_id == "a:nonce" and value.messages[2].context.id == "wamid.OUT"  # type: ignore[union-attr]
    assert value.messages[5].is_group and not value.messages[0].is_group
    assert value.messages[0].provider_ts == datetime.fromtimestamp(1760239500, tz=UTC)
    assert payloads.status_event_key(value.statuses[0]) == "wamid.OUT:delivered:1760239600"


def test_template_status_update_parses() -> None:
    raw = {"object": "whatsapp_business_account", "entry": [{"id": "999", "time": 1760239700, "changes": [{"field": "message_template_status_update", "value": {
        "event": "PAUSED", "message_template_id": 42, "message_template_name": "lk_quote_ready", "message_template_language": "en", "reason": "LOW_QUALITY"}}]}]}
    (waba, value), = payloads.template_changes(payloads.parse_payload(raw))
    assert waba == "999" and payloads.TEMPLATE_EVENT_TO_STATUS[value.event] == "paused"
    assert payloads.template_event_key(value, 1760239700) == "tpl:42:PAUSED:1760239700"


# ---- error codes ---------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("http_status", "code", "outcome"),
    [
        (None, None, "unknown"), (500, None, "unknown"), (503, 131000, "unknown"), (429, None, "throttle"), (400, 130429, "throttle"),
        (400, 131047, "blocked"), (400, 132015, "blocked"), (400, 131026, "failed"), (400, 100, "failed"), (403, 200, "failed"),
        (400, 131016, "retry"), (400, None, "failed"), (400, 299, "failed"),
    ],
)
def test_error_classification(http_status: int | None, code: int | None, outcome: str) -> None:
    assert error_codes.classify(http_status, code) == outcome


def test_error_table_is_versioned() -> None:
    assert error_codes.GRAPH_API_VERSION == "v26.0" and error_codes.ERROR_TABLE_CHECKED == "2026-11-03"
    assert 131047 in error_codes.NOT_PROCESSED_CODES or error_codes.ERROR_TABLE[131047].outcome == "blocked"


# ---- Cloud API adapter -----------------------------------------------------------------------------------------------------
def _provider(handler) -> CloudApiProvider:  # type: ignore[no-untyped-def]
    return CloudApiProvider(transport=httpx.MockTransport(handler))


def test_send_request_shape_and_accepted_outcome() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"messaging_product": "whatsapp", "contacts": [{"wa_id": "919800000001"}], "messages": [{"id": "wamid.OK"}]})

    body = {"type": "interactive", "text": "Draft ready.", "buttons": [{"id": "a:n1", "title": "Review quote"}, {"id": "a:n2", "title": "Open workspace"}], "reply_to": "wamid.IN"}
    result = _provider(handler).send(ACCOUNT, "919800000001", body, biz_opaque="outbox-1")
    assert result.outcome == "accepted" and result.wamid == "wamid.OK"
    assert seen["url"] == "https://graph.facebook.com/v26.0/123456/messages" and seen["auth"] == "Bearer token-xyz"
    sent = seen["body"]
    assert sent["messaging_product"] == "whatsapp" and sent["to"] == "919800000001" and sent["biz_opaque_callback_data"] == "outbox-1"
    assert sent["context"] == {"message_id": "wamid.IN"} and sent["type"] == "interactive"
    assert [b["reply"]["id"] for b in sent["interactive"]["action"]["buttons"]] == ["a:n1", "a:n2"]


@pytest.mark.parametrize(
    ("response", "outcome"),
    [
        (httpx.Response(500, json={"error": {"code": 131000}}), "unknown"),
        (httpx.Response(429, headers={"retry-after": "7"}, json={"error": {"code": 130429}}), "throttle"),
        (httpx.Response(400, json={"error": {"code": 131047, "message": "Re-engagement message"}}), "blocked"),
        (httpx.Response(400, json={"error": {"code": 131009}}), "failed"),
        (httpx.Response(200, json={"messages": []}), "unknown"),
    ],
)
def test_send_outcomes(response: httpx.Response, outcome: str) -> None:
    result = _provider(lambda _r: response).send(ACCOUNT, "919800000001", {"type": "text", "text": "x"}, biz_opaque="o")
    assert result.outcome == outcome
    if outcome == "throttle":
        assert result.retry_after_seconds == 7


def test_timeouts_and_resets_are_unknown_never_retried() -> None:
    def timeout(_r: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    def reset(_r: httpx.Request) -> httpx.Response:
        raise httpx.RemoteProtocolError("reset")

    assert _provider(timeout).send(ACCOUNT, "1", {"type": "text", "text": "x"}, biz_opaque="o").outcome == "unknown"
    assert _provider(reset).send(ACCOUNT, "1", {"type": "text", "text": "x"}, biz_opaque="o").outcome == "unknown"


def test_media_download_enforces_size_and_sha256() -> None:
    data = b"OggS" + b"\x00" * 100
    import hashlib

    ok = MediaInfo("m", "https://lookaside.fbsbx.com/m", "audio/ogg", hashlib.sha256(data).hexdigest(), len(data))
    provider = _provider(lambda _r: httpx.Response(200, content=data))
    assert provider.download_media(ACCOUNT, ok, max_bytes=1000) == data
    with pytest.raises(MediaError) as too_big:
        provider.download_media(ACCOUNT, ok, max_bytes=10)
    assert too_big.value.code == "media_too_large"
    bad = MediaInfo("m", "https://lookaside.fbsbx.com/m", "audio/ogg", "0" * 64, None)
    with pytest.raises(MediaError) as mismatch:
        provider.download_media(ACCOUNT, bad, max_bytes=1000)
    assert mismatch.value.code == "media_sha256_mismatch"
    expired = _provider(lambda _r: httpx.Response(404))
    with pytest.raises(MediaError) as gone:
        expired.download_media(ACCOUNT, ok, max_bytes=1000)
    assert gone.value.code == "media_url_expired"


def test_template_and_document_bodies() -> None:
    template = to_cloud_body("1", {"type": "template", "name": "lk_quote_ready", "language": "en", "components": []}, biz_opaque="o")
    assert template["template"]["name"] == "lk_quote_ready" and template["template"]["language"] == {"code": "en"}
    document = to_cloud_body("1", {"type": "document", "media_id": "MID", "filename": "LK-QT-2026-0003-r1.pdf", "caption": "Quote"}, biz_opaque="o")
    assert document["document"] == {"id": "MID", "filename": "LK-QT-2026-0003-r1.pdf", "caption": "Quote"}


# ---- rendering -------------------------------------------------------------------------------------------------------------
QUOTE_CARD = {
    "kind": "quote_draft", "quote_id": "q-1", "quote_number": "LK-QT-2026-0009", "status": "draft", "currency": "EUR",
    "lines": [{"product_name": "Oak tray", "quantity": "240", "uom": "", "unit_price": "24.0000"}],
    "totals": {"grand_total": "5760.0000", "currency": "EUR", "minimum_status": "MEETS"}, "review": {"path": "/sales/quotes/q-1"},
    "cost_price": "11.00",
}


def test_quote_draft_renders_card_figures_with_the_demo_prefix_and_two_buttons() -> None:
    out = render.render_turn("ignored model prose with 9999", [QUOTE_CARD], demo=True)
    assert out.text.startswith("Demo: Draft ready (LK-QT-2026-0009).")
    assert "240 Oak tray at EUR 24.00 each." in out.text and "Total EUR 5,760.00." in out.text
    assert "9999" not in out.text and "11.00" not in out.text
    assert [b.title for b in out.buttons] == ["Review quote", "Open workspace"]
    live = render.render_turn(None, [QUOTE_CARD], demo=False)
    assert not live.text.startswith("Demo:")


def test_clarification_renders_at_most_three_options() -> None:
    card = {"kind": "clarification", "question": "Which Nordhaus?", "options": [
        {"label": f"Option {i}", "action": {"slot": "party", "value": str(i)}} for i in range(5)]}
    out = render.render_turn(None, [card], demo=False)
    assert len(out.buttons) == 3 and "(2 more option(s) on the web.)" in out.text
    assert all(len(b.title) <= render.BUTTON_TITLE for b in out.buttons)


# ---- consent and window ---------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text", ["STOP", "stop", " Unsubscribe! ", "band karo", "Band Karo.", "बंद करो"])
def test_opt_out_keywords(text: str) -> None:
    assert consent.is_opt_out(text)


@pytest.mark.parametrize("text", ["stop the quote", "please band karo the order", "hello"])
def test_ordinary_messages_are_not_opt_outs(text: str) -> None:
    assert not consent.is_opt_out(text)


def test_window_is_24_hours_from_the_last_inbound() -> None:
    now = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)
    identity = SimpleNamespace(last_inbound_at=now - timedelta(hours=23, minutes=59))
    assert window.window_open(identity, now)  # type: ignore[arg-type]
    identity.last_inbound_at = now - timedelta(hours=24)
    assert not window.window_open(identity, now)  # type: ignore[arg-type]
    assert not window.window_open(SimpleNamespace(last_inbound_at=None), now)  # type: ignore[arg-type]
