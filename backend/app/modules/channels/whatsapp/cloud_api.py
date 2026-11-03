"""Meta WhatsApp Cloud API adapter (Graph API ``/{api_version}/...``, synchronous httpx).

Request shapes verified on 2026-11-03 against the Cloud API reference (messages, media, phone numbers, message
templates). A transport can be injected for tests (``httpx.MockTransport``); the live client uses a 10 s connect /
20 s read timeout. Timeouts and connection errors after the request was sent are reported as ``unknown`` — the
outbox never resends those automatically.
"""

from __future__ import annotations

import hashlib
from typing import Any

import httpx

from app.modules.channels.error_codes import classify, title_of
from app.modules.channels.whatsapp.provider import (
    AccountConfig,
    CheckOutcome,
    MediaError,
    MediaInfo,
    SendResult,
    TemplateInfo,
)

GRAPH_BASE = "https://graph.facebook.com"
TIMEOUT = httpx.Timeout(connect=10.0, read=20.0, write=20.0, pool=10.0)


def to_cloud_body(to: str, payload: dict[str, Any], *, biz_opaque: str) -> dict[str, Any]:
    """Our provider-neutral payload to the documented ``POST /{phone_number_id}/messages`` body."""
    kind = payload.get("type", "text")
    body: dict[str, Any] = {"messaging_product": "whatsapp", "recipient_type": "individual", "to": to, "biz_opaque_callback_data": biz_opaque}
    if payload.get("reply_to"):
        body["context"] = {"message_id": payload["reply_to"]}
    if kind == "text":
        body["type"] = "text"
        body["text"] = {"preview_url": False, "body": str(payload.get("text", ""))}
    elif kind == "interactive":
        buttons = [
            {"type": "reply", "reply": {"id": str(b["id"])[:256], "title": str(b["title"])[:20]}}
            for b in list(payload.get("buttons") or [])[:3]
        ]
        body["type"] = "interactive"
        body["interactive"] = {"type": "button", "body": {"text": str(payload.get("text", ""))[:1024]}, "action": {"buttons": buttons}}
    elif kind == "template":
        body["type"] = "template"
        body["template"] = {
            "name": payload["name"],
            "language": {"code": payload.get("language", "en")},
            "components": list(payload.get("components") or []),
        }
    elif kind == "document":
        document: dict[str, Any] = {}
        if payload.get("media_id"):
            document["id"] = payload["media_id"]
        elif payload.get("link"):
            document["link"] = payload["link"]
        if payload.get("filename"):
            document["filename"] = payload["filename"]
        if payload.get("caption"):
            document["caption"] = str(payload["caption"])[:1024]
        body["type"] = "document"
        body["document"] = document
    else:
        raise ValueError(f"unsupported outbound payload type {kind!r}")
    return body


class CloudApiProvider:
    name = "whatsapp_cloud"

    def __init__(self, transport: httpx.BaseTransport | None = None, base_url: str = GRAPH_BASE) -> None:
        self._transport = transport
        self._base_url = base_url

    def _client(self, account: AccountConfig) -> httpx.Client:
        return httpx.Client(
            base_url=self._base_url,
            transport=self._transport,
            timeout=TIMEOUT,
            headers={"Authorization": f"Bearer {account.access_token}", "Accept": "application/json"},
        )

    # ---- messages --------------------------------------------------------------------------------------------
    def send(self, account: AccountConfig, to: str, body: dict[str, Any], *, biz_opaque: str) -> SendResult:
        request_body = to_cloud_body(to, body, biz_opaque=biz_opaque)
        path = f"/{account.api_version}/{account.phone_number_id}/messages"
        try:
            with self._client(account) as client:
                response = client.post(path, json=request_body)
        except httpx.TimeoutException:
            return SendResult(outcome="unknown", error_title="timeout")
        except httpx.TransportError as exc:
            return SendResult(outcome="unknown", error_title=type(exc).__name__)
        return _send_result(response)

    # ---- media -----------------------------------------------------------------------------------------------
    def get_media(self, account: AccountConfig, media_id: str) -> MediaInfo:
        with self._client(account) as client:
            response = client.get(f"/{account.api_version}/{media_id}", params={"phone_number_id": account.phone_number_id})
        if response.status_code >= 400:
            raise MediaError("media_lookup_failed", f"HTTP {response.status_code}")
        data = response.json()
        return MediaInfo(
            media_id=media_id, url=str(data.get("url", "")), mime_type=data.get("mime_type"),
            sha256=data.get("sha256"), file_size=int(data["file_size"]) if data.get("file_size") is not None else None,
        )

    def download_media(self, account: AccountConfig, info: MediaInfo, *, max_bytes: int) -> bytes:
        if info.file_size is not None and info.file_size > max_bytes:
            raise MediaError("media_too_large", f"{info.file_size} bytes")
        with self._client(account) as client, client.stream("GET", info.url) as response:
            if response.status_code in (401, 403, 404):
                raise MediaError("media_url_expired", f"HTTP {response.status_code}")
            if response.status_code >= 400:
                raise MediaError("media_download_failed", f"HTTP {response.status_code}")
            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_bytes():
                total += len(chunk)
                if total > max_bytes:
                    raise MediaError("media_too_large", f"> {max_bytes} bytes")
                chunks.append(chunk)
        data = b"".join(chunks)
        if info.sha256 and not _sha_matches(data, info.sha256):
            raise MediaError("media_sha256_mismatch")
        return data

    def upload_media(self, account: AccountConfig, data: bytes, mime_type: str, filename: str) -> str:
        with self._client(account) as client:
            response = client.post(
                f"/{account.api_version}/{account.phone_number_id}/media",
                data={"messaging_product": "whatsapp", "type": mime_type},
                files={"file": (filename, data, mime_type)},
            )
        if response.status_code >= 400:
            raise MediaError("media_upload_failed", f"HTTP {response.status_code}")
        return str(response.json()["id"])

    # ---- account ---------------------------------------------------------------------------------------------
    def check_phone_number(self, account: AccountConfig) -> CheckOutcome:
        try:
            with self._client(account) as client:
                response = client.get(
                    f"/{account.api_version}/{account.phone_number_id}",
                    params={"fields": "display_phone_number,verified_name,quality_rating,code_verification_status"},
                )
        except httpx.TransportError as exc:
            return CheckOutcome(False, f"network: {type(exc).__name__}")
        if response.status_code >= 400:
            code = _error_code(response)
            return CheckOutcome(False, f"HTTP {response.status_code} {title_of(code) or ''}".strip(), {"error_code": code})
        data = response.json()
        return CheckOutcome(True, None, {
            "display_phone_number": data.get("display_phone_number"),
            "verified_name": data.get("verified_name"),
            "quality_rating": data.get("quality_rating"),
            "api_version": account.api_version,
        })

    def list_templates(self, account: AccountConfig) -> list[TemplateInfo]:
        if not account.waba_id:
            return []
        out: list[TemplateInfo] = []
        with self._client(account) as client:
            response = client.get(
                f"/{account.api_version}/{account.waba_id}/message_templates",
                params={"fields": "id,name,language,category,status,components", "limit": 200},
            )
        if response.status_code >= 400:
            raise MediaError("template_sync_failed", f"HTTP {response.status_code}")
        for item in response.json().get("data", []):
            out.append(TemplateInfo(
                provider_template_id=str(item.get("id")) if item.get("id") is not None else None,
                name=str(item["name"]), language=str(item.get("language", "en")),
                category=str(item.get("category", "UTILITY")), status=str(item.get("status", "UNKNOWN")).lower(),
                components=list(item.get("components") or []),
            ))
        return out


def _sha_matches(data: bytes, expected: str) -> bool:
    digest = hashlib.sha256(data)
    expected = expected.strip()
    if len(expected) == 64:
        return digest.hexdigest().lower() == expected.lower()
    import base64

    try:
        return digest.digest() == base64.b64decode(expected)
    except Exception:
        return False


def _error_code(response: httpx.Response) -> int | None:
    try:
        error = response.json().get("error") or {}
        code = error.get("code")
        return int(code) if code is not None else None
    except Exception:
        return None


def _send_result(response: httpx.Response) -> SendResult:
    request_id = response.headers.get("x-fb-trace-id") or response.headers.get("x-fb-request-id")
    if 200 <= response.status_code < 300:
        wamid: str | None = None
        try:
            messages = response.json().get("messages") or []
            wamid = str(messages[0]["id"]) if messages else None
        except Exception:
            wamid = None
        if wamid is None:  # a 2xx without a message id cannot be reconciled: treat as unknown, never resend
            return SendResult(outcome="unknown", http_status=response.status_code, error_title="no_message_id", request_id=request_id)
        return SendResult(outcome="accepted", wamid=wamid, http_status=response.status_code, request_id=request_id)
    code = _error_code(response)
    outcome = classify(response.status_code, code)
    retry_after = None
    if outcome == "throttle":
        header = response.headers.get("retry-after")
        retry_after = int(header) if header and header.isdigit() else 60
    return SendResult(
        outcome=outcome, http_status=response.status_code, error_code=code, error_title=title_of(code),
        retry_after_seconds=retry_after, request_id=request_id,
    )


__all__ = ["GRAPH_BASE", "CloudApiProvider", "to_cloud_body"]
