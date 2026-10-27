"""Transient-failure retry for work-lane commands (conventions §8).

Lock order inside the work lane is fixed: an issue row first, then its task rows (by id), then queue
issues, then per-user briefing rows. A deadlock or serialisation failure can still come from rows other
modules lock, so whole commands are retried up to three times in a fresh unit of work; this is safe
because unsafe commands carry idempotency keys. Event consumers and jobs are retried by the job runtime
(any non-application error is retryable there), so only HTTP commands use this wrapper.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable

from sqlalchemy.exc import DBAPIError

#: deadlock_detected, serialization_failure
TRANSIENT_SQLSTATES = frozenset({"40P01", "40001"})
MAX_ATTEMPTS = 3


def is_transient(exc: BaseException | None) -> bool:
    seen = 0
    while exc is not None and seen < 10:
        if isinstance(exc, DBAPIError):
            state = getattr(exc.orig, "sqlstate", None) or getattr(getattr(exc.orig, "diag", None), "sqlstate", None)
            if state in TRANSIENT_SQLSTATES:
                return True
        exc = exc.__cause__ or exc.__context__
        seen += 1
    return False


def retry_transient[T](fn: Callable[[], T], *, attempts: int = MAX_ATTEMPTS) -> T:
    """Run ``fn`` (which opens and commits its own unit of work) again after a transient failure."""
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:
            if attempt >= attempts or not is_transient(exc):
                raise
            time.sleep(0.02 * attempt * random.uniform(0.5, 1.5))  # noqa: S311 - jitter, not security
    raise AssertionError("unreachable")  # pragma: no cover
