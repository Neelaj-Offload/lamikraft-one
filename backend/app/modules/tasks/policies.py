"""Tasks resource policy. Keys come from the frozen catalogue (permissions.md §7.5); templates are
granted centrally by ``app.platform.authz`` (employee O, management C, operations B).

``tasks.task`` record scope: owner or assignee (own), team peers (team), the task's branch (branch),
everything (company). Approval candidates see their approval tasks through ``visibility.candidate_clause``.
Reminders have no policy: they are self-service and filtered by ``user_id`` (others' ids return 404).
"""

from __future__ import annotations

from typing import Any

from app.modules.tasks.models import OPEN_STATES, Task
from app.platform.authz.context import ActorContext
from app.platform.authz.policy import Decision, ResourcePolicy


def _rules(actor: ActorContext, task: Any) -> dict[str, Decision]:
    open_ = task.state in OPEN_STATES
    closed = Decision(False, "closed")
    out: dict[str, Decision] = {}
    for action in ("update", "assign", "dismiss"):
        if not open_:
            out[action] = closed
    if task.kind == "approval_decision":
        out["dismiss"] = Decision(False, "undismissable_kind")
        out["assign"] = Decision(False, "approvals_use_candidates")
    return out


TASK_POLICY = ResourcePolicy(
    resource_type="tasks.task",
    model=Task,
    permission_prefix="tasks.task",
    owner_columns=("owner_user_id", "assignee_user_id"),
    branch_column="scope_branch_id",
    label=lambda t: t.title,
    canonical_path=lambda t: f"/inbox/{t.id}",
    rules=_rules,
)

POLICIES = [TASK_POLICY]
