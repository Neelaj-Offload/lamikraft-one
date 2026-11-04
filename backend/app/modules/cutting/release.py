"""Cut-plan release for work orders (Slice 4, operations.md §7 lifecycle; added by the production lane).

A plan can back a work order's board operation once it has a current calculation (not stale, not recalculating) and,
when the calculation assumed the oversize board, a physical verification (business decision #12). Releasing it for
a work order freezes it (``released`` is not editable) and emits ``cutting.plan.released`` with the work order id.
Release is idempotent: a plan already released for the same work order is returned unchanged.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select

from app.core.errors import Conflict
from app.modules.cutting import events as ev
from app.modules.cutting.models import CalcGroup, CalcOffcut, Plan
from app.platform.uow import UnitOfWork

PLAN_RELEASED = "cutting.plan.released"


@dataclass(frozen=True)
class Readiness:
    ready: bool
    reason_code: str | None
    boards: int | None


def readiness(uow: UnitOfWork, plan: Plan) -> Readiness:
    boards = None
    if plan.latest_calculation_id is not None:
        boards = int(uow.session.scalar(
            select(func.coalesce(func.sum(CalcGroup.boards), 0)).where(
                CalcGroup.calculation_id == plan.latest_calculation_id)
        ) or 0)
    if plan.archived_at is not None or plan.status == "archived":
        return Readiness(False, "plan_archived", boards)
    if plan.latest_calculation_id is None:
        return Readiness(False, "plan_not_calculated", boards)
    if plan.calc_status in ("queued", "running"):
        return Readiness(False, "calculation_in_progress", boards)
    if plan.inputs_changed_since_calc:
        return Readiness(False, "plan_stale", boards)
    if plan.requires_physical_verification and plan.verified_at is None:
        return Readiness(False, "verification_required", boards)
    return Readiness(True, None, boards)


def visible_plan(uow: UnitOfWork, plan_id: uuid.UUID) -> Plan:
    """The plan when the actor may read it (404 otherwise: an invisible plan id is never confirmed)."""
    return uow.repo(Plan).get(plan_id)


def predicted_offcuts(uow: UnitOfWork, calculation_id: uuid.UUID) -> list[CalcOffcut]:
    return list(uow.session.scalars(
        select(CalcOffcut).where(CalcOffcut.calculation_id == calculation_id)
        .order_by(CalcOffcut.group_no, CalcOffcut.board_no, CalcOffcut.seq)
    ))


def release_for_work_order(uow: UnitOfWork, plan_id: uuid.UUID, work_order_id: uuid.UUID) -> Plan:
    plan = uow.session.scalars(
        select(Plan).where(Plan.company_id == uow.actor.company_id, Plan.id == plan_id).with_for_update()
    ).first()
    if plan is None:
        raise Conflict("The cut plan no longer exists", code="cut_plan_not_found")
    if plan.status == "released":
        return plan
    state = readiness(uow, plan)
    if not state.ready:
        raise Conflict(f"Cut plan {plan.plan_number} is not ready ({state.reason_code})", code="cut_plan_not_ready",
                       reason_code=state.reason_code)
    plan.status = "released"
    plan.updated_at = uow.now()
    uow.flush()
    uow.emit(PLAN_RELEASED, aggregate_id=plan.id, aggregate_version=plan.version,
             payload={"plan_id": str(plan.id), "work_order_id": str(work_order_id)})
    uow.audit("cutting.plan.released", resource_type="cutting.plan", resource_id=plan.id,
              resource_label=plan.plan_number, details={"work_order_id": str(work_order_id)})
    return plan


EMITTED_EVENTS = (*ev.EMITTED_EVENTS, PLAN_RELEASED)
