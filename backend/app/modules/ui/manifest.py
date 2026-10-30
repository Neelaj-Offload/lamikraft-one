from __future__ import annotations

from typing import Any

from app.platform.manifest import ModuleManifest


def _router() -> Any:
    from app.modules.ui.router import router

    return router


def _on_load() -> None:
    from app.modules.ui.recents import read_recent_record_facts
    from app.platform.sources import register_reader

    register_reader("ui.recent_record", read_recent_record_facts)


MANIFEST = ModuleManifest(name="ui", models=("app.modules.ui.models",), routers=[_router], on_load=_on_load)
