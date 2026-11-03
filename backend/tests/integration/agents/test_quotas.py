"""Quotas (ai-routing.md section 7): checked before enqueue, per user and workflow per day. Over quota the run is
degraded: the deterministic grammar still answers, anything that needs a model ends with a clear quota ErrorCard
and no provider call; the per-company escalation cap keeps Opus off and the run stays on the orchestrator."""

from __future__ import annotations

from typing import Any

import pytest

from app.modules.agents.providers.base import ModelRequest, ModelResponse
from app.modules.agents.providers.demo import DemoProvider
from app.modules.agents.routing import AI_ROUTING_KEY
from app.platform.authz.context import ActorContext
from app.platform.org import service as org
from app.platform.uow import UnitOfWork
from tests.integration.agents.conftest import Assistant, cards_of, tool_calls
from tests.integration.catalogue.world import World

pytestmark = pytest.mark.db
SCENARIO_C_TEXT = "Prepare Nordhaus's usual oak tray quote"


def set_quotas(world: World, **quotas: int) -> None:
    with UnitOfWork(ActorContext.system(world.company_id, reason="test").with_(idempotency_key=None)) as uow:
        current = org.get_setting(uow, AI_ROUTING_KEY)
        value: dict[str, Any] = dict(current.value)
        value["quotas"] = {**value.get("quotas", {}), **quotas}
        org.update_setting(uow, AI_ROUTING_KEY, value=value, expected_version=current.version, change_reason="test")


def test_over_quota_degrades_to_deterministic_path(meera: Assistant, world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    set_quotas(world, orchestrator_runs_per_user=1)
    first = meera.say(SCENARIO_C_TEXT)
    assert first["run"]["status"] == "succeeded" and first["run"]["degraded_reason"] is None

    calls: list[str] = []
    original = DemoProvider.generate

    def spy(self: DemoProvider, request: ModelRequest) -> ModelResponse:
        calls.append(request.task_class)
        return original(self, request)

    monkeypatch.setattr(DemoProvider, "generate", spy)
    second = meera.say(SCENARIO_C_TEXT)
    assert second["run"]["degraded_reason"] == "quota_exceeded" and second["run"]["status"] == "failed"
    assert tool_calls(second) == [] and calls == [], "nothing reaches a model over quota"
    card = cards_of(second, "error")[0]
    assert card["code"] == "quota_exceeded" and "quota" in card["message"].lower()
    assert {link["path"] for link in card["direct_controls"]} >= {"/sales/quotes"}

    command = meera.say("go to quotes")
    assert command["run"]["status"] == "succeeded" and cards_of(command, "record_link")[0]["path"] == "/sales/quotes"


def test_escalation_cap_keeps_the_run_on_the_orchestrator(meera: Assistant, world: World) -> None:
    set_quotas(world, escalations_per_user=0)
    detail = meera.say("think harder: prepare Nordhaus's usual oak tray quote")
    route = detail["steps"][0]["output"]
    assert route["escalation"] == "think_harder:quota_exceeded" and route["task_class"] == "orchestration"
    assert detail["run"]["status"] == "succeeded"


def test_think_harder_escalates_within_quota(meera: Assistant) -> None:
    detail = meera.say("think harder: prepare Nordhaus's usual oak tray quote")
    route = detail["steps"][0]["output"]
    assert route["escalation"] == "think_harder" and route["task_class"] == "escalation"
    assert detail["run"]["step_budget"] == 10 and detail["run"]["time_budget_seconds"] == 90
    assert detail["run"]["input_token_budget"] == 200_000
