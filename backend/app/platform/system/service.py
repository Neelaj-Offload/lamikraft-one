"""Integration status: the effective state of every registered integration for the actor's company.

Effective state = the stored verification result when it was recorded for the currently configured mode,
otherwise ``not_connected``; live mode with a missing secret is ``error`` / ``secret_missing``. Only
``record_verification`` (called by ``run_verification`` with the adapter's routine) writes rows, and only
it can produce ``connected``; state changes emit ``system.integration.status_changed``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from app.core.config import get_settings
from app.core.errors import NotConfigured, NotFound
from app.platform.service import command, query
from app.platform.system.integrations import (
    IntegrationDef,
    VerificationResult,
    integration_def,
    integration_defs,
)
from app.platform.system.models import IntegrationMode, IntegrationState, IntegrationStatus
from app.platform.system.schemas import IntegrationRead

if TYPE_CHECKING:
    from app.platform.uow import UnitOfWork

_LABELS = {
    IntegrationState.CONNECTED: "Connected",
    IntegrationState.NOT_CONNECTED: "Not connected",
    IntegrationState.ERROR: "Error",
}


def _rows(uow: UnitOfWork) -> dict[str, IntegrationStatus]:
    if uow.actor.company_id is None:
        return {}
    rows = uow.session.scalars(select(IntegrationStatus).where(IntegrationStatus.company_id == uow.actor.company_id))
    return {r.integration_key: r for r in rows}


def _effective(definition: IntegrationDef, row: IntegrationStatus | None) -> IntegrationRead:
    settings = get_settings()
    mode = definition.configured_mode(settings)
    missing = definition.missing_secrets(settings) if mode == IntegrationMode.LIVE else []
    state = IntegrationState.NOT_CONNECTED
    error_code: str | None = None
    verified_at = last_checked_at = None
    details: dict[str, Any] | None = None
    if row is not None and row.mode == mode.value:
        state = IntegrationState(row.state)
        error_code = row.last_error_code
        verified_at, last_checked_at, details = row.verified_at, row.last_checked_at, row.details
    if missing:
        state, error_code = IntegrationState.ERROR, "secret_missing"
        details = {"missing": missing}
    label_text = "Demo" if mode == IntegrationMode.DEMO else _LABELS[state]
    return IntegrationRead(
        key=definition.key,
        label=definition.label,
        mode=mode.value,  # type: ignore[arg-type]
        state=state.value,  # type: ignore[arg-type]
        label_text=label_text,
        verified_at=verified_at,
        last_checked_at=last_checked_at,
        last_error_code=error_code,
        details=details,
    )


def effective_statuses(uow: UnitOfWork) -> list[IntegrationRead]:
    rows = _rows(uow)
    return [_effective(d, rows.get(d.key)) for d in integration_defs()]


@query("system.integration.read")
def list_integrations(uow: UnitOfWork) -> list[IntegrationRead]:
    return effective_statuses(uow)


def ui_section(uow: UnitOfWork) -> dict[str, Any]:
    """Session bootstrap section ``integrations``: modes and states for Demo / Not connected labels only."""
    return {
        "integrations": [
            {"key": s.key, "label": s.label, "mode": s.mode, "state": s.state, "label_text": s.label_text}
            for s in effective_statuses(uow)
        ]
    }


@command("system.integration.manage")
def record_verification(uow: UnitOfWork, key: str, result: VerificationResult) -> IntegrationRead:
    """Persist the outcome of a verification routine for the configured mode (the only way to 'connected')."""
    definition = integration_def(key)
    if definition is None:
        raise NotFound(code="not_found", resource_type="system.integration")
    mode = definition.configured_mode(get_settings())
    previous = _effective(definition, _rows(uow).get(key))
    row = uow.session.scalars(
        select(IntegrationStatus)
        .where(IntegrationStatus.company_id == uow.actor.company_id, IntegrationStatus.integration_key == key)
        .with_for_update()
    ).first()
    now = uow.now()
    state = IntegrationState.CONNECTED if result.ok else IntegrationState.ERROR
    if row is None:
        row = uow.add(
            IntegrationStatus(
                company_id=uow.actor.company_id,
                integration_key=key,
                mode=mode.value,
                state=state.value,
            )
        )
    row.mode = mode.value
    row.state = state.value
    row.last_checked_at = now
    row.verified_at = now if result.ok else None
    row.last_error_code = None if result.ok else (result.error_code or "verification_failed")
    row.details = dict(result.details) or None
    uow.flush()
    current = _effective(definition, row)
    if current.state != previous.state:
        uow.emit(
            "system.integration.status_changed",
            aggregate_id=row.id,
            aggregate_version=row.version,
            payload={"integration_key": key, "mode": mode.value, "state_from": previous.state, "state_to": current.state},
        )
    uow.audit(
        "system.integration.verified",
        resource_type="system.integration",
        resource_id=row.id,
        resource_label=key,
        outcome="success" if result.ok else "failed",
        details={"mode": mode.value, "state": current.state, "error_code": row.last_error_code},
    )
    return current


@command("system.integration.manage")
def run_verification(uow: UnitOfWork, key: str) -> IntegrationRead:
    definition = integration_def(key)
    if definition is None:
        raise NotFound(code="not_found", resource_type="system.integration")
    if definition.verify is None:
        raise NotConfigured(f"{definition.label} has no verification routine yet.", code="not_configured")
    return record_verification(uow, key, definition.verify(uow))
