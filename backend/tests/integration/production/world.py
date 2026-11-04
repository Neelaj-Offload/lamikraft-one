"""The fixture world for the production lane: the inventory world (every seed to Slice 4 in registry order), the
production persona Deepa (template ``production``, company scope; fixtures key ``DEEPA``), the production seed
(LK-WP-0001, work centres, BOM/routing v1 approved by Sahil, WO-2026-0001 released and blocked by the LK-WB-1800
shortage) and the cutting seed (CUT-2026-0001), plus helpers for work orders, supply and the ledger."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from types import MappingProxyType
from typing import Any

import pytest
from sqlalchemy import func, select

from app.modules.inventory import service as inventory
from app.modules.inventory.enums import LocationType
from app.modules.inventory.models import Lot, StockPosting
from app.modules.production import service
from app.modules.production.schemas import WorkOrderCreate, WorkOrderTransition
from app.platform.authz.catalogue import template_grants
from app.platform.authz.context import ActorContext
from app.platform.uow import UnitOfWork
from app.seed.context import D0
from app.seed.world import keys
from tests.integration.catalogue import world as catalogue_world
from tests.integration.catalogue.world import World
from tests.integration.inventory.world import InvWorld, assert_ledger_consistent, build_inv_world
from tests.support import create_user

__all__ = ["D0", "DEEPA", "ProdWorld", "assert_ledger_consistent", "prod_world"]

DEEPA = "DEEPA"


def add_persona(w: World, key: str) -> None:
    """A later-slice persona the Slice-1 builder does not create (same construction as ``build_personas``)."""
    p = keys.PEOPLE[key]
    user_id = create_user(w.company_id, p.name)
    actor = ActorContext(actor_type="user", company_id=w.company_id, user_id=user_id, display_name=p.name,
                         branch_ids=frozenset({w.branch_id}), team_peer_user_ids=frozenset(),
                         permissions=MappingProxyType(dict(template_grants()[p.role_template])), channel="test")
    w.actors[key] = actor
    w.ctx.refs[key] = user_id
    catalogue_world._PERSONAS[(w.company_id, user_id)] = actor


class ProdWorld(InvWorld):
    @property
    def wo_id(self) -> uuid.UUID:
        return self.ref(keys.WORK_ORDER_REFS.PANEL_SETS)

    @property
    def panel_set(self) -> uuid.UUID:
        return self.ref("WALNUT_PANEL_SET")

    @property
    def walnut(self) -> uuid.UUID:
        return self.ref("WALNUT_BOARD")

    def wo(self, wo_id: uuid.UUID, person: str = DEEPA) -> Any:
        with self.uow(person) as uow:
            return service.work_order(uow, wo_id)

    def new_wo(self, qty: str = "2", person: str = DEEPA, **extra: Any) -> Any:
        with self.uow(person) as uow:
            return service.create_work_order(uow, WorkOrderCreate(product_id=self.panel_set, quantity=Decimal(qty),
                                                                  warehouse_id=self.warehouse_id, **extra))

    def act(self, wo_id: uuid.UUID, action: str, person: str = DEEPA, **extra: Any) -> Any:
        with self.uow(person, idempotency_key=str(uuid.uuid7())) as uow:
            version = service.work_order(uow, wo_id).version
            return service.transition_work_order(uow, wo_id, WorkOrderTransition(action=action, expected_version=version,
                                                                                  **extra))

    def cancel_seed_wo(self) -> None:
        """Free the 40 walnut sheets reserved by WO-2026-0001."""
        self.act(self.wo_id, "cancel", reason_code="replanned", reason="test frees the walnut boards")

    def receive(self, product: str, qty: str, *, lot_code: str | None = None, location: str | None = None) -> uuid.UUID:
        """Stand-in for a goods receipt (procurement lane): supplier -> stock through the inventory posting service."""
        with self.system() as uow:
            lot_id = None
            if lot_code:
                from app.modules.inventory.documents import ensure_lot

                lot_id = ensure_lot(uow, self.ref(product), lot_code).id
            src = inventory.company_location(uow, LocationType.SUPPLIER)
            dest = inventory.get_location(uow, self.ref(location)) if location else inventory.default_location(uow, self.warehouse_id)
            p = uow.session.get(__import__("app.modules.catalogue.models", fromlist=["Product"]).Product, self.ref(product))
            receipt = inventory.post_movement(uow, inventory.PostingRequest(
                source_type="goods_receipt", source_id=uuid.uuid7(), purpose="receive",
                lines=(inventory.PostingLine(product_id=p.id, quantity=Decimal(qty), uom_code=p.stock_uom_code,
                                             from_location_id=src.id, to_location_id=dest.id, lot_id=lot_id),)))
            return receipt.posting.id

    def walnut_lot(self) -> uuid.UUID:
        with self.system() as uow:
            return uow.session.scalar(select(Lot.id).where(Lot.company_id == self.company_id, Lot.lot_code == keys.LOTS.WALNUT))

    def count(self, model: type, *conds: Any) -> int:
        with self.system() as uow:
            return int(uow.session.scalar(select(func.count()).select_from(model).where(model.company_id == self.company_id, *conds)) or 0)

    def wo_postings(self) -> int:
        return self.count(StockPosting, StockPosting.source_type == "work_order")

    @contextmanager
    def as_(self, person: str, **changes: Any) -> Iterator[UnitOfWork]:
        with self.uow(person, idempotency_key=str(uuid.uuid7()), **changes) as uow:
            yield uow

    def d(self, offset: int) -> date:
        from datetime import timedelta

        return (D0 + timedelta(days=offset)).date()


def build_prod_world(personas: World) -> ProdWorld:
    from app.seed.world.cutting import seed_cutting
    from app.seed.world.production import seed_production

    base = build_inv_world(personas)
    w = ProdWorld(base.company_id, base.branch_id, base.ctx, base.actors)
    add_persona(w, DEEPA)
    seed_production(w.ctx)
    seed_cutting(w.ctx)
    w.at(D0)
    return w


@pytest.fixture
def prod_world(personas: World) -> ProdWorld:
    return build_prod_world(personas)
