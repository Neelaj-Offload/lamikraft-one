"""Quote numbering: ``{brand}-QT-{yyyy}-{seq:04}`` from the atomic allocator (LM-45, BUG-13, FG-QST-01)."""

from __future__ import annotations

import re
import threading
import uuid
from collections.abc import Iterator

import pytest

from app.modules.sales import service as sales
from app.modules.sales.schemas import QuoteCreate, QuoteFilters
from app.platform.uow import UnitOfWork
from app.seed.world import keys
from tests.integration.catalogue.world import build_personas
from tests.integration.sales.world import SalesWorld

pytestmark = pytest.mark.db
THREADS = 40


@pytest.fixture
def committed_world(committed_db: str, member_actors: None) -> Iterator[SalesWorld]:
    from app.seed.world.commercial import seed_commercial
    from app.seed.world.parties import seed_parties

    personas = build_personas()
    seed_parties(personas.ctx)
    seed_commercial(personas.ctx)
    yield SalesWorld(personas.company_id, personas.branch_id, personas.ctx, personas.actors)


@pytest.mark.committed
def test_concurrent_quote_numbers_unique_gapless(committed_world: SalesWorld) -> None:
    """40 threads, separate connections, one barrier: 40 distinct consecutive numbers and no gap."""
    w = committed_world
    actor = w.actor(keys.USERS.MEERA)
    party_id = w.ref("NORDHAUS")
    barrier = threading.Barrier(THREADS)
    numbers: list[str] = []
    errors: list[BaseException] = []
    lock = threading.Lock()

    def worker() -> None:
        try:
            barrier.wait(timeout=30)
            with UnitOfWork(actor.with_(correlation_id=str(uuid.uuid7()))) as uow:
                quote = sales.create_quote(uow, QuoteCreate(party_id=party_id))
                number = quote.quote_number
            with lock:
                numbers.append(number)
        except BaseException as exc:  # noqa: BLE001 - collected and asserted below
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker, name=f"quote-{i}") for i in range(THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)
    assert errors == [], errors[:3]
    assert len(numbers) == THREADS and len(set(numbers)) == THREADS
    sequence = sorted(int(n.rsplit("-", 1)[1]) for n in numbers)
    assert sequence == list(range(1, THREADS + 1)), "numbers must be consecutive with no gap"
    assert all(re.fullmatch(r"LK-QT-2026-\d{4}", n) for n in numbers)
    with UnitOfWork(w.actor(keys.USERS.SAHIL)) as uow:
        assert sales.list_quotes(uow, QuoteFilters(), limit=1).total == THREADS


def test_brand_token_and_shared_counter(world: SalesWorld) -> None:
    """Brands LK and CR share one never-resetting counter; the brand token only changes the prefix."""
    with world.uow(keys.USERS.MEERA) as uow:
        lk = sales.create_quote(uow, QuoteCreate(party_id=world.ref("NORDHAUS"), brand="LK")).quote_number
        cr = sales.create_quote(uow, QuoteCreate(party_id=world.ref("NORDHAUS"), brand="CR")).quote_number
        lk2 = sales.create_quote(uow, QuoteCreate(party_id=world.ref("NORDHAUS"))).quote_number
    assert lk == "LK-QT-2026-0001" and cr == "CR-QT-2026-0002" and lk2 == "LK-QT-2026-0003"
