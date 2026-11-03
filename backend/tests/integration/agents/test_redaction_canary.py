"""Redaction canary (ai-routing.md section 6): a costing sentinel behind ``Restricted(..., model_exposure="deny")``
is planted in a tool output for a user who may read costs. It must never reach the provider payloads, the call
log, the trace, the assistant turn or the process logs."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Annotated, Any

import pytest
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.modules.agents.models import AiCallLog, RunStep, Turn
from app.modules.pricing.schemas import COST_GUARD
from app.platform.authz.context import ActorContext
from app.platform.tools import ToolDef
from app.platform.uow import UnitOfWork
from app.registry import get_registry
from app.seed.world import keys
from tests.integration.agents.conftest import API, Assistant, tool_calls
from tests.integration.agents.live_fake import (
    FakeClaude,
    is_router,
    live_mode,
    message,
    text,
    tool_results,
    tool_use,
)
from tests.integration.catalogue.world import World

pytestmark = pytest.mark.db
SENTINEL = "CANARY-COST-73519"


class CostingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str


class CostingOutput(BaseModel):
    product_key: str
    note: str
    unit_cost: Annotated[str | None, COST_GUARD] = None
    cost_components: Annotated[list[dict[str, Any]] | None, COST_GUARD] = None


def _costing(uow: UnitOfWork, data: BaseModel) -> CostingOutput:
    return CostingOutput(product_key="OAK_TRAY", note="costing on file", unit_cost=SENTINEL,
                         cost_components=[{"label": "board", "amount": SENTINEL}])


COSTING_TOOL = ToolDef(
    name="read_product_costing", group="Sales", description="Test-only: product costing (restricted, model-denied).",
    input_model=CostingInput, output_model=CostingOutput, handler=_costing, effect="read", permission="parties.party.read",
)


@pytest.fixture
def costing_tool(meera: Assistant) -> Iterator[None]:
    registry = get_registry()
    registry.tools.append(COSTING_TOOL)
    try:
        yield
    finally:
        registry.tools[:] = [t for t in registry.tools if t is not COSTING_TOOL]


def _router() -> dict[str, Any]:
    payload = {"request_type": "data_or_action", "domains": ["sales"], "think_harder": False,
               "slots": {k: None for k in ("customer", "product", "quantity", "quantity_source", "unit", "currency", "date")}}
    return message([text(json.dumps(payload))], model="claude-haiku-5-5")


def script(body: dict[str, Any]) -> dict[str, Any]:
    if is_router(body):
        return _router()
    if "tu_cost" not in tool_results(body):
        return message([tool_use("tu_cost", "read_product_costing", {"query": "oak tray"})], stop_reason="tool_use")
    return message([text("The costing is on file; open the product for details.")])


def test_costing_never_reaches_provider_payloads(meera: Assistant, world: World, costing_tool: None,
                                                 monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
                                                 caplog: pytest.LogCaptureFixture) -> None:
    priya = Assistant(meera.client, keys.USERS.PRIYA)
    assert world.actor(keys.USERS.PRIYA).can("pricing.cost.read"), "the canary is meaningful only for a cost reader"
    fake = FakeClaude(script)
    with live_mode(monkeypatch, fake):
        detail = priya.say("what does the oak tray cost us to make")
    assert tool_calls(detail) == ["read_product_costing"] and detail["run"]["status"] == "succeeded", detail
    assert len(fake.bodies) == 3
    result = json.loads(tool_results(fake.bodies[2])["tu_cost"])
    assert result["ok"] is True and result["output"]["note"] == "costing on file"
    assert SENTINEL not in fake.raw(), "provider payloads"

    trace = priya.client.get(f"{API}/traces/{detail['run']['correlation_id']}", headers=priya.headers)
    assert trace.status_code == 200 and SENTINEL not in trace.text, "trace"
    assert SENTINEL not in json.dumps(detail["cards"]) and SENTINEL not in (detail["text"] or ""), "assistant turn"
    with UnitOfWork(ActorContext.system(world.company_id, reason="test")) as uow:
        calls = list(uow.session.scalars(select(AiCallLog).where(AiCallLog.run_id == detail["run"]["id"])))
        turns = list(uow.session.scalars(select(Turn).where(Turn.run_id == detail["run"]["id"])))
        steps = list(uow.session.scalars(select(RunStep).where(RunStep.run_id == detail["run"]["id"])))
    stored = json.dumps([[c.model, c.error_type, c.request_id] for c in calls] + [[t.text, t.cards] for t in turns]
                        + [[s.input, s.output] for s in steps], default=str)
    assert SENTINEL not in stored, "call log, turns and run steps"
    captured = capsys.readouterr()
    assert SENTINEL not in captured.out + captured.err and SENTINEL not in caplog.text, "process logs"
