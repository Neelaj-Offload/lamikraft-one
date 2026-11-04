"""Quality record scope (permissions.md §7.7): inspections are visible through their warehouse's branch
(``quality.inspection.read``: operations and production branch, procurement company). The catalogue has two keys;
recording the results is part of creating the inspection record, so deciding needs ``quality.inspection.create`` in
scope over the inspection **and** over its warehouse (``require_warehouse``)."""

from __future__ import annotations

from app.modules.quality.models import Inspection
from app.platform.authz.policy import ResourcePolicy

READ = "quality.inspection.read"
CREATE = "quality.inspection.create"

INSPECTION_POLICY = ResourcePolicy(
    resource_type="quality.inspection",
    model=Inspection,
    permission_prefix="quality.inspection",
    branch_column="branch_id",
    business_key_column="inspection_number",
    label=lambda i: f"{i.inspection_number} · {i.subject_label}",
    canonical_path=lambda i: f"/operations/quality/{i.id}",
    archived_column=None,
)

POLICIES = [INSPECTION_POLICY]
