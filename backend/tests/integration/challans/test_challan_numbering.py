"""Challan numbering: ``DC-{yyyy}-{seq:04}`` from the atomic allocator, reset yearly (LM-85, FG-DC-01, BUG-13)."""

from __future__ import annotations

import re
import threading
import uuid
from collections.abc import Iterator
from datetime import date

import pytest

from app.modules.challans import service as challans
from app.modules.challans.schemas import ChallanCreate, ChallanFilters
from app.platform.uow import UnitOfWork
from app.seed.world import keys
from tests.integration.catalogue.world import build_personas
from tests.integration.challans.world import ChallanWorld, with_uoms

pytestmark = pytest.mark.db
THREADS = 40


@pytest.fixture
def committed_world(committed_db: str, member_actors: None) -> Iterator[ChallanWorld]:
    from app.seed.world.parties import seed_parties

    personas = build_personas()
    with_uoms(personas)
    seed_parties(personas.ctx)
    yield ChallanWorld(personas.company_id, personas.branch_id, personas.ctx, personas.actors)


@pytest.mark.committed
def test_concurrent_dc_numbers_unique_yearly_reset(committed_world: ChallanWorld) -> None:
    """40 threads, separate connections, one barrier: 40 distinct consecutive 2026 numbers and no gap; a challan dated
    in another year starts that year's counter at 0001 and never collides."""
    w = committed_world
    actor = w.actor(keys.USERS.RAVI)
    party_id = w.ref("NORDHAUS")
    barrier = threading.Barrier(THREADS)
    numbers: list[str] = []
    errors: list[BaseException] = []
    lock = threading.Lock()

    def worker() -> None:
        try:
            barrier.wait(timeout=30)
            with UnitOfWork(actor.with_(correlation_id=str(uuid.uuid7()))) as uow:
                number = challans.create_challan(uow, ChallanCreate(party_id=party_id, challan_date=date(2026, 10, 12))).challan_number
            with lock:
                numbers.append(number)
        except BaseException as exc:  # noqa: BLE001 - collected and asserted below
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker, name=f"challan-{i}") for i in range(THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)
    assert errors == [], errors[:3]
    assert len(numbers) == THREADS and len(set(numbers)) == THREADS
    sequence = sorted(int(n.rsplit("-", 1)[1]) for n in numbers)
    assert sequence == list(range(1, THREADS + 1)), "numbers must be consecutive with no gap"
    assert all(re.fullmatch(r"DC-2026-\d{4}", n) for n in numbers)
    with UnitOfWork(actor) as uow:
        # the yearly reset: a 2027-dated challan starts its own counter; 2026 continues after it
        assert challans.create_challan(uow, ChallanCreate(party_id=party_id, challan_date=date(2027, 1, 4))).challan_number == "DC-2027-0001"
        assert challans.create_challan(uow, ChallanCreate(party_id=party_id, challan_date=date(2026, 12, 30))).challan_number == f"DC-2026-{THREADS + 1:04d}"
        assert challans.list_challans(uow, ChallanFilters(), limit=1).total == THREADS + 2
        # a rolled-back creation consumes nothing visible: the next number continues the sequence
    with UnitOfWork(actor) as uow:
        nxt = challans.create_challan(uow, ChallanCreate(party_id=party_id, challan_date=date(2026, 12, 31))).challan_number
    assert nxt == f"DC-2026-{THREADS + 2:04d}"
