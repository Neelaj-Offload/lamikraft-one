"""Upload rate limiting (api-conventions §11: ``POST /api/v1/files`` is rate-limited).

The router calls ``check_upload_rate`` before a single byte of the body is read, so rejected and accepted
uploads both count. The limiter itself belongs to identity, which owns ``rate_limit_counter`` (Postgres-backed,
so every worker shares one count): identity installs it through ``set_upload_limiter`` in its manifest
``on_load`` (``app.platform.identity.ratelimit.upload_limiter``; 60 uploads per 10-minute window per user).
Until a limiter is installed, uploads are refused (fail closed) rather than left unlimited.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import TYPE_CHECKING

from app.core.errors import RateLimited

if TYPE_CHECKING:
    from app.platform.authz.context import ActorContext

#: (actor) -> seconds until the next upload is allowed, or None when it is allowed now (and counted)
UploadLimiter = Callable[["ActorContext"], float | None]

_limiter: UploadLimiter | None = None


def set_upload_limiter(limiter: UploadLimiter | None) -> UploadLimiter | None:
    """Install the upload limiter (identity's Postgres counter; tests install small limits) and return the
    previous one so a caller can restore it. None uninstalls it."""
    global _limiter
    previous, _limiter = _limiter, limiter
    return previous


def check_upload_rate(actor: ActorContext) -> None:
    """Raise 429 ``rate_limited`` (with ``retry_after_seconds``) when the actor uploads too often."""
    if actor.is_system:
        return
    if _limiter is None:
        raise RuntimeError("no upload limiter is installed (identity installs one in its manifest on_load)")
    retry_after = _limiter(actor)
    if retry_after is not None:
        raise RateLimited(
            "Too many uploads in a short time; try again shortly.",
            retry_after_seconds=max(1, math.ceil(retry_after)),
        )
