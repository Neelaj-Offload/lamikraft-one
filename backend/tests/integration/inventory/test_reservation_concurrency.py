"""SCN-I2: reserving never oversells under concurrency (committed database, separate connections, one barrier).

Reserving and posting wait for the same ``inventory_stock_summary`` row lock, so two requests can never both take the
same units; whatever is short is reported (``inventory.reservation.shortfall_detected``), never silently granted."""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable, Iterator
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.modules.inventory import service as inventory
from app.modules.inventory.models import Reservation
from app.modules.inventory.schemas import AdjustmentCreate, AdjustmentLineIn, Decision, Versioned
from app.platform.events.models import DomainEvent
from app.platform.uow import UnitOfWork
from app.seed.world import keys
from tests.integration.catalogue.world import build_personas
from tests.integration.inventory.world import InvWorld, assert_ledger_consistent, build_inv_world

pytestmark = pytest.mark.db
RAVI, SAHIL = keys.USERS.RAVI, keys.USERS.SAHIL


@pytest.fixture
def committed_world(committed_db: str, member_actors: None) -> Iterator[InvWorld]:
    yield build_inv_world(build_personas())


def _set_on_hand(w: InvWorld, product: str, target: Decimal) -> None:
    from app.modules.inventory import documents

    on_hand, _ = w.summary(product)
    with w.uow(RAVI) as uow:
        adj = documents.create_adjustment(uow, AdjustmentCreate(
            warehouse_id=w.warehouse_id, reason_code="correction", reason="test setup",
            lines=[AdjustmentLineIn(product_id=w.ref(product), quantity=on_hand - target, direction="out")]))
        documents.submit_adjustment(uow, adj.id, Versioned(expected_version=adj.version))
        adj_id = adj.id
    with w.uow(SAHIL) as uow:
        from app.modules.inventory.models import Adjustment

        version = uow.session.get(Adjustment, adj_id).version  # type: ignore[union-attr]
        documents.decide_adjustment(uow, adj_id, Decision(expected_version=version), approve=True)
    assert w.summary(product)[0] == target


def _race(n: int, fn: Callable[[int], None]) -> list[BaseException]:
    barrier = threading.Barrier(n)
    errors: list[BaseException] = []
    lock = threading.Lock()

    def run(i: int) -> None:
        try:
            barrier.wait(timeout=60)
            fn(i)
        except BaseException as exc:  # noqa: BLE001 - asserted by the caller
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=run, args=(i,), name=f"race-{i}") for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=180)
    return errors


@pytest.mark.committed
def test_no_oversell_under_concurrency(committed_world: InvWorld) -> None:
    """On-hand 10, 8 threads reserve 3 each through a barrier: sum reserved <= 10, the short demands get a shortfall
    event each, and the ledger stays consistent."""
    w = committed_world
    _set_on_hand(w, "MAPLE_TRIVET", Decimal(10))
    demands = [uuid.uuid7() for _ in range(8)]
    granted: dict[int, Decimal] = {}
    lock = threading.Lock()

    def reserve(i: int) -> None:
        with UnitOfWork(w.actor(RAVI).with_(correlation_id=str(uuid.uuid7()))) as uow:
            result = inventory.reserve(uow, demand_type="so_line", demand_id=demands[i], demand_parent_id=None, demand_label=f"race {i}",
                                       product_id=w.ref("MAPLE_TRIVET"), warehouse_id=w.warehouse_id, quantity=Decimal(3))
        with lock:
            granted[i] = result.granted

    assert _race(8, reserve) == []
    assert sum(granted.values()) == Decimal(10)  # 3 + 3 + 3 + 1: never more than on hand
    assert sorted(granted.values()) == [0, 0, 0, 0, 1, 3, 3, 3]
    with w.system() as uow:
        reserved = uow.session.scalar(select(func.sum(Reservation.quantity)).where(Reservation.company_id == w.company_id,
                                                                                  Reservation.product_id == w.ref("MAPLE_TRIVET")))
        shortfalls = uow.session.scalar(select(func.count()).select_from(DomainEvent).where(
            DomainEvent.company_id == w.company_id, DomainEvent.event_type == "inventory.reservation.shortfall_detected"))
    assert reserved == Decimal(10) and shortfalls == 5  # four got nothing, one got 1 of 3
    assert w.summary("MAPLE_TRIVET") == (Decimal(10), Decimal(10))
    assert_ledger_consistent(w)


@pytest.mark.committed
def test_reserve_and_unreserved_posting_race_never_oversells(committed_world: InvWorld) -> None:
    """A reservation and an unreserved outbound posting race for the last 10: exactly one wins, the other is refused
    (shortfall or reserved_stock_conflict / negative_stock), and nothing is double-counted."""
    w = committed_world
    _set_on_hand(w, "ASH_BOARD", Decimal(10))
    customer = None
    with w.system() as uow:
        from app.modules.inventory.enums import LocationType

        customer = inventory.company_location(uow, LocationType.CUSTOMER).id
        stock = inventory.default_location(uow, w.warehouse_id).id
    outcome: dict[str, object] = {}

    def run(i: int) -> None:
        with UnitOfWork(w.actor(RAVI).with_(correlation_id=str(uuid.uuid7()))) as uow:
            if i == 0:
                outcome["reserved"] = inventory.reserve(uow, demand_type="so_line", demand_id=uuid.uuid7(), demand_parent_id=None,
                                                        demand_label="race", product_id=w.ref("ASH_BOARD"), warehouse_id=w.warehouse_id,
                                                        quantity=Decimal(10)).granted
            else:
                inventory.post_movement(uow, inventory.PostingRequest(
                    source_type="relocation", source_id=uuid.uuid7(), purpose="relocate",
                    lines=(inventory.PostingLine(product_id=w.ref("ASH_BOARD"), quantity=Decimal(10), uom_code="pcs",
                                                 from_location_id=stock, to_location_id=customer),)))
                outcome["posted"] = True

    errors = _race(2, run)
    on_hand, reserved = w.summary("ASH_BOARD")
    if outcome.get("posted"):
        assert on_hand == 0 and reserved == 0 and outcome.get("reserved") == Decimal(0) and errors == []
    else:
        assert on_hand == 10 and reserved == 10 and len(errors) == 1
        assert getattr(errors[0], "code", None) in {"reserved_stock_conflict", "negative_stock"}
    assert_ledger_consistent(w)
