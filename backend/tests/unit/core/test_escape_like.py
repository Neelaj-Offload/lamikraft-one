"""SEC-06: user text is matched literally (escaped ILIKE) and no module builds a regular expression in SQL."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.text import LIKE_ESCAPE, contains_pattern, escape_like

APP = Path(__file__).resolve().parents[3] / "app"


def _like_matches(pattern: str, text: str) -> bool:
    """A reference LIKE matcher honouring the escape character (what PostgreSQL does)."""
    out, i = "", 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == LIKE_ESCAPE and i + 1 < len(pattern):
            out += re.escape(pattern[i + 1])
            i += 2
            continue
        out += ".*" if ch == "%" else "." if ch == "_" else re.escape(ch)
        i += 1
    return re.fullmatch(out, text, flags=re.DOTALL) is not None


def test_metacharacters_match_literally() -> None:
    for term in ("100%", "a_b", "back\\slash", ".*", "[a-z]+", "((", "^$|", "LK-OT-0450"):
        assert _like_matches(contains_pattern(term), f"x{term}y")
    # wildcards in the input never act as wildcards
    assert not _like_matches(contains_pattern("100%"), "x1000y")
    assert not _like_matches(contains_pattern("a_b"), "xaZby")
    assert not _like_matches(contains_pattern(".*"), "anything")
    assert escape_like("50%_off\\") == r"50\%\_off\\"


@settings(max_examples=200, derandomize=True)
@given(st.text(min_size=1, max_size=30))
def test_any_input_matches_only_itself_literally(term: str) -> None:
    pattern = contains_pattern(term)
    assert _like_matches(pattern, f"..{term}..")
    unescaped = re.sub(r"\\.", "", pattern[1:-1])
    assert "%" not in unescaped and "_" not in unescaped


_REGEX_OPERATORS = {"~", "~*", "!~", "!~*", "similar to", "regexp_match", "regexp_matches", "regexp_replace"}


def test_no_module_builds_sql_regular_expressions() -> None:
    """Architecture rule: no ``.op('~')``-style operators, ``regexp_*`` calls or SIMILAR TO in application code."""
    problems: list[str] = []
    for path in sorted(APP.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                name = node.func.attr
                if name in {"regexp_match", "regexp_replace"}:
                    problems.append(f"{path}:{node.lineno} .{name}()")
                if name == "op" and node.args and isinstance(node.args[0], ast.Constant) and str(node.args[0].value).lower() in _REGEX_OPERATORS:
                    problems.append(f"{path}:{node.lineno} .op({node.args[0].value!r})")
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "func" and node.attr.lower().startswith("regexp"):
                problems.append(f"{path}:{node.lineno} func.{node.attr}")
    assert problems == []
