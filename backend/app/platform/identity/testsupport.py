"""Test-support router (``/api/v1/_test/**``), mounted only when ``LK_ENV=test`` (conventions §13).

The identity manifest includes this router only in the test environment, and every handler re-checks the
environment, so the paths are 404 everywhere else (a contract test proves it). Sessions created here are
real sessions (``auth_method=test_support``) with real cookies; nothing here bypasses permissions.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.clock import FrozenClock, get_clock, set_company_clock, set_global_clock
from app.core.config import get_settings
from app.core.errors import NotFound, ValidationFailed
from app.core.http.authz_decl import test_support
from app.platform.identity import service
from app.platform.identity.http import client_info, set_session_cookies, set_ui_cookie
from app.platform.identity.schemas import SessionInfo

router = APIRouter(prefix="/_test", tags=["identity"])


def _guard() -> None:
    if not get_settings().is_test:
        raise NotFound(code="not_found")


class TestSignInRequest(BaseModel):
    __test__ = False  # not a pytest class
    model_config = ConfigDict(extra="forbid")

    user_key: str | None = Field(default=None, max_length=40)
    company_key: str | None = Field(default=None, max_length=40)
    company_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _one_way(self) -> TestSignInRequest:
        by_key = self.user_key is not None
        by_id = self.company_id is not None and self.user_id is not None
        if by_key == by_id:
            raise ValueError("send either user_key or company_id with user_id")
        return self


class ClockRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    at: datetime
    company_id: uuid.UUID | None = None


class ClockState(BaseModel):
    at: datetime
    scope: str


@router.post(
    "/sign-in",
    openapi_extra=test_support(),
    operation_id="identity_create_test_session",
    response_model=SessionInfo,
)
def sign_in(body: TestSignInRequest, request: Request) -> JSONResponse:
    _guard()
    if body.user_key is not None:
        from app.seed.world.keys import COMPANY_KEY, PEOPLE

        person = PEOPLE.get(body.user_key.upper())
        if person is None:
            raise NotFound(f"Unknown fixture user {body.user_key!r}", code="not_found")
        company_id, user_id = service.find_member_by_email(body.company_key or COMPANY_KEY, person.email)
    else:
        assert body.company_id is not None and body.user_id is not None  # noqa: S101 - validated above
        company_id, user_id = body.company_id, body.user_id
    signed = service.test_sign_in(company_id, user_id, client_info(request))
    response = JSONResponse(signed.info.model_dump(mode="json"))
    set_session_cookies(response, signed.issued)
    set_ui_cookie(response, signed.preferences.ui)
    return response


@router.get("/fixtures", openapi_extra=test_support(), operation_id="identity_get_test_fixtures")
def fixtures() -> dict[str, Any]:
    _guard()
    from app.seed.runner import last_world

    world = last_world()
    if world is None:
        raise NotFound("No world has been seeded in this environment", code="not_found")
    return world


@router.post("/clock", openapi_extra=test_support(), operation_id="identity_update_test_clock", response_model=ClockState)
def set_clock(body: ClockRequest) -> ClockState:
    _guard()
    if body.at.tzinfo is None:
        raise ValidationFailed("at must carry a time zone", code="validation_failed")
    if body.company_id is not None:
        current = get_clock(body.company_id)
        if isinstance(current, FrozenClock) and current is not get_clock(None):
            current.set(body.at)
        else:
            set_company_clock(body.company_id, FrozenClock(body.at))
        return ClockState(at=get_clock(body.company_id).now(), scope="company")
    current = get_clock(None)
    if isinstance(current, FrozenClock):
        current.set(body.at)
    else:
        set_global_clock(FrozenClock(body.at))
    return ClockState(at=get_clock(None).now(), scope="global")
