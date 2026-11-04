"""The fixture world for the orders/inventory lane: the Slice-1 personas, every seed up to Slice 4 in registry order
(parties 20, catalogue 30, pricing/commercial 40, sales 50, challans 52, party changes 55, inventory 60) and helpers
for won quotes, orders, reservations, challans and the ledger invariants (``assert_ledger_consistent``)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import func, select

from app.modules.challans import service as challans
from app.modules.challans.schemas import ChallanCreate, ChallanLineCreate, ChallanTransition, LineType
from app.modules.challans.transitions import transition_challan_command
from app.modules.inventory import integrity
from app.modules.inventory.models import StockPosting, StockSummary
from app.modules.orders import service as orders
from app.modules.orders.schemas import OrderTransition, ReserveRequest
from app.modules.sales import service as sales
from app.modules.sales.schemas import QuoteCreate, QuoteLineCreate, QuoteTransition
from app.platform.authz.context import ActorContext
from app.platform.org.reference import ensure_default_uoms
from app.platform.uow import UnitOfWork
from app.seed.context import D0
from app.seed.world import keys
from tests.integration.catalogue.world import World, build_personas
from tests.support import drain

__all__ = ["D0", "InvWorld", "assert_ledger_consistent", "build_inv_world", "inv_world"]


class InvWorld(World):
    @contextmanager
    def uow(self, person: str, *, idempotency_key: str | None = None, step_up: bool = False, **changes: Any) -> Iterator[UnitOfWork]:
        actor: ActorContext = self.actor(person).with_(idempotency_key=idempotency_key, **changes)
        if step_up:
            actor = actor.with_(auth_strength="mfa", recent_auth_at=self.ctx.clock.now())
        with UnitOfWork(actor, clock=self.ctx.clock) as uow:
            yield uow

    def system(self) -> UnitOfWork:
        return UnitOfWork(ActorContext.system(self.company_id, reason="test"), clock=self.ctx.clock)

    @property
    def warehouse_id(self) -> uuid.UUID:
        return self.ref(keys.WAREHOUSE_REFS.MAIN)

    def won_quote(self, person: str = keys.USERS.MEERA, party: str = "NORDHAUS", *lines: tuple[str, str]) -> uuid.UUID:
        """A new quote with catalog lines (product key, quantity) taken through sent to won as ``person``."""
        lines = lines or (("OAK_TRAY", "240"),)
        with self.uow(person) as uow:
            q = sales.create_quote(uow, QuoteCreate(party_id=self.ref(party)))
            for product, qty in lines:
                sales.add_line(uow, q.id, QuoteLineCreate(expected_version=q.version, product_id=self.ref(product), quantity=Decimal(qty)))
            quote_id = q.id
        for action in ("mark_sent", "mark_won"):
            with self.uow(person, idempotency_key=str(uuid.uuid7())) as uow:
                version = sales.get_quote(uow, quote_id).version
                sales.transition_quote_command(uow, quote_id, QuoteTransition(action=action, expected_version=version))
        return quote_id

    def order(self, person: str, quote_id: uuid.UUID, *, confirm: bool = True) -> uuid.UUID:
        with self.uow(person) as uow:
            order, _ = orders.convert_quote(uow, quote_id)
            order_id = order.id
        if confirm:
            self.transition_order(person, order_id, "confirm")
        return order_id

    def transition_order(self, person: str, order_id: uuid.UUID, action: str, **extra: Any) -> Any:
        with self.uow(person) as uow:
            version = orders.get_order(uow, order_id).version
            return orders.detail(uow, orders.transition_order(uow, order_id, OrderTransition(action=action, expected_version=version, **extra)))

    def reserve(self, person: str, order_id: uuid.UUID, **extra: Any) -> Any:
        with self.uow(person) as uow:
            return orders.reserve_order(uow, order_id, ReserveRequest(**extra))

    def get_order(self, person: str, order_id: uuid.UUID) -> Any:
        with self.uow(person) as uow:
            return orders.get_order(uow, order_id)

    def challan(self, person: str, challan_id: uuid.UUID) -> Any:
        with self.uow(person) as uow:
            return challans.get_challan(uow, challan_id)

    def new_challan(self, person: str = keys.USERS.RAVI, *lines: tuple[str, str], **header: Any) -> Any:
        with self.uow(person) as uow:
            body = ChallanCreate(**header, lines=[
                ChallanLineCreate(line_type=LineType.CATALOG, product_id=self.ref(p), quantity=Decimal(q)) for p, q in lines])
            return challans.detail(uow, challans.create_challan(uow, body))

    def transition_challan(self, person: str, challan_id: uuid.UUID, action: str, *, key: str | None = None, **extra: Any) -> Any:
        with self.uow(person, idempotency_key=key or str(uuid.uuid7()), step_up=True) as uow:
            version = challans.get_challan(uow, challan_id).version
            detail, _ = transition_challan_command(uow, challan_id, ChallanTransition(action=action, expected_version=version, **extra))
            return detail

    def summary(self, product: str) -> tuple[Decimal, Decimal]:
        with self.system() as uow:
            s = uow.session.scalars(select(StockSummary).where(StockSummary.company_id == self.company_id,
                                                               StockSummary.product_id == self.ref(product),
                                                               StockSummary.warehouse_id == self.warehouse_id)).first()
            return (Decimal(s.available_on_hand), Decimal(s.reserved)) if s else (Decimal(0), Decimal(0))

    def postings(self, source_type: str | None = None, source_id: uuid.UUID | None = None) -> int:
        with self.system() as uow:
            stmt = select(func.count()).select_from(StockPosting).where(StockPosting.company_id == self.company_id)
            if source_type:
                stmt = stmt.where(StockPosting.source_type == source_type)
            if source_id:
                stmt = stmt.where(StockPosting.source_id == source_id)
            return int(uow.session.scalar(stmt) or 0)

    def at(self, when: datetime) -> None:
        self.ctx.at(when)

    def drain(self) -> int:
        return drain()


def assert_ledger_consistent(w: World) -> None:
    """balances == SUM(movements); summaries == balances and active reservations; no stock-bearing balance < 0."""
    with UnitOfWork(ActorContext.system(w.company_id, reason="test")) as uow:
        problems = integrity.check(uow)
    assert problems == [], problems


def build_inv_world(personas: World) -> InvWorld:
    from app.seed.world.catalogue import seed_catalogue
    from app.seed.world.challans import seed_challans
    from app.seed.world.commercial import seed_commercial
    from app.seed.world.inventory import seed_inventory
    from app.seed.world.parties import seed_parties, seed_party_changes
    from app.seed.world.pricing import seed_pricing
    from app.seed.world.sales import seed_sales

    with UnitOfWork(ActorContext.system(personas.company_id, reason="test-setup"), clock=personas.ctx.clock) as uow:
        ensure_default_uoms(uow)
    w = InvWorld(personas.company_id, personas.branch_id, personas.ctx, personas.actors)
    for seed in (seed_parties, seed_catalogue, seed_pricing, seed_commercial, seed_sales, seed_challans, seed_party_changes, seed_inventory):
        seed(w.ctx)
    w.at(D0)
    return w


@pytest.fixture
def inv_world(personas: World) -> InvWorld:
    return build_inv_world(personas)
