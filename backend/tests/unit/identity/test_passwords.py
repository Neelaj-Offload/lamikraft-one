"""argon2id hashing and the password policy (api-conventions §7)."""

from __future__ import annotations

import threading
import time

import pytest

from app.platform.identity import passwords

GOOD = "plover-Granite-41-quarry"


def test_hash_is_argon2id_and_verifies() -> None:
    stored = passwords.hash_password(GOOD)
    assert stored.startswith("$argon2id$")
    assert passwords.verify_password(stored, GOOD)
    assert not passwords.verify_password(stored, GOOD + "!")
    assert not passwords.verify_password(stored, GOOD.upper())
    assert not passwords.needs_rehash(stored)


def test_missing_or_corrupt_hash_never_verifies() -> None:
    assert not passwords.verify_password(None, GOOD)
    assert not passwords.verify_password("not-a-hash", GOOD)
    assert passwords.needs_rehash("not-a-hash")


def test_out_of_policy_lengths_never_verify() -> None:
    long_password = "a1-" * 100  # 300 characters
    stored = passwords.hash_password(long_password[:256])
    assert not passwords.verify_password(stored, long_password)  # never hashes more than 256 characters
    assert not passwords.verify_password(passwords.hash_password("short"), "short")


@pytest.mark.parametrize(
    ("password", "code"),
    [
        ("x" * 11, "password_too_short"),
        ("x" * 257, "password_too_long"),
        ("Password1234", "password_too_common"),
        ("qwertyuiop123", "password_too_common"),
        ("meera.iyer-rocks-2026", "password_contains_email"),
        ("crown-decor-forever-9", "password_contains_company"),
    ],
)
def test_policy_rejections(password: str, code: str) -> None:
    violation = passwords.check_policy(password, email="meera.iyer@demo.lamikraft.test", company_names=("crown-decor", "Crown Decor"))
    assert violation is not None and violation.code == code


def test_policy_accepts_twelve_to_256_characters_without_composition_rules() -> None:
    assert passwords.check_policy("aaaabbbbcccc") is None
    assert passwords.check_policy("ab" * 128) is None
    assert passwords.check_policy(GOOD, email="someone@example.test") is None
    assert all(len(p) >= 12 for p in passwords.COMMON_PASSWORDS)


def test_at_most_four_hashes_run_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    active = 0
    peak = 0
    lock = threading.Lock()
    real = passwords._hasher

    class SlowHasher:
        def hash(self, value: str) -> str:
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.05)
            with lock:
                active -= 1
            return real.hash(value)

    monkeypatch.setattr(passwords, "_hasher", SlowHasher())
    threads = [threading.Thread(target=passwords.hash_password, args=(GOOD,)) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert 1 <= peak <= passwords.HASH_CONCURRENCY
