"""Review links (32-byte token stored hashed, 15 minutes, single use for decisions, bound user), template sync and
the ``message_template_status_update`` webhook, and the honest reply when the assistant run fails."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.clock import FrozenClock
from app.modules.channels import review_links
from app.modules.channels.models import ReviewLink, WaTemplate
from app.modules.channels.schemas import ReviewPurpose
from app.modules.channels.whatsapp import templates
from app.platform.uow import UnitOfWork
from tests.integration.channels.conftest import API, WhatsApp

pytestmark = pytest.mark.db


def _link(wa: WhatsApp, persona: str, purpose: ReviewPurpose) -> str:
    with UnitOfWork(wa.system()) as uow:
        _row, token = review_links.create(uow, user_id=wa.world.user_id(persona), target_type="approvals.proposal", target_id=uuid.uuid7(),
                                          redirect_path="/inbox/approvals/x", purpose=purpose)
        return token


def test_review_link_is_hashed_bound_single_use_for_decisions_and_expires(wa: WhatsApp, client: TestClient, frozen_clock: FrozenClock) -> None:
    token = _link(wa, "SAHIL", ReviewPurpose.DECIDE)
    assert len(token) >= 43  # 32 random bytes, url-safe base64
    with UnitOfWork(wa.system()) as uow:
        stored = uow.session.scalars(select(ReviewLink)).one()
        assert token.encode() not in bytes(stored.token_hash)
    url = f"{API}/review-links/{token}/resolve"
    assert client.post(url, json={}, headers={"x-test-persona": "MEERA"}).status_code == 403
    first = client.post(url, json={}, headers={"x-test-persona": "SAHIL"})
    assert first.status_code == 200 and first.json()["redirect_path"] == "/inbox/approvals/x" and first.json()["purpose"] == "decide"
    again = client.post(url, json={}, headers={"x-test-persona": "SAHIL"})
    assert again.status_code == 410 and again.json()["code"] == "review_link_used"
    view = _link(wa, "SAHIL", ReviewPurpose.VIEW)
    assert client.post(f"{API}/review-links/{view}/resolve", json={}, headers={"x-test-persona": "SAHIL"}).status_code == 200
    assert client.post(f"{API}/review-links/{view}/resolve", json={}, headers={"x-test-persona": "SAHIL"}).status_code == 200
    frozen_clock.advance(minutes=16)
    expired = client.post(f"{API}/review-links/{view}/resolve", json={}, headers={"x-test-persona": "SAHIL"})
    assert expired.status_code == 410 and expired.json()["code"] == "review_link_expired"
    assert client.post(f"{API}/review-links/not-a-token/resolve", json={}, headers={"x-test-persona": "SAHIL"}).status_code == 404


def test_template_sync_and_status_webhook(wa: WhatsApp, client: TestClient) -> None:
    headers = {"x-test-persona": "PRIYA"}
    synced = client.post(f"{API}/channels/whatsapp/templates/sync", headers=headers)
    assert synced.status_code == 200, synced.text
    statuses = {t["name"]: t["status"] for t in synced.json()}
    assert statuses == {"lk_daily_briefing": "approved", "lk_followup_offer": "paused", "lk_price_update": "rejected", "lk_quote_ready": "approved"}
    assert client.get(f"{API}/channels/whatsapp/templates", headers={"x-test-persona": "MEERA"}).status_code == 403
    account = wa.account()
    assert account.waba_id and account.waba_id.startswith("demo-waba-")
    update = {"object": "whatsapp_business_account", "entry": [{"id": account.waba_id, "time": 1760239700, "changes": [{
        "field": "message_template_status_update",
        "value": {"event": "PAUSED", "message_template_id": "demo-tpl-1", "message_template_name": "lk_quote_ready", "message_template_language": "en"}}]}]}
    with UnitOfWork(wa.system()) as uow:
        template_id = uow.session.scalars(select(WaTemplate).where(WaTemplate.name == "lk_quote_ready")).one().id
    wa.deliver(update)
    with UnitOfWork(wa.system()) as uow:
        assert uow.session.get(WaTemplate, template_id).status == "paused"  # type: ignore[union-attr]
        assert templates.find_sendable(uow, uow.session.get(type(account), account.id), "lk_quote_ready").status == "paused"  # type: ignore[union-attr,arg-type]


def test_admin_message_list_shows_blocked_rows(wa: WhatsApp, client: TestClient, frozen_clock: FrozenClock) -> None:
    from tests.integration.channels.test_scenario_k import _queue
    from tests.support import drain

    identity = wa.enrol("MEERA")
    frozen_clock.advance(hours=25)
    _queue(wa, identity.id, "late")
    drain()
    listed = client.get(f"{API}/channels/whatsapp/messages", params={"state": "blocked"}, headers={"x-test-persona": "PRIYA"})
    assert listed.status_code == 200
    row = listed.json()[0]
    assert row["outbox_state"] == "blocked" and row["blocked_reason"] == "window_closed" and row["body"] == "late"
    assert row["capabilities"]["resend"]["allowed"] is True
    assert client.get(f"{API}/channels/whatsapp/messages", headers={"x-test-persona": "MEERA"}).status_code == 403
