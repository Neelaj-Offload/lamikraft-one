"""Identity API, Slice 2: two-step sign-in, step-up, enrolment, invitations, password resets and sessions.

Link tokens are only ever read from JSON bodies (the pages take them from the URL fragment). Public endpoints are
rate-limited per address; problem codes: ``invalid_code``, ``link_invalid_or_used``, ``mfa_verification_required``,
``mfa_enrollment_required``, ``mfa_required`` and ``reauth_required`` (step-up), ``rate_limited``.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse

from app.core.http.authz_decl import authenticated, public, requires
from app.core.http.deps import Actor
from app.platform.authz.context import ActorContext
from app.platform.identity import account, credentials, mfa_service
from app.platform.identity.errors import TooManyAttempts
from app.platform.identity.http import (
    client_info,
    problem_response,
    resolve_enrolling_actor,
    set_session_cookies,
    set_ui_cookie,
)
from app.platform.identity.schemas import (
    InvitationAccept,
    InvitationCreate,
    InvitationIssued,
    InvitationPreview,
    InvitationView,
    MfaCodeRequest,
    MfaConfirmed,
    MfaEnrollment,
    MfaStatus,
    PasswordResetComplete,
    PasswordResetIssued,
    PasswordResetRequestBody,
    ReasonBody,
    ReauthRequest,
    ReauthResult,
    RecoveryCodes,
    RevokedCount,
    SessionInfo,
    SessionList,
    TokenBody,
)

router = APIRouter(prefix="/identity", tags=["identity"])

EnrollingActor = Annotated[ActorContext, Depends(resolve_enrolling_actor)]

_LIMITED = {429: {"description": "rate_limited (problem+json, Retry-After header)"}}


def _signed_in(signed) -> JSONResponse:  # type: ignore[no-untyped-def]  # service.SignedIn
    response = JSONResponse(signed.info.model_dump(mode="json"))
    set_session_cookies(response, signed.issued)
    set_ui_cookie(response, signed.preferences.ui)
    return response


def _limited(request: Request, exc: TooManyAttempts) -> Response:
    return problem_response(request, exc, {"Retry-After": str(exc.retry_after_seconds)})


# ---- two-step sign-in and step-up ------------------------------------------------------------------------------
@router.post(
    "/session/verification",
    openapi_extra=public("second sign-in step; the pending session cookie identifies the person"),
    operation_id="identity_create_session_verification",
    response_model=SessionInfo,
    responses={401: {"description": "invalid_code, or session_expired after five wrong codes"}},
)
def verify_session(body: MfaCodeRequest, request: Request) -> Response:
    """Finish a two-step sign-in with an authenticator code or an unused recovery code (the session rotates)."""
    return _signed_in(mfa_service.verify_sign_in_code(body.code, client_info(request)))


@router.post(
    "/session/reauthentication",
    openapi_extra=authenticated(),
    operation_id="identity_create_session_reauthentication",
    response_model=ReauthResult,
    responses=_LIMITED,
)
def reauthenticate(body: ReauthRequest, actor: Actor, request: Request) -> ReauthResult | Response:
    """Confirm it is you before a sensitive change: the password (recent authentication) or a code (also MFA)."""
    try:
        return mfa_service.reauth(actor, password=body.password, code=body.code, client=client_info(request))
    except TooManyAttempts as exc:
        return _limited(request, exc)


# ---- own authenticator -------------------------------------------------------------------------------------------
@router.get("/me/mfa", openapi_extra=authenticated(), operation_id="identity_get_my_mfa", response_model=MfaStatus)
def get_my_mfa(actor: EnrollingActor) -> MfaStatus:
    return mfa_service.status(actor)


@router.post("/me/mfa/totp", openapi_extra=authenticated(), operation_id="identity_create_my_totp", response_model=MfaEnrollment)
def start_totp(actor: EnrollingActor) -> MfaEnrollment:
    """Start setting up an authenticator app (QR code and secret, shown once; confirm with a code next)."""
    return mfa_service.enroll(actor)


@router.post(
    "/me/mfa/totp/confirmation",
    openapi_extra=authenticated(),
    operation_id="identity_create_my_totp_confirmation",
    response_model=MfaConfirmed,
)
def confirm_totp(body: MfaCodeRequest, actor: EnrollingActor, request: Request) -> Response:
    """Confirm the new authenticator with its first code: returns ten recovery codes (shown once); the session
    becomes MFA-verified and rotates."""
    done = mfa_service.confirm(actor, body.code, client_info(request))
    signed = done.signed
    payload = done.result.model_copy(update={"session": signed.info if signed is not None else None})  # type: ignore[attr-defined]
    response = JSONResponse(payload.model_dump(mode="json"))
    if signed is not None:
        set_session_cookies(response, signed.issued)  # type: ignore[attr-defined]
    return response


@router.delete("/me/mfa/totp", openapi_extra=authenticated(), operation_id="identity_delete_my_totp", response_model=MfaStatus)
def remove_totp(body: MfaCodeRequest, actor: Actor) -> MfaStatus:
    """Remove your authenticator (a current code is required; refused while your role requires two-step sign-in)."""
    return mfa_service.disable_own(actor, body.code)


@router.post(
    "/me/mfa/recovery-codes",
    openapi_extra=authenticated(),
    operation_id="identity_create_my_recovery_codes",
    response_model=RecoveryCodes,
)
def regenerate_recovery_codes(body: MfaCodeRequest, actor: Actor) -> RecoveryCodes:
    return mfa_service.regenerate_codes(actor, body.code)


@router.delete(
    "/users/{user_id}/mfa",
    openapi_extra=requires("identity.mfa.manage"),
    operation_id="identity_delete_user_mfa",
    status_code=204,
    response_class=Response,
)
def reset_member_mfa(user_id: uuid.UUID, body: ReasonBody, actor: Actor) -> Response:
    """Remove another member's authenticator (lost phone); their sessions end and they enrol again."""
    mfa_service.admin_reset(actor, user_id, body.reason)
    return Response(status_code=204)


# ---- sessions --------------------------------------------------------------------------------------------------
@router.get("/me/sessions", openapi_extra=authenticated(), operation_id="identity_list_my_sessions", response_model=SessionList)
def list_my_sessions(actor: Actor) -> SessionList:
    return account.my_sessions(actor)


@router.delete(
    "/me/sessions/{session_id}",
    openapi_extra=authenticated(),
    operation_id="identity_delete_my_session",
    status_code=204,
    response_class=Response,
)
def end_my_session(session_id: uuid.UUID, actor: Actor) -> Response:
    account.end_my_session(actor, session_id)
    return Response(status_code=204)


@router.delete("/me/sessions", openapi_extra=authenticated(), operation_id="identity_delete_my_other_sessions", response_model=RevokedCount)
def end_my_other_sessions(actor: Actor) -> RevokedCount:
    """Sign out everywhere else (this session stays)."""
    return account.end_my_other_sessions(actor)


@router.get(
    "/users/{user_id}/sessions",
    openapi_extra=requires("identity.session.manage"),
    operation_id="identity_list_user_sessions",
    response_model=SessionList,
)
def list_member_sessions(user_id: uuid.UUID, actor: Actor) -> SessionList:
    return account.member_sessions(actor, user_id)


@router.delete(
    "/users/{user_id}/sessions",
    openapi_extra=requires("identity.session.manage"),
    operation_id="identity_delete_user_sessions",
    response_model=RevokedCount,
)
def end_member_sessions(user_id: uuid.UUID, actor: Actor) -> RevokedCount:
    return account.end_member_sessions(actor, user_id)


# ---- invitations -----------------------------------------------------------------------------------------------
@router.post(
    "/invitations",
    status_code=201,
    openapi_extra=requires("identity.user.manage"),
    operation_id="identity_create_invitation",
    response_model=InvitationIssued,
)
def invite(body: InvitationCreate, actor: Actor) -> InvitationIssued:
    """Invite a person with roles and branches; the 7-day link goes by email (demo mode: shown once here)."""
    return credentials.invite(actor, body)


@router.post(
    "/invitations/{invitation_id}/reissue",
    openapi_extra=requires("identity.user.manage"),
    operation_id="identity_issue_invitation",
    response_model=InvitationIssued,
)
def resend_invitation(invitation_id: uuid.UUID, actor: Actor) -> InvitationIssued:
    """Send a fresh link (the previous one stops working) and restart the 7 days."""
    return credentials.resend_invitation(actor, invitation_id)


@router.delete(
    "/invitations/{invitation_id}",
    openapi_extra=requires("identity.user.manage"),
    operation_id="identity_delete_invitation",
    response_model=InvitationView,
)
def revoke_invitation(invitation_id: uuid.UUID, actor: Actor) -> InvitationView:
    return credentials.revoke_invitation(actor, invitation_id)


@router.post(
    "/invitations/preview",
    openapi_extra=public("invitation page: shows who is invited where (token from the URL fragment)"),
    operation_id="identity_resolve_invitation",
    response_model=InvitationPreview,
    responses={401: {"description": "link_invalid_or_used"}, **_LIMITED},
)
def preview_invitation(body: TokenBody, request: Request) -> InvitationPreview | Response:
    try:
        return credentials.preview_invitation(body.token, client_info(request))
    except TooManyAttempts as exc:
        return _limited(request, exc)


@router.post(
    "/invitations/acceptance",
    openapi_extra=public("accept an invitation: choose a password and sign in (token from the URL fragment)"),
    operation_id="identity_create_invitation_acceptance",
    response_model=SessionInfo,
    responses={401: {"description": "link_invalid_or_used"}, **_LIMITED},
)
def accept_invitation(body: InvitationAccept, request: Request) -> Response:
    try:
        signed = credentials.accept_invitation(body.token, body.password, body.display_name, client_info(request))
    except TooManyAttempts as exc:
        return _limited(request, exc)
    return _signed_in(signed)


# ---- password resets -------------------------------------------------------------------------------------------
@router.post(
    "/password-resets",
    status_code=202,
    openapi_extra=public("forgot password: always accepted, a link is sent only to a real member"),
    operation_id="identity_create_password_reset",
    response_class=Response,
    responses=_LIMITED,
)
def request_password_reset(body: PasswordResetRequestBody, request: Request) -> Response:
    try:
        credentials.request_reset(body.email, client_info(request))
    except TooManyAttempts as exc:
        return _limited(request, exc)
    return Response(status_code=202)


@router.post(
    "/password-resets/completion",
    status_code=204,
    openapi_extra=public("choose a new password with a reset link (token from the URL fragment)"),
    operation_id="identity_create_password_reset_completion",
    response_class=Response,
    responses={401: {"description": "link_invalid_or_used"}, **_LIMITED},
)
def complete_password_reset(body: PasswordResetComplete, request: Request) -> Response:
    """Set the new password; every session ends (sign in again) and the authenticator is kept."""
    try:
        credentials.complete_reset(body.token, body.password, client_info(request))
    except TooManyAttempts as exc:
        return _limited(request, exc)
    return Response(status_code=204)


@router.post(
    "/users/{user_id}/password-reset",
    status_code=201,
    openapi_extra=requires("identity.user.manage"),
    operation_id="identity_issue_password_reset",
    response_model=PasswordResetIssued,
)
def issue_password_reset(user_id: uuid.UUID, actor: Actor) -> PasswordResetIssued:
    """A one-time reset link for a member (24 h). Never a temporary password."""
    return credentials.issue_reset(actor, user_id)
