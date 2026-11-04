"""The ledger is append-only in the database: UPDATE and DELETE on postings and movements are rejected by the trigger
(and revoked from the application role); the balance CHECK refuses a negative stock-bearing balance."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.integration.inventory.world import InvWorld

pytestmark = pytest.mark.db


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE inventory_stock_movement SET quantity = quantity + 1",
        "DELETE FROM inventory_stock_movement",
        "UPDATE inventory_stock_posting SET reason = 'edited'",
        "DELETE FROM inventory_stock_posting",
    ],
)
def test_update_delete_on_movements_and_postings_rejected_by_trigger(inv_world: InvWorld, statement: str) -> None:
    w = inv_world
    assert w.postings() >= 1  # the approved opening batch
    with w.system() as uow:
        uow.session.execute(text("SAVEPOINT immut"))
        with pytest.raises(DBAPIError) as exc:
            uow.session.execute(text(statement))
        uow.session.execute(text("ROLLBACK TO SAVEPOINT immut"))
    assert "append-only" in str(exc.value) or "permission denied" in str(exc.value)


def test_negative_stock_bearing_balance_is_refused_by_check(inv_world: InvWorld) -> None:
    w = inv_world
    with w.system() as uow:
        uow.session.execute(text("SAVEPOINT neg"))
        with pytest.raises(DBAPIError) as exc:
            uow.session.execute(text("UPDATE inventory_stock_balance SET quantity = -1 WHERE enforce_non_negative"))
        uow.session.execute(text("ROLLBACK TO SAVEPOINT neg"))
    assert "non_negative" in str(exc.value)
