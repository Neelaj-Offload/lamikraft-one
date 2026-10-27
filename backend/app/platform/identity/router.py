"""Identity API (api-conventions §7.1): sign-in, sign-out, demo sign-in, own profile and preferences."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Path, Request, Response
from fastapi.responses import JSONResponse

from app.core.errors import Unauthenticated
from app.core.http.authz_decl import authenticated, public, requires
from app.core.http.deps import Actor, get_actor
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
    PasswordChangeRequest,
    PermissionOverrideList,
    PermissionOverridePut,
    PermissionOverrideView,
    PreferencesUpdated,
    SessionInfo,
)
from app.platform.identity.startup import lifespan

#: the lifespan syncs the permission catalogue and system role templates when the API starts (platform.md §5)
router = APIRouter(prefix="/identity", tags=["identity"], lifespan=lifespan)

PermissionKey = Annotated[str, Path(min_length=5, max_length=120, pattern=r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")]

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
def delete_session(request: Request) -> Response:
    """Revoke the current session and clear the cookies. A signed-out, expired or revoked session still gets its
    cookies cleared (with the 401), so a stale cookie never traps the browser."""
    try:
        actor = get_actor(request)
    except Unauthenticated as exc:
        response: Response = problem_response(request, exc)
        clear_session_cookies(response)
        return response
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


@router.post(
    "/me/password",
    openapi_extra=authenticated(),
    operation_id="identity_update_password",
    response_model=SessionInfo,
    responses={
        422: {"description": "Current password not correct, or the new one breaks the policy (problem+json)"},
        429: {"description": "rate_limited (problem+json, Retry-After header)"},
    },
)
def change_password(body: PasswordChangeRequest, actor: Actor, request: Request) -> Response:
    """Change your own password: the session rotates (new cookies and CSRF) and your other sessions end."""
    try:
        signed = service.change_password(actor, body.current_password, body.new_password, client_info(request))
    except TooManyAttempts as exc:
        return problem_response(request, exc, {"Retry-After": str(exc.retry_after_seconds)})
    return _signed_in(signed)


@router.get(
    "/users/{user_id}/permission-overrides",
    openapi_extra=requires("identity.user.read", "identity.permission.manage"),
    operation_id="identity_list_permission_overrides",
    response_model=PermissionOverrideList,
)
def list_permission_overrides(user_id: uuid.UUID, actor: Actor) -> PermissionOverrideList:
    """A member's open per-user overrides (either key at company scope)."""
    return service.list_permission_overrides(actor, user_id)


@router.put(
    "/users/{user_id}/permission-overrides/{permission_key}",
    openapi_extra=requires("identity.permission.manage"),
    operation_id="identity_set_permission_override",
    response_model=PermissionOverrideView,
    responses={401: {"description": "reauth_required: sign in with the password again (recent authentication)"}},
)
def set_permission_override(
    user_id: uuid.UUID, permission_key: PermissionKey, body: PermissionOverridePut, actor: Actor
) -> PermissionOverrideView:
    """Grant (with a scope) or revoke one permission for a member, with a reason and an optional expiry."""
    return service.put_permission_override(actor, user_id, permission_key, body)


@router.delete(
    "/users/{user_id}/permission-overrides/{permission_key}",
    openapi_extra=requires("identity.permission.manage"),
    operation_id="identity_delete_permission_override",
    status_code=204,
    response_class=Response,
)
def delete_permission_override(user_id: uuid.UUID, permission_key: PermissionKey, actor: Actor) -> Response:
    """Archive a member's open override for one permission (the role grants apply again)."""
    service.delete_permission_override(actor, user_id, permission_key)
    return Response(status_code=204)
