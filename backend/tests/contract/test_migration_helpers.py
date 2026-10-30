"""``migrations.helpers.immutable_columns``: the SQL it emits (no database; the behaviour on PostgreSQL is pinned
by ``tests/integration/test_migration_helpers.py``)."""

from __future__ import annotations

import pytest

from migrations import helpers


class _Recorder:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(self, sql: str) -> None:
        self.statements.append(" ".join(sql.split()))


@pytest.fixture
def recorded(monkeypatch: pytest.MonkeyPatch) -> _Recorder:
    recorder = _Recorder()
    monkeypatch.setattr(helpers, "op", recorder)
    return recorder


def test_one_function_and_one_column_scoped_trigger_per_table(recorded: _Recorder) -> None:
    helpers.immutable_columns("sales_quote", ["quote_number", "company_id"])
    function, drop, trigger = recorded.statements
    assert function.startswith("CREATE OR REPLACE FUNCTION lk_sales_quote_immutable() RETURNS trigger")
    for column in ("quote_number", "company_id"):
        assert f'IF NEW."{column}" IS DISTINCT FROM OLD."{column}" THEN' in function
        assert f"RAISE EXCEPTION 'sales_quote.{column} is immutable'" in function
    assert function.count("ERRCODE = 'integrity_constraint_violation'") == 2
    assert drop == 'DROP TRIGGER IF EXISTS trg_sales_quote_immutable ON "sales_quote"'
    assert trigger == (
        'CREATE TRIGGER trg_sales_quote_immutable BEFORE UPDATE OF "quote_number", "company_id" ON "sales_quote" '
        "FOR EACH ROW EXECUTE FUNCTION lk_sales_quote_immutable()"
    )


@pytest.mark.parametrize(
    ("table", "columns"),
    [
        ("sales_quote", []),
        ("sales_quote", ["number", "number"]),
        ('sales_quote"; DROP TABLE x; --', ["number"]),
        ("sales_quote", ["Number"]),
        ("sales_quote", ["number; --"]),
    ],
)
def test_rejects_empty_duplicate_or_unsafe_identifiers(recorded: _Recorder, table: str, columns: list[str]) -> None:
    with pytest.raises(ValueError):
        helpers.immutable_columns(table, columns)
    assert recorded.statements == []
