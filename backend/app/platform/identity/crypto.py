"""Authenticated encryption of small secrets (TOTP seeds) with the ``LK_DATA_ENCRYPTION_KEYS`` keyring.

The keyring is ``kid:base64key[,kid2:base64key]``; the first key encrypts, every key decrypts, so keys can be
rotated by prepending a new one. AES-256-GCM with a random 96-bit nonce; the stored value is ``nonce || ciphertext``
and the key id is stored next to it. The associated data binds a ciphertext to its purpose and owner, so a seed
copied onto another user's row does not decrypt. Development and test fall back to a fixed key when the keyring
is empty; production refuses (losing the keys forces MFA re-enrolment, see the runbook).
"""

from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings

_DEV_KID = "dev"


@dataclass(frozen=True)
class Sealed:
    key_id: str
    blob: bytes


def _keyring() -> list[tuple[str, bytes]]:
    settings = get_settings()
    raw = settings.data_encryption_keys.get_secret_value().strip()
    ring: list[tuple[str, bytes]] = []
    for part in (p.strip() for p in raw.split(",") if p.strip()):
        kid, sep, b64 = part.partition(":")
        if not sep:
            raise RuntimeError("LK_DATA_ENCRYPTION_KEYS entries must be kid:base64key")
        key = base64.b64decode(b64)
        if len(key) not in (16, 24, 32):
            raise RuntimeError(f"LK_DATA_ENCRYPTION_KEYS key {kid!r} must be 128, 192 or 256 bits")
        ring.append((kid, key))
    if ring:
        return ring
    if settings.is_production:
        raise RuntimeError("LK_DATA_ENCRYPTION_KEYS must be set in production")
    return [(_DEV_KID, hashlib.sha256(b"lamikraft-one-development-only-data-key").digest())]


def seal(plaintext: bytes, *, aad: str) -> Sealed:
    kid, key = _keyring()[0]
    nonce = os.urandom(12)
    return Sealed(kid, nonce + AESGCM(key).encrypt(nonce, plaintext, aad.encode()))


def unseal(sealed: Sealed, *, aad: str) -> bytes:
    keys = dict(_keyring())
    key = keys.get(sealed.key_id)
    if key is None:
        raise RuntimeError(f"encryption key {sealed.key_id!r} is not in LK_DATA_ENCRYPTION_KEYS")
    blob = bytes(sealed.blob)
    return AESGCM(key).decrypt(blob[:12], blob[12:], aad.encode())
