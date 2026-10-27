"""Briefings module manifest: models, refresh/access subscriptions, refresh and precompute jobs, the
Today router, the ``briefing`` UI section and the fixture seed (order 80)."""

from __future__ import annotations

from typing import Any

from app.modules.briefings.events import SUBSCRIPTIONS
from app.modules.briefings.jobs import JOBS, SCHEDULES
from app.platform.manifest import ModuleManifest


def _router() -> Any:
    from app.modules.briefings.router import router

    return router


def _briefing_section(uow: Any) -> dict[str, Any]:
    from app.modules.briefings import service

    return service.briefing_section(uow)


def _on_load() -> None:
    from app.platform.bootstrap import UiSection, register_ui_section

    register_ui_section(UiSection(key="briefing", build=_briefing_section, in_poll=True))


def _seeds() -> list[Any]:
    from app.seed.world.briefings import SEEDS

    return list(SEEDS)


MANIFEST = ModuleManifest(
    name="briefings",
    models=("app.modules.briefings.models",),
    subscriptions=list(SUBSCRIPTIONS),
    jobs=list(JOBS),
    schedules=list(SCHEDULES),
    routers=[_router],
    seeds=_seeds(),
    on_load=_on_load,
)
