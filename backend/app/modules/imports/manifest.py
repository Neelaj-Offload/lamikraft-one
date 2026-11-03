"""Imports module manifest: the import workbench (models, job policy, API, background jobs) and the catalogue price
bridge (the catalogue may not import pricing; this module depends on both)."""

from __future__ import annotations

from typing import Any

from app.modules.imports.jobs import JOBS
from app.modules.imports.policies import POLICIES
from app.platform.manifest import ModuleManifest


def _router() -> Any:
    from app.modules.imports.router import router

    return router


def _on_load() -> None:
    from app.modules.catalogue.service import register_price_presence
    from app.modules.imports.bridges import price_presence
    from app.modules.imports.service import file_access
    from app.platform.files.access import register_file_access

    register_price_presence(price_presence)
    register_file_access("imports.job", file_access)


MANIFEST = ModuleManifest(
    name="imports",
    models=("app.modules.imports.models",),
    policies=list(POLICIES),
    routers=[_router],
    jobs=list(JOBS),
    on_load=_on_load,
)
