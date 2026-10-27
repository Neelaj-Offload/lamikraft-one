"""Access-catalogue sync when the API starts (platform.md §5: permissions are synced at startup).

Effective access is read only from ``role_permission`` rows, so a permission key or template grant added in code (or
by a newly installed module) must reach every company without a manual ``lk admin sync-access``. The identity router
carries :func:`lifespan`; FastAPI merges a router lifespan into the application's, so every API process runs
:func:`run_startup_sync` once before serving. The sync is idempotent, runs under the advisory locks of
:mod:`app.platform.identity.roles`, and bumps a company's ``authz_epoch`` only when its templates drifted.

A failure (database not reachable, migrations not applied yet) is logged and the API still starts: readiness reports
the database, and the next start or ``lk admin sync-access`` repairs the drift. In the test environment the hook is
skipped (tests and ``lk seed demo`` sync explicitly); tests call it with ``force=True``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import anyio

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger("lk.identity.startup")


def run_startup_sync(*, force: bool = False) -> dict[str, int] | None:
    """Sync the catalogue, legacy aliases and system templates of every company; None when skipped or failed."""
    if get_settings().is_test and not force:
        return None
    from app.platform.identity import roles

    try:
        result = roles.sync_access_all(origin="startup")
    except Exception as exc:  # never block the API from starting; logged for operators
        log.error("identity.access_sync_failed", error=type(exc).__name__)
        return None
    log.info("identity.access_synced", permissions=result["permissions"], companies=result["companies"])
    return result


@asynccontextmanager
async def lifespan(_app: Any) -> AsyncIterator[None]:
    await anyio.to_thread.run_sync(_startup_hook)
    yield


def _startup_hook() -> None:
    # resolved at call time so tests can replace ``run_startup_sync``
    import app.platform.identity.startup as module

    module.run_startup_sync()
