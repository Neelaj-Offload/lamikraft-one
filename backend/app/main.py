"""FastAPI application factory. Run: ``uv run uvicorn app.main:app --host 127.0.0.1``."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.routing import APIRoute

from app.core.config import get_settings
from app.core.http.authz_decl import validate_routes, webhook_paths
from app.core.http.errors import install_error_handlers
from app.core.http.middleware import CsrfOriginMiddleware, RequestContextMiddleware
from app.core.logging import configure_logging
from app.registry import get_registry

API_PREFIX = "/api/v1"


def _operation_id(route: APIRoute) -> str:
    tag = route.tags[0] if route.tags else "api"
    return f"{tag}_{route.name}"


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    registry = get_registry()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> Any:
        yield

    app = FastAPI(
        title="Lamikraft One API",
        version="0.1.0",
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=None if settings.is_production else f"{API_PREFIX}/docs",
        redoc_url=None,
        separate_input_output_schemas=False,
        generate_unique_id_function=_operation_id,
        lifespan=lifespan,
    )
    install_error_handlers(app)
    for router in registry.routers():
        app.include_router(router, prefix=API_PREFIX)

    exempt = webhook_paths(app)
    app.add_middleware(CsrfOriginMiddleware, public_origin=settings.public_origin, exempt_paths=lambda: exempt)
    app.add_middleware(RequestContextMiddleware)
    validate_routes(app, set(registry.permissions))
    return app


app = create_app()
