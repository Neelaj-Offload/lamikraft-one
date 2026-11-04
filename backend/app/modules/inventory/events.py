"""Inventory events (names and payload fields frozen in docs/architecture/events.md §3.10), the document sequences, the
``inventory_policy`` setting and the ``inventory.shortage_refresh`` subscriptions.

Payloads carry ids and codes only, never quantities: consumers re-read the projections through ``service.py``.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.platform.numbering.defs import SequenceDef
from app.platform.org.settings import SettingDef

STOCK_POSTED = "inventory.stock.posted"
POSTING_REVERSED = "inventory.posting.reversed"
RESERVATION_CREATED = "inventory.reservation.created"
RESERVATION_RELEASED = "inventory.reservation.released"
RESERVATION_SHORTFALL = "inventory.reservation.shortfall_detected"
RESERVATION_CONFLICT = "inventory.reservation.conflict_detected"
SHORTAGE_DETECTED = "inventory.shortage.detected"
SHORTAGE_CHANGED = "inventory.shortage.changed"
SHORTAGE_RESOLVED = "inventory.shortage.resolved"
ADJUSTMENT_POSTED = "inventory.adjustment.posted"
COUNT_FROZEN = "inventory.stock_count.frozen"
COUNT_POSTED = "inventory.stock_count.posted"
OPENING_POSTED = "inventory.opening_batch.posted"
PICK_RELEASED = "inventory.pick_list.released"
PICK_PICKED = "inventory.pick_list.picked"
PROJECTION_MISMATCH = "inventory.projection.mismatch_detected"
LOT_MEASURED = "inventory.lot.measured"

EMITTED_EVENTS: tuple[str, ...] = (
    STOCK_POSTED,
    POSTING_REVERSED,
    RESERVATION_CREATED,
    RESERVATION_RELEASED,
    RESERVATION_SHORTFALL,
    RESERVATION_CONFLICT,
    SHORTAGE_DETECTED,
    SHORTAGE_CHANGED,
    SHORTAGE_RESOLVED,
    ADJUSTMENT_POSTED,
    COUNT_FROZEN,
    COUNT_POSTED,
    OPENING_POSTED,
    PICK_RELEASED,
    PICK_PICKED,
    PROJECTION_MISMATCH,
    LOT_MEASURED,
)

#: events whose (product, warehouse) pairs the ``inventory.shortage_refresh`` consumer recomputes
SHORTAGE_TRIGGERS: tuple[str, ...] = (
    STOCK_POSTED,
    POSTING_REVERSED,
    RESERVATION_CREATED,
    RESERVATION_RELEASED,
    RESERVATION_SHORTFALL,
    "orders.sales_order.confirmed",
    "orders.sales_order.put_on_hold",
    "orders.sales_order.completed",
    "orders.sales_order.cancelled",
    "orders.sales_order_line.cancelled",
    # work-order materials are demand while released / in progress (production lane; pair resolver in its manifest)
    "production.work_order.released",
    "production.work_order.completed",
    "production.work_order.closed",
    "production.work_order.cancelled",
)
SHORTAGE_REFRESH = "inventory.shortage_refresh"


def _seq(key: str, name: str, prefix: str) -> SequenceDef:
    return SequenceDef(
        key=key,
        name=name,
        format_template=f"{prefix}-{{yyyy}}-{{seq:04}}",
        reset_policy="yearly",
        resource_type=key,
    )


#: ADR-015: PL- yearly; counts, adjustments, opening batches and transfers follow the same yearly pattern
SEQUENCES = [
    _seq("inventory.pick_list", "Pick list number", "PL"),
    _seq("inventory.stock_count", "Stock count number", "SC"),
    _seq("inventory.adjustment", "Stock adjustment number", "ADJ"),
    _seq("inventory.opening_batch", "Opening stock batch number", "OB"),
    _seq("inventory.transfer", "Stock transfer number", "TR"),
]


class InventoryPolicy(BaseModel):
    """Inventory go-live switches (operations.md §4: before go-live challans are documents only)."""

    model_config = ConfigDict(extra="forbid")

    #: after go-live every issued challan posts stock per the movement policy (legacy and imported challans never do)
    challan_postings_enabled: bool = False
    #: the warehouse a challan posts from when it names none (and the default for new sales orders)
    default_warehouse_code: str | None = Field(
        default=None, max_length=20, pattern=r"^[A-Z0-9][A-Z0-9-]{0,19}$"
    )


INVENTORY_POLICY = SettingDef(
    key="inventory_policy",
    model=InventoryPolicy,
    description="Inventory go-live: whether challans post stock, and the default warehouse",
    read_permission="org.settings.read",
    manage_permission="org.settings.manage",
    owner_module="inventory",
)
