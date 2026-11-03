"""Field encryption for message bodies (``channels_message.body_encrypted``).

Uses ``LK_DATA_ENCRYPTION_KEYS`` (``kid:base64key[,kid2:base64key]``, 32-byte keys): AES-256-GCM with a random
96-bit nonce; the ciphertext is ``kid || 0x00 || nonce || ciphertext+tag`` so a key rotation can decrypt old rows
while new rows use the first listed key. Without configured keys (development and test) a deterministic
development key is used and production refuses to start.

Candidate for ``app/platform``: the integrator may lift it there when a second module needs field encryption.
"""

from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings

_DEV_KID = "dev"
_DEV_KEY = b"lamikraft-one-dev-field-key-32by"  # exactly 32 bytes, development/test only


class DecryptError(ValueError):
    pass


def _keys() -> dict[str, bytes]:
    settings = get_settings()
    raw = settings.data_encryption_keys.get_secret_value().strip()
    if not raw:
        if settings.is_production:
            raise RuntimeError("LK_DATA_ENCRYPTION_KEYS must be set in production")
        return {_DEV_KID: _DEV_KEY}
    out: dict[str, bytes] = {}
    for part in raw.split(","):
        kid, _, b64 = part.strip().partition(":")
        if not kid or not b64 or ":" in kid or "\x00" in kid:
            raise RuntimeError("LK_DATA_ENCRYPTION_KEYS must be kid:base64key[,kid:base64key]")
        key = base64.b64decode(b64)
        if len(key) != 32:
            raise RuntimeError(f"data encryption key {kid} must be 32 bytes")
        out[kid] = key
    return out


def encrypt_text(text: str) -> bytes:
    keys = _keys()
    kid, key = next(iter(keys.items()))
    nonce = os.urandom(12)
    sealed = AESGCM(key).encrypt(nonce, text.encode("utf-8"), kid.encode("utf-8"))
    return kid.encode("utf-8") + b"\x00" + nonce + sealed


def decrypt_text(blob: bytes | None) -> str | None:
    if blob is None:
        return None
    kid_bytes, sep, rest = bytes(blob).partition(b"\x00")
    if not sep or len(rest) < 12 + 16:
        raise DecryptError("malformed ciphertext")
    kid = kid_bytes.decode("utf-8", errors="replace")
    key = _keys().get(kid)
    if key is None:
        raise DecryptError(f"no data encryption key {kid!r}")
    try:
        return AESGCM(key).decrypt(rest[:12], rest[12:], kid_bytes).decode("utf-8")
    except Exception as exc:  # cryptography raises InvalidTag
        raise DecryptError("ciphertext did not authenticate") from exc


__all__ = ["DecryptError", "decrypt_text", "encrypt_text"]
