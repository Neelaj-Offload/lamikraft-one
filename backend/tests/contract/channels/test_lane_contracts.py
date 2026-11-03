"""Channels lane contracts: route authz kinds and operationIds, events emitted are catalogued with the catalogued
payload fields, the agent tool input carries no identity fields, CHECKs mirror the enums, RLS is forced on every
tenant table (and the webhook inbox/rejection tables are the only exempt ones), append-only triggers exist, the
jobs and the approval handler are registered, and no business code reads the wall clock."""

from __future__ import annotations

import ast
import re
from enum import StrEnum
from pathlib import Path

import pytest
from pydantic import BaseModel
from sqlalchemy import text

from app.core.config import BACKEND_DIR
from app.core.http.authz_decl import route_kind
from app.modules.channels import events, models, schemas
from app.modules.channels.tools import PrepareQuoteSendInput
from app.platform.authz.context import ActorContext
from app.platform.tools import FORBIDDEN_INPUT_FIELDS
from app.platform.uow import UnitOfWork
from app.registry import get_registry

CHANNELS_DIR = BACKEND_DIR / "app" / "modules" / "channels"
EXPECTED_OPERATIONS = {
    ("get", "/channels/whatsapp/account"): ("channels_get_account", "authenticated"),
    ("post", "/channels/whatsapp/account/verify"): ("channels_run_account_verify", "permission"),
    ("post", "/channels/whatsapp/enrolments"): ("channels_create_enrolment", "permission"),
    ("get", "/channels/whatsapp/identities"): ("channels_list_identities", "authenticated"),
    ("delete", "/channels/whatsapp/identities/{identity_id}"): ("channels_delete_identity", "authenticated"),
    ("put", "/channels/whatsapp/consents"): ("channels_update_consent", "authenticated"),
    ("get", "/channels/whatsapp/messages"): ("channels_list_messages", "permission"),
    ("post", "/channels/whatsapp/outbox/{outbox_id}/resolve"): ("channels_resolve_outbox", "authenticated"),
    ("get", "/channels/whatsapp/templates"): ("channels_list_templates", "permission"),
    ("post", "/channels/whatsapp/templates/sync"): ("channels_run_templates_sync", "permission"),
    ("post", "/channels/whatsapp/demo/inbound"): ("channels_create_demo_inbound", "permission"),
    ("get", "/channels/whatsapp/demo/thread"): ("channels_get_demo_thread", "permission"),
    ("get", "/webhooks/whatsapp"): ("channels_verify_subscription", "webhook"),
    ("post", "/webhooks/whatsapp"): ("channels_receive_delivery", "webhook"),
    ("post", "/review-links/{token}/resolve"): ("channels_resolve_review_link", "authenticated"),
}
ENUM_COLUMNS: dict[tuple[str, str], type[StrEnum]] = {
    ("channels_account", "purpose"): schemas.AccountPurpose,
    ("channels_account", "provider"): schemas.AccountProvider,
    ("channels_account", "mode"): schemas.AccountMode,
    ("channels_account", "status"): schemas.AccountStatus,
    ("channels_identity", "kind"): schemas.IdentityKind,
    ("channels_identity", "status"): schemas.IdentityStatus,
    ("channels_enrolment", "status"): schemas.EnrolmentStatus,
    ("channels_enrolment", "mode"): schemas.AccountMode,
    ("channels_webhook_inbox", "status"): schemas.InboxStatus,
    ("channels_inbound_event", "kind"): schemas.InboundKind,
    ("channels_inbound_event", "status"): schemas.InboundStatus,
    ("channels_message", "direction"): schemas.Direction,
    ("channels_message", "status"): schemas.MessageStatus,
    ("channels_outbox_message", "kind"): schemas.OutboxKind,
    ("channels_outbox_message", "state"): schemas.OutboxState,
    ("channels_outbox_message", "purpose"): schemas.ConsentPurpose,
    ("channels_consent", "purpose"): schemas.ConsentPurpose,
    ("channels_consent", "status"): schemas.ConsentStatus,
    ("channels_template", "status"): schemas.TemplateStatus,
    ("channels_review_link", "purpose"): schemas.ReviewPurpose,
    ("channels_action_ref", "action"): schemas.ActionRefAction,
}
PAYLOADS: dict[str, type[BaseModel]] = {
    events.IDENTITY_LINKED: events.IdentityPayload, events.IDENTITY_REVOKED: events.IdentityPayload,
    events.IDENTITY_SUSPENDED: events.IdentityPayload, events.MESSAGE_RECEIVED: events.MessageReceivedPayload,
    events.MESSAGE_STATUS_CHANGED: events.StatusChangedPayload, events.MESSAGE_DELIVERY_UNKNOWN: events.DeliveryUnknownPayload,
    events.CONSENT_CHANGED: events.ConsentChangedPayload,
}


def test_routes_declare_authz_and_carry_stable_operation_ids() -> None:
    from fastapi.routing import APIRoute

    from app.main import create_app
    from app.modules.channels.router import review_router, router
    from app.modules.channels.webhook import router as webhook_router

    app = create_app()
    spec = app.openapi()
    found = {
        (m, p.removeprefix("/api/v1")): op["operationId"] for p, item in spec["paths"].items() for m, op in item.items()
        if p.startswith(("/api/v1/channels/", "/api/v1/webhooks/", "/api/v1/review-links/"))
    }
    assert found == {k: v[0] for k, v in EXPECTED_OPERATIONS.items()}
    routes = {}
    for r in (*router.routes, *review_router.routes, *webhook_router.routes):
        if isinstance(r, APIRoute):
            for m in r.methods:
                routes[(m.lower(), r.path)] = r
    for (method, path), (_op, kind) in EXPECTED_OPERATIONS.items():
        assert route_kind(routes[(method, path)]) == kind, (method, path)


def test_emitted_events_and_payloads_are_in_the_frozen_catalogue() -> None:
    registry = get_registry()
    for name, payload in PAYLOADS.items():
        event = registry.events[name]
        assert event.fields is not None and set(payload.model_fields) - {"origin"} == set(event.fields), name
    for name in (events.ACCOUNT_VERIFIED, events.TEMPLATE_STATUS_CHANGED):
        assert name in registry.events
    source = "\n".join(p.read_text(encoding="utf-8") for p in CHANNELS_DIR.rglob("*.py"))
    used = set(re.findall(r"\"(channels\.[a-z_]+\.[a-z_]+)\"", source)) & {e for e in registry.events if e.startswith("channels.")}
    assert used <= set(registry.events)


def test_tool_input_carries_no_identity_fields_and_forbids_extras() -> None:
    tool = next(t for t in get_registry().tools if t.name == "prepare_quote_send")
    assert tool.input_model is PrepareQuoteSendInput and tool.effect == "propose" and tool.permission == "channels.message.send"
    assert not FORBIDDEN_INPUT_FIELDS & set(PrepareQuoteSendInput.model_fields)
    assert PrepareQuoteSendInput.model_config.get("extra") == "forbid"


def test_jobs_schedule_policies_and_the_approval_handler_are_registered() -> None:
    from app.modules.approvals import service as approvals

    registry = get_registry()
    assert {events.JOB_INBOX_PROCESS, events.JOB_OUTBOX_SEND, events.JOB_OUTBOX_RECONCILE, events.JOB_TEMPLATES_SYNC} <= set(registry.jobs)
    assert registry.jobs[events.JOB_OUTBOX_SEND].max_attempts == 1  # never a blind resend
    assert "channels.outbox_reconcile" in registry.schedules
    assert approvals.handler_for(events.SEND_PROPOSAL_KIND).approve_permission == "channels.message.send"
    assert {"channels.account", "channels.identity", "channels.message", "channels.outbox_message"} <= set(registry.policies)


def test_model_enum_tuples_mirror_the_schema_enums() -> None:
    assert set(models.MESSAGE_STATUSES) == {e.value for e in schemas.MessageStatus}
    assert set(models.OUTBOX_STATES) == {e.value for e in schemas.OutboxState}
    assert set(models.TENANT_TABLES) | set(models.EXEMPT_TABLES) == {t for t in models.Base.metadata.tables if t.startswith("channels_")}


def _check_values(uow: UnitOfWork, table: str, name: str) -> set[str]:
    definition = uow.session.execute(
        text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = CAST(:t AS regclass) AND conname = :n"),
        {"t": table, "n": name},
    ).scalar_one()
    return set(re.findall(r"'([^']*)'", definition))


@pytest.mark.db
def test_tables_have_forced_rls_append_only_triggers_and_enum_checks(db: None) -> None:
    with UnitOfWork(ActorContext.system(None)) as uow:
        policies = set(uow.session.execute(text("SELECT tablename FROM pg_policies WHERE policyname = 'tenant_isolation'")).scalars())
        forced = set(uow.session.execute(text("SELECT relname FROM pg_class WHERE relforcerowsecurity")).scalars())
        triggers = set(uow.session.execute(text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal")).scalars())
        for (table, column), enum in ENUM_COLUMNS.items():
            assert _check_values(uow, table, f"ck_{table}_{column}_values") == {e.value for e in enum}, (table, column)
    assert set(models.TENANT_TABLES) <= policies and set(models.TENANT_TABLES) <= forced
    assert not set(models.EXEMPT_TABLES) & policies
    assert {f"trg_{t}_append_only" for t in models.APPEND_ONLY_TABLES} <= triggers


def test_no_wall_clock_in_business_code() -> None:
    offenders = []
    for path in CHANNELS_DIR.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in {"now", "utcnow", "today", "time"}:
                if isinstance(node.value, ast.Name) and node.value.id in {"datetime", "date", "time"}:
                    offenders.append(f"{path.relative_to(BACKEND_DIR)}:{node.lineno}")
    assert offenders == []


def test_migration_is_the_lane_placeholder_with_rls_and_append_only() -> None:
    source = Path(BACKEND_DIR / "migrations" / "versions" / "0022_channels_slice3.py").read_text(encoding="utf-8")
    assert "revision: str = '0022'" in source and "down_revision: str | Sequence[str] | None = '0009'" in source
    assert "helpers.enable_tenant_rls(table)" in source and "helpers.append_only(table)" in source


def test_message_bodies_are_encrypted_at_rest() -> None:
    from app.modules.channels import crypto

    blob = crypto.encrypt_text("Prepare Nordhaus's usual oak tray quote")
    assert b"Nordhaus" not in blob and crypto.decrypt_text(blob) == "Prepare Nordhaus's usual oak tray quote"
    assert "body_encrypted" in models.ChannelMessage.__table__.c and "body" not in models.ChannelMessage.__table__.c
