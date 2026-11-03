"""The public WhatsApp webhook (``/api/v1/webhooks/whatsapp``; design §15).

- ``GET``: the subscription handshake. ``hub.mode=subscribe`` with the verify token (constant-time compare) → 200
  with ``hub.challenge`` as text and ``handshake_ok_at`` recorded; anything else → 403.
- ``POST``: the raw body (at most 4 MB) is verified against ``X-Hub-Signature-256`` (HMAC-SHA256 with the
  current or previous app secret, ``compare_digest``). Missing or invalid → 403 and a ``webhook_rejection`` row
  (no payload stored). Valid → one inbox row and a ``wa.inbox.process`` job in one short transaction, then 200;
  a database failure → 500 so Meta retries (duplicates are normal and dedupe downstream).

No session and no CSRF check (``webhook`` authz kind); rate-limited per remote address. The Demo provider's
simulated statuses and the Settings simulator call :func:`ingest_signed`, the same function the route calls.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta

from fastapi import APIRouter, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, PlainTextResponse, Response

from app.core.http.authz_decl import webhook
from app.core.logging import get_logger
from app.modules.channels import events as ev
from app.modules.channels.models import WebhookInbox, WebhookRejection
from app.modules.channels.whatsapp import signature
from app.platform.authz.context import ActorContext
from app.platform.uow import UnitOfWork

log = get_logger("lk.channels.webhook")

MAX_BODY = 4 * 1024 * 1024
INBOX_RETENTION = timedelta(days=30)
#: per remote address per 10-minute window: signed deliveries (Meta bursts) and rejected ones (probing)
DELIVERY_LIMIT = 20000
REJECTION_LIMIT = 100

router = APIRouter(prefix="/webhooks", tags=["channels"])


@dataclass(frozen=True)
class IngestResult:
    status_code: int
    inbox_id: str | None = None
    reason: str | None = None


def _addr_hash(remote_addr: str | None) -> str | None:
    if not remote_addr:
        return None
    from app.platform.identity.tokens import keyed_hash

    return keyed_hash("channels.webhook.addr", remote_addr).hex()


def _limited(bucket: str, limit: int) -> bool:
    from app.platform.identity.ratelimit import hit

    with UnitOfWork(ActorContext.system(None, reason="channels.webhook.rate")) as uow:
        return not hit(uow.session, bucket, limit=limit, now=uow.now()).allowed


def _reject(reason: str, remote_addr: str | None, body: bytes | None) -> IngestResult:
    try:
        with UnitOfWork(ActorContext.system(None, reason="channels.webhook.reject")) as uow:
            import uuid

            uow.add(WebhookRejection(
                id=uuid.uuid7(), received_at=uow.now(), reason=reason[:40], remote_addr_hash=_addr_hash(remote_addr),
                body_sha256=hashlib.sha256(body).hexdigest() if body is not None else None,
            ))
    except Exception as exc:  # the 403 stands even when the rejection row could not be written
        log.warning("channels.webhook.rejection_not_recorded", error=type(exc).__name__)
    return IngestResult(403, reason=reason)


def _simulated(payload: dict) -> bool:
    """Deliveries for a demo account (``demo-…`` phone number id) carry simulated content."""
    try:
        for entry in payload.get("entry") or []:
            for change in entry.get("changes") or []:
                pnid = str(((change.get("value") or {}).get("metadata") or {}).get("phone_number_id") or "")
                if not pnid.startswith("demo-"):
                    return False
        return True
    except AttributeError:
        return False


def ingest_signed(body: bytes, signature_header: str | None, *, remote_addr: str | None = None) -> IngestResult:
    """Verify, store and enqueue one delivery (synchronous; the route runs it in the thread pool)."""
    import uuid

    addr_bucket = _addr_hash(remote_addr) or "-"
    if len(body) > MAX_BODY:
        return _reject("body_too_large", remote_addr, None)
    if not signature.verify_signature(body, signature_header):
        if _limited(f"wa_webhook_reject:{addr_bucket[:40]}", REJECTION_LIMIT):
            return IngestResult(429, reason="rate_limited")
        return _reject("signature_missing" if not signature_header else "signature_invalid", remote_addr, body)
    if _limited(f"wa_webhook:{addr_bucket[:40]}", DELIVERY_LIMIT):
        return IngestResult(429, reason="rate_limited")
    try:
        payload = json.loads(body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("payload is not an object")
    except (UnicodeDecodeError, ValueError):
        return _reject("malformed_json", remote_addr, body)
    if payload.get("object") != "whatsapp_business_account":
        return _reject("unexpected_object", remote_addr, body)
    with UnitOfWork(ActorContext.system(None, reason="channels.webhook")) as uow:
        now = uow.now()
        inbox = WebhookInbox(
            id=uuid.uuid7(), provider="whatsapp", received_at=now, body_sha256=hashlib.sha256(body).hexdigest(), payload=payload,
            simulated=_simulated(payload), status="pending", attempts=0, purge_at=now + INBOX_RETENTION,
        )
        uow.add(inbox)
        uow.flush()
        uow.enqueue(ev.JOB_INBOX_PROCESS, {"inbox_id": str(inbox.id)}, resource_type="channels.webhook_inbox", resource_id=inbox.id)
        inbox_id = str(inbox.id)
    return IngestResult(200, inbox_id=inbox_id)


@router.get("/whatsapp", openapi_extra=webhook("whatsapp"), response_class=PlainTextResponse)
def verify_subscription(
    mode: str | None = Query(default=None, alias="hub.mode"),
    token: str | None = Query(default=None, alias="hub.verify_token", max_length=512),
    challenge: str | None = Query(default=None, alias="hub.challenge", max_length=512),
) -> Response:
    """Meta's subscription handshake: echoes the challenge when the verify token matches."""
    if not signature.verify_handshake(mode, token) or challenge is None:
        return PlainTextResponse("Forbidden", status_code=403)
    from app.core.clock import get_clock
    from app.modules.channels.whatsapp.accounts import mark_handshake

    try:
        mark_handshake(get_clock().now())
    except Exception as exc:  # the handshake answer must not depend on the bookkeeping
        log.warning("channels.webhook.handshake_not_recorded", error=type(exc).__name__)
    return PlainTextResponse(challenge, status_code=200)


@router.post("/whatsapp", openapi_extra=webhook("whatsapp"), status_code=200)
async def receive_delivery(request: Request) -> Response:
    """A signed delivery from Meta (or the Demo provider): stored and queued; 200 within the time budget."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BODY:
        await run_in_threadpool(_reject, "body_too_large", request.client.host if request.client else None, None)
        return JSONResponse({"status": "rejected"}, status_code=413)
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BODY:
            await run_in_threadpool(_reject, "body_too_large", request.client.host if request.client else None, None)
            return JSONResponse({"status": "rejected"}, status_code=413)
        chunks.append(chunk)
    body = b"".join(chunks)
    remote = request.client.host if request.client else None
    try:
        result = await run_in_threadpool(ingest_signed, body, request.headers.get("x-hub-signature-256"), remote_addr=remote)
    except Exception as exc:  # database down: Meta retries for up to 7 days
        log.error("channels.webhook.ingest_failed", error=type(exc).__name__)
        return JSONResponse({"status": "error"}, status_code=500)
    if result.status_code == 200:
        return JSONResponse({"status": "accepted"}, status_code=200)
    if result.status_code == 429:
        return JSONResponse({"status": "rate_limited"}, status_code=429, headers={"Retry-After": "60"})
    return JSONResponse({"status": "rejected"}, status_code=result.status_code)


__all__ = ["INBOX_RETENTION", "MAX_BODY", "IngestResult", "ingest_signed", "router"]
