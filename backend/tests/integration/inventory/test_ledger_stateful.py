"""Ledger property tests (hypothesis stateful, derandomized): random reserve, release, inbound, outbound, relocation,
approved loss and reversal steps keep balances == SUM(ledger), summaries == balances and active reservations, and no
stock-bearing balance below zero. A step that would oversell or go negative is refused and changes nothing; there is
no allow-negative switch."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from hypothesis import HealthCheck, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule, run_state_machine_as_test

from app.core.errors import AppError
from app.modules.inventory import integrity
from app.modules.inventory import service as inventory
from app.modules.inventory.enums import LocationType
from app.modules.inventory.models import Reservation
from app.seed.world import keys
from tests.integration.inventory.world import InvWorld

pytestmark = pytest.mark.db
PRODUCTS = ("OAK_TRAY", "MAPLE_TRIVET")
QTY = st.integers(min_value=1, max_value=400)


class LedgerMachine(RuleBasedStateMachine):
    world: InvWorld  # set by the test

    def __init__(self) -> None:
        super().__init__()
        w = self.world
        with w.system() as uow:
            self.stock = inventory.default_location(uow, w.warehouse_id).id
            self.bin = w.ref(keys.WAREHOUSE_REFS.BIN_A12)
            self.customer = inventory.company_location(uow, LocationType.CUSTOMER).id
            self.adjust = inventory.company_location(uow, LocationType.ADJUSTMENT).id
            self.opening = inventory.company_location(uow, LocationType.OPENING).id
        self.reservations: list[uuid.UUID] = []
        self.postings: list[uuid.UUID] = []

    def _uow(self):  # noqa: ANN202
        return self.world.uow(keys.USERS.RAVI)

    def _post(self, product: str, qty: int, src: uuid.UUID, dst: uuid.UUID, *, allow: bool = False, reservation: uuid.UUID | None = None) -> None:
        req = inventory.PostingRequest(source_type="relocation", source_id=uuid.uuid7(), purpose="relocate", allow_reserved_shortfall=allow,
                                       lines=(inventory.PostingLine(product_id=self.world.ref(product), quantity=Decimal(qty), uom_code="pcs",
                                                                    from_location_id=src, to_location_id=dst, reservation_id=reservation),))
        before = self._snapshot(product)
        try:
            with self._uow() as uow:
                receipt = inventory.post_movement(uow, req)
                self.postings.append(receipt.posting.id)
        except AppError as exc:
            assert exc.code in {"negative_stock", "reserved_stock_conflict", "reservation_exceeded", "reservation_not_active"}, exc.code
            assert self._snapshot(product) == before  # refused steps change nothing

    def _snapshot(self, product: str) -> tuple[Decimal, Decimal]:
        return self.world.summary(product)

    @rule(product=st.sampled_from(PRODUCTS), qty=QTY)
    def inbound(self, product: str, qty: int) -> None:
        self._post(product, qty, self.opening, self.stock)

    @rule(product=st.sampled_from(PRODUCTS), qty=QTY)
    def outbound_unreserved(self, product: str, qty: int) -> None:
        self._post(product, qty, self.stock, self.customer)

    @rule(product=st.sampled_from(PRODUCTS), qty=QTY, to_bin=st.booleans())
    def relocate(self, product: str, qty: int, to_bin: bool) -> None:
        self._post(product, qty, self.stock if to_bin else self.bin, self.bin if to_bin else self.stock)

    @rule(product=st.sampled_from(PRODUCTS), qty=QTY)
    def approved_loss(self, product: str, qty: int) -> None:
        self._post(product, qty, self.stock, self.adjust, allow=True)

    @rule(product=st.sampled_from(PRODUCTS), qty=QTY)
    def reserve(self, product: str, qty: int) -> None:
        on_hand, reserved = self._snapshot(product)
        with self._uow() as uow:
            r = inventory.reserve(uow, demand_type="so_line", demand_id=uuid.uuid7(), demand_parent_id=None, demand_label="prop",
                                  product_id=self.world.ref(product), warehouse_id=self.world.warehouse_id, quantity=Decimal(qty))
            granted = r.granted
            if r.reservation is not None:
                self.reservations.append(r.reservation.id)
        assert granted == min(Decimal(qty), max(on_hand - reserved, Decimal(0)))

    @rule(data=st.data())
    def consume_or_release(self, data: st.DataObject) -> None:
        if not self.reservations:
            return
        rid = data.draw(st.sampled_from(self.reservations))
        with self.world.system() as uow:
            res = uow.session.get(Reservation, rid)
            if res is None or res.status != "active":
                return
            left, product_id = inventory.remaining(res), res.product_id
        product = next(p for p in PRODUCTS if self.world.ref(p) == product_id)
        if data.draw(st.booleans()):
            with self._uow() as uow:
                inventory.release(uow, rid, reason_code="prop")
        else:
            self._post(product, int(min(left, Decimal(data.draw(QTY)))) or 1, self.stock, self.customer, reservation=rid)

    @rule(data=st.data())
    def reverse(self, data: st.DataObject) -> None:
        if not self.postings:
            return
        pid = data.draw(st.sampled_from(self.postings))
        try:
            with self._uow() as uow:
                inventory.reverse_posting(uow, pid, reason_code="prop")
        except AppError as exc:
            assert exc.code in {"negative_stock", "reserved_stock_conflict", "already_reversed", "reversal_of_reversal"}, exc.code

    @invariant()
    def ledger_consistent(self) -> None:
        with self.world.system() as uow:
            assert integrity.check(uow) == []


def test_ledger_machine(inv_world: InvWorld) -> None:
    LedgerMachine.world = inv_world
    run_state_machine_as_test(
        LedgerMachine,
        settings=settings(max_examples=12, stateful_step_count=15, derandomize=True, deadline=None,
                          suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture]),
    )
