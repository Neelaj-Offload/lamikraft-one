"""The fixture world for the challans lane's tests: the catalogue lane's personas and seeds (parties, catalogue,
pricing, commercial), the company UOM master, and the challan seed (DC-2026-0001 .. 0003) run exactly as
``lk seed demo --slice 2`` runs it (docs/architecture/fixtures.md §8)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from typing import Any

import pytest

from app.modules.challans import service as challans
from app.modules.challans.schemas import ChallanCreate, ChallanLineCreate, ChallanTransition, LineType
from app.modules.challans.transitions import transition_challan_command
from app.platform.authz.context import ActorContext
from app.platform.org.reference import ensure_default_uoms
from app.platform.uow import UnitOfWork
from app.seed.context import D0
from app.seed.world import keys
from tests.integration.catalogue.world import World, build_personas, seed_world
from tests.support import drain

__all__ = ["D0", "ChallanWorld", "World", "build_personas", "challan_world", "seed_challan_world", "world"]

RAVI = keys.USERS.RAVI


class ChallanWorld(World):
    """The catalogue world plus helpers that act as a persona at the frozen clock."""

    @contextmanager
    def uow(self, person: str, *, idempotency_key: str | None = None, **changes: Any) -> Iterator[UnitOfWork]:
        actor: ActorContext = self.actor(person).with_(idempotency_key=idempotency_key, **changes)
        with UnitOfWork(actor, clock=self.ctx.clock) as uow:
            yield uow

    def at(self, when: datetime) -> None:
        self.ctx.at(when)

    def challan(self, person: str, key: str) -> Any:
        with self.uow(person) as uow:
            return challans.get_challan(uow, self.ref(key))

    def new_draft(self, person: str = RAVI, *lines: tuple[str, str], **header: Any) -> Any:
        """A draft with catalog lines (product fixture key, quantity) as ``person``; returns the detail."""
        with self.uow(person) as uow:
            body = ChallanCreate(
                **header,
                lines=[
                    ChallanLineCreate(line_type=LineType.CATALOG, product_id=self.ref(product), quantity=Decimal(qty))
                    for product, qty in lines
                ],
            )
            return challans.detail(uow, challans.create_challan(uow, body))

    def transition(self, person: str, challan_id: uuid.UUID, action: str, **extra: Any) -> Any:
        with self.uow(person, idempotency_key=str(uuid.uuid7())) as uow:
            version = challans.get_challan(uow, challan_id).version
            detail, _ = transition_challan_command(
                uow, challan_id, ChallanTransition(action=action, expected_version=version, **extra)
            )
            return detail

    def drain(self) -> int:
        return drain()


def with_uoms(world: World) -> None:
    with UnitOfWork(ActorContext.system(world.company_id, reason="test-setup"), clock=world.ctx.clock) as uow:
        ensure_default_uoms(uow)


def seed_challan_world(world: World) -> ChallanWorld:
    """Seeds in registry order: parties 20, catalogue 30, pricing/commercial 40, challans 52, party changes 55."""
    from app.seed.world.catalogue import seed_catalogue
    from app.seed.world.challans import seed_challans
    from app.seed.world.commercial import seed_commercial
    from app.seed.world.parties import seed_parties, seed_party_changes
    from app.seed.world.pricing import seed_pricing

    with_uoms(world)
    cw = ChallanWorld(world.company_id, world.branch_id, world.ctx, world.actors)
    for seed in (seed_parties, seed_catalogue, seed_pricing, seed_commercial, seed_challans, seed_party_changes):
        seed(cw.ctx)
    cw.at(D0)
    return cw


@pytest.fixture
def world(personas: World) -> ChallanWorld:
    """Personas + catalogue-lane seeds + the UOM master (no challans)."""
    with_uoms(personas)
    seed_world(personas)
    cw = ChallanWorld(personas.company_id, personas.branch_id, personas.ctx, personas.actors)
    cw.at(D0)
    return cw


@pytest.fixture
def challan_world(personas: World) -> ChallanWorld:
    """The Slice-2 challan world at D0 (fixtures.md §8)."""
    return seed_challan_world(personas)
