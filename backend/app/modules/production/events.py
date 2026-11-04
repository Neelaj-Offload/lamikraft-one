"""Production events (names and fields frozen in docs/architecture/events.md §3.10), the ``WO-YYYY-NNNN`` sequence and
the subscriptions this module adds. Payloads carry ids, numbers, versions and status codes only (never quantities,
minutes or money)."""

from __future__ import annotations

from app.platform.numbering.defs import SequenceDef

BOM_APPROVED = "production.bom.approved"
ROUTING_APPROVED = "production.routing.approved"
WO_RELEASED = "production.work_order.released"
WO_BLOCKED = "production.work_order.blocked"
WO_UNBLOCKED = "production.work_order.unblocked"
WO_COMPLETED = "production.work_order.completed"
WO_CLOSED = "production.work_order.closed"
WO_CANCELLED = "production.work_order.cancelled"
CAPACITY_OVERLOADED = "production.capacity.overloaded"
COST_ROLLUP_COMPUTED = "production.cost_rollup.computed"

EMITTED_EVENTS: tuple[str, ...] = (
    BOM_APPROVED,
    ROUTING_APPROVED,
    WO_RELEASED,
    WO_BLOCKED,
    WO_UNBLOCKED,
    WO_COMPLETED,
    WO_CLOSED,
    WO_CANCELLED,
    CAPACITY_OVERLOADED,
    COST_ROLLUP_COMPUTED,
)
WORK_ORDER_EVENTS: tuple[str, ...] = (WO_RELEASED, WO_BLOCKED, WO_UNBLOCKED, WO_COMPLETED, WO_CLOSED, WO_CANCELLED)

#: ``production.material_retry:<event>``: a blocked work order retries its reservations when stock arrives or is freed
MATERIAL_RETRY = "production.material_retry"
MATERIAL_RETRY_TRIGGERS: tuple[str, ...] = (
    "inventory.stock.posted",
    "inventory.posting.reversed",
    "inventory.reservation.released",
)

#: ADR-015 pattern: ``WO-`` yearly by the company-local business date
WO_SEQUENCE = SequenceDef(
    key="production.work_order",
    name="Work order number",
    format_template="WO-{yyyy}-{seq:04}",
    reset_policy="yearly",
    resource_type="production.work_order",
)
