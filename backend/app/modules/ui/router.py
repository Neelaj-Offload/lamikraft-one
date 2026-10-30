"""``GET /api/v1/session/bootstrap`` (documented path exception), ``GET /api/v1/ui/poll`` (ETag/304) and
``POST /api/v1/ui/recent-records`` (remember an opened detail record)."""

from __future__ import annotations

from fastapi import APIRouter, Header, Response
from fastapi.responses import JSONResponse

from app.core.http.authz_decl import authenticated
from app.core.http.deps import Actor
from app.platform.identity.http import set_csrf_cookie

from . import recents, service
from .schemas import RecentRecordCreate, RecentRecordRead, SessionBootstrap, UiPoll

router = APIRouter(tags=["ui"])


@router.get(
    "/session/bootstrap",
    openapi_extra=authenticated(),
    operation_id="ui_get_session_bootstrap",
    response_model=SessionBootstrap,
    responses={401: {"description": "Signed out (problem+json); the client redirects to /login"}},
)
def session_bootstrap(actor: Actor, response: Response) -> SessionBootstrap:
    payload = service.bootstrap(actor)
    max_age = None
    if payload.session is not None:
        max_age = max(0, int((payload.session.absolute_expires_at - payload.server_now).total_seconds()))
    set_csrf_cookie(response, payload.csrf_token, max_age=max_age)
    return payload


@router.get(
    "/ui/poll",
    openapi_extra=authenticated(),
    operation_id="ui_poll_sections",
    response_model=UiPoll,
    responses={304: {"description": "Not modified since the ETag in If-None-Match"}},
)
def ui_poll(actor: Actor, if_none_match: str | None = Header(default=None, alias="If-None-Match")) -> Response:
    body = service.poll(actor).model_dump(mode="json")
    etag = service.etag_of(body)
    if service.etag_matches(if_none_match, etag):
        return Response(status_code=304, headers={"ETag": etag})
    return JSONResponse(body, headers={"ETag": etag})


@router.post(
    "/ui/recent-records",
    status_code=201,
    openapi_extra=authenticated(),
    operation_id="ui_create_recent_record",
    response_model=RecentRecordRead,
    summary="Remember a detail record the user opened (newest 20 kept per user; invisible records are 404)",
)
def create_recent_record(body: RecentRecordCreate, actor: Actor) -> RecentRecordRead:
    return recents.record_recent_record(actor, body)
