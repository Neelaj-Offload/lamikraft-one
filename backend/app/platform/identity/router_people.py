"""Identity API (Slice 2): delegation, leave and access requests (self-service plus approver routes)."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter

from app.core.http.authz_decl import authenticated, requires
from app.core.http.deps import Actor
from app.platform.identity import availability, delegation
from app.platform.identity.schemas import (
    AbsenceCreate,
    AbsenceDecision,
    AbsenceList,
    AbsenceView,
    AccessRequestCreate,
    AccessRequestDecision,
    AccessRequestList,
    AccessRequestView,
    DelegationCreate,
    DelegationList,
    DelegationView,
)

router = APIRouter(prefix="/identity", tags=["identity"])


# ---- delegation ------------------------------------------------------------------------------------------------
@router.get("/delegations", openapi_extra=authenticated(), operation_id="identity_list_delegations", response_model=DelegationList)
def list_delegations(actor: Actor, scope: Literal["mine", "all"] = "mine", include_past: bool = False) -> DelegationList:
    """Delegations you gave or received (``all`` needs identity.delegation.manage)."""
    return delegation.list_delegations(actor, scope=scope, include_past=include_past)


@router.post(
    "/delegations", status_code=201, openapi_extra=authenticated(), operation_id="identity_create_delegation", response_model=DelegationView
)
def create_delegation(body: DelegationCreate, actor: Actor) -> DelegationView:
    """Let a colleague act on your records for some delegable permissions they already hold (at most 90 days)."""
    return delegation.create_delegation(actor, body)


@router.post(
    "/delegations/{delegation_id}/cancel",
    openapi_extra=authenticated(),
    operation_id="identity_archive_delegation",
    response_model=DelegationView,
)
def cancel_delegation(delegation_id: uuid.UUID, actor: Actor) -> DelegationView:
    return delegation.cancel_delegation(actor, delegation_id)


# ---- leave -----------------------------------------------------------------------------------------------------
@router.get("/absences", openapi_extra=authenticated(), operation_id="identity_list_absences", response_model=AbsenceList)
def list_absences(actor: Actor, scope: Literal["mine", "team"] = "mine", include_past: bool = False) -> AbsenceList:
    """Your leave, or (``team``) the leave you approve: your reports', or everyone's with identity.absence.approve."""
    return availability.list_absences(actor, scope=scope, include_past=include_past)


@router.post("/absences", status_code=201, openapi_extra=authenticated(), operation_id="identity_create_absence", response_model=AbsenceView)
def request_absence(body: AbsenceCreate, actor: Actor) -> AbsenceView:
    return availability.request_absence(actor, body)


@router.post(
    "/absences/{absence_id}/decision", openapi_extra=authenticated(), operation_id="identity_decide_absence", response_model=AbsenceView
)
def decide_absence(absence_id: uuid.UUID, body: AbsenceDecision, actor: Actor) -> AbsenceView:
    """Approve or reject leave: the person's manager, or a holder of identity.absence.approve."""
    return availability.decide_absence(actor, absence_id, body)


@router.post(
    "/absences/{absence_id}/cancel", openapi_extra=authenticated(), operation_id="identity_archive_absence", response_model=AbsenceView
)
def cancel_absence(absence_id: uuid.UUID, actor: Actor) -> AbsenceView:
    return availability.cancel_absence(actor, absence_id)


# ---- access requests -------------------------------------------------------------------------------------------
@router.get(
    "/access-requests", openapi_extra=authenticated(), operation_id="identity_list_access_requests", response_model=AccessRequestList
)
def list_access_requests(
    actor: Actor,
    scope: Literal["mine", "all"] = "mine",
    status: Literal["pending", "approved", "rejected", "withdrawn"] | None = None,
) -> AccessRequestList:
    return availability.list_access_requests(actor, scope=scope, status=status)


@router.post(
    "/access-requests",
    status_code=201,
    openapi_extra=authenticated(),
    operation_id="identity_create_access_request",
    response_model=AccessRequestView,
)
def submit_access_request(body: AccessRequestCreate, actor: Actor) -> AccessRequestView:
    """Ask for a permission (with a reason and a duration); an approver grants it as an expiring personal grant."""
    return availability.submit_access_request(actor, body)


@router.post(
    "/access-requests/{request_id}/decision",
    openapi_extra=requires("identity.access_request.approve"),
    operation_id="identity_decide_access_request",
    response_model=AccessRequestView,
    responses={401: {"description": "mfa_required or reauth_required"}},
)
def decide_access_request(request_id: uuid.UUID, body: AccessRequestDecision, actor: Actor) -> AccessRequestView:
    return availability.decide_access_request(actor, request_id, body)


@router.post(
    "/access-requests/{request_id}/withdrawal",
    openapi_extra=authenticated(),
    operation_id="identity_archive_access_request",
    response_model=AccessRequestView,
)
def withdraw_access_request(request_id: uuid.UUID, actor: Actor) -> AccessRequestView:
    return availability.withdraw_access_request(actor, request_id)
