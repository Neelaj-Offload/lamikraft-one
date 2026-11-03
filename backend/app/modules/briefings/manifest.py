"""Briefings module manifest: models, refresh/access subscriptions, refresh, precompute, phrasing and WhatsApp
summary jobs, the Today router, the ``briefing`` UI section, the summary's "Got it" button handler and the
fixture seed (order 80)."""

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
    try:  # "Got it" on the WhatsApp summary acknowledges the briefing (channels owns the button dispatch)
        from app.modules.briefings.summary import ACK_BUTTON_KIND, handle_ack_button
        from app.modules.channels.whatsapp.replies import register_button_handler
    except ImportError:  # pragma: no cover - the channels module is not installed
        return
    register_button_handler(ACK_BUTTON_KIND, handle_ack_button)


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
