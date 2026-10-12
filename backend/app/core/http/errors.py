"""Exception handlers producing application/problem+json."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.errors import AppError
from app.core.logging import get_logger

log = get_logger("lk.http")
PROBLEM = "application/problem+json"


def _rid(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        if exc.status >= 500:
            log.error("app_error", code=exc.code, path=request.url.path)
        return JSONResponse(exc.to_problem(_rid(request)), status_code=exc.status, media_type=PROBLEM)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors: list[dict[str, Any]] = []
        for err in exc.errors():
            errors.append({"loc": [str(p) for p in err.get("loc", [])], "msg": err.get("msg"), "type": err.get("type")})
        body = {
            "type": "https://lamikraft.one/problems/validation_failed",
            "title": "Some values are not valid",
            "status": 422,
            "code": "validation_failed",
            "detail": "Check the highlighted fields.",
            "errors": errors,
            "request_id": _rid(request),
        }
        return JSONResponse(body, status_code=422, media_type=PROBLEM)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed", 401: "unauthenticated", 403: "forbidden"}.get(
            exc.status_code, "http_error"
        )
        body = {
            "type": f"https://lamikraft.one/problems/{code}",
            "title": str(exc.detail),
            "status": exc.status_code,
            "code": code,
            "detail": str(exc.detail),
            "request_id": _rid(request),
        }
        return JSONResponse(body, status_code=exc.status_code, media_type=PROBLEM)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled_error", path=request.url.path, error_type=type(exc).__name__)
        body = {
            "type": "https://lamikraft.one/problems/internal_error",
            "title": "Something went wrong on our side",
            "status": 500,
            "code": "internal_error",
            "detail": "The error was recorded. Your last change may not have been saved; please retry.",
            "request_id": _rid(request),
        }
        return JSONResponse(body, status_code=500, media_type=PROBLEM)
