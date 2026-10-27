"""The fixture world for the sales lane's tests: the catalogue lane's personas and seeds (parties, catalogue,
pricing, commercial) plus the sales seed (enquiries, messages, quotes 0001..0008, proposals) run exactly as
``lk seed demo`` runs them (docs/architecture/fixtures.md §7)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from typing import Any

import pytest

from app.modules.sales import service as sales
from app.modules.sales.schemas import QuoteCreate, QuoteLineCreate, QuoteTransition
from app.platform.authz.context import ActorContext
from app.platform.uow import UnitOfWork
from app.seed.context import D0
from tests.integration.catalogue.world import World, build_personas, seed_world
from tests.support import drain

__all__ = ["D0", "SalesWorld", "World", "build_personas", "sales_world", "seed_sales_world", "world"]


class SalesWorld(World):
    """The catalogue world plus helpers that act as a persona at the frozen clock."""

    @contextmanager
    def uow(self, person: str, *, idempotency_key: str | None = None, **changes: Any) -> Iterator[UnitOfWork]:
        actor: ActorContext = self.actor(person).with_(idempotency_key=idempotency_key, **changes)
        with UnitOfWork(actor, clock=self.ctx.clock) as uow:
            yield uow

    def at(self, when: datetime) -> None:
        self.ctx.at(when)

    def quote_id(self, key: str) -> uuid.UUID:
        return self.ref(key)

    def quote(self, person: str, key: str) -> Any:
        with self.uow(person) as uow:
            return sales.get_quote(uow, self.ref(key))

    def new_draft(self, person: str, party: str, *lines: tuple[str, str], **header: Any) -> Any:
        """A draft with catalog lines (product key, quantity) as ``person``; returns the detail."""
        with self.uow(person) as uow:
            quote = sales.create_quote(uow, QuoteCreate(party_id=self.ref(party), **header))
            for product, qty in lines:
                sales.add_line(uow, quote.id, QuoteLineCreate(expected_version=quote.version, product_id=self.ref(product), quantity=Decimal(qty)))
            return sales.detail(uow, quote)

    def transition(self, person: str, quote_id: uuid.UUID, action: str, **extra: Any) -> Any:
        with self.uow(person, idempotency_key=str(uuid.uuid7())) as uow:
            version = sales.get_quote(uow, quote_id).version
            detail, _ = sales.transition_quote_command(uow, quote_id, QuoteTransition(action=action, expected_version=version, **extra))
            return detail

    def drain(self) -> int:
        return drain()


def seed_sales_world(world: World) -> SalesWorld:
    """Seeds in registry order: parties 20, catalogue 30, pricing/commercial 40, sales 50, party changes 55."""
    from app.seed.world.catalogue import seed_catalogue
    from app.seed.world.commercial import seed_commercial
    from app.seed.world.parties import seed_parties, seed_party_changes
    from app.seed.world.pricing import seed_pricing
    from app.seed.world.sales import seed_sales

    sw = SalesWorld(world.company_id, world.branch_id, world.ctx, world.actors)
    for seed in (seed_parties, seed_catalogue, seed_pricing, seed_commercial, seed_sales, seed_party_changes):
        seed(sw.ctx)
    sw.at(D0)
    return sw


@pytest.fixture
def world(personas: World) -> SalesWorld:
    """Personas + catalogue-lane seeds (no sales history)."""
    seed_world(personas)
    sw = SalesWorld(personas.company_id, personas.branch_id, personas.ctx, personas.actors)
    sw.at(D0)
    return sw


@pytest.fixture
def sales_world(personas: World) -> SalesWorld:
    """The full Slice-1 world at D0 (fixtures.md §7)."""
    return seed_sales_world(personas)
