"""Quality module manifest: the inspection model and policy, the ``QC`` sequence, the API, the source reader and the
``ops.qc`` completion check (permissions and events come from the frozen catalogues)."""

from __future__ import annotations

from typing import Any

from app.modules.quality.events import INSPECTION_SEQUENCE
from app.modules.quality.policies import POLICIES
from app.platform.manifest import ModuleManifest


def _router() -> Any:
    from app.modules.quality.router import router

    return router


def _on_load() -> None:
    from app.modules.quality.readers import READERS
    from app.modules.quality.rules import register_checks
    from app.platform.sources import register_reader

    for source_type, reader in READERS.items():
        register_reader(source_type, reader)
    register_checks()


MANIFEST = ModuleManifest(
    name="quality",
    models=("app.modules.quality.models",),
    policies=list(POLICIES),
    sequences=[INSPECTION_SEQUENCE],
    routers=[_router],
    on_load=_on_load,
)
