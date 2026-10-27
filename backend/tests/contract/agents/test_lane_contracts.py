"""Lane contracts: route authz and operationIds, events used are in the frozen catalogue with the catalogued payload
fields, tool inputs carry no identity fields and forbid extras, model flags match the database (RLS forced on
every ``agents_`` table, append-only triggers on run steps and the call log, CHECKs mirror the enums), the job kind
and policies are registered, and no business code calls ``datetime.now``."""

from __future__ import annotations

import ast
import re
from enum import StrEnum
from pathlib import Path

import pytest
from pydantic import BaseModel
from sqlalchemy import text

from app.core.config import BACKEND_DIR
from app.core.http.authz_decl import route_kind
from app.modules.agents import events, schemas
from app.modules.agents.events import JOB_KIND
from app.modules.agents.models import AiCallLog, RunStep
from app.modules.agents.providers.demo_intents import parse_command
from app.platform.authz.context import ActorContext
from app.platform.tools import FORBIDDEN_INPUT_FIELDS
from app.platform.uow import UnitOfWork
from app.registry import get_registry

AGENTS_DIR = BACKEND_DIR / "app" / "modules" / "agents"
LANE_TABLES = ("agents_conversation", "agents_turn", "agents_run", "agents_run_step", "agents_object_context", "agents_ai_call_log")
APPEND_ONLY = ("agents_run_step", "agents_ai_call_log")
EXPECTED_OPERATIONS = {
    ("post", "/agents/conversations"): "agents_create_conversation",
    ("get", "/agents/conversations/{conversation_id}"): "agents_get_conversation",
    ("post", "/agents/conversations/{conversation_id}/turns"): "agents_create_turn",
    ("get", "/agents/runs/{run_id}"): "agents_get_run",
    ("post", "/agents/runs/{run_id}/cancel"): "agents_cancel_run",
}
ENUM_COLUMNS: dict[tuple[str, str], type[StrEnum]] = {
    ("agents_conversation", "channel"): schemas.ConversationChannel,
    ("agents_conversation", "status"): schemas.ConversationStatus,
    ("agents_turn", "role"): schemas.TurnRole,
    ("agents_run", "status"): schemas.RunStatus,
    ("agents_run", "trigger"): schemas.RunTrigger,
    ("agents_run", "provider"): schemas.ProviderName,
    ("agents_run_step", "kind"): schemas.StepKind,
    ("agents_object_context", "origin"): schemas.ContextOrigin,
    ("agents_ai_call_log", "provider"): schemas.ProviderName,
    ("agents_ai_call_log", "outcome"): schemas.CallOutcome,
}
PAYLOADS: dict[str, type[BaseModel]] = {events.RUN_COMPLETED: events.RunCompletedPayload, events.RUN_FAILED: events.RunFailedPayload}


def test_routes_require_the_assistant_permission_and_carry_stable_operation_ids() -> None:
    from fastapi.routing import APIRoute

    from app.main import create_app
    from app.modules.agents.router import router as agents_router

    app = create_app()
    routes = {(m.lower(), r.path): r for r in agents_router.routes if isinstance(r, APIRoute) for m in r.methods}
    for key in EXPECTED_OPERATIONS:
        route = routes[key]
        assert route_kind(route) == "permission" and route.openapi_extra["x-authz"]["permissions"] == ["agents.assistant.use"]
    spec = app.openapi()
    found = {(m, p.removeprefix("/api/v1")): op["operationId"] for p, item in spec["paths"].items() for m, op in item.items() if "/agents/" in p}
    assert found == EXPECTED_OPERATIONS
    turns = spec["paths"]["/api/v1/agents/conversations/{conversation_id}/turns"]["post"]
    assert "202" in turns["responses"]
    schemas_ = spec["components"]["schemas"]
    assert {"QuoteDraftCard", "ClarificationCard", "ErrorCard", "RecordLinkCard", "ReceiptCard", "ScreenContext"} <= set(schemas_)
    assert schemas_["QuoteLineCard"]["properties"]["quantity"]["anyOf"][0]["type"] == "string"


def test_emitted_events_and_payloads_are_in_the_frozen_catalogue() -> None:
    registry = get_registry()
    for name, payload in PAYLOADS.items():
        event = registry.events[name]
        assert event.fields is not None and set(payload.model_fields) - {"origin"} == set(event.fields), name
    used = set(re.findall(r"\"(agents\.[a-z_]+\.[a-z_]+)\"", (AGENTS_DIR / "events.py").read_text(encoding="utf-8")))
    assert used <= set(registry.events) and used == set(PAYLOADS)


def test_tool_inputs_carry_no_identity_fields_and_forbid_extras() -> None:
    from tests.integration.agents import fake_sales

    tools = list(get_registry().tools) + list(fake_sales.FAKE_TOOLS)
    assert tools, "no tools registered"
    for tool in tools:
        assert not FORBIDDEN_INPUT_FIELDS & set(tool.input_model.model_fields), tool.name
        assert tool.input_model.model_config.get("extra") == "forbid", tool.name
        assert tool.effect != "execute"


def test_registry_has_the_job_kind_and_policies() -> None:
    registry = get_registry()
    job = registry.jobs[JOB_KIND]
    assert job.queue == "ai" and job.max_attempts == 1
    assert "agents.conversation" in registry.policies and registry.policies["agents.run"].parent is not None
    assert registry.policies["agents.conversation"].permission("read") == "agents.assistant.use"
    assert "agents.assistant.use" in registry.permissions


def test_model_flags_match_the_models() -> None:
    assert RunStep.__append_only__ and AiCallLog.__append_only__
    assert set(schemas.RunStatus) == {"queued", "running", "succeeded", "failed", "budget_exceeded", "cancelled"}


def _check_values(uow: UnitOfWork, table: str, name: str) -> set[str]:
    definition = uow.session.execute(
        text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = CAST(:t AS regclass) AND conname = :n"),
        {"t": table, "n": name},
    ).scalar_one()
    return set(re.findall(r"'([^']*)'", definition))


@pytest.mark.db
def test_lane_tables_have_forced_rls_append_only_triggers_and_enum_checks(db: None) -> None:
    with UnitOfWork(ActorContext.system(None)) as uow:
        policies = set(uow.session.execute(text("SELECT tablename FROM pg_policies WHERE policyname = 'tenant_isolation'")).scalars())
        forced = set(uow.session.execute(text("SELECT relname FROM pg_class WHERE relforcerowsecurity")).scalars())
        triggers = set(uow.session.execute(text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal")).scalars())
        for (table, column), enum in ENUM_COLUMNS.items():
            assert _check_values(uow, table, f"ck_{table}_{column}_values") == {e.value for e in enum}, (table, column)
    assert set(LANE_TABLES) <= policies and set(LANE_TABLES) <= forced
    assert {f"trg_{t}_append_only" for t in APPEND_ONLY} <= triggers


def test_no_wall_clock_in_business_code() -> None:
    offenders = []
    for path in AGENTS_DIR.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in {"now", "utcnow", "today"}:
                if isinstance(node.value, ast.Name) and node.value.id in {"datetime", "date"}:
                    offenders.append(f"{path.relative_to(BACKEND_DIR)}:{node.lineno}")
    assert offenders == []


def test_migration_is_the_lane_revision_with_rls_and_append_only() -> None:
    source = Path(BACKEND_DIR / "migrations" / "versions" / "0008_agents_slice1.py").read_text(encoding="utf-8")
    assert "revision: str = '0008'" in source and "down_revision: str | Sequence[str] | None = '0005'" in source
    assert "helpers.enable_tenant_rls(table)" in source and "helpers.append_only(table)" in source


def test_grammar_never_needs_a_provider() -> None:
    import app.modules.agents.providers.demo_intents as grammar

    source = Path(grammar.__file__).read_text(encoding="utf-8")
    assert "providers.base" not in source and "anthropic" not in source and parse_command("stop") is not None
