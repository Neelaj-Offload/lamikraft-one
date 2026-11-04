"""Logistics record scope (permissions.md §7.7): packing lists and shipments are scoped by the order owner
(``owner_user_id``, so sales read their own orders' lists) and the branch (operations branch, management company).
Commands that name an order, a challan, a packing list or a transporter need that record to be visible to the actor
(404 otherwise); container profiles and load suggestions are company keys."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.modules.logistics.enums import PackingListStatus
from app.modules.logistics.models import PackingList, PackingListLine, Shipment, ShipmentTrackingRef
from app.platform.authz.context import ActorContext
from app.platform.authz.policy import Decision, ParentRef, ResourcePolicy


def _packing_rules(_ctx: ActorContext, p: Any) -> Mapping[str, Decision]:
    draft = p.status == PackingListStatus.DRAFT.value
    return {"update": Decision(draft, None if draft else "packing_list_not_draft")}


PACKING_LIST_POLICY = ResourcePolicy(
    resource_type="logistics.packing_list",
    model=PackingList,
    permission_prefix="logistics.packing_list",
    owner_columns=("owner_user_id",),
    branch_column="branch_id",
    business_key_column="packing_list_number",
    label=lambda p: f"{p.packing_list_number} · {p.party_name}",
    canonical_path=lambda p: f"/operations/dispatch/packing-lists/{p.id}",
    rules=_packing_rules,
    archived_column=None,
)
PACKING_LINE_POLICY = ResourcePolicy(
    resource_type="logistics.packing_list_line",
    model=PackingListLine,
    permission_prefix="logistics.packing_list",
    parent=ParentRef("logistics.packing_list", "packing_list_id"),
    archived_column=None,
)
SHIPMENT_POLICY = ResourcePolicy(
    resource_type="logistics.shipment",
    model=Shipment,
    permission_prefix="logistics.shipment",
    owner_columns=("owner_user_id",),
    branch_column="branch_id",
    business_key_column="shipment_number",
    label=lambda s: f"{s.shipment_number} · {s.party_name}",
    canonical_path=lambda s: f"/operations/dispatch/shipments/{s.id}",
    archived_column=None,
)
TRACKING_POLICY = ResourcePolicy(
    resource_type="logistics.shipment_tracking_ref",
    model=ShipmentTrackingRef,
    permission_prefix="logistics.shipment",
    parent=ParentRef("logistics.shipment", "shipment_id"),
    archived_column=None,
)
POLICIES = [PACKING_LIST_POLICY, PACKING_LINE_POLICY, SHIPMENT_POLICY, TRACKING_POLICY]
