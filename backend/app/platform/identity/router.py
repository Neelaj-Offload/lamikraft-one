"""Identity API (api-conventions §7.1): sign-in, sign-out, demo sign-in, own profile and preferences."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from app.core.http.authz_decl import authenticated, public
from app.core.http.deps import Actor
from app.platform.identity import service
from app.platform.identity.errors import TooManyAttempts
from app.platform.identity.http import (
    clear_session_cookies,
    client_info,
    problem_response,
    set_session_cookies,
    set_ui_cookie,
)
from app.platform.identity.preferences import PreferencesPatch
from app.platform.identity.schemas import (
    DemoSignInRequest,
    LoginRequest,
    MeRead,
    PreferencesUpdated,
    SessionInfo,
)

router = APIRouter(prefix="/identity", tags=["identity"])

_AUTH_RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"description": "Generic sign-in failure (problem+json)"},
    429: {"description": "rate_limited or account_locked (problem+json, Retry-After header)"},
}


def _signed_in(signed: service.SignedIn) -> JSONResponse:
    response = JSONResponse(signed.info.model_dump(mode="json"))
    set_session_cookies(response, signed.issued)
    set_ui_cookie(response, signed.preferences.ui)
    return response


@router.post(
    "/session",
    openapi_extra=public("sign-in; Origin and Sec-Fetch-Site checked, rate-limited"),
    operation_id="identity_create_session",
    response_model=SessionInfo,
    responses=_AUTH_RESPONSES,
)
def create_session(body: LoginRequest, request: Request) -> Response:
    try:
        signed = service.login(body.email, body.password, client_info(request))
    except TooManyAttempts as exc:
        return problem_response(request, exc, {"Retry-After": str(exc.retry_after_seconds)})
    return _signed_in(signed)


@router.delete(
    "/session",
    openapi_extra=authenticated(),
    operation_id="identity_delete_session",
    status_code=204,
    response_class=Response,
)
def delete_session(actor: Actor) -> Response:
    service.logout(actor)
    response = Response(status_code=204)
    clear_session_cookies(response)
    return response


@router.post(
    "/demo-sign-in",
    openapi_extra=public("one-time demo sign-in link (demo companies only)"),
    operation_id="identity_create_demo_session",
    response_model=SessionInfo,
    responses=_AUTH_RESPONSES,
)
def demo_sign_in(body: DemoSignInRequest, request: Request) -> Response:
    try:
        signed = service.demo_sign_in(body.token, client_info(request))
    except TooManyAttempts as exc:
        return problem_response(request, exc, {"Retry-After": str(exc.retry_after_seconds)})
    return _signed_in(signed)


@router.get("/me", openapi_extra=authenticated(), operation_id="identity_get_me", response_model=MeRead)
def get_me(actor: Actor) -> MeRead:
    return service.get_me(actor)


@router.patch(
    "/me/preferences",
    openapi_extra=authenticated(),
    operation_id="identity_update_preferences",
    response_model=PreferencesUpdated,
)
def update_preferences(body: PreferencesPatch, actor: Actor, response: Response) -> PreferencesUpdated:
    result = service.update_preferences(actor, body)
    set_ui_cookie(response, result.preferences.ui)
    return result
