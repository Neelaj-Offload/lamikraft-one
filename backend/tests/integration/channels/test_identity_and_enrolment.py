"""Enrolment, identity matching and the inbound rules that do not need business data.

Codes: recent sign-in required, hashed (never stored or echoed), 10 minutes, five wrong codes lock the sender;
a reassigned number revokes the previous holder; BSUID matching and suspension on a BSUID change; generic
"not linked" replies at most hourly; groups ignored; late events flagged; unsupported types answered politely;
identities and consents through the API (own scope, admin scope with ``channels.identity.manage``).
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.clock import FrozenClock
from app.modules.channels.models import ChannelEnrolment, ChannelIdentity, ChannelMessage, InboundEvent
from app.modules.channels.whatsapp import enrolment
from app.platform.uow import UnitOfWork
from tests.integration.channels.conftest import API, WhatsApp

pytestmark = pytest.mark.db


def _code(wa: WhatsApp, persona: str) -> str:
    with UnitOfWork(wa.actor(persona)) as uow:
        return enrolment.create(uow).code


def test_enrolment_stores_only_a_hash(wa: WhatsApp) -> None:
    code = _code(wa, "MEERA")
    assert len(code) == 8 and code.isdigit()
    with UnitOfWork(wa.system()) as uow:
        row = uow.session.scalars(select(ChannelEnrolment)).one()
        assert code.encode() not in bytes(row.code_hash) and row.status == "pending"
        assert row.expires_at - wa.now() == timedelta(minutes=10)
    wa.text(wa.wa_id("MEERA"), f"link {code}")
    identity = wa.identity("MEERA")
    assert identity is not None and identity.kind == "employee" and identity.user_id == wa.world.user_id("MEERA")
    inbound = wa.messages(identity.id, "inbound")[0]
    assert code not in (inbound["body"] or "")
    assert wa.replies(identity.id)[-1].startswith("Demo: Linked to Lamikraft One as Meera Iyer.")


def test_a_new_code_cancels_the_previous_one_and_expired_codes_fail(wa: WhatsApp, frozen_clock: FrozenClock) -> None:
    first = _code(wa, "MEERA")
    second = _code(wa, "MEERA")
    wa.text(wa.wa_id("MEERA"), f"LINK {first}")
    assert "not valid" in wa.replies(wa.identity("MEERA").id)[-1]  # type: ignore[union-attr]
    frozen_clock.advance(minutes=11)
    wa.text(wa.wa_id("MEERA"), f"LINK {second}")
    identity = wa.identity("MEERA")
    assert identity is not None and identity.status == "pending" and "expired" in wa.replies(identity.id)[-1]


def test_five_wrong_codes_lock_the_sender(wa: WhatsApp) -> None:
    code = _code(wa, "MEERA")
    wrong = f"{(int(code) + 1) % 10**8:08d}"
    for _ in range(5):
        wa.text(wa.wa_id("MEERA"), f"LINK {wrong}")
    wa.text(wa.wa_id("MEERA"), f"LINK {code}")
    identity = wa.identity("MEERA")
    assert identity is not None and identity.status == "pending" and "Too many wrong codes" in wa.replies(identity.id)[-1]


def test_a_reassigned_number_revokes_the_previous_holder(wa: WhatsApp) -> None:
    meera = wa.enrol("MEERA")
    number = wa.wa_id("MEERA")
    code = _code(wa, "NEHA")
    wa.text(number, f"LINK {code}")  # Meera's old number now belongs to Neha
    with UnitOfWork(wa.system()) as uow:
        old = uow.session.get(ChannelIdentity, meera.id)
        new = uow.session.scalars(select(ChannelIdentity).where(ChannelIdentity.wa_id == number)).one()
    assert old is not None and old.status == "revoked" and old.suspended_reason == "number_reassigned"
    assert new.user_id == wa.world.user_id("NEHA") and new.status == "active" and new.id != meera.id


def test_bsuid_matches_first_and_a_bsuid_change_suspends(wa: WhatsApp) -> None:
    code = _code(wa, "MEERA")
    wa.text(wa.wa_id("MEERA"), f"LINK {code}", bsuid="IN.BSUID.MEERA")
    identity = wa.identity("MEERA")
    assert identity is not None and identity.bsuid == "IN.BSUID.MEERA"
    # a username user with no phone: matched on the BSUID alone
    wamid = wa.wamid()
    payload = wa.message_payload("", {"id": wamid, "type": "text", "text": {"body": "STOP"}}, bsuid="IN.BSUID.MEERA")
    payload["entry"][0]["changes"][0]["value"]["messages"][0].pop("from")
    payload["entry"][0]["changes"][0]["value"]["contacts"][0].pop("wa_id")
    wa.deliver(payload)
    assert "Proactive messages are off" in wa.replies(identity.id)[-1]
    system = {"id": wa.wamid(), "type": "system", "system": {"type": "user_changed_user_id", "body": "changed", "user_id": "IN.BSUID.NEW"}}
    wa.deliver(wa.message_payload(wa.wa_id("MEERA"), system, bsuid="IN.BSUID.MEERA"))
    suspended = wa.identity("MEERA")
    assert suspended is not None and suspended.status == "suspended" and suspended.suspended_reason == "user_changed_user_id"
    wa.text(wa.wa_id("MEERA"), "hello?")
    assert "not linked" in wa.replies(identity.id)[-1]


def test_unknown_senders_get_one_generic_reply_per_hour_with_no_data(wa: WhatsApp, frozen_clock: FrozenClock) -> None:
    stranger = "919811122233"
    for _ in range(3):
        wa.text(stranger, "what is the price of the oak tray?")
    with UnitOfWork(wa.system()) as uow:
        identity = uow.session.scalars(select(ChannelIdentity).where(ChannelIdentity.wa_id == stranger)).one()
    replies = wa.replies(identity.id)
    assert len(replies) == 1 and "not linked" in replies[0] and "EUR" not in replies[0]
    assert all(m["run_id"] is None for m in wa.messages(identity.id))
    frozen_clock.advance(minutes=61)
    wa.text(stranger, "hello")
    assert len(wa.replies(identity.id)) == 2


def test_group_messages_are_ignored_and_late_events_flagged(wa: WhatsApp) -> None:
    identity = wa.enrol("MEERA")
    group = wa.message_payload(wa.wa_id("MEERA"), {"id": wa.wamid(), "type": "text", "text": {"body": "group chat"}, "group_id": "120363000"})
    wa.deliver(group)
    assert all(m["body"] != "group chat" for m in wa.messages(identity.id))
    newer = wa.text(wa.wa_id("MEERA"), "STOP", ts=wa.now() + timedelta(minutes=2))
    older = wa.text(wa.wa_id("MEERA"), "START", ts=wa.now() + timedelta(minutes=1))
    with UnitOfWork(wa.system()) as uow:
        flags = {e.provider_event_key: e.late for e in uow.session.scalars(select(InboundEvent).where(InboundEvent.provider_event_key.in_((newer, older))))}
        refreshed = uow.session.get(ChannelIdentity, identity.id)
    assert flags == {newer: False, older: True}
    assert refreshed is not None and refreshed.last_inbound_at == wa.now() + timedelta(minutes=2)  # the maximum provider_ts


def test_unsupported_types_get_a_polite_reply(wa: WhatsApp) -> None:
    identity = wa.enrol("MEERA")
    wa.deliver(wa.message_payload(wa.wa_id("MEERA"), {"id": wa.wamid(), "type": "location", "location": {"latitude": 19.0, "longitude": 72.8}}))
    assert wa.replies(identity.id)[-1] == "Demo: I can read text messages, voice notes, images and documents. Please send your request as text or a voice note."


def test_inbound_document_is_stored_as_external_content(wa: WhatsApp) -> None:
    from app.modules.channels.whatsapp.demo_provider import register_media

    identity = wa.enrol("MEERA")
    pdf = b"%PDF-1.4\n%demo\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
    media_id = register_media(pdf, "application/pdf")
    wa.deliver(wa.message_payload(wa.wa_id("MEERA"), {"id": wa.wamid(), "type": "document",
                                                     "document": {"id": media_id, "mime_type": "application/pdf", "filename": "drawing.pdf"}}))
    inbound = next(m for m in wa.messages(identity.id, "inbound") if m["type"] == "document")
    assert inbound["provenance"] == "external"
    with UnitOfWork(wa.system()) as uow:
        row = uow.session.get(ChannelMessage, inbound["id"])
        assert row is not None and row.media_file_id is not None and row.media_sha256
    assert wa.replies(identity.id)[-1].startswith("Demo: Saved drawing.pdf")


def test_expired_voice_note_url_gets_an_honest_reply(wa: WhatsApp) -> None:
    identity = wa.enrol("MEERA")
    wa.deliver(wa.message_payload(wa.wa_id("MEERA"), {"id": wa.wamid(), "type": "audio", "audio": {"id": "demo-media-gone", "mime_type": "audio/ogg", "voice": True}}))
    assert "link expired" in wa.replies(identity.id)[-1]


def test_identities_and_consents_through_the_api(wa: WhatsApp, client: TestClient) -> None:
    meera = wa.enrol("MEERA")
    wa.enrol("NEHA")
    mine = client.get(f"{API}/channels/whatsapp/identities", headers={"x-test-persona": "MEERA"})
    assert mine.status_code == 200 and [i["id"] for i in mine.json()] == [str(meera.id)]
    body = mine.json()[0]
    assert body["wa_id_masked"].endswith(wa.wa_id("MEERA")[-4:]) and wa.wa_id("MEERA") not in str(body)
    assert body["consents"] == {"assistant_replies": "opted_in"} and body["capabilities"]["revoke"]["allowed"]
    assert client.get(f"{API}/channels/whatsapp/identities", params={"scope": "all"}, headers={"x-test-persona": "MEERA"}).status_code == 403
    everyone = client.get(f"{API}/channels/whatsapp/identities", params={"scope": "all"}, headers={"x-test-persona": "PRIYA"})
    assert everyone.status_code == 200 and len(everyone.json()) == 2
    consent = client.put(f"{API}/channels/whatsapp/consents", json={"identity_id": str(meera.id), "purpose": "daily_briefing", "status": "opted_in"},
                         headers={"x-test-persona": "MEERA"})
    assert consent.status_code == 200 and consent.json()["source"] == "web_settings"
    other = client.put(f"{API}/channels/whatsapp/consents", json={"identity_id": str(meera.id), "purpose": "daily_briefing", "status": "opted_out"},
                       headers={"x-test-persona": "NEHA"})
    assert other.status_code == 404  # another user's identity is not revealed
    assert client.delete(f"{API}/channels/whatsapp/identities/{meera.id}", headers={"x-test-persona": "NEHA"}).status_code == 404
    assert client.delete(f"{API}/channels/whatsapp/identities/{meera.id}", headers={"x-test-persona": "MEERA"}).status_code == 204
    assert wa.identity("MEERA").status == "revoked"  # type: ignore[union-attr]


def test_unknown_mode_requires_recent_auth(wa: WhatsApp, monkeypatch: pytest.MonkeyPatch) -> None:
    """The step-up fails closed: only the explicit demo mode skips it; an unknown mode needs a recent sign-in."""
    from app.modules.channels.whatsapp import accounts
    from app.platform.org.stepup import ReauthRequired

    real = accounts.ensure_account

    def odd_mode(uow: UnitOfWork, purpose: str = "employee_assistant") -> object:
        account = real(uow, purpose)
        uow.session.expunge(account)  # never written back: the CHECK only knows demo and live
        account.mode = "sandbox"
        return account

    monkeypatch.setattr(enrolment.accounts, "ensure_account", odd_mode)
    with pytest.raises(ReauthRequired), UnitOfWork(wa.actor("MEERA", recent_auth=False)) as uow:
        enrolment.create(uow)
    monkeypatch.undo()
    with UnitOfWork(wa.actor("MEERA", recent_auth=False)) as uow:
        assert enrolment.create(uow).mode == "demo"  # demo mode: no step-up, and the code records its mode


def test_demo_enrolment_rejected_on_a_live_account(wa: WhatsApp) -> None:
    from sqlalchemy import update

    from app.modules.channels.models import ChannelAccount

    code = _code(wa, "MEERA")
    with UnitOfWork(wa.system()) as uow:
        enrolled = uow.session.scalars(select(ChannelEnrolment)).one()
        assert enrolled.mode == "demo"
        # the account is live now (without passing through ensure_account, which would also cancel the code)
        uow.session.execute(update(ChannelAccount).where(ChannelAccount.id == enrolled.account_id).values(mode="live"))
    wa.text(wa.wa_id("MEERA"), f"LINK {code}")
    with UnitOfWork(wa.system()) as uow:
        row = uow.session.scalars(select(ChannelEnrolment)).one()
        identity = uow.session.scalars(select(ChannelIdentity).where(ChannelIdentity.wa_id == wa.wa_id("MEERA"))).one()
    assert row.status == "cancelled" and row.identity_id is None
    assert identity.kind == "unknown" and identity.user_id is None and identity.status == "pending"
