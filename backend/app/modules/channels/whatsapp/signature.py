"""Webhook signature (``X-Hub-Signature-256``) and the verify-token handshake, both constant-time.

The HMAC is computed over the raw request bytes exactly as received; re-serialising the JSON (whitespace,
unicode escaping) changes the bytes and must fail. The current and the previous app secret are accepted during a
rotation. In demo mode the Demo provider signs with the same secrets, so its payloads travel the real route.
"""

from __future__ import annotations

import hashlib
import hmac

from app.core.config import Settings, get_settings

PREFIX = "sha256="


def _derived(purpose: str) -> str:
    """A deterministic development secret derived from the application secret (demo mode without Meta values)."""
    from app.platform.identity.tokens import keyed_hash

    return keyed_hash(f"channels.whatsapp.{purpose}", "demo").hex()


def app_secrets(settings: Settings | None = None) -> list[str]:
    settings = settings or get_settings()
    current = settings.whatsapp_app_secret.get_secret_value()
    previous = settings.whatsapp_app_secret_previous.get_secret_value()
    if not current:
        if settings.whatsapp_mode == "live":
            return []  # live mode without a secret verifies nothing (fails visibly as not_configured)
        current = _derived("app_secret")
    return [s for s in (current, previous) if s]


def verify_token(settings: Settings | None = None) -> str | None:
    settings = settings or get_settings()
    value = settings.whatsapp_verify_token.get_secret_value()
    if value:
        return value
    return None if settings.whatsapp_mode == "live" else _derived("verify_token")


def sign(body: bytes, secret: str) -> str:
    return PREFIX + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def verify_signature(body: bytes, header: str | None, settings: Settings | None = None) -> bool:
    if not header or not header.startswith(PREFIX):
        return False
    presented = header[len(PREFIX):].strip().lower()
    if len(presented) != 64:
        return False
    ok = False
    for secret in app_secrets(settings):
        expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        # evaluate every secret so timing does not reveal which one matched
        ok = hmac.compare_digest(expected, presented) or ok
    return ok


def verify_handshake(mode: str | None, token: str | None, settings: Settings | None = None) -> bool:
    expected = verify_token(settings)
    if mode != "subscribe" or not token or expected is None:
        return False
    return hmac.compare_digest(expected.encode("utf-8"), token.encode("utf-8"))


__all__ = ["PREFIX", "app_secrets", "sign", "verify_handshake", "verify_signature", "verify_token"]
