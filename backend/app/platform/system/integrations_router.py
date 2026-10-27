"""Integration status API (administrators). Every member sees the modes through the session bootstrap
section ``integrations``; this endpoint adds verification times, error codes and details."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.http.authz_decl import requires
from app.core.http.deps import Actor
from app.platform.system import service
from app.platform.system.schemas import IntegrationRead

router = APIRouter(prefix="/system", tags=["system"])


@router.get(
    "/integrations",
    openapi_extra=requires("system.integration.read"),
    operation_id="system_list_integrations",
    summary="Mode (demo or live) and verified state of every integration",
)
def list_integrations(actor: Actor) -> list[IntegrationRead]:
    return service.list_integrations(actor)
