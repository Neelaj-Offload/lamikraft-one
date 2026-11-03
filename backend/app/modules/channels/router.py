"""Channels API (design §16 "Channels"; api-conventions.md): WhatsApp enrolment, identities, consents, the admin
account / messages / outbox / templates views, the demo simulator, and review links (``/review-links``).

operationIds are ``channels_<verb>_<noun>``. Every route declares its authz; services enforce record scope (own
identity unless ``channels.identity.manage``; admin views need their catalogued key)."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Query, Response
from fastapi.concurrency import run_in_threadpool

from app.core.errors import AppError
from app.core.http.authz_decl import authenticated, requires
from app.core.http.deps import Actor
from app.modules.channels import review_links, service
from app.modules.channels.policies import ACCOUNT_MANAGE, OUTBOX_MANAGE
from app.modules.channels.schemas import (
    AccountRead,
    ConsentRead,
    ConsentUpdate,
    DemoInbound,
    DemoInboundResult,
    DemoThread,
    EnrolmentCreate,
    EnrolmentRead,
    IdentityRead,
    MessageRead,
    OutboxRead,
    OutboxResolve,
    ReviewLinkResolve,
    ReviewLinkResolved,
    TemplateRead,
    VerifyResult,
)
from app.modules.channels.whatsapp import accounts, enrolment, templates
from app.platform.uow import UnitOfWork

router = APIRouter(prefix="/channels/whatsapp", tags=["channels"])
review_router = APIRouter(prefix="/review-links", tags=["channels"])

ASSISTANT_USE = "agents.assistant.use"


class WebhookIngestFailed(AppError):
    status, code, title = 502, "simulation_failed", "The simulated message could not be delivered"


# ---- account (label for everyone; details and checks for admins) ----------------------------------------------------
@router.get("/account", openapi_extra=authenticated())
def get_account(actor: Actor) -> AccountRead:
    with UnitOfWork(actor) as uow:
        return accounts.account_read(uow, accounts.ensure_account(uow))


@router.post("/account/verify", openapi_extra=requires(ACCOUNT_MANAGE))
def run_account_verify(actor: Actor) -> VerifyResult:
    from app.platform.org.stepup import require_recent_auth

    with UnitOfWork(actor) as uow:
        uow.actor.require(ACCOUNT_MANAGE)
        require_recent_auth(uow, ACCOUNT_MANAGE)
        return accounts.run_checks(uow, accounts.ensure_account(uow))


# ---- enrolment and identities -------------------------------------------------------------------------------------
@router.post("/enrolments", status_code=201, openapi_extra=requires(ASSISTANT_USE))
def create_enrolment(actor: Actor, body: EnrolmentCreate | None = None) -> EnrolmentRead:
    del body
    with UnitOfWork(actor) as uow:
        return enrolment.create(uow)


@router.get("/identities", openapi_extra=authenticated())
def list_identities(actor: Actor, scope: Literal["mine", "all"] = Query(default="mine")) -> list[IdentityRead]:
    with UnitOfWork(actor) as uow:
        return service.list_identities(uow, scope=scope)


@router.delete("/identities/{identity_id}", status_code=204, openapi_extra=authenticated())
def delete_identity(actor: Actor, identity_id: uuid.UUID) -> Response:
    with UnitOfWork(actor) as uow:
        service.revoke(uow, identity_id)
    return Response(status_code=204)


@router.put("/consents", openapi_extra=authenticated())
def update_consent(actor: Actor, body: ConsentUpdate) -> ConsentRead:
    with UnitOfWork(actor) as uow:
        return service.update_consent(uow, body)


# ---- admin: messages, outbox, templates ---------------------------------------------------------------------------
@router.get("/messages", openapi_extra=requires(OUTBOX_MANAGE))
def list_messages(actor: Actor, state: Literal["unknown", "failed", "blocked", "escalated"] | None = Query(default=None)) -> list[MessageRead]:
    with UnitOfWork(actor) as uow:
        return service.admin_messages(uow, state)


@router.post("/outbox/{outbox_id}/resolve", openapi_extra=authenticated())
def resolve_outbox(actor: Actor, outbox_id: uuid.UUID, body: OutboxResolve) -> OutboxRead:
    with UnitOfWork(actor) as uow:
        return service.resolve_outbox(uow, outbox_id, body)


@router.get("/templates", openapi_extra=requires(ACCOUNT_MANAGE))
def list_templates(actor: Actor) -> list[TemplateRead]:
    with UnitOfWork(actor) as uow:
        return templates.list_templates(uow)


@router.post("/templates/sync", openapi_extra=requires(ACCOUNT_MANAGE))
def run_templates_sync(actor: Actor) -> list[TemplateRead]:
    from app.platform.org.stepup import require_recent_auth

    with UnitOfWork(actor) as uow:
        require_recent_auth(uow, ACCOUNT_MANAGE)
        return templates.sync(uow)


# ---- demo simulator (demo mode only) -------------------------------------------------------------------------------
@router.post("/demo/inbound", status_code=202, openapi_extra=requires(ASSISTANT_USE))
async def create_demo_inbound(actor: Actor, body: DemoInbound) -> DemoInboundResult:
    """Simulate a message from the signed-in user's demo number: signed and delivered through the real webhook
    ingest (signature check, inbox, worker) exactly like a Meta delivery."""
    from app.modules.channels.webhook import ingest_signed

    def build() -> tuple[DemoInboundResult, bytes, str]:
        with UnitOfWork(actor) as uow:
            return service.demo_inbound(uow, body)

    result, raw, signature = await run_in_threadpool(build)
    outcome = await run_in_threadpool(ingest_signed, raw, signature, remote_addr="demo-simulator")
    if outcome.status_code != 200 or outcome.inbox_id is None:
        raise WebhookIngestFailed(f"webhook ingest answered {outcome.status_code} ({outcome.reason})")
    return result.model_copy(update={"inbox_id": uuid.UUID(outcome.inbox_id)})


@router.get("/demo/thread", openapi_extra=requires(ASSISTANT_USE))
def get_demo_thread(actor: Actor) -> DemoThread:
    with UnitOfWork(actor) as uow:
        return service.demo_thread(uow)


# ---- review links -------------------------------------------------------------------------------------------------
@review_router.post("/{token}/resolve", openapi_extra=authenticated())
def resolve_review_link(actor: Actor, token: str, body: ReviewLinkResolve | None = None) -> ReviewLinkResolved:
    del body
    with UnitOfWork(actor) as uow:
        return review_links.resolve(uow, token)


__all__ = ["review_router", "router"]
