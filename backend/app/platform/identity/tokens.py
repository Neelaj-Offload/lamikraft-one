"""Opaque tokens and keyed hashes.

Session, CSRF and demo sign-in tokens are 256-bit random values; only their SHA-256 is stored. Emails, IP
addresses and user agents used for rate limiting and attempt records are stored as HMAC-SHA256 under
``LK_SECRET_KEY`` so the tables never hold the raw values.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

from app.core.config import get_settings

#: development/test fallback when LK_SECRET_KEY is unset (production refuses to run without a key)
_DEV_KEY = b"lamikraft-one-development-only-key"


def new_token() -> str:
    """A 256-bit URL-safe random token."""
    return secrets.token_urlsafe(32)


def sha256(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).digest()


def _key() -> bytes:
    settings = get_settings()
    secret = settings.secret_key.get_secret_value()
    if secret:
        return secret.encode("utf-8")
    if settings.is_production:
        raise RuntimeError("LK_SECRET_KEY must be set in production")
    return _DEV_KEY


def keyed_hash(purpose: str, value: str) -> bytes:
    """HMAC-SHA256 of ``value`` under the application secret, domain-separated by ``purpose``."""
    return hmac.new(_key(), f"{purpose}\x00{value}".encode(), hashlib.sha256).digest()


def matches(token: str | None, stored_hash: bytes | None) -> bool:
    """Constant-time comparison of a presented token with a stored SHA-256."""
    if not token or not stored_hash:
        return False
    return hmac.compare_digest(sha256(token), bytes(stored_hash))


def normalize_email(email: str) -> str:
    return email.strip().lower()
