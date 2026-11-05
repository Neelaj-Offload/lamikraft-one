"""Cutting services: the public entry point for routers, tools, jobs, seeds and other modules.

Implementation lives in ``config`` (settings, machine profiles, grain locks), ``plans`` (plans, calculations, the
stateless calculation, the calculation job, catalogue autocomplete), ``offcuts`` (offcut reuse: candidates, the
plan's selection, the lots a calculation cuts from), ``release`` (work-order release) and ``exports`` (CSV, PDF,
SVG); the pure packer is ``cutting.packer``.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.core.errors import NotFound
from app.modules.cutting.config import (
    add_grain_lock,
    create_machine_profile,
    get_settings,
    list_grain_locks,
    list_machine_profiles,
    locked_decor_keys,
    remove_grain_lock,
    replace_grain_locks,
    update_machine_profile,
    update_settings,
)
from app.modules.cutting.exports import board_svg, placements_csv, plan_pdf, summary_csv
from app.modules.cutting.models import Calculation, Plan
from app.modules.cutting.offcuts import PlannedOffcut, planned_offcuts
from app.modules.cutting.offcuts import candidates as offcut_candidates
from app.modules.cutting.plans import (
    calculate_plan_command,
    calculate_stateless,
    calculation_job,
    calculation_read,
    create_plan,
    create_plan_command,
    detail,
    duplicate_plan,
    duplicate_plan_command,
    get_calculation,
    get_plan,
    list_plans,
    replace_offcuts_command,
    request_calculation,
    search_products,
    transition_plan,
    transition_plan_command,
    update_plan,
    update_plan_command,
    verify_boards,
    verify_boards_command,
)
from app.modules.cutting.schemas import CalculationRead, PlanDetail
from app.platform.org.models import Company
from app.platform.uow import UnitOfWork


def _export_context(uow: UnitOfWork, plan_id: uuid.UUID, calc_no: int | None = None) -> tuple[PlanDetail, CalculationRead]:
    """The plan (``export`` action: in scope, ``cutting.plan.export``, calculated) and the requested calculation."""
    plan = uow.repo(Plan).get(plan_id, "export")
    number = calc_no if calc_no is not None else plan.calc_count
    calc = uow.session.scalars(
        uow.repo(Calculation).select("export").where(Calculation.plan_id == plan.id, Calculation.calc_no == number)
    ).first()
    if calc is None:
        raise NotFound(code="not_found", resource_type="cutting.calculation")
    return detail(uow, plan), calculation_read(uow, calc)


def export_csv(uow: UnitOfWork, plan_id: uuid.UUID, kind: str = "placements") -> tuple[bytes, str]:
    plan, calc = _export_context(uow, plan_id)
    body = summary_csv(plan, calc) if kind == "summary" else placements_csv(plan, calc)
    suffix = "summary" if kind == "summary" else "placements"
    uow.audit("cutting.plan.exported", resource_type="cutting.plan", resource_id=plan.id, resource_label=plan.plan_number,
              details={"format": "csv", "kind": suffix, "calc_no": calc.calc_no})
    return body, f"{plan.plan_number}-{calc.calc_no}-{suffix}.csv"


def export_pdf(uow: UnitOfWork, plan_id: uuid.UUID) -> tuple[bytes, str]:
    plan, calc = _export_context(uow, plan_id)
    zone = uow.session.scalar(select(Company.default_time_zone).where(Company.id == uow.actor.company_id)) or "Asia/Kolkata"
    uow.audit("cutting.plan.exported", resource_type="cutting.plan", resource_id=plan.id, resource_label=plan.plan_number,
              details={"format": "pdf", "calc_no": calc.calc_no})
    return plan_pdf(uow, plan, calc, zone), f"{plan.plan_number}-{calc.calc_no}.pdf"


def export_board_svg(uow: UnitOfWork, plan_id: uuid.UUID, calc_no: int, index: int) -> tuple[str, str]:
    plan, calc = _export_context(uow, plan_id, calc_no)
    for group in calc.groups:
        for board in group.boards:
            if board.index == index:
                return board_svg(plan.plan_number, group, board), f"{plan.plan_number}-{calc_no}-board-{index}.svg"
    raise NotFound(code="not_found", resource_type="cutting.calc_board")


__all__ = [
    "add_grain_lock",
    "calculate_plan_command",
    "calculate_stateless",
    "calculation_job",
    "create_machine_profile",
    "create_plan",
    "create_plan_command",
    "detail",
    "duplicate_plan",
    "duplicate_plan_command",
    "export_board_svg",
    "export_csv",
    "export_pdf",
    "get_calculation",
    "get_plan",
    "get_settings",
    "list_grain_locks",
    "list_machine_profiles",
    "list_plans",
    "locked_decor_keys",
    "offcut_candidates",
    "planned_offcuts",
    "PlannedOffcut",
    "replace_offcuts_command",
    "remove_grain_lock",
    "replace_grain_locks",
    "request_calculation",
    "search_products",
    "transition_plan",
    "transition_plan_command",
    "update_machine_profile",
    "update_plan",
    "update_plan_command",
    "update_settings",
    "verify_boards",
    "verify_boards_command",
]
