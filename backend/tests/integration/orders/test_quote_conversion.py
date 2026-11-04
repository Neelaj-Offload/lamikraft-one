"""SCN-I1: accepting a quote once — conversion is idempotent under concurrency and retries (UNIQUE(company_id,
source_quote_id) plus the quote row lock), requires a won quote with an accepted revision, and the order's snapshot
survives later catalogue and price changes."""

from __future__ import annotations

import threading
import uuid
from collections.abc import Iterator
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.core.errors import Conflict, Forbidden, NotFound
from app.modules.orders import service as orders
from app.modules.orders.models import SalesOrder
from app.platform.events.models import DomainEvent
from app.platform.uow import UnitOfWork
from app.seed.world import keys
from tests.integration.catalogue.world import build_personas
from tests.integration.inventory.world import InvWorld, build_inv_world

pytestmark = pytest.mark.db
MEERA, NEHA, RAVI = keys.USERS.MEERA, keys.USERS.NEHA, keys.USERS.RAVI


@pytest.fixture
def committed_world(committed_db: str, member_actors: None) -> Iterator[InvWorld]:
    yield build_inv_world(build_personas())


@pytest.mark.committed
def test_concurrent_and_retried_conversion_creates_one_order(committed_world: InvWorld) -> None:
    """Two threads through a barrier plus a retry give one order; the others get created=false with the same id; the
    total EUR 5,760.0000 matches the accepted snapshot."""
    w = committed_world
    quote_id = w.won_quote(MEERA, "NORDHAUS", ("OAK_TRAY", "240"))
    barrier = threading.Barrier(2)
    results: list[tuple[uuid.UUID, bool]] = []
    errors: list[BaseException] = []
    lock = threading.Lock()

    def convert() -> None:
        try:
            barrier.wait(timeout=30)
            with UnitOfWork(w.actor(MEERA).with_(correlation_id=str(uuid.uuid7()))) as uow:
                order, created = orders.convert_quote(uow, quote_id)
                out = (order.id, created)
            with lock:
                results.append(out)
        except BaseException as exc:  # noqa: BLE001
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=convert) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)
    assert errors == []
    with UnitOfWork(w.actor(MEERA)) as uow:  # the retry
        retry, created = orders.convert_quote(uow, quote_id)
        results.append((retry.id, created))
        detail = orders.detail(uow, retry)
    assert len({oid for oid, _ in results}) == 1
    assert sorted(c for _, c in results) == [False, False, True]
    assert detail.total is not None and detail.total.amount == Decimal("5760.0000") and detail.total.currency == "EUR"
    assert detail.subtotal.amount == Decimal("5760.0000") and [ln.qty_ordered for ln in detail.lines] == [Decimal(240)]
    with w.system() as uow:
        assert uow.session.scalar(select(func.count()).select_from(SalesOrder).where(SalesOrder.source_quote_id == quote_id)) == 1
        created_events = uow.session.scalar(select(func.count()).select_from(DomainEvent).where(
            DomainEvent.company_id == w.company_id, DomainEvent.event_type == "orders.sales_order.created"))
    assert created_events == 1


def test_conversion_requires_won_quote_and_linked_party_and_snapshot_survives_catalogue_change(inv_world: InvWorld) -> None:
    w = inv_world
    # not won: a draft is refused
    with w.uow(MEERA) as uow:
        from app.modules.sales import service as sales
        from app.modules.sales.schemas import QuoteCreate

        draft = sales.create_quote(uow, QuoteCreate(party_id=w.ref("NORDHAUS")))
        draft_id = draft.id
    with pytest.raises(Conflict) as exc, w.uow(MEERA) as uow:
        orders.convert_quote(uow, draft_id)
    assert exc.value.code == "quote_not_won"
    # outside the actor's quote scope: 404; without orders.sales_order.create (operations): 403
    quote_id = w.won_quote(MEERA, "NORDHAUS", ("OAK_TRAY", "240"))
    with pytest.raises(NotFound), w.uow(NEHA) as uow:
        orders.convert_quote(uow, quote_id)
    with pytest.raises(Forbidden), w.uow(RAVI) as uow:
        orders.convert_quote(uow, quote_id)
    with w.uow(MEERA) as uow:
        order, created = orders.convert_quote(uow, quote_id)
        order_id = order.id
    assert created
    # catalogue and price changes after conversion never touch the order
    with w.uow(keys.USERS.PRIYA) as uow:
        from app.modules.catalogue import service as catalogue
        from app.modules.catalogue.models import Product
        from app.modules.catalogue.schemas import ProductUpdate

        p = uow.session.get(Product, w.ref("OAK_TRAY"))
        assert p is not None
        catalogue.update_product(uow, p.id, ProductUpdate(expected_version=p.version, product_name="Oak tray renamed"))
    d = w.get_order(MEERA, order_id)
    assert d.lines[0].description != "Oak tray renamed" and d.lines[0].unit_price is not None
    assert d.lines[0].unit_price.amount == Decimal("24.0000") and d.party.display_name == "Nordhaus Interiors GmbH"
    assert d.quote.id == quote_id and d.status == "draft" and d.snapshot_hash
    assert [h.action for h in d.history] == ["create"]
