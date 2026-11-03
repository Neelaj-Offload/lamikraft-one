"""Assistant golden set (``golden.json``): request type, tool choice, clarification and latency per case.

``test_golden_demo`` runs in CI on the Demo provider and pins the exact tool sequence. ``test_golden_live`` runs the
same cases against Claude only when ``LK_AI_MODE=live`` and ``ANTHROPIC_API_KEY`` are set (manual; it spends real
tokens and is skipped everywhere else); live runs are checked on the request type, the tools that must (not) be
called, the card kind and the latency budget, not on the exact sequence."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from app.core.config import get_settings
from tests.integration.agents.conftest import Assistant, tool_calls
from tests.integration.catalogue.world import World

pytestmark = pytest.mark.db
CASES: list[dict[str, Any]] = json.loads((Path(__file__).parent / "golden.json").read_text(encoding="utf-8"))["cases"]
LIVE = os.environ.get("LK_AI_MODE") == "live" and bool(os.environ.get("ANTHROPIC_API_KEY"))


def _setup(case: dict[str, Any], world: World) -> None:
    if case.get("setup") == "second_nordhaus":
        from tests.integration.agents.test_scenario_c import _create_nordhaus_logistik

        _create_nordhaus_logistik(world)


def _check(case: dict[str, Any], detail: dict[str, Any], mode: str) -> dict[str, Any]:
    calls = tool_calls(detail)
    route = next((s for s in detail["steps"] if s["kind"] == "route"), None)
    kinds = [c["kind"] for c in detail["cards"]]
    report = {"id": case["id"], "request_type": route["output"]["request_type"] if route else None, "tools": calls,
              "cards": kinds, "elapsed_ms": detail["run"]["elapsed_ms"], "status": detail["run"]["status"]}
    assert report["request_type"] == case["request_type"], report
    for name in case.get("must_call", []):
        assert name in calls, report
    for name in case.get("must_not_call", []):
        assert name not in calls, report
    if mode == "demo":
        assert calls == case["demo_tools"], report
    if case.get("card"):
        assert case["card"] in kinds, report
    assert ("clarification" in kinds) is case["clarification"], report
    assert detail["run"]["elapsed_ms"] <= case["latency_ms"][mode], report
    return report


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_golden_demo(case: dict[str, Any], meera: Assistant, world: World) -> None:
    if get_settings().ai_mode != "demo":
        pytest.skip("the demo golden run needs LK_AI_MODE=demo")
    _setup(case, world)
    _check(case, meera.say(case["text"]), "demo")


@pytest.mark.skipif(not LIVE, reason="live evals need LK_AI_MODE=live and ANTHROPIC_API_KEY (manual run only)")
@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_golden_live(case: dict[str, Any], meera: Assistant, world: World) -> None:
    _setup(case, world)
    report = _check(case, meera.say(case["text"]), "live")
    print(json.dumps(report))  # noqa: T201 - the manual run's evidence
