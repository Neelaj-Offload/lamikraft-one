"""Tasks module manifest: models, the ``tasks.task`` policy, rule subscriptions, jobs, the Inbox router,
the ``inbox_counts`` UI section and the fixture seed (order 80)."""

from __future__ import annotations

from typing import Any

from app.modules.tasks.events import SUBSCRIPTIONS
from app.modules.tasks.jobs import JOBS, SCHEDULES
from app.modules.tasks.policies import POLICIES
from app.platform.manifest import ModuleManifest


def _router() -> Any:
    from app.modules.tasks.router import router

    return router


def _inbox_counts_section(uow: Any) -> dict[str, Any]:
    from app.modules.tasks import service

    if uow.actor.user_id is None or not uow.actor.can("tasks.task.read"):
        return {}
    return service.inbox_counts(uow).model_dump(mode="json")


def _on_load() -> None:
    from app.platform.bootstrap import UiSection, register_ui_section

    register_ui_section(UiSection(key="inbox_counts", build=_inbox_counts_section, in_poll=True))


def _seeds() -> list[Any]:
    from app.seed.world.tasks import SEEDS

    return list(SEEDS)


MANIFEST = ModuleManifest(
    name="tasks",
    models=("app.modules.tasks.models",),
    policies=list(POLICIES),
    subscriptions=list(SUBSCRIPTIONS),
    jobs=list(JOBS),
    schedules=list(SCHEDULES),
    routers=[_router],
    seeds=_seeds(),
    on_load=_on_load,
)
