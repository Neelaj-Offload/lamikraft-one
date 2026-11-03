"""Challan record scope (permissions.md §7.6, SEC-03 for challans).

- ``challans.challan``: own/team/branch/company on ``owner_user_id`` and ``branch_id`` (operations branch, sales own,
  management and finance company read). Lines, status history and return links are children authorised only through
  their challan, so an invisible challan is a 404 for every child path, the PDF, the print view and the CSV.
- Object rules feed ``capabilities`` and ``ScopedRepository.require_action``. ``update`` deliberately has **no** state
  rule: the internal note (``platform/collab``) needs the parent's ``update`` and stays editable after issue; the
  service refuses header and line edits outside ``draft`` itself (409 ``challan_not_editable``).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.modules.challans.models import (
    Challan,
    ChallanLine,
    ChallanReturnLink,
    ChallanRevision,
    ChallanStatusHistory,
)
from app.modules.challans.schemas import ChallanStatus
from app.platform.authz.context import ActorContext
from app.platform.authz.policy import Decision, ParentRef, ResourcePolicy

DRAFT = ChallanStatus.DRAFT.value
ISSUED = ChallanStatus.ISSUED.value


def challan_rules(_ctx: ActorContext, c: Any) -> Mapping[str, Decision]:
    deleted = c.deleted_at is not None
    draft = c.status == DRAFT and not deleted
    return {
        "delete": Decision(draft, None if draft else ("challan_deleted" if deleted else "challan_not_draft")),
        "issue": Decision(draft, None if draft else ("challan_deleted" if deleted else "invalid_status")),
        "transition": Decision(
            c.status in (DRAFT, ISSUED) and not deleted,
            None if c.status in (DRAFT, ISSUED) and not deleted else "invalid_status",
        ),
        "reverse": Decision(c.status == ISSUED, None if c.status == ISSUED else "invalid_status"),
        "export": Decision(not deleted, None if not deleted else "challan_deleted"),
    }


def _label(c: Any) -> str:
    return f"{c.challan_number} · {c.destination_party}"


CHALLAN_POLICY = ResourcePolicy(
    resource_type="challans.challan",
    model=Challan,
    permission_prefix="challans.challan",
    owner_columns=("owner_user_id",),
    branch_column="branch_id",
    business_key_column="challan_number",
    label=_label,
    canonical_path=lambda c: f"/operations/challans/{c.id}",
    rules=challan_rules,
    archived_column="deleted_at",
)
CHALLAN_LINE_POLICY = ResourcePolicy(
    resource_type="challans.challan_line",
    model=ChallanLine,
    permission_prefix="challans.challan",
    parent=ParentRef("challans.challan", "challan_id"),
    archived_column=None,
)
CHALLAN_HISTORY_POLICY = ResourcePolicy(
    resource_type="challans.challan_status_history",
    model=ChallanStatusHistory,
    permission_prefix="challans.challan",
    parent=ParentRef("challans.challan", "challan_id"),
    archived_column=None,
)
CHALLAN_REVISION_POLICY = ResourcePolicy(
    resource_type="challans.challan_revision",
    model=ChallanRevision,
    permission_prefix="challans.challan",
    parent=ParentRef("challans.challan", "challan_id", {"export": "export", "download": "export"}),
    archived_column=None,
)
RETURN_LINK_POLICY = ResourcePolicy(
    resource_type="challans.return_link",
    model=ChallanReturnLink,
    permission_prefix="challans.challan",
    parent=ParentRef("challans.challan", "return_challan_id"),
    archived_column=None,
)

POLICIES = [
    CHALLAN_POLICY,
    CHALLAN_LINE_POLICY,
    CHALLAN_HISTORY_POLICY,
    CHALLAN_REVISION_POLICY,
    RETURN_LINK_POLICY,
]
