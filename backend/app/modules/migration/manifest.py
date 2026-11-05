"""Migration module manifest: models and the read-only API (``/api/v1/migration``, ``/api/v1/system/backups``).

Dry runs, the guarded apply and backups run from the CLI (``lk migration ...``, ``lk backup ...``): backup is CLI-only
(permissions.md §7.8) and a dry run reads an export directory on the server. Permissions and events come from the
frozen catalogues (``migration.*``, ``system.backup.*``; events.md §3.12).
"""

from __future__ import annotations

from typing import Any

from app.platform.manifest import ModuleManifest


def _router() -> Any:
    from app.modules.migration.router import router

    return router


def _backups_router() -> Any:
    from app.modules.migration.router import backups_router

    return backups_router


MANIFEST = ModuleManifest(
    name="migration",
    models=("app.modules.migration.models",),
    routers=[_router, _backups_router],
)
