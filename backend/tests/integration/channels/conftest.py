"""Fixtures for the WhatsApp lane: the persona world (no business data unless a test asks for it), a driver that
delivers Cloud-API-shaped payloads through the real signed webhook ingest and drains the worker inline, and an API
client resolving the persona from ``x-test-persona`` exactly as a session would."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import datetime
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import get_settings
from app.core.http.deps import get_actor
from app.modules.channels import crypto
from app.modules.channels.models import ChannelAccount, ChannelIdentity, ChannelMessage, OutboxMessage
from app.modules.channels.service import demo_wa_id
from app.modules.channels.webhook import IngestResult, ingest_signed
from app.modules.channels.whatsapp import accounts, enrolment
from app.modules.channels.whatsapp.demo_provider import inbound_payload, signed_webhook_body, status_payload
from app.platform.authz.context import ActorContext
from app.platform.uow import UnitOfWork
from app.seed.world import keys
from tests.integration.agents.conftest import sales_tools  # noqa: F401  (scenario C over WhatsApp)
from tests.integration.catalogue.world import World, member_actors, personas, world  # noqa: F401
from tests.support import drain

API = "/api/v1"


class WhatsApp:
    """Drive WhatsApp as Meta would: signed deliveries into the real ingest, then the worker inline."""

    def __init__(self, fixture_world: World) -> None:
        self.world = fixture_world
        self.company_id = fixture_world.company_id
        self._seq = 0

    # ---- actors and account --------------------------------------------------------------------------------------
    def actor(self, persona: str, *, recent_auth: bool = True, mfa: bool = False) -> ActorContext:
        base = self.world.actor(persona)
        actor = base.with_(recent_auth_at=self.now() if recent_auth else None, channel="web")
        # platform-2 step-up (ADR-052): MFA-flagged keys such as channels.account.manage need an MFA session
        return actor.with_(auth_strength="mfa") if mfa else actor

    def system(self) -> ActorContext:
        return ActorContext.system(self.company_id, reason="test")

    def now(self) -> datetime:
        from app.core.clock import get_clock

        return get_clock(self.company_id).now()

    def account(self) -> ChannelAccount:
        with UnitOfWork(self.system()) as uow:
            account = accounts.ensure_account(uow)
            uow.session.expunge(account)
            return account

    def wa_id(self, persona: str) -> str:
        return demo_wa_id(self.world.user_id(persona))

    # ---- deliveries ------------------------------------------------------------------------------------------------
    def wamid(self) -> str:
        self._seq += 1
        return f"wamid.test.{uuid.uuid4().hex[:12]}.{self._seq}"

    def deliver(self, payload: dict[str, Any], *, secret: str | None = None, process: bool = True) -> IngestResult:
        body, signature = signed_webhook_body(payload)
        if secret is not None:
            from app.modules.channels.whatsapp.signature import sign

            signature = sign(body, secret)
        result = ingest_signed(body, signature, remote_addr="203.0.113.7")
        if process:
            drain()
        return result

    def message_payload(self, wa_id: str, message: dict[str, Any], *, ts: datetime | None = None, bsuid: str | None = None) -> dict[str, Any]:
        account = self.account()
        return inbound_payload(accounts.account_config(account), wa_id=wa_id, bsuid=bsuid, message=message, ts=int((ts or self.now()).timestamp()))

    def text(self, wa_id: str, body: str, *, wamid: str | None = None, ts: datetime | None = None, bsuid: str | None = None,
             process: bool = True) -> str:
        wamid = wamid or self.wamid()
        self.deliver(self.message_payload(wa_id, {"id": wamid, "type": "text", "text": {"body": body}}, ts=ts, bsuid=bsuid), process=process)
        return wamid

    def button(self, wa_id: str, button_id: str, *, ts: datetime | None = None) -> str:
        wamid = self.wamid()
        message = {"id": wamid, "type": "interactive", "interactive": {"type": "button_reply", "button_reply": {"id": button_id, "title": "x"}}}
        self.deliver(self.message_payload(wa_id, message, ts=ts))
        return wamid

    def statuses(self, wamid: str, recipient: str, pairs: list[tuple[str, int]], *, biz_opaque: str | None = None, process: bool = True) -> IngestResult:
        payload = status_payload(accounts.account_config(self.account()), wamid, recipient, pairs, biz_opaque=biz_opaque)
        return self.deliver(payload, process=process)

    # ---- enrolment -------------------------------------------------------------------------------------------------
    def enrol(self, persona: str) -> ChannelIdentity:
        with UnitOfWork(self.actor(persona)) as uow:
            code = enrolment.create(uow).code
        self.text(self.wa_id(persona), f"LINK {code}")
        identity = self.identity(persona)
        assert identity is not None and identity.status == "active", identity
        return identity

    # ---- reads -----------------------------------------------------------------------------------------------------
    def identity(self, persona: str) -> ChannelIdentity | None:
        with UnitOfWork(self.system()) as uow:
            row = uow.session.scalars(select(ChannelIdentity).where(ChannelIdentity.wa_id == self.wa_id(persona))).first()
            if row is not None:
                uow.session.expunge(row)
            return row

    def messages(self, identity_id: uuid.UUID, direction: str | None = None) -> list[dict[str, Any]]:
        with UnitOfWork(self.system()) as uow:
            stmt = select(ChannelMessage).where(ChannelMessage.identity_id == identity_id)
            if direction:
                stmt = stmt.where(ChannelMessage.direction == direction)
            out = []
            for row in uow.session.scalars(stmt.order_by(ChannelMessage.created_at, ChannelMessage.id)):
                outbox = uow.session.get(OutboxMessage, row.outbox_id) if row.outbox_id else None
                out.append({
                    "id": row.id, "direction": row.direction, "type": row.type, "body": crypto.decrypt_text(row.body_encrypted),
                    "status": row.status, "rank": row.status_rank, "simulated": row.simulated, "wamid": row.provider_message_id,
                    "outbox_state": outbox.state if outbox else None, "blocked_reason": outbox.blocked_reason if outbox else None,
                    "outbox_id": outbox.id if outbox else None, "buttons": (outbox.payload or {}).get("buttons") if outbox else None,
                    "run_id": row.run_id, "input_mode": row.input_mode, "provenance": row.provenance,
                })
            return out

    def replies(self, identity_id: uuid.UUID) -> list[str]:
        return [m["body"] or "" for m in self.messages(identity_id, "outbound")]


@pytest.fixture
def wa(personas: World) -> WhatsApp:  # noqa: F811
    return WhatsApp(personas)


@pytest.fixture(scope="module")
def app() -> FastAPI:
    from app.main import create_app

    return create_app()


@pytest.fixture
def client(app: FastAPI, wa: WhatsApp) -> Iterator[TestClient]:
    def resolve(request: Request) -> ActorContext:
        persona = request.headers.get("x-test-persona", keys.USERS.MEERA)
        return wa.actor(persona, recent_auth=request.headers.get("x-test-recent-auth", "1") == "1",
                        mfa=request.headers.get("x-test-mfa", "1") == "1").with_(
            idempotency_key=request.headers.get("idempotency-key"))

    app.dependency_overrides[get_actor] = resolve
    try:
        with TestClient(app, headers={"Origin": get_settings().public_origin}) as c:
            yield c
    finally:
        app.dependency_overrides.clear()


def unix(dt: datetime) -> int:
    return int(dt.timestamp())
