"""Message templates: sync from the provider (``GET /{waba_id}/message_templates``; the Demo provider lists fixture
templates), the ``message_template_status_update`` webhook, and the list for Settings › WhatsApp. Only
``approved`` templates may be sent; a paused, disabled, rejected or pending template blocks the outbox row with the
status as the reason (``window.template_check``)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from app.modules.channels import events as ev
from app.modules.channels.models import ChannelAccount, WaTemplate
from app.modules.channels.policies import ACCOUNT_MANAGE
from app.modules.channels.schemas import TemplateRead
from app.modules.channels.whatsapp import accounts
from app.modules.channels.whatsapp.payloads import TEMPLATE_EVENT_TO_STATUS, TemplateStatusValue
from app.modules.channels.whatsapp.provider import TemplateInfo, get_provider
from app.platform.authz.context import ActorContext
from app.platform.uow import UnitOfWork

KNOWN_STATUSES = frozenset({"approved", "pending", "rejected", "paused", "disabled"})


def _status(value: str) -> str:
    value = (value or "").lower()
    return value if value in KNOWN_STATUSES else "unknown"


def _set_status(uow: UnitOfWork, template: WaTemplate, status: str) -> None:
    if template.status == status:
        return
    template.status = status
    uow.flush()
    uow.emit(ev.TEMPLATE_STATUS_CHANGED, aggregate_id=template.id, payload={"template_id": str(template.id), "status": status})


def upsert(uow: UnitOfWork, account: ChannelAccount, info: TemplateInfo) -> WaTemplate:
    row = uow.session.scalars(
        select(WaTemplate).where(WaTemplate.account_id == account.id, WaTemplate.name == info.name, WaTemplate.language == info.language)
    ).first()
    now = uow.now()
    if row is None:
        row = WaTemplate(
            id=uuid.uuid7(), account_id=account.id, name=info.name[:120], language=info.language[:12], category=info.category[:30],
            status="unknown", provider_template_id=info.provider_template_id, components=list(info.components),
            param_schema={"body_params": sum(str(c.get("text", "")).count("{{") for c in info.components if c.get("type") == "BODY")},
        )
        uow.add(row)
        uow.flush()
    row.category = info.category[:30]
    row.components = list(info.components)
    row.provider_template_id = info.provider_template_id or row.provider_template_id
    row.synced_at = now
    _set_status(uow, row, _status(info.status))
    return row


def sync(uow: UnitOfWork) -> list[TemplateRead]:
    uow.actor.require(ACCOUNT_MANAGE)
    account = accounts.ensure_account(uow)
    for info in get_provider().list_templates(accounts.account_config(account)):
        upsert(uow, account, info)
    uow.audit("channels.templates.synced", resource_type="channels.account", resource_id=account.id)
    return list_templates(uow)


def list_templates(uow: UnitOfWork) -> list[TemplateRead]:
    uow.actor.require(ACCOUNT_MANAGE)
    account = accounts.ensure_account(uow)
    rows = uow.session.scalars(select(WaTemplate).where(WaTemplate.account_id == account.id).order_by(WaTemplate.name, WaTemplate.language))
    return [
        TemplateRead(id=r.id, name=r.name, language=r.language, category=r.category, status=r.status, synced_at=r.synced_at)  # type: ignore[arg-type]
        for r in rows
    ]


def find_sendable(uow: UnitOfWork, account: ChannelAccount, name: str, language: str = "en") -> WaTemplate | None:
    return uow.session.scalars(
        select(WaTemplate).where(WaTemplate.account_id == account.id, WaTemplate.name == name, WaTemplate.language == language)
    ).first()


def apply_status_update(uow: UnitOfWork, account: ChannelAccount, value: TemplateStatusValue) -> bool:
    """A ``message_template_status_update`` webhook; True when a known template changed."""
    row = uow.session.scalars(
        select(WaTemplate).where(
            WaTemplate.account_id == account.id,
            (WaTemplate.provider_template_id == str(value.message_template_id))
            | ((WaTemplate.name == value.message_template_name) & (WaTemplate.language == value.message_template_language)),
        ).with_for_update()
    ).first()
    if row is None:
        return False
    status = TEMPLATE_EVENT_TO_STATUS.get(value.event.upper(), "unknown")
    changed = row.status != status
    _set_status(uow, row, status)
    row.synced_at = uow.now()
    return changed


def sync_job(ctx: Any, payload: dict[str, Any]) -> dict[str, Any] | None:
    company_id = uuid.UUID(str(payload["company_id"]))
    with UnitOfWork(ActorContext.system(company_id, reason="channels.templates.sync")) as uow:
        return {"templates": len(sync(uow))}


__all__ = ["apply_status_update", "find_sendable", "list_templates", "sync", "sync_job", "upsert"]
