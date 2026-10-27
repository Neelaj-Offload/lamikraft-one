"""Upload rate limiting (api-conventions §11: ``POST /api/v1/files`` is rate-limited).

The router calls ``check_upload_rate`` before a single byte of the body is read, so rejected and accepted
uploads both count. The built-in limiter is a sliding window per (company, user) held by this process:
``UPLOADS_PER_WINDOW`` uploads per ``WINDOW_SECONDS``. Postgres-backed counting shared by every worker belongs to
the identity lane (``rate_limit_counter``); its limiter replaces this one through ``set_upload_limiter`` when it
lands (merge dependency recorded in docs/lanes/platform.md), and the call site does not change.
"""

from __future__ import annotations

import math
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable
from typing import TYPE_CHECKING

from app.core.errors import RateLimited

if TYPE_CHECKING:
    from app.platform.authz.context import ActorContext

UPLOADS_PER_WINDOW = 60
WINDOW_SECONDS = 600

#: (actor) -> seconds until the next upload is allowed, or None when it is allowed now (and counted)
UploadLimiter = Callable[["ActorContext"], float | None]


class SlidingWindowLimiter:
    """At most ``limit`` hits per ``window`` seconds per key (monotonic time; not business time)."""

    def __init__(self, limit: int, window: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.limit = limit
        self.window = window
        self._clock = clock
        self._hits: dict[tuple[uuid.UUID | None, uuid.UUID | None], deque[float]] = {}
        self._lock = threading.Lock()

    def __call__(self, actor: ActorContext) -> float | None:
        key = (actor.company_id, actor.user_id)
        now = self._clock()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= now - self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return max(0.0, hits[0] + self.window - now)
            hits.append(now)
            if len(self._hits) > 10_000:  # bound memory: forget keys whose window has passed
                for stale in [k for k, v in self._hits.items() if not v or v[-1] <= now - self.window]:
                    del self._hits[stale]
            return None


_limiter: UploadLimiter = SlidingWindowLimiter(UPLOADS_PER_WINDOW, WINDOW_SECONDS)


def set_upload_limiter(limiter: UploadLimiter | None) -> None:
    """Install a limiter (identity's Postgres counter at merge; tests use small windows). None restores the
    built-in per-process limiter."""
    global _limiter
    _limiter = limiter if limiter is not None else SlidingWindowLimiter(UPLOADS_PER_WINDOW, WINDOW_SECONDS)


def check_upload_rate(actor: ActorContext) -> None:
    """Raise 429 ``rate_limited`` (with ``retry_after_seconds``) when the actor uploads too often."""
    if actor.is_system:
        return
    retry_after = _limiter(actor)
    if retry_after is not None:
        raise RateLimited(
            "Too many uploads in a short time; try again shortly.",
            retry_after_seconds=max(1, math.ceil(retry_after)),
        )
