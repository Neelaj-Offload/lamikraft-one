"""Import job policy: ``imports.job.read`` / ``.run`` at own scope cover the jobs the user started (``created_by``),
at company scope every job of the company. Rows, issues, changes and the source file are reached through the job."""

from __future__ import annotations

from app.modules.imports.models import ImportJob
from app.platform.authz.policy import ResourcePolicy

JOB_POLICY = ResourcePolicy(
    resource_type="imports.job",
    model=ImportJob,
    permission_prefix="imports.job",
    owner_columns=("created_by",),
    label=lambda j: f"{j.import_type} · {j.file_name}",
    canonical_path=lambda j: f"/settings/imports/{j.id}",
    archived_column=None,
)

POLICIES = [JOB_POLICY]
