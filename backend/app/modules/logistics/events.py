"""Logistics events (events.md §3.10: ids, numbers, codes and the cutoff instant), the sequences and the consumers:
``logistics.shipment_status`` (a shipment linked to a challan becomes dispatched when the challan is issued) and
``logistics.packing_list_staleness`` (draft packing lists go stale when a product's packaging or the order changes)."""

from __future__ import annotations

from app.platform.numbering.defs import SequenceDef

SHIPMENT_SCHEDULED = "logistics.shipment.scheduled"
SHIPMENT_DISPATCHED = "logistics.shipment.dispatched"
SHIPMENT_DELIVERED = "logistics.shipment.delivered"
SHIPMENT_EXCEPTION = "logistics.shipment.exception_recorded"
PACKING_FINALISED = "logistics.packing_list.finalised"
PACKING_STALE = "logistics.packing_list.became_stale"

EMITTED_EVENTS: tuple[str, ...] = (
    SHIPMENT_SCHEDULED,
    SHIPMENT_DISPATCHED,
    SHIPMENT_DELIVERED,
    SHIPMENT_EXCEPTION,
    PACKING_FINALISED,
    PACKING_STALE,
)

SHIPMENT_STATUS = "logistics.shipment_status"
STALENESS = "logistics.packing_list_staleness"
#: events that make draft packing lists stale (catalogue packaging edits; order changes)
STALENESS_TRIGGERS: tuple[str, ...] = (
    "catalogue.product.updated",
    "orders.sales_order_line.cancelled",
    "orders.sales_order.cancelled",
)


def _seq(key: str, name: str, prefix: str) -> SequenceDef:
    return SequenceDef(
        key=key,
        name=name,
        format_template=f"{prefix}-{{yyyy}}-{{seq:04}}",
        reset_policy="yearly",
        resource_type=key,
    )


SEQUENCES = [
    _seq("logistics.packing_list", "Packing list number", "PK"),
    _seq("logistics.shipment", "Shipment number", "SH"),
]
