"""Org API: settings, currencies, units of measure and the actor's work calendar."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Path, Query

from app.core.http.authz_decl import authenticated, requires
from app.core.http.deps import Actor, IdempotencyKeyHeader
from app.platform.org import calendar_service, reference, service
from app.platform.org.schemas import (
    CurrencyRead,
    MyCalendar,
    SettingRead,
    SettingRevisionRead,
    SettingUpdate,
    UomRead,
)

SETTING_KEY = r"^[a-z][a-z0-9_]{1,63}$"


def build_router() -> APIRouter:
    """Built at app start so the route declarations list every registered setting's permission keys."""
    defs = service.setting_defs().values()
    read_keys = sorted({"org.settings.read", *(d.read_permission for d in defs)})
    manage_keys = sorted({d.manage_permission for d in defs})
    router = APIRouter(prefix="/org", tags=["org"])

    @router.get(
        "/settings",
        openapi_extra=requires(*read_keys),
        operation_id="org_list_settings",
        summary="Settings the actor may read, with defaults for values never written",
    )
    def list_settings(actor: Actor, branch_id: uuid.UUID | None = None) -> list[SettingRead]:
        return service.list_settings(actor, branch_id=branch_id)

    @router.get("/settings/{key}", openapi_extra=requires(*read_keys), operation_id="org_get_setting")
    def get_setting(
        actor: Actor, key: str = Path(pattern=SETTING_KEY), branch_id: uuid.UUID | None = None
    ) -> SettingRead:
        return service.get_setting(actor, key, branch_id=branch_id)

    @router.put(
        "/settings/{key}",
        openapi_extra=requires(*manage_keys),
        operation_id="org_update_setting",
        summary="Replace a setting value (optimistic version; 409 carries the current value)",
    )
    def update_setting(
        body: SettingUpdate,
        actor: Actor,
        key: str = Path(pattern=SETTING_KEY),
        idempotency_key: IdempotencyKeyHeader = None,  # optional; read by the actor dependency
    ) -> SettingRead:
        return service.update_setting(
            actor,
            key,
            value=body.value,
            expected_version=body.expected_version,
            branch_id=body.branch_id,
            change_reason=body.change_reason,
        )

    @router.get(
        "/settings/{key}/revisions", openapi_extra=requires(*read_keys), operation_id="org_list_setting_revisions"
    )
    def list_setting_revisions(
        actor: Actor,
        key: str = Path(pattern=SETTING_KEY),
        branch_id: uuid.UUID | None = None,
        limit: int = Query(default=50, ge=1, le=200),
    ) -> list[SettingRevisionRead]:
        return service.list_setting_revisions(actor, key, branch_id=branch_id, limit=limit)

    @router.get("/currencies", openapi_extra=authenticated(), operation_id="org_list_currencies")
    def list_currencies(actor: Actor) -> list[CurrencyRead]:
        return reference.list_currencies(actor)

    @router.get("/uoms", openapi_extra=authenticated(), operation_id="org_list_uoms")
    def list_uoms(actor: Actor) -> list[UomRead]:
        return reference.list_uoms(actor)

    @router.get("/calendar/me", openapi_extra=requires("org.calendar.read"), operation_id="org_get_my_calendar")
    def get_my_calendar(actor: Actor) -> MyCalendar:
        return calendar_service.my_calendar(actor)

    return router
