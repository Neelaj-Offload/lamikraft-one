"""Cutting record scope (permissions.md §7.6).

- ``cutting.plan``: own/team/branch/company on ``owner_user_id`` and ``branch_id`` (sales own, operations branch,
  management and production company). Items and calculations are children authorised only through their plan, and
  every calculation result row only through its calculation (an invisible plan is a 404 for every child path,
  including the CSV, PDF and SVG exports).
- Object rules feed ``capabilities``: drafts and calculated plans are editable and calculable; archived plans are
  read-only; exports need a stored calculation; verification only applies to plans that assumed the oversize board.
- Settings, machine profiles and grain locks are company configuration: read by anyone holding a ``cutting.`` key,
  written with ``cutting.settings.manage`` / ``cutting.grain_lock.manage`` (see ``service``); they have no record
  scope of their own.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.modules.cutting.models import (
    CalcBoard,
    CalcCut,
    CalcGroup,
    CalcItemResult,
    CalcOffcut,
    CalcPlacement,
    Calculation,
    Plan,
    PlanItem,
)
from app.platform.authz.context import ActorContext
from app.platform.authz.policy import Decision, ParentRef, ResourcePolicy

EDITABLE = frozenset({"draft", "calculated"})


def plan_rules(_ctx: ActorContext, p: Any) -> Mapping[str, Decision]:
    archived = p.archived_at is not None or p.status == "archived"
    editable = p.status in EDITABLE and not archived
    calculated = p.latest_calculation_id is not None
    return {
        "update": Decision(editable, None if editable else ("plan_archived" if archived else f"plan_{p.status}_not_editable")),
        "export": Decision(calculated, None if calculated else "plan_not_calculated"),
        "transition": Decision(not archived, None if not archived else "plan_archived"),
    }


PLAN_POLICY = ResourcePolicy(
    resource_type="cutting.plan",
    model=Plan,
    permission_prefix="cutting.plan",
    owner_columns=("owner_user_id",),
    branch_column="branch_id",
    business_key_column="plan_number",
    label=lambda p: f"{p.plan_number} · {p.name}",
    canonical_path=lambda p: f"/operations/cutting/{p.id}",
    rules=plan_rules,
    archived_column=None,
)
PLAN_ITEM_POLICY = ResourcePolicy(
    resource_type="cutting.plan_item",
    model=PlanItem,
    permission_prefix="cutting.plan",
    parent=ParentRef("cutting.plan", "plan_id"),
    archived_column=None,
)
CALCULATION_POLICY = ResourcePolicy(
    resource_type="cutting.calculation",
    model=Calculation,
    permission_prefix="cutting.plan",
    parent=ParentRef("cutting.plan", "plan_id", {"export": "export"}),
    archived_column=None,
)


def _result_policy(resource_type: str, model: type) -> ResourcePolicy:
    return ResourcePolicy(
        resource_type=resource_type,
        model=model,
        permission_prefix="cutting.plan",
        parent=ParentRef("cutting.calculation", "calculation_id", {"export": "export"}),
        archived_column=None,
    )


RESULT_POLICIES = [
    _result_policy("cutting.calc_group", CalcGroup),
    _result_policy("cutting.calc_board", CalcBoard),
    _result_policy("cutting.calc_placement", CalcPlacement),
    _result_policy("cutting.calc_item_result", CalcItemResult),
    _result_policy("cutting.calc_offcut", CalcOffcut),
    _result_policy("cutting.calc_cut", CalcCut),
]

POLICIES = [PLAN_POLICY, PLAN_ITEM_POLICY, CALCULATION_POLICY, *RESULT_POLICIES]
