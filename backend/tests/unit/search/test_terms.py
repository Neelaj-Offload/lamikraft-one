"""Search terms are literal text: tokenised, folded and escaped for ILIKE; never a pattern or a regex."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import column
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import operators
from sqlalchemy.sql.elements import BinaryExpression
from sqlalchemy.sql.visitors import iterate

from app.platform.search.service import MAX_TERMS, match_all_terms, search_terms


def _sql(q: str) -> str:
    expr = match_all_terms([column("display_name")], q)
    return str(expr.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def test_terms_are_folded_and_capped() -> None:
    assert search_terms("  Oak   TRAY  ") == ["oak", "tray"]
    assert search_terms("Ünal Çelik") == ["unal", "celik"]
    assert len(search_terms(" ".join(f"t{i}" for i in range(20)))) == MAX_TERMS
    assert search_terms("   ") == []


def test_like_wildcards_and_backslash_are_escaped() -> None:
    sql = _sql("100% a_b c\\d")
    assert "'%%100\\%%%%'" in sql or "100\\%" in sql
    assert "a\\_b" in sql
    assert "c\\\\d" in sql
    assert sql.count("ESCAPE '\\'") >= 3


def test_regex_metacharacters_stay_plain_text() -> None:
    sql = _sql(".* [a-z]+ (?i) ^$")
    for fragment in (".*", "[a-z]+", "(?i)", "^$"):
        assert fragment in sql
    assert "~" not in sql and "SIMILAR" not in sql.upper() and "REGEXP" not in sql.upper()


def test_original_spelling_is_matched_alongside_the_folded_form() -> None:
    sql = _sql("Ünal")
    assert "ünal" in sql and "unal" in sql


def test_empty_query_matches_nothing() -> None:
    assert _sql("   ") == "false"


def _patterns(q: str) -> list[str]:
    """The ILIKE patterns of a compiled filter; asserts that ILIKE is the only operator used."""
    out: list[str] = []
    for element in iterate(match_all_terms([column("display_name")], q)):
        if isinstance(element, BinaryExpression):
            assert element.operator is operators.ilike_op
            assert element.modifiers.get("escape") == "\\"
            out.append(element.right.value)  # type: ignore[attr-defined]
    return out


def _unescaped_wildcards(pattern: str) -> list[str]:
    assert pattern.startswith("%") and pattern.endswith("%")
    inner, found, i = pattern[1:-1], [], 0
    while i < len(inner):
        ch = inner[i]
        if ch == "\\":
            assert inner[i + 1] in ("\\", "%", "_"), "escape must protect a special character"
            i += 2
            continue
        if ch in "%_":
            found.append(ch)
        i += 1
    return found


@settings(max_examples=300, derandomize=True, deadline=None)
@given(st.text(min_size=0, max_size=60))
def test_any_input_becomes_literal_ilike_patterns_only(q: str) -> None:
    patterns = _patterns(q)
    assert len(patterns) >= len(search_terms(q))
    for pattern in patterns:
        assert _unescaped_wildcards(pattern) == []
