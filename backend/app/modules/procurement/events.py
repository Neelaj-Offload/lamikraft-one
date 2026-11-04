"""Procurement events (names and payload fields frozen in docs/architecture/events.md §3.10), the ``PR``/``PO``/``GRN``
sequences and the ``procurement_policy`` setting. Payloads carry ids, numbers and codes only (never quantities,
prices or amounts)."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.platform.numbering.defs import SequenceDef
from app.platform.org.settings import SettingDef

REQUISITION_SUBMITTED = "procurement.requisition.submitted"
REQUISITION_APPROVED = "procurement.requisition.approved"
REQUISITION_REJECTED = "procurement.requisition.rejected"
PO_APPROVED = "procurement.purchase_order.approved"
PO_ISSUED = "procurement.purchase_order.issued"
PO_CLOSED = "procurement.purchase_order.closed"
PO_CANCELLED = "procurement.purchase_order.cancelled"
PO_OVERDUE = "procurement.purchase_order.became_overdue"
PO_LINE_DATE_CHANGED = "procurement.purchase_order_line.expected_date_changed"
GRN_POSTED = "procurement.goods_receipt.posted"
BILL_MISMATCH = "procurement.vendor_bill.mismatch_detected"
BILL_HANDED_OFF = "procurement.vendor_bill.handed_off"

EMITTED_EVENTS: tuple[str, ...] = (
    REQUISITION_SUBMITTED,
    REQUISITION_APPROVED,
    REQUISITION_REJECTED,
    PO_APPROVED,
    PO_ISSUED,
    PO_CLOSED,
    PO_CANCELLED,
    PO_OVERDUE,
    PO_LINE_DATE_CHANGED,
    GRN_POSTED,
    BILL_MISMATCH,
    BILL_HANDED_OFF,
)

#: procurement events that change supply for the shortage state (events.md §3.10: inventory.shortage_refresh);
#: ``became_overdue`` is added so a newly late line appears in ``caused_by`` (integrator request)
SHORTAGE_EVENTS: tuple[str, ...] = (
    PO_APPROVED,
    PO_ISSUED,
    PO_CLOSED,
    PO_CANCELLED,
    PO_OVERDUE,
    PO_LINE_DATE_CHANGED,
    GRN_POSTED,
)


def _seq(key: str, name: str, prefix: str) -> SequenceDef:
    return SequenceDef(
        key=key,
        name=name,
        format_template=f"{prefix}-{{yyyy}}-{{seq:04}}",
        reset_policy="yearly",
        resource_type=key,
    )


#: ADR-015 pattern: yearly by the company-local document date
SEQUENCES = [
    _seq("procurement.requisition", "Purchase requisition number", "PR"),
    _seq("procurement.purchase_order", "Purchase order number", "PO"),
    _seq("procurement.goods_receipt", "Goods receipt number", "GRN"),
]


class ProcurementPolicy(BaseModel):
    """Matching and receiving tolerances (percent; Decimal)."""

    model_config = ConfigDict(extra="forbid")

    #: a bill unit price may differ from the PO price by at most this percentage before it is a price variance
    price_variance_tolerance_pct: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    #: default over-receipt tolerance for new PO lines
    default_over_receipt_tolerance_pct: Decimal = Field(default=Decimal("0"), ge=0, le=100)


PROCUREMENT_POLICY = SettingDef(
    key="procurement_policy",
    model=ProcurementPolicy,
    description="Purchasing tolerances: bill price variance and default over-receipt",
    read_permission="org.settings.read",
    manage_permission="org.settings.manage",
    owner_module="procurement",
)
