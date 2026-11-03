"""The Demo WhatsApp provider: accepts every send with a ``wamid.demo.`` id and, after the sender's transaction
commits, posts **signed** simulated status payloads (sent, delivered, read) through the real webhook ingest, so
reconciliation, replay and signature checks run exactly as in live mode. Simulated statuses are flagged
``simulated`` (the wamid prefix identifies them) and never shown as real delivery evidence.

Demo media are registered in memory by the simulator (fixture bytes); the demo STT maps their SHA-256 to a
transcript. Nothing here talks to Meta."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.modules.channels.whatsapp.provider import (
    AccountConfig,
    CheckOutcome,
    MediaError,
    MediaInfo,
    SendResult,
    TemplateInfo,
)
from app.modules.channels.whatsapp.signature import app_secrets, sign

DEMO_WAMID_PREFIX = "wamid.demo."
DEMO_MEDIA_PREFIX = "demo-media-"

#: fixture audio: key -> (bytes, mime, transcript); the STT demo adapter answers by SHA-256 of the bytes
DEMO_AUDIO_FIXTURES: dict[str, tuple[bytes, str, str]] = {
    "oak_tray_quote": (b"LK-DEMO-AUDIO:oak_tray_quote:v1", "audio/ogg; codecs=opus", "Prepare Nordhaus's usual oak tray quote"),
    "hinglish_oak_tray": (b"LK-DEMO-AUDIO:hinglish_oak_tray:v1", "audio/ogg; codecs=opus", "Nordhaus ka usual oak tray quote bana do"),
    "unclear": (b"LK-DEMO-AUDIO:unclear:v1", "audio/ogg; codecs=opus", ""),
}

DEMO_TEMPLATES: tuple[TemplateInfo, ...] = (
    TemplateInfo("demo-tpl-1", "lk_quote_ready", "en", "UTILITY", "approved", [{"type": "BODY", "text": "Demo: your quote {{1}} is ready. Total {{2}}."}]),
    TemplateInfo("demo-tpl-2", "lk_daily_briefing", "en", "UTILITY", "approved", [{"type": "BODY", "text": "Demo: your briefing for {{1}}: {{2}}"}]),
    TemplateInfo("demo-tpl-3", "lk_followup_offer", "en", "MARKETING", "paused", [{"type": "BODY", "text": "Demo: offer {{1}}"}]),
    TemplateInfo("demo-tpl-4", "lk_price_update", "en", "UTILITY", "rejected", [{"type": "BODY", "text": "Demo: price update {{1}}"}]),
)

Ingest = Callable[[bytes, str, str | None], Any]
_ingest: Ingest | None = None
_media: dict[str, tuple[bytes, str]] = {}


def set_ingest(fn: Ingest | None) -> None:
    """How simulated statuses reach the webhook; default: the in-process ingest function the route itself calls."""
    global _ingest
    _ingest = fn


def _default_ingest(body: bytes, signature: str, remote_addr: str | None) -> Any:
    from app.modules.channels.webhook import ingest_signed

    return ingest_signed(body, signature, remote_addr=remote_addr or "demo-provider")


def register_media(data: bytes, mime_type: str) -> str:
    media_id = DEMO_MEDIA_PREFIX + hashlib.sha256(data).hexdigest()[:24]
    _media[media_id] = (data, mime_type)
    return media_id


def lookup_media(media_id: str) -> tuple[bytes, str] | None:
    """Registered bytes, else a fixture voice note by its content-derived id. The simulator registers media in the API
    process but the worker downloads them, so fixture media must resolve in any process (Slice-3 stage-1 merge)."""
    entry = _media.get(media_id)
    if entry is not None:
        return entry
    for data, mime, _transcript in DEMO_AUDIO_FIXTURES.values():
        if DEMO_MEDIA_PREFIX + hashlib.sha256(data).hexdigest()[:24] == media_id:
            return data, mime
    return None


def register_fixture_audio(key: str) -> tuple[str, str, str]:
    """(media id, mime, sha256) of a fixture voice note."""
    data, mime, _ = DEMO_AUDIO_FIXTURES[key]
    return register_media(data, mime), mime, hashlib.sha256(data).hexdigest()


def transcript_for_sha256(sha256: str) -> str | None:
    for data, _mime, transcript in DEMO_AUDIO_FIXTURES.values():
        if hashlib.sha256(data).hexdigest() == sha256:
            return transcript
    return None


def signed_webhook_body(payload: dict[str, Any]) -> tuple[bytes, str]:
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    secrets = app_secrets()
    if not secrets:
        raise RuntimeError("demo provider cannot sign: no app secret available")
    return body, sign(body, secrets[0])


def status_payload(account: AccountConfig, wamid: str, recipient: str, statuses: list[tuple[str, int]], *, biz_opaque: str | None) -> dict[str, Any]:
    """A Cloud-API-shaped ``messages`` change carrying the given (status, unix timestamp) pairs."""
    items = []
    for status, ts in statuses:
        item: dict[str, Any] = {"id": wamid, "status": status, "timestamp": str(ts), "recipient_id": recipient}
        if biz_opaque:
            item["biz_opaque_callback_data"] = biz_opaque
        if status == "sent":
            item["conversation"] = {"id": f"demo-conv-{wamid[-8:]}", "origin": {"type": "service"}}
            item["pricing"] = {"billable": False, "pricing_model": "CBP", "category": "service"}
        items.append(item)
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": account.waba_id or "demo-waba",
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"display_phone_number": account.display_phone or "", "phone_number_id": account.phone_number_id},
                    "statuses": items,
                },
            }],
        }],
    }


def inbound_payload(
    account: AccountConfig, *, wa_id: str, bsuid: str | None, message: dict[str, Any], ts: int, name: str = "Demo user",
) -> dict[str, Any]:
    """A Cloud-API-shaped inbound ``messages`` change from ``wa_id`` at unix time ``ts`` (business clock; used by
    the simulator endpoint and tests)."""
    contact: dict[str, Any] = {"profile": {"name": name}, "wa_id": wa_id}
    if bsuid:
        contact["user_id"] = bsuid
    message = {"from": wa_id, "timestamp": str(ts), **message}
    if bsuid:
        message["from_user_id"] = bsuid
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": account.waba_id or "demo-waba",
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"display_phone_number": account.display_phone or "", "phone_number_id": account.phone_number_id},
                    "contacts": [contact],
                    "messages": [message],
                },
            }],
        }],
    }


def new_wamid() -> str:
    return DEMO_WAMID_PREFIX + uuid.uuid4().hex


def is_simulated_wamid(wamid: str | None) -> bool:
    return bool(wamid) and str(wamid).startswith(DEMO_WAMID_PREFIX)


@dataclass
class DemoProvider:
    name: str = "demo"

    def send(self, account: AccountConfig, to: str, body: dict[str, Any], *, biz_opaque: str) -> SendResult:
        return SendResult(outcome="accepted", wamid=new_wamid(), http_status=200, request_id="demo")

    def simulate_statuses(self, account: AccountConfig, wamid: str, recipient: str, *, biz_opaque: str, now_ts: int) -> None:
        """Post sent/delivered/read (one second apart) through the signed webhook ingest; called after commit."""
        payload = status_payload(account, wamid, recipient, [("sent", now_ts), ("delivered", now_ts + 1), ("read", now_ts + 2)], biz_opaque=biz_opaque)
        self.post(payload)

    def post(self, payload: dict[str, Any]) -> Any:
        body, signature = signed_webhook_body(payload)
        return (_ingest or _default_ingest)(body, signature, "demo-provider")

    def get_media(self, account: AccountConfig, media_id: str) -> MediaInfo:
        entry = lookup_media(media_id)
        if entry is None:
            raise MediaError("media_url_expired", "demo media not registered")
        data, mime = entry
        return MediaInfo(media_id=media_id, url=f"demo://media/{media_id}", mime_type=mime, sha256=hashlib.sha256(data).hexdigest(), file_size=len(data))

    def download_media(self, account: AccountConfig, info: MediaInfo, *, max_bytes: int) -> bytes:
        entry = lookup_media(info.media_id)
        if entry is None:
            raise MediaError("media_url_expired", "demo media not registered")
        data = entry[0]
        if len(data) > max_bytes:
            raise MediaError("media_too_large", f"{len(data)} bytes")
        if info.sha256 and hashlib.sha256(data).hexdigest() != info.sha256:
            raise MediaError("media_sha256_mismatch")
        return data

    def upload_media(self, account: AccountConfig, data: bytes, mime_type: str, filename: str) -> str:
        return register_media(data, mime_type)

    def check_phone_number(self, account: AccountConfig) -> CheckOutcome:
        return CheckOutcome(False, "Demo provider: no Graph API check is possible without live credentials", {"simulated": True})

    def list_templates(self, account: AccountConfig) -> list[TemplateInfo]:
        return list(DEMO_TEMPLATES)


__all__ = [
    "DEMO_AUDIO_FIXTURES", "DEMO_MEDIA_PREFIX", "DEMO_TEMPLATES", "DEMO_WAMID_PREFIX", "DemoProvider", "inbound_payload", "is_simulated_wamid",
    "lookup_media", "new_wamid", "register_fixture_audio", "register_media", "set_ingest", "signed_webhook_body", "status_payload", "transcript_for_sha256",
]
