"""Receipts and allocations (operations.md §9): partial allocations, over-allocation impossible on either side (also
under concurrency, committed database + barrier), append-only rows with at-most-once reversal, receipt reversal,
same party and currency only, and ageing per (party, currency) in company time."""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable, Iterator
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.core.errors import Conflict
from app.modules.finance import ageing, receipts
from app.modules.finance.models import Allocation
from app.modules.finance.schemas import AllocationReverse, ReceiptReverse
from app.platform.uow import UnitOfWork
from tests.integration.catalogue.world import build_personas
from tests.integration.finance.world import ANANYA, SAHIL, FinWorld, build_fin_world

pytestmark = pytest.mark.db


def test_allocations_bounded_and_ageing_per_currency(fin_world: FinWorld) -> None:
    w = fin_world
    w.configure_identity()
    inv = w.issued_invoice("100")  # EUR 2,400.0000, due D0+30
    r = w.receipt("1000.0000")
    w.allocate(r.id, inv.id, "600")
    w.allocate(r.id, inv.id, "300")
    detail = w.get(inv.id)
    assert detail.allocated.amount == Decimal("900.0000") and detail.outstanding.amount == Decimal("1500.0000")
    with pytest.raises(Conflict) as exc:  # the receipt has 100 left
        w.allocate(r.id, inv.id, "100.01")
    assert exc.value.code == "over_allocation"
    big = w.receipt("5000")
    with pytest.raises(Conflict) as exc:  # the invoice has 1,500 left
        w.allocate(big.id, inv.id, "1500.01")
    assert exc.value.code == "over_allocation"
    w.allocate(big.id, inv.id, "1500")
    assert w.get(inv.id).outstanding.amount == Decimal(0)
    # other currency / other party are refused
    gbp = w.receipt("10", currency="GBP")
    with pytest.raises(Conflict) as exc:
        w.allocate(gbp.id, inv.id, "1")
    assert exc.value.code == "currency_mismatch"
    other = w.receipt("10", party="MAISON")
    with pytest.raises(Conflict) as exc:
        w.allocate(other.id, inv.id, "1")
    assert exc.value.code == "party_mismatch"

    # ageing: a second invoice partly paid, 45 days later it sits in 1-30 (due D0+30 → 15 days past due)
    inv2 = w.issued_invoice("20")  # EUR 480
    w.allocate(r.id, inv2.id, "100")
    with w.uow(ANANYA) as uow:
        report = ageing.ageing(uow, w.ctx.clock.now().date() + timedelta(days=45))
    row = next(x for x in report.rows if x.party.display_name.startswith("Nordhaus") and x.currency == "EUR")
    assert row.buckets.days_1_30.amount == Decimal("380.0000") and row.buckets.total.amount == Decimal("380.0000")
    assert row.invoice_count == 1 and row.unallocated_receipts.amount == Decimal("3500.0000")
    assert [t.total.currency for t in report.totals] == ["EUR"]  # never summed across currencies
    with w.uow(ANANYA) as uow:
        today = ageing.ageing(uow)
    assert next(x for x in today.rows if x.currency == "EUR").buckets.current.amount == Decimal("380.0000")
    # management reads ageing, sales does not
    with w.uow(SAHIL) as uow:
        assert ageing.ageing(uow).rows
    from app.core.errors import Forbidden

    with w.uow("MEERA") as uow, pytest.raises(Forbidden):
        ageing.ageing(uow)


def test_reversal_once_append_only_and_receipt_void(fin_world: FinWorld) -> None:
    w = fin_world
    w.configure_identity()
    inv = w.issued_invoice("50")  # EUR 1,200
    r = w.receipt("1200")
    a = w.allocate(r.id, inv.id, "1200")
    with w.uow(ANANYA) as uow:
        rev = receipts.reverse_allocation(uow, a.id, AllocationReverse(reason_code="wrong_invoice"))
    assert rev.amount == Decimal("-1200.0000") and rev.reverses_allocation_id == a.id
    with w.uow(ANANYA) as uow, pytest.raises(Conflict):
        receipts.reverse_allocation(uow, a.id, AllocationReverse(reason_code="again"))
    with w.uow(ANANYA) as uow, pytest.raises(Conflict):
        receipts.reverse_allocation(uow, rev.id, AllocationReverse(reason_code="reverse_reversal"))
    assert w.get(inv.id).outstanding.amount == Decimal("1200.0000")
    with w.system() as uow:
        for sql in ("UPDATE finance_allocation SET amount = 1 WHERE id = :i", "DELETE FROM finance_allocation WHERE id = :i"):
            with pytest.raises(DBAPIError), uow.session.begin_nested():
                uow.session.execute(text(sql), {"i": a.id})
    # re-allocate, then void the receipt: its live allocation is reversed with it, the receipt is kept
    w.allocate(r.id, inv.id, "700")
    with w.uow(ANANYA, step_up=True) as uow:
        version = uow.repo(receipts.Receipt).get(r.id).version
        receipts.reverse_receipt(uow, r.id, ReceiptReverse(expected_version=version, reason_code="bounced"))
    with w.uow(ANANYA) as uow:
        got = receipts.get_receipt(uow, r.id)
    assert got.status.value == "reversed" and got.allocated.amount == 0 and got.capabilities["allocate"].allowed is False
    assert w.get(inv.id).outstanding.amount == Decimal("1200.0000")
    assert w.count(Allocation, Allocation.receipt_id == r.id) == 4  # 1200, −1200, 700, −700
    with pytest.raises(Conflict):
        w.allocate(r.id, inv.id, "1")


# ---- concurrency ------------------------------------------------------------------------------------------------
@pytest.fixture
def committed_world(committed_db: str, member_actors: None) -> Iterator[FinWorld]:
    yield build_fin_world(build_personas())


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

    threads = [threading.Thread(target=run, args=(i,), name=f"alloc-{i}") for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=180)
    return errors


@pytest.mark.committed
def test_concurrent_allocations_never_over_allocate(committed_world: FinWorld) -> None:
    """One receipt of EUR 1,000 and two invoices; 8 threads allocate 300 each (4 per invoice) through a barrier: the
    receipt never goes beyond 1,000 and every refusal is ``over_allocation``."""
    w = committed_world
    w.configure_identity()
    a = w.issued_invoice("100")
    b = w.issued_invoice("100")
    r = w.receipt("1000")

    def allocate(i: int) -> None:
        target = a.id if i % 2 == 0 else b.id
        with UnitOfWork(w.actor(ANANYA).with_(idempotency_key=str(uuid.uuid7())), clock=w.ctx.clock) as uow:
            receipts.allocate_receipt(uow, r.id, receipts.AllocationCreate(invoice_id=target, amount=Decimal(300)))

    errors = _race(8, allocate)
    assert len(errors) == 5 and all(isinstance(e, Conflict) and e.code == "over_allocation" for e in errors), errors
    with w.system() as uow:
        total = uow.session.scalar(select(func.sum(Allocation.amount)).where(Allocation.receipt_id == r.id))
    assert Decimal(total) == Decimal(900)
