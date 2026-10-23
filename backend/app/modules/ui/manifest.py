from __future__ import annotations

from typing import Any

from app.platform.manifest import ModuleManifest


def _router() -> Any:
    from app.modules.ui.router import router

    return router


MANIFEST = ModuleManifest(name="ui", routers=[_router])
