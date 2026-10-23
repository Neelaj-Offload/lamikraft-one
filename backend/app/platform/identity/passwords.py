"""Password hashing (argon2id) and the password policy.

argon2-cffi's ``PasswordHasher`` defaults (argon2id, RFC 9106 low-memory profile) cost about 64 MiB per
hash, so hashing and verification run in a dedicated pool of four threads behind a semaphore of four: at most
four run at once, however many requests arrive (api-conventions §7). Verification against a fixed dummy hash keeps the
timing of unknown, locked or password-less accounts identical to a real check.

Policy: 12–256 characters, no composition rules, not in the bundled common-password list, and not
containing the email local part or the company name/key.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

MIN_LENGTH = 12
MAX_LENGTH = 256
HASH_CONCURRENCY = 4

_hasher = PasswordHasher()
_pool = ThreadPoolExecutor(max_workers=HASH_CONCURRENCY, thread_name_prefix="lk-argon2")
_slots = threading.BoundedSemaphore(HASH_CONCURRENCY)
_dummy_lock = threading.Lock()
_dummy_hash: str | None = None

#: Frequently breached or guessable passwords of at least 12 characters (shorter ones fail the length rule).
COMMON_PASSWORDS: frozenset[str] = frozenset(
    {
        "password1234", "password12345", "password123456", "password@123", "password@1234", "passwordpassword",
        "password!234", "p@ssw0rd1234", "p@ssword1234", "passw0rd1234", "mypassword123", "newpassword123",
        "123456789012", "1234567890123", "12345678901234", "123456123456", "111111111111", "000000000000",
        "121212121212", "123123123123", "112233445566", "987654321098", "098765432109", "147258369147",
        "qwertyuiop12", "qwertyuiop123", "qwerty123456", "qwerty1234567", "qwertyqwerty", "1q2w3e4r5t6y",
        "1qaz2wsx3edc", "zaq12wsxcde3", "asdfghjkl123", "zxcvbnm12345", "abcdefghijkl", "abc123456789",
        "abcd12345678", "aaaaaaaaaaaa", "iloveyou1234", "iloveyou12345", "welcome12345", "welcome@1234",
        "welcometoindia", "letmein12345", "changeme1234", "changeme12345", "administrator", "admin1234567",
        "admin@123456", "adminadmin12", "superman1234", "batman123456", "football1234", "baseball1234",
        "cricket12345", "sunshine1234", "princess1234", "monkey123456", "dragon123456", "master123456",
        "trustno11234", "starwars1234", "computer1234", "internet1234", "whatever1234", "india@123456",
        "bharat123456", "mumbai123456", "delhi1234567", "lamikraft123", "lamikraft@123", "lamikraft1234",
        "crowndecor123", "crown@123456", "crowndecor@1", "company12345", "welcome2026!", "welcome@2026",
        "password2026", "password2025", "spring2026!!", "summer2026!!", "winter2026!!", "january2026!",
        "letmeinplease", "openthedoor1", "correcthorsebatterystaple",
    }
)


@dataclass(frozen=True)
class PolicyViolation:
    code: str
    message: str


def check_policy(password: str, *, email: str | None = None, company_names: tuple[str, ...] = ()) -> PolicyViolation | None:
    if len(password) < MIN_LENGTH:
        return PolicyViolation("password_too_short", f"Use at least {MIN_LENGTH} characters.")
    if len(password) > MAX_LENGTH:
        return PolicyViolation("password_too_long", f"Use at most {MAX_LENGTH} characters.")
    lowered = password.lower()
    if lowered in COMMON_PASSWORDS:
        return PolicyViolation("password_too_common", "This password is too common. Choose another one.")
    if email:
        local = email.split("@", 1)[0].strip().lower()
        if len(local) >= 3 and local in lowered:
            return PolicyViolation("password_contains_email", "Do not include your email name in the password.")
    for name in company_names:
        token = name.strip().lower()
        if len(token) >= 4 and token in lowered:
            return PolicyViolation("password_contains_company", "Do not include the company name in the password.")
    return None


def _hash(password: str) -> str:
    with _slots:
        return _hasher.hash(password)


def hash_password(password: str) -> str:
    return _pool.submit(_hash, password).result()


def _verify(stored_hash: str, password: str) -> bool:
    with _slots:
        try:
            return _hasher.verify(stored_hash, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False


def _dummy() -> str:
    global _dummy_hash
    with _dummy_lock:
        if _dummy_hash is None:
            _dummy_hash = _hasher.hash("lamikraft-one/dummy-password-for-uniform-timing")
        return _dummy_hash


def verify_password(stored_hash: str | None, password: str) -> bool:
    """True when ``password`` matches; a missing hash or an out-of-policy length still costs one verification."""
    candidate = password if len(password) <= MAX_LENGTH else password[:MAX_LENGTH]
    if not stored_hash:
        _pool.submit(_verify, _dummy(), candidate).result()
        return False
    ok = _pool.submit(_verify, stored_hash, candidate).result()
    return ok and MIN_LENGTH <= len(password) <= MAX_LENGTH


def needs_rehash(stored_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(stored_hash)
    except InvalidHashError:
        return True
