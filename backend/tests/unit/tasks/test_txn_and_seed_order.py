"""Transient-failure retry for work-lane commands (conventions 8) and the seed order of the lane."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import OperationalError

from app.modules.tasks import txn


class _Orig(Exception):
    def __init__(self, sqlstate: str) -> None:
        super().__init__(sqlstate)
        self.sqlstate = sqlstate


def _db_error(sqlstate: str) -> OperationalError:
    return OperationalError("stmt", {}, _Orig(sqlstate))


def test_deadlock_is_retried_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(txn.time, "sleep", lambda _s: None)
    calls = {"n": 0}

    def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise _db_error("40P01")
        return "ok"

    assert txn.retry_transient(flaky) == "ok" and calls["n"] == 3


def test_retry_gives_up_after_three_attempts_and_skips_other_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(txn.time, "sleep", lambda _s: None)
    calls = {"n": 0}

    def always() -> None:
        calls["n"] += 1
        raise _db_error("40001")

    with pytest.raises(OperationalError):
        txn.retry_transient(always)
    assert calls["n"] == txn.MAX_ATTEMPTS
    calls["n"] = 0

    def unique_violation() -> None:
        calls["n"] += 1
        raise _db_error("23505")

    with pytest.raises(OperationalError):
        txn.retry_transient(unique_violation)
    assert calls["n"] == 1


def test_briefings_seed_runs_after_the_tasks_seed() -> None:
    """Review minor 10: the briefings seed depends on the tasks seed (reminders, onboarding, manual tasks)."""
    from app.seed.world import briefings, tasks

    assert tasks.SEEDS[0].order < briefings.SEEDS[0].order
