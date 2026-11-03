"""Order events (names and fields frozen in docs/architecture/events.md §3.10) and the ``SO-YYYY-NNNN`` sequence.
Payloads carry ids, numbers and reason codes only (never quantities or amounts)."""

from __future__ import annotations

from app.platform.numbering.defs import SequenceDef

ORDER_CREATED = "orders.sales_order.created"
ORDER_CONFIRMED = "orders.sales_order.confirmed"
ORDER_ON_HOLD = "orders.sales_order.put_on_hold"
ORDER_COMPLETED = "orders.sales_order.completed"
ORDER_CANCELLED = "orders.sales_order.cancelled"
LINE_CANCELLED = "orders.sales_order_line.cancelled"
LINE_DELIVERED = "orders.sales_order_line.delivered"

EMITTED_EVENTS: tuple[str, ...] = (
    ORDER_CREATED,
    ORDER_CONFIRMED,
    ORDER_ON_HOLD,
    ORDER_COMPLETED,
    ORDER_CANCELLED,
    LINE_CANCELLED,
    LINE_DELIVERED,
)

#: ADR-015: ``SO-`` yearly by the company-local order date
ORDER_SEQUENCE = SequenceDef(
    key="orders.sales_order",
    name="Sales order number",
    format_template="SO-{yyyy}-{seq:04}",
    reset_policy="yearly",
    resource_type="orders.sales_order",
)
