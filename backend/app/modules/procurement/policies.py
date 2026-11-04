"""Procurement record scope (permissions.md §7.7).

- Requisitions and purchase orders: own/team/branch/company on ``owner_user_id`` (requester / buyer) and ``branch_id``
  (the destination warehouse's branch). Procurement holds company scope, operations and production branch scope.
- Goods receipts: branch scope through the receiving warehouse (operations post at branch scope).
- Vendor items and vendor bills: company-only keys.
Lines are children authorised only through their parent. Every command that names a warehouse also checks the
warehouse scope (``inventory.policies.require_warehouse``); every command that names a vendor needs the party to be
visible (``parties.party.read``), so a guessed id is a 404.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.modules.procurement.enums import PurchaseOrderStatus, RequisitionStatus
from app.modules.procurement.models import (
    GoodsReceipt,
    GoodsReceiptLine,
    PurchaseOrder,
    PurchaseOrderLine,
    Requisition,
    RequisitionLine,
    VendorBill,
    VendorBillLine,
    VendorItem,
)
from app.platform.authz.context import ActorContext
from app.platform.authz.policy import Decision, ParentRef, ResourcePolicy

PR_READ = "procurement.requisition.read"
PO_READ = "procurement.purchase_order.read"
GRN_READ = "procurement.goods_receipt.read"
GRN_POST = "procurement.goods_receipt.post"
BILL_READ = "procurement.vendor_bill.read"
BILL_CREATE = "procurement.vendor_bill.create"
VI_READ = "procurement.vendor_item.read"
VI_MANAGE = "procurement.vendor_item.manage"


def _requisition_rules(_ctx: ActorContext, r: Any) -> Mapping[str, Decision]:
    draft = r.status == RequisitionStatus.DRAFT.value
    return {"update": Decision(draft, None if draft else "requisition_not_draft")}


def _po_rules(_ctx: ActorContext, po: Any) -> Mapping[str, Decision]:
    draft = po.status == PurchaseOrderStatus.DRAFT.value
    return {"update": Decision(draft, None if draft else "purchase_order_not_draft")}


REQUISITION_POLICY = ResourcePolicy(
    resource_type="procurement.requisition",
    model=Requisition,
    permission_prefix="procurement.requisition",
    owner_columns=("owner_user_id",),
    branch_column="branch_id",
    business_key_column="requisition_number",
    label=lambda r: r.requisition_number,
    canonical_path=lambda r: f"/operations/purchasing/requisitions/{r.id}",
    rules=_requisition_rules,
    archived_column=None,
)
REQUISITION_LINE_POLICY = ResourcePolicy(
    resource_type="procurement.requisition_line",
    model=RequisitionLine,
    permission_prefix="procurement.requisition",
    parent=ParentRef("procurement.requisition", "requisition_id"),
    archived_column=None,
)
PO_POLICY = ResourcePolicy(
    resource_type="procurement.purchase_order",
    model=PurchaseOrder,
    permission_prefix="procurement.purchase_order",
    owner_columns=("owner_user_id",),
    branch_column="branch_id",
    business_key_column="po_number",
    label=lambda po: f"{po.po_number} · {po.vendor_name}",
    canonical_path=lambda po: f"/operations/purchasing/orders/{po.id}",
    rules=_po_rules,
    archived_column=None,
)
PO_LINE_POLICY = ResourcePolicy(
    resource_type="procurement.purchase_order_line",
    model=PurchaseOrderLine,
    permission_prefix="procurement.purchase_order",
    parent=ParentRef("procurement.purchase_order", "purchase_order_id"),
    archived_column=None,
)
GRN_POLICY = ResourcePolicy(
    resource_type="procurement.goods_receipt",
    model=GoodsReceipt,
    permission_prefix="procurement.goods_receipt",
    branch_column="branch_id",
    business_key_column="grn_number",
    label=lambda g: g.grn_number,
    canonical_path=lambda g: f"/operations/purchasing/receipts/{g.id}",
    archived_column=None,
)
GRN_LINE_POLICY = ResourcePolicy(
    resource_type="procurement.goods_receipt_line",
    model=GoodsReceiptLine,
    permission_prefix="procurement.goods_receipt",
    parent=ParentRef("procurement.goods_receipt", "goods_receipt_id"),
    archived_column=None,
)
BILL_POLICY = ResourcePolicy(
    resource_type="procurement.vendor_bill",
    model=VendorBill,
    permission_prefix="procurement.vendor_bill",
    label=lambda b: b.bill_number,
    canonical_path=lambda b: f"/operations/purchasing/orders/{b.purchase_order_id}",
    archived_column=None,
)
BILL_LINE_POLICY = ResourcePolicy(
    resource_type="procurement.vendor_bill_line",
    model=VendorBillLine,
    permission_prefix="procurement.vendor_bill",
    parent=ParentRef("procurement.vendor_bill", "vendor_bill_id"),
    archived_column=None,
)
VENDOR_ITEM_POLICY = ResourcePolicy(
    resource_type="procurement.vendor_item",
    model=VendorItem,
    permission_prefix="procurement.vendor_item",
    archived_column=None,
)

POLICIES = [
    REQUISITION_POLICY,
    REQUISITION_LINE_POLICY,
    PO_POLICY,
    PO_LINE_POLICY,
    GRN_POLICY,
    GRN_LINE_POLICY,
    BILL_POLICY,
    BILL_LINE_POLICY,
    VENDOR_ITEM_POLICY,
]
