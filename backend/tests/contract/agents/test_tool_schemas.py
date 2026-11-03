"""Tool schemas as the Anthropic adapter sends them (ai-routing.md sections 5 and 5.1): every write/proposal tool is
strict-compatible after ``strict_schema`` (closed objects, every property required), the strict budget holds, no
tool input carries an identity field (at any nesting depth) and the model never gets an approve tool."""

from __future__ import annotations

from typing import Any

from app.modules.agents.orchestrator import STRICT_EFFECTS
from app.modules.agents.providers.anthropic import STRICT_TOOL_BUDGET, is_strict_compatible, render_tools, strict_schema
from app.modules.agents.providers.base import ToolSpec
from app.platform.tools import FORBIDDEN_INPUT_FIELDS
from app.registry import get_registry


def _tools() -> list[Any]:
    from tests.integration.agents import fake_sales

    return list(get_registry().tools) + list(fake_sales.FAKE_TOOLS)


def _property_names(node: Any) -> set[str]:
    names: set[str] = set()
    if isinstance(node, dict):
        for key, value in (node.get("properties") or {}).items():
            names.add(key)
            names |= _property_names(value)
        for key in ("items", "anyOf", "oneOf", "allOf", "$defs", "additionalProperties"):
            child = node.get(key)
            if isinstance(child, dict):
                names |= _property_names(child) if key != "$defs" else set().union(*(_property_names(v) for v in child.values()))
            elif isinstance(child, list):
                for item in child:
                    names |= _property_names(item)
    return names


def test_strict_compatible_and_no_identity_fields() -> None:
    tools = _tools()
    assert tools
    strict_tools = [t for t in tools if t.effect in STRICT_EFFECTS]
    assert strict_tools, "the draft tools are registered"
    assert len(strict_tools) <= STRICT_TOOL_BUDGET
    for tool in tools:
        schema = tool.json_schema()
        assert not FORBIDDEN_INPUT_FIELDS & _property_names(schema), tool.name
        assert "approve" not in tool.name, f"{tool.name}: the model has no approve tool"
        if tool.effect in STRICT_EFFECTS:
            assert is_strict_compatible(strict_schema(schema)), tool.name
    specs = [ToolSpec(name=t.name, description=t.description, input_schema=t.json_schema(), effect=t.effect) for t in tools]
    rendered = render_tools(specs, {t.name for t in strict_tools})
    assert [d["name"] for d in rendered] == sorted(d["name"] for d in rendered), "deterministic order for the cache prefix"
    assert {d["name"] for d in rendered if d.get("strict")} == {t.name for t in strict_tools}
    assert "cache_control" in rendered[-1]
