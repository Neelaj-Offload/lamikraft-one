"""Order transitions and cancellation: line cancellation under the line lock releases reservations beyond the new
need and is audited; holds block deliveries; a whole-order cancel releases everything and is refused once delivered."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.errors import Conflict, InvalidTransition, ValidationFailed
from app.modules.orders import service as orders
from app.modules.orders.schemas import LineCancel
from app.platform.audit.models import AuditLog
from app.platform.events.models import DomainEvent
from app.seed.world import keys
from tests.integration.inventory.world import InvWorld, assert_ledger_consistent

pytestmark = pytest.mark.db
MEERA = keys.USERS.MEERA


def test_line_cancellation_releases_reservation_and_is_audited(inv_world: InvWorld) -> None:
    w = inv_world
    order_id = w.order(MEERA, w.won_quote(MEERA, "NORDHAUS", ("OAK_TRAY", "240")))
    w.reserve(MEERA, order_id)
    d = w.get_order(MEERA, order_id)
    line = d.lines[0]
    assert line.qty_reserved == Decimal(240) and w.summary("OAK_TRAY") == (Decimal(600), Decimal(240))
    with pytest.raises(ValidationFailed), w.uow(MEERA) as uow:  # more than remains
        orders.cancel_line(uow, order_id, line.id, LineCancel(expected_version=line.version, quantity=Decimal(241), reason_code="customer_cancelled"))
    with w.uow(MEERA) as uow:
        orders.cancel_line(uow, order_id, line.id, LineCancel(expected_version=line.version, quantity=Decimal(90), reason_code="customer_cancelled",
                                                              reason="Customer reduced the order"))
    after = w.get_order(MEERA, order_id).lines[0]
    assert (after.qty_cancelled, after.qty_remaining, after.qty_reserved) == (Decimal(90), Decimal(150), Decimal(150))
    assert w.summary("OAK_TRAY") == (Decimal(600), Decimal(150))
    with w.system() as uow:
        audit = uow.session.scalars(select(AuditLog).where(AuditLog.company_id == w.company_id, AuditLog.action == "orders.sales_order_line.cancel")).all()
        events = uow.session.scalars(select(DomainEvent).where(DomainEvent.company_id == w.company_id,
                                                               DomainEvent.event_type == "orders.sales_order_line.cancelled")).all()
    assert len(audit) == 1 and audit[0].reason == "Customer reduced the order"
    assert [e.payload["line_id"] for e in events] == [str(line.id)]
    hist = w.get_order(MEERA, order_id).history
    assert hist[-1].action == "cancel_line" and hist[-1].reason_code == "customer_cancelled" and hist[-1].line_id == line.id
    # cancelling the rest cancels the order (nothing was delivered) and releases the reservation
    with w.uow(MEERA) as uow:
        orders.cancel_line(uow, order_id, line.id, LineCancel(expected_version=after.version, reason_code="customer_cancelled"))
    final = w.get_order(MEERA, order_id)
    assert final.status == "cancelled" and final.lines[0].qty_reserved == 0 and w.summary("OAK_TRAY") == (Decimal(600), Decimal(0))
    assert_ledger_consistent(w)


def test_hold_cancel_and_transition_table(inv_world: InvWorld) -> None:
    w = inv_world
    order_id = w.order(MEERA, w.won_quote(MEERA, "NORDHAUS", ("OAK_TRAY", "240")), confirm=False)
    with pytest.raises(InvalidTransition):
        w.transition_order(MEERA, order_id, "release_hold")
    d = w.get_order(MEERA, order_id)
    assert {t.action for t in d.allowed_transitions} == {"confirm", "cancel"}
    with pytest.raises(Conflict) as exc:  # a draft order reserves nothing
        w.reserve(MEERA, order_id)
    assert exc.value.code == "order_not_confirmed"
    w.transition_order(MEERA, order_id, "confirm")
    w.reserve(MEERA, order_id)
    with pytest.raises(ValidationFailed):
        w.transition_order(MEERA, order_id, "hold")  # a reason is required
    held = w.transition_order(MEERA, order_id, "hold", reason_code="credit", reason="Awaiting payment")
    assert held.status == "on_hold" and held.hold_reason_code == "credit"
    assert w.transition_order(MEERA, order_id, "release_hold").status == "confirmed"
    cancelled = w.transition_order(MEERA, order_id, "cancel", reason_code="customer_cancelled")
    assert cancelled.status == "cancelled" and cancelled.lines[0].qty_cancelled == Decimal(240) and w.summary("OAK_TRAY")[1] == 0
    assert [h.action for h in cancelled.history] == ["create", "confirm", "hold", "release_hold", "cancel"]
    assert_ledger_consistent(w)
