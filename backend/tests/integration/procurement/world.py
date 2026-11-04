"""The fixture world for the procurement / quality / logistics lane: the inventory world (every seed up to inventory 60)
plus procurement (62) and logistics (64), and a test-local purchasing persona **Tara** (procurement template, HO).
Helpers drive requisitions, purchase orders, receipts, inspections, bills, packing lists and shipments through the
services as the named persona."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from types import MappingProxyType
from typing import Any

import pytest
from sqlalchemy import select

from app.modules.logistics import packing_lists, shipments
from app.modules.logistics.schemas import PackingListCreate, ShipmentCreate, ShipmentTransition
from app.modules.procurement import matching, purchase_orders, receiving, requisitions
from app.modules.procurement.models import PurchaseOrder, PurchaseOrderLine
from app.modules.procurement.schemas import (
    BillCreate,
    BillLineIn,
    GrnCreate,
    GrnLineIn,
    PoCreate,
    PoLineIn,
    PoTransition,
)
from app.modules.quality import service as quality
from app.modules.quality.models import Inspection
from app.modules.quality.schemas import ChecklistItem, InspectionDecision
from app.modules.tasks.models import Issue, Task
from app.platform.authz.catalogue import template_grants
from app.platform.authz.context import ActorContext
from app.seed.world import keys
from tests.integration.catalogue import world as catalogue_world
from tests.integration.catalogue.world import World
from tests.integration.inventory.world import InvWorld, build_inv_world
from tests.support import create_user

TARA = "TARA"
MEERA, NEHA, RAVI, KABIR, PRIYA, SAHIL, ANANYA = (
    keys.USERS.MEERA,
    keys.USERS.NEHA,
    keys.USERS.RAVI,
    keys.USERS.KABIR,
    keys.USERS.PRIYA,
    keys.USERS.SAHIL,
    keys.USERS.ANANYA,
)


class PqlWorld(InvWorld):
    def at(self, when: datetime) -> None:
        """Move the world clock and the global test clock (the drained worker reads the latter)."""
        from app.core.clock import FrozenClock, get_clock

        self.ctx.at(when)
        clock = get_clock(self.company_id)
        if isinstance(clock, FrozenClock) and clock is not self.ctx.clock:
            clock.set(when)

    def po_lines(self, po_id: uuid.UUID) -> list[PurchaseOrderLine]:
        with self.system() as uow:
            return purchase_orders.lines_of(uow, po_id)

    def po(self, po_id: uuid.UUID) -> PurchaseOrder:
        with self.system() as uow:
            po = uow.session.get(PurchaseOrder, po_id)
            assert po is not None
            return po

    def new_po(self, *lines: tuple[str, str, str | None], person: str = TARA, expected: date | None = None,
               **header: Any) -> uuid.UUID:
        """A draft PO to Kaveri (product, quantity, unit price or None for the vendor price) into WH-MAIN."""
        with self.uow(person) as uow:
            po = purchase_orders.create_purchase_order(uow, PoCreate(
                vendor_party_id=header.pop("vendor", self.ref("KAVERI")),
                warehouse_id=header.pop("warehouse_id", self.warehouse_id),
                lines=[PoLineIn(product_id=self.ref(p), quantity=Decimal(q),
                                unit_price=Decimal(price) if price else None,
                                price_override_reason=header.get("override_reason") if price else None,
                                expected_date=expected) for p, q, price in lines]))
            return po.id

    def po_action(self, po_id: uuid.UUID, action: str, person: str = TARA, **extra: Any) -> Any:
        with self.uow(person) as uow:
            version = uow.session.get(PurchaseOrder, po_id).version  # type: ignore[union-attr]
            return purchase_orders.detail(uow, purchase_orders.transition(
                uow, po_id, PoTransition(action=action, expected_version=version, **extra)))

    def issued_po(self, *lines: tuple[str, str, str | None], expected: date | None = None) -> uuid.UUID:
        po_id = self.new_po(*lines, expected=expected)
        self.po_action(po_id, "submit")
        self.po_action(po_id, "approve", SAHIL)
        self.po_action(po_id, "issue")
        return po_id

    def receive(self, po_id: uuid.UUID, *lines: tuple[int, str, str | None], person: str = RAVI,
                key: str | None = None) -> Any:
        """Post a receipt: (PO line no, quantity, lot code)."""
        by_no = {ln.line_no: ln for ln in self.po_lines(po_id)}
        with self.uow(person, idempotency_key=key) as uow:
            grn = receiving.create_receipt(uow, GrnCreate(purchase_order_id=po_id, lines=[
                GrnLineIn(po_line_id=by_no[n].id, quantity=Decimal(q), lot_code=lot) for n, q, lot in lines]))
            grn = receiving.post_receipt(uow, grn.id)
            return receiving.detail(uow, grn)

    def inspections(self, source_id: uuid.UUID | None = None) -> list[Inspection]:
        with self.system() as uow:
            stmt = select(Inspection).where(Inspection.company_id == self.company_id)
            if source_id is not None:
                stmt = stmt.where(Inspection.source_id == source_id)
            return list(uow.session.scalars(stmt.order_by(Inspection.inspection_number)))

    def decide(self, inspection_id: uuid.UUID, accepted: str, rejected: str = "0", person: str = RAVI,
               **extra: Any) -> Any:
        with self.uow(person) as uow:
            insp = uow.session.get(Inspection, inspection_id)
            assert insp is not None
            checklist = [ChecklistItem(code="visual_ok", label="Surface free of defects",
                                       result="fail" if Decimal(rejected) > 0 else "pass")]
            return quality.detail(uow, quality.decide_inspection(uow, inspection_id, InspectionDecision(
                expected_version=insp.version, qty_accepted=Decimal(accepted), qty_rejected=Decimal(rejected),
                checklist=checklist, reject_reason_code="surface_damage" if Decimal(rejected) > 0 else None,
                **extra)))

    def bill(self, po_id: uuid.UUID, number: str, *lines: tuple[int, str, str], subtotal: str | None = None,
             person: str = ANANYA) -> Any:
        by_no = {ln.line_no: ln for ln in self.po_lines(po_id)}
        computed = sum((Decimal(q) * Decimal(p) for _, q, p in lines), Decimal(0))
        with self.uow(person) as uow:
            b = matching.create_bill(uow, BillCreate(
                purchase_order_id=po_id, bill_number=number, bill_date=self.ctx.clock.now().date(),
                subtotal_amount=Decimal(subtotal) if subtotal else computed, total_amount=computed,
                lines=[BillLineIn(po_line_id=by_no[n].id, quantity=Decimal(q), unit_price=Decimal(p))
                       for n, q, p in lines]))
            return matching.read(uow, b)

    def packing_list(self, order_id: uuid.UUID, person: str = RAVI, **extra: Any) -> Any:
        with self.uow(person) as uow:
            return packing_lists.detail(uow, packing_lists.create_packing_list(
                uow, PackingListCreate(sales_order_id=order_id, **extra)))

    def shipment(self, person: str = RAVI, **body: Any) -> Any:
        with self.uow(person) as uow:
            return shipments.detail(uow, shipments.create_shipment(uow, ShipmentCreate(**body)))

    def shipment_action(self, shipment_id: uuid.UUID, action: str, person: str = RAVI, *, key: str | None = None,
                        **extra: Any) -> Any:
        with self.uow(person, idempotency_key=key or str(uuid.uuid7())) as uow:
            version = shipments.get_shipment(uow, shipment_id).version
            return shipments.detail(uow, shipments.transition(
                uow, shipment_id, ShipmentTransition(action=action, expected_version=version, **extra)))

    def issues(self, family: str) -> list[Issue]:
        with self.system() as uow:
            return list(uow.session.scalars(select(Issue).where(Issue.company_id == self.company_id,
                                                                Issue.family == family).order_by(Issue.created_at)))

    def open_tasks(self, issue: Issue) -> list[Task]:
        with self.system() as uow:
            return list(uow.session.scalars(select(Task).where(Task.issue_id == issue.id,
                                                               Task.state.in_(["open", "in_progress"]))
                                            .order_by(Task.created_at)))


def add_persona(w: World, key: str, name: str, template: str) -> None:
    user_id = create_user(w.company_id, name)
    actor = ActorContext(
        actor_type="user",
        company_id=w.company_id,
        user_id=user_id,
        display_name=name,
        branch_ids=frozenset({w.branch_id}),
        permissions=MappingProxyType(dict(template_grants()[template])),
        channel="test",
    )
    w.actors[key] = actor
    w.ctx.refs[key] = user_id
    catalogue_world._PERSONAS[(w.company_id, user_id)] = actor


def build_pql_world(personas: World) -> PqlWorld:
    from app.seed.world.logistics import seed_logistics
    from app.seed.world.procurement import seed_procurement

    base = build_inv_world(personas)
    w = PqlWorld(base.company_id, base.branch_id, base.ctx, base.actors)
    add_persona(w, TARA, "Tara Menon", "procurement")
    seed_procurement(w.ctx)
    seed_logistics(w.ctx)
    from app.seed.context import D0

    w.at(D0)
    return w


@pytest.fixture
def pql_world(personas: World) -> PqlWorld:
    return build_pql_world(personas)
