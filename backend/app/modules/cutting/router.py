"""Cutting API (``/api/v1/cutting``): the stateless calculation, catalogue autocomplete, settings, machine profiles,
grain locks, plans, calculations and exports. Routers never import models; services enforce scope and state."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal
from urllib.parse import quote as urlquote

from fastapi import APIRouter, Depends, Query, Response

from app.core.http.authz_decl import authenticated, requires
from app.core.http.deps import Actor, IdempotencyKeyHeader
from app.core.http.pagination import MAX_LIMIT, Page
from app.modules.cutting import service
from app.modules.cutting.schemas import (
    CalculateIn,
    CalculationRead,
    CalculationResult,
    CuttingProduct,
    GrainLockIn,
    GrainLockList,
    GrainLockReplace,
    MachineProfileCreate,
    MachineProfileRead,
    MachineProfileUpdate,
    OffcutCandidates,
    PlanCommand,
    PlanCreate,
    PlanDetail,
    PlanFilters,
    PlanOffcutsUpdate,
    PlanStatus,
    PlanSummary,
    PlanTransition,
    PlanUpdate,
    SettingsRead,
    SettingsUpdate,
    VerifyBoards,
)
from app.platform.uow import UnitOfWork

router = APIRouter(prefix="/cutting", tags=["cutting"])
REPLAYED = "Idempotent-Replayed"
Limit = Annotated[int, Query(ge=1, le=MAX_LIMIT)]
Offset = Annotated[int, Query(ge=0)]


def _replayed(response: Response, replayed: bool) -> None:
    if replayed:
        response.headers[REPLAYED] = "true"


def _download(content: bytes | str, media_type: str, filename: str, *, inline: bool = False) -> Response:
    disposition = "inline" if inline else "attachment"
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f"{disposition}; filename=\"{filename}\"; filename*=UTF-8''{urlquote(filename)}",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
            "Content-Security-Policy": "sandbox",
        },
    )


# =====================================================================================================
# stateless calculation and autocomplete
# =====================================================================================================
@router.post("/calculate", openapi_extra=requires("cutting.calculation.run"))
def calculate_cut_list(actor: Actor, body: CalculateIn) -> CalculationResult:
    """Pack a cut list without saving it (legacy ``POST /sheet-optimizer/calculate``; up to the synchronous limit)."""
    with UnitOfWork(actor) as uow:
        return service.calculate_stateless(uow, body)


@router.get("/products", openapi_extra=requires("cutting.calculation.run"))
def search_cutting_products(
    actor: Actor, search: Annotated[str, Query(max_length=200)] = "", limit: Annotated[int, Query(ge=1, le=25)] = 10
) -> list[CuttingProduct]:
    """Catalogue autocomplete for the cut list: fills decor, thickness and dimensions (catalogue scope applies)."""
    with UnitOfWork(actor) as uow:
        return service.search_products(uow, search, limit=limit)


# =====================================================================================================
# settings, machine profiles, grain locks
# =====================================================================================================
@router.get("/settings", openapi_extra=authenticated())
def get_cutting_settings(actor: Actor) -> SettingsRead:
    """Company board defaults (legacy constants 2440 × 1220, margin 5, gap 6, oversize 10); any ``cutting.`` key."""
    with UnitOfWork(actor) as uow:
        return service.get_settings(uow)


@router.patch("/settings", openapi_extra=requires("cutting.settings.manage"))
def update_cutting_settings(actor: Actor, body: SettingsUpdate) -> SettingsRead:
    with UnitOfWork(actor) as uow:
        return service.update_settings(uow, body)


@router.get("/machine-profiles", openapi_extra=authenticated())
def list_machine_profiles(actor: Actor, include_archived: bool = False) -> list[MachineProfileRead]:
    with UnitOfWork(actor) as uow:
        return service.list_machine_profiles(uow, include_archived=include_archived)


@router.post("/machine-profiles", status_code=201, openapi_extra=requires("cutting.settings.manage"))
def create_machine_profile(actor: Actor, body: MachineProfileCreate) -> MachineProfileRead:
    with UnitOfWork(actor) as uow:
        return service.create_machine_profile(uow, body)


@router.patch("/machine-profiles/{profile_id}", openapi_extra=requires("cutting.settings.manage"))
def update_machine_profile(actor: Actor, profile_id: uuid.UUID, body: MachineProfileUpdate) -> MachineProfileRead:
    with UnitOfWork(actor) as uow:
        return service.update_machine_profile(uow, profile_id, body)


@router.get("/grain-locks", openapi_extra=authenticated())
def list_grain_locks(actor: Actor) -> GrainLockList:
    """Grain-locked decors (canonical keys); readable with any ``cutting.`` key."""
    with UnitOfWork(actor) as uow:
        return service.list_grain_locks(uow)


@router.put("/grain-locks", openapi_extra=requires("cutting.grain_lock.manage"))
def replace_grain_locks(actor: Actor, body: GrainLockReplace) -> GrainLockList:
    """Bulk replace (legacy ``PUT /grain-settings``); audited with the added, removed and relabelled decors."""
    with UnitOfWork(actor) as uow:
        return service.replace_grain_locks(uow, body)


@router.post("/grain-locks", status_code=201, openapi_extra=requires("cutting.grain_lock.manage"))
def add_grain_lock(actor: Actor, body: GrainLockIn) -> GrainLockList:
    with UnitOfWork(actor) as uow:
        return service.add_grain_lock(uow, body)


@router.delete("/grain-locks/{decor_key}", openapi_extra=requires("cutting.grain_lock.manage"))
def remove_grain_lock(actor: Actor, decor_key: str) -> GrainLockList:
    """Remove one lock by its decor (canonicalised, so ``120.0`` removes ``120``)."""
    with UnitOfWork(actor) as uow:
        return service.remove_grain_lock(uow, decor_key)


# =====================================================================================================
# plans
# =====================================================================================================
def _plan_filters(
    q: Annotated[str | None, Query(max_length=200, description="Tokens matched against the plan number and name")] = None,
    status: Annotated[list[PlanStatus] | None, Query()] = None,
    scope: Annotated[Literal["mine", "all"], Query()] = "all",
    include_archived: bool = False,
) -> PlanFilters:
    return PlanFilters(q=q, status=status, scope=scope, include_archived=include_archived)


@router.get("/plans", openapi_extra=requires("cutting.plan.read"))
def list_cut_plans(
    actor: Actor, filters: Annotated[PlanFilters, Depends(_plan_filters)], limit: Limit = 25, offset: Offset = 0
) -> Page[PlanSummary]:
    """Plans within the actor's read scope; filters apply before paging; archived plans only when asked."""
    with UnitOfWork(actor) as uow:
        return service.list_plans(uow, filters, limit=limit, offset=offset)


@router.post("/plans", status_code=201, openapi_extra=requires("cutting.plan.create"))
def create_cut_plan(actor: Actor, body: PlanCreate, response: Response, idempotency_key: IdempotencyKeyHeader = None) -> PlanDetail:
    """Save a plan; ``CUT-YYYY-NNNN`` is allocated atomically and never reused. Settings snapshot from the company."""
    with UnitOfWork(actor) as uow:
        out, replayed = service.create_plan_command(uow, body)
    _replayed(response, replayed)
    return out


@router.get("/plans/{plan_id}", openapi_extra=requires("cutting.plan.read"))
def get_cut_plan(actor: Actor, plan_id: uuid.UUID) -> PlanDetail:
    """Reopen: inputs, settings snapshot and the stored latest calculation (never recomputed on read)."""
    with UnitOfWork(actor) as uow:
        return service.get_plan(uow, plan_id)


@router.patch("/plans/{plan_id}", openapi_extra=requires("cutting.plan.update"))
def update_cut_plan(
    actor: Actor, plan_id: uuid.UUID, body: PlanUpdate, response: Response, idempotency_key: IdempotencyKeyHeader = None
) -> PlanDetail:
    """Dirty fields plus ``expected_version`` (409 ``version_conflict`` when stale); changed inputs mark it stale."""
    with UnitOfWork(actor) as uow:
        out, replayed = service.update_plan_command(uow, plan_id, body)
    _replayed(response, replayed)
    return out


@router.post("/plans/{plan_id}/calculate", openapi_extra=requires("cutting.calculation.run", "cutting.plan.update"))
def calculate_cut_plan(
    actor: Actor, plan_id: uuid.UUID, body: PlanCommand, response: Response, idempotency_key: IdempotencyKeyHeader = None
) -> PlanDetail:
    """Calculate now (≤ 300 pieces) or queue the calculation job (≤ 5000); poll the plan for ``calculation.status``."""
    with UnitOfWork(actor) as uow:
        out, replayed = service.calculate_plan_command(uow, plan_id, body)
    _replayed(response, replayed)
    return out


@router.post("/plans/{plan_id}/duplicate", status_code=201, openapi_extra=requires("cutting.plan.create"))
def duplicate_cut_plan(actor: Actor, plan_id: uuid.UUID, response: Response, idempotency_key: IdempotencyKeyHeader = None) -> PlanDetail:
    """A new draft with the same inputs and settings (calculations are not copied)."""
    with UnitOfWork(actor) as uow:
        out, replayed = service.duplicate_plan_command(uow, plan_id)
    _replayed(response, replayed)
    return out


@router.post("/plans/{plan_id}/transitions", openapi_extra=requires("cutting.plan.transition"))
def transition_cut_plan(
    actor: Actor, plan_id: uuid.UUID, body: PlanTransition, response: Response, idempotency_key: IdempotencyKeyHeader = None
) -> PlanDetail:
    with UnitOfWork(actor) as uow:
        out, replayed = service.transition_plan_command(uow, plan_id, body)
    _replayed(response, replayed)
    return out


@router.get("/plans/{plan_id}/offcut-candidates", openapi_extra=requires("cutting.plan.read", "inventory.stock.read"))
def list_cut_plan_offcut_candidates(actor: Actor, plan_id: uuid.UUID) -> OffcutCandidates:
    """Measured offcut lots on hand (visible warehouses) the plan could cut from, with whether a group matches and
    which other plans chose them. Without ``inventory.stock.read`` the list is empty (``stock_visible: false``)."""
    with UnitOfWork(actor) as uow:
        return service.offcut_candidates(uow, plan_id)


@router.put("/plans/{plan_id}/offcuts", openapi_extra=requires("cutting.plan.update", "inventory.stock.read"))
def replace_cut_plan_offcuts(
    actor: Actor, plan_id: uuid.UUID, body: PlanOffcutsUpdate, response: Response,
    idempotency_key: IdempotencyKeyHeader = None,
) -> PlanDetail:
    """Replace the offcut lots the plan may cut from (filled in this order before standard sheets); every lot must
    be on hand with a measured size (422 ``offcut_not_available``). A changed selection marks a calculated plan stale."""
    with UnitOfWork(actor) as uow:
        out, replayed = service.replace_offcuts_command(uow, plan_id, body)
    _replayed(response, replayed)
    return out


@router.post("/plans/{plan_id}/verify-boards", openapi_extra=requires("cutting.plan.transition"))
def verify_cut_plan_boards(
    actor: Actor, plan_id: uuid.UUID, body: VerifyBoards, response: Response, idempotency_key: IdempotencyKeyHeader = None
) -> PlanDetail:
    """Record measured boards for a plan that assumed the +oversize board (``verify before release``)."""
    with UnitOfWork(actor) as uow:
        out, replayed = service.verify_boards_command(uow, plan_id, body)
    _replayed(response, replayed)
    return out


@router.get("/plans/{plan_id}/calculations/{calc_no}", openapi_extra=requires("cutting.plan.read"))
def get_cut_plan_calculation(actor: Actor, plan_id: uuid.UUID, calc_no: int) -> CalculationRead:
    with UnitOfWork(actor) as uow:
        return service.get_calculation(uow, plan_id, calc_no)


@router.get(
    "/plans/{plan_id}/export.csv",
    openapi_extra=requires("cutting.plan.export"),
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}}},
)
def export_cut_plan_csv(
    actor: Actor, plan_id: uuid.UUID, kind: Annotated[Literal["placements", "summary"], Query()] = "placements"
) -> Response:
    """Placements or per-SKU summary of the latest calculation (formula-escaped, UTF-8 BOM)."""
    with UnitOfWork(actor) as uow:
        body, filename = service.export_csv(uow, plan_id, kind)
    return _download(body, "text/csv; charset=utf-8", filename)


@router.get(
    "/plans/{plan_id}/export.pdf",
    openapi_extra=requires("cutting.plan.export"),
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
def export_cut_plan_pdf(actor: Actor, plan_id: uuid.UUID) -> Response:
    """Summary, pieces and one page per board (true-proportion drawing plus placement table)."""
    with UnitOfWork(actor) as uow:
        body, filename = service.export_pdf(uow, plan_id)
    return _download(body, "application/pdf", filename, inline=True)


@router.get(
    "/plans/{plan_id}/calculations/{calc_no}/boards/{index}.svg",
    openapi_extra=requires("cutting.plan.export"),
    response_class=Response,
    responses={200: {"content": {"image/svg+xml": {}}}},
)
def export_cut_plan_board_svg(actor: Actor, plan_id: uuid.UUID, calc_no: int, index: int) -> Response:
    """One board at true scale (viewBox in millimetres)."""
    with UnitOfWork(actor) as uow:
        body, filename = service.export_board_svg(uow, plan_id, calc_no, index)
    return _download(body, "image/svg+xml", filename, inline=True)
