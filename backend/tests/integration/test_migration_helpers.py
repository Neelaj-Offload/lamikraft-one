"""``migrations.helpers.immutable_columns`` on PostgreSQL: changing a named column is refused, other columns and
no-op writes of the same value pass. Runs as the schema owner inside a transaction that is rolled back."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, create_engine, text
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from migrations import helpers

pytestmark = pytest.mark.db


class _ConnectionOp:
    def __init__(self, conn: Connection) -> None:
        self.conn = conn

    def execute(self, sql: str) -> None:
        self.conn.execute(text(sql))


@pytest.fixture
def owner_conn(migrated_db: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[Connection]:
    engine = create_engine(get_settings().owner_database_url)
    with engine.connect() as conn:
        tx = conn.begin()
        monkeypatch.setattr(helpers, "op", _ConnectionOp(conn))
        try:
            yield conn
        finally:
            tx.rollback()
    engine.dispose()


def test_named_columns_are_immutable_and_the_rest_stays_editable(owner_conn: Connection) -> None:
    owner_conn.execute(text("CREATE TABLE zz_immutable_probe (id int PRIMARY KEY, doc_no text, note text)"))
    owner_conn.execute(text("INSERT INTO zz_immutable_probe VALUES (1, 'LK-1', 'a')"))
    helpers.immutable_columns("zz_immutable_probe", ["doc_no"])

    owner_conn.execute(text("UPDATE zz_immutable_probe SET note = 'b' WHERE id = 1"))
    owner_conn.execute(text("UPDATE zz_immutable_probe SET doc_no = 'LK-1' WHERE id = 1"))  # same value: allowed
    savepoint = owner_conn.begin_nested()
    with pytest.raises(IntegrityError, match="zz_immutable_probe.doc_no is immutable"):
        owner_conn.execute(text("UPDATE zz_immutable_probe SET doc_no = 'LK-2' WHERE id = 1"))
    savepoint.rollback()

    # a later migration can widen the list: the function and trigger are replaced, not duplicated
    helpers.immutable_columns("zz_immutable_probe", ["doc_no", "note"])
    triggers = owner_conn.scalar(
        text("SELECT count(*) FROM pg_trigger WHERE tgrelid = 'zz_immutable_probe'::regclass AND NOT tgisinternal")
    )
    assert triggers == 1
    savepoint = owner_conn.begin_nested()
    with pytest.raises(IntegrityError, match="zz_immutable_probe.note is immutable"):
        owner_conn.execute(text("UPDATE zz_immutable_probe SET note = 'c' WHERE id = 1"))
    savepoint.rollback()
    assert owner_conn.scalar(text("SELECT doc_no || ':' || note FROM zz_immutable_probe")) == "LK-1:b"
