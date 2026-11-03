"""Voice through the API (design section 14, scenario C via voice, scenario J): Demo STT from fixture recordings,
one turn per utterance id, corrections as new turns, read-back before a voice confirm, spoken replies bound to the
owner's session, 7-day audio purge, and readiness."""

from __future__ import annotations

import io
import uuid
import wave
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.core.clock import FrozenClock
from app.modules.agents.models import Run, Turn
from app.modules.parties import service as parties
from app.modules.parties.schemas import PartyCreate
from app.modules.voice import readback as readback_mod
from app.modules.voice import service as voice_service
from app.modules.voice.config import get_voice_settings
from app.modules.voice.models import VoiceSpeech, VoiceUtterance
from app.platform.uow import UnitOfWork
from app.seed.world import keys
from tests.integration.agents.conftest import cards_of, tool_calls
from tests.integration.catalogue.world import World
from tests.integration.voice.conftest import API, Voice, fixture_audio
from tests.support import drain

pytestmark = pytest.mark.db

EXPECTED_TOOLS = ["resolve_party", "find_usual_order", "resolve_price", "calculate_quote", "draft_quote"]


def _wav(seconds: float, rate: int = 8000) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(b"\x00\x00" * int(rate * seconds))
    return buffer.getvalue()


def _say_by_voice(voice: Voice, fixture: str, *, text: str | None = None, **submit: object) -> tuple[dict, dict]:
    """Record (fixture) -> transcribe -> submit (optionally edited) -> drain -> finished run detail."""
    transcribed = voice.transcribe(fixture_audio(fixture), conversation_id=voice.conversation_id())
    assert transcribed.status_code == 200, transcribed.text
    utterance = transcribed.json()
    sent = voice.submit(utterance["id"], text if text is not None else utterance["text"], **submit)
    assert sent.status_code == 202, sent.text
    drain()
    return sent.json(), voice.assistant.poll(sent.json()["turn"]["run_id"])


def test_capabilities_are_demo_with_untested_hindi_and_hinglish(voice: Voice) -> None:
    response = voice.client.get(f"{API}/voice/capabilities", headers=voice.headers)
    assert response.status_code == 200, response.text
    caps = response.json()
    assert caps["available"] is True and caps["stt"]["status"] == "demo" and caps["stt"]["label"] == "Demo"
    assert caps["tts"]["status"] == "demo"
    assert caps["browser_fallback"] == {"provider": "browser", "label": "Browser fallback", "status": "off"}
    labels = {lang["code"]: (lang["tested"], lang["status_label"]) for lang in caps["languages"]}
    assert labels["hi-IN"] == (False, "Untested") and labels["hinglish"] == (False, "Untested")
    assert caps["max_seconds"] == 60 and caps["max_bytes"] == 10 * 1024 * 1024
    assert caps["can_speak"] is True and caps["speak_responses"] is False and caps["read_back_values"] is True


def test_agent_c_voice_path_same_result(voice: Voice, world: World) -> None:
    """Scenario C via voice: the fixture recording goes through Demo STT, the turn carries the utterance id, and the
    draft, card amounts and tool path are those of the text path; the read-back text is deterministic."""
    submitted, detail = _say_by_voice(voice, "usual_oak_tray")
    assert submitted["utterance"]["text"] == "Prepare Nordhaus's usual oak tray quote"
    assert submitted["utterance"]["simulated"] is False and submitted["utterance"]["provider_label"] == "Demo"
    assert detail["run"]["status"] == "succeeded" and tool_calls(detail) == EXPECTED_TOOLS
    card = cards_of(detail, "quote_draft")[0]
    assert card["quote_number"] == keys.QUOTES.SCENARIO_C_NEW
    assert Decimal(card["totals"]["grand_total"]) == Decimal(keys.EXPECTED.SCENARIO_C_TOTAL)
    with UnitOfWork(world.actor(keys.USERS.MEERA)) as uow:
        turn = uow.session.get(Turn, uuid.UUID(submitted["turn"]["turn_id"]))
        assert turn is not None and str(turn.client_utterance_id) == submitted["utterance"]["id"]
        row = uow.session.get(VoiceUtterance, uuid.UUID(submitted["utterance"]["id"]))
        assert row is not None and row.status == "submitted" and row.edited is False
        assert row.turn_id == turn.id and row.audio_key is not None and row.audio_mime == "audio/wav"

    first = voice.client.post(f"{API}/voice/readbacks", json={"subject_type": "sales.quote", "subject_id": card["quote_id"]},
                              headers=voice.headers)
    second = voice.client.post(f"{API}/voice/readbacks", json={"subject_type": "sales.quote", "subject_id": card["quote_id"]},
                               headers=voice.headers)
    assert first.status_code == 201, first.text
    text = first.json()["text"]
    assert text == second.json()["text"]
    assert text.startswith(f"{keys.PARTY_NAMES['NORDHAUS']}. Quote {keys.QUOTES.SCENARIO_C_NEW}, draft, not sent.")
    assert "240 pcs" in text and "at EUR 24.00 each" in text and "Total EUR 5,760.00." in text
    assert text.endswith("Prepared 12 Oct 2026.")  # D0 03:25 UTC is 08:55 in Asia/Kolkata


def test_hinglish_recording_is_labelled_untested_and_takes_the_same_path(voice: Voice) -> None:
    submitted, detail = _say_by_voice(voice, "hinglish_usual_oak_tray")
    assert submitted["utterance"]["language"] == "hinglish" and submitted["utterance"]["untested_language"] is True
    assert tool_calls(detail) == EXPECTED_TOOLS


def test_same_utterance_id_one_turn(voice: Voice, world: World) -> None:
    """SCN-J1: the edited final transcript is sent twice (double tap, retry after a blip, queued offline draft):
    one turn, one run, the same ids, and only one draft."""
    utterance = voice.transcribe(fixture_audio("usual_oak_tray")).json()
    edited = "Prepare Nordhaus's usual oak tray quote please"
    first = voice.submit(utterance["id"], edited)
    again = voice.submit(utterance["id"], edited)
    retry_upload = voice.transcribe(fixture_audio("usual_oak_tray"), utterance_id=uuid.UUID(utterance["id"]))
    assert first.status_code == again.status_code == 202
    assert first.json()["turn"]["turn_id"] == again.json()["turn"]["turn_id"]
    assert first.json()["turn"]["run_id"] == again.json()["turn"]["run_id"] and again.json()["turn"]["replayed"] is True
    assert retry_upload.status_code == 200 and retry_upload.json()["replayed"] is True
    drain()
    with UnitOfWork(world.actor(keys.USERS.MEERA)) as uow:
        turns = uow.session.scalar(select(func.count()).select_from(Turn).where(
            Turn.conversation_id == voice.conversation_id(), Turn.role == "user"))
        runs = uow.session.scalar(select(func.count()).select_from(Run).where(Run.conversation_id == voice.conversation_id()))
        row = uow.session.get(VoiceUtterance, uuid.UUID(utterance["id"]))
    assert turns == 1 and runs == 1
    assert row is not None and row.edited is True and row.submitted_text == edited and row.transcript != edited


def test_only_a_final_transcript_can_be_sent(voice: Voice) -> None:
    failed = voice.transcribe(_wav(0.5), language="hi-IN")
    assert failed.status_code == 200
    # the Demo adapter answers unknown recordings with its scripted phrase, flagged as simulated
    assert failed.json()["simulated"] is True and failed.json()["confidence"] == 0.0
    unknown = voice.submit(str(uuid.uuid7()), "anything")
    assert unknown.status_code == 404


def test_recordings_are_checked_by_magic_bytes_size_and_length(voice: Voice) -> None:
    mp3 = voice.transcribe(b"ID3\x03\x00\x00\x00" + b"\x00" * 200, mime="audio/webm")
    assert mp3.status_code == 415 and mp3.json()["code"] == "unsupported_media_type"
    long = voice.transcribe(_wav(61))
    assert long.status_code == 422 and long.json()["code"] == "audio_too_long"
    v4 = voice.transcribe(fixture_audio("usual_oak_tray"), utterance_id=uuid.uuid4())
    assert v4.status_code == 422 and v4.json()["code"] == "invalid_utterance_id"
    webm_claimed_long = voice.transcribe(b"\x1a\x45\xdf\xa3" + b"\x42\x82\x84webm" + b"\x00" * 100, duration_ms=70_000)
    assert webm_claimed_long.status_code == 422 and webm_claimed_long.json()["code"] == "audio_too_long"


def test_correction_after_submission_is_a_new_turn_that_revises_the_draft(voice: Voice) -> None:
    first, detail = _say_by_voice(voice, "usual_oak_tray")
    card = cards_of(detail, "quote_draft")[0]
    line_id, quote_id = card["lines"][0]["line_id"], card["quote_id"]
    context = {
        "schema_version": 1,
        "route": {"path": "/sales/quotes/[quoteId]", "params": {"quoteId": quote_id}, "area": "sales"},
        "focus": {"type": "sales.quote_line", "id": line_id, "version": 1},
        "records": [{"type": "sales.quote", "id": quote_id, "version": 1, "role": "primary"}],
    }
    correction, revised = _say_by_voice(voice, "change_to_300", context=context,
                                        corrects_turn_id=first["turn"]["turn_id"])
    assert correction["turn"]["turn_id"] != first["turn"]["turn_id"]
    assert correction["utterance"]["corrects_turn_id"] == first["turn"]["turn_id"]
    assert revised["run"]["status"] == "succeeded", revised
    assert Decimal(cards_of(revised, "quote_draft")[0]["totals"]["grand_total"]) == Decimal("7200.00")
    bad = voice.submit(voice.transcribe(fixture_audio("change_to_300")).json()["id"], "change it to 300",
                       corrects_turn_id=str(uuid.uuid7()))
    assert bad.status_code == 422 and bad.json()["code"] == "invalid_correction"


def test_ambiguous_customer_by_voice_asks_for_clarification(voice: Voice, world: World) -> None:
    with UnitOfWork(world.actor(keys.USERS.MEERA)) as uow:
        parties.create_party(uow, PartyCreate(
            legal_name="Nordhaus Logistik AG", display_name="Nordhaus Logistik AG", country_code="CH",
            default_currency="EUR", customer_type="standard", roles=["customer"],  # type: ignore[arg-type]
            owner_user_id=world.user_id(keys.USERS.MEERA),
        ))
    _, detail = _say_by_voice(voice, "usual_oak_tray")
    assert tool_calls(detail) == ["resolve_party", "ask_clarification"]
    assert len(cards_of(detail, "clarification")[0]["options"]) == 2


def test_voice_readback_required_before_confirm(voice: Voice, world: World, frozen_clock: FrozenClock) -> None:
    """A voice confirm without a presented read-back, after its 10-minute expiry, or after the record changed is
    refused (409 ``readback_required``); a fresh read-back is consumed once."""
    _, detail = _say_by_voice(voice, "usual_oak_tray")
    quote_id = uuid.UUID(cards_of(detail, "quote_draft")[0]["quote_id"])
    actor = world.actor(keys.USERS.MEERA)

    def confirm() -> str | None:
        try:
            with UnitOfWork(actor) as uow:
                readback_mod.require_presented_readback(uow, "sales.quote", quote_id, action="sales.quote.submit")
        except Exception as exc:  # noqa: BLE001
            return f"{getattr(exc, 'code', type(exc).__name__)}:{getattr(exc, 'extra', {}).get('reason')}"
        return None

    assert confirm() == "readback_required:missing"
    with UnitOfWork(actor) as uow:
        readback_mod.present(uow, "sales.quote", quote_id)
    assert confirm() is None
    assert confirm() == "readback_required:missing", "a read-back is consumed by one confirm"
    with UnitOfWork(actor) as uow:
        readback_mod.present(uow, "sales.quote", quote_id)
    frozen_clock.advance(minutes=11)
    assert confirm() == "readback_required:expired"
    with UnitOfWork(actor) as uow:
        readback_mod.present(uow, "sales.quote", quote_id)
    from app.modules.sales.models import QuoteLine

    with UnitOfWork(actor) as uow:
        line = uow.session.scalars(select(QuoteLine).where(QuoteLine.quote_id == quote_id)).first()
        assert line is not None
        line.quantity = Decimal("300")
    assert confirm() == "readback_required:changed"


def test_speech_is_owner_only_and_short_lived(voice: Voice, world: World, frozen_clock: FrozenClock) -> None:
    response = voice.client.post(f"{API}/voice/speech", json={"text": "Draft ready, not sent."}, headers=voice.headers)
    assert response.status_code == 201, response.text
    speech = response.json()
    assert speech["provider_label"] == "Demo" and speech["mime_type"] == "audio/wav" and "?" not in speech["url"]
    audio = voice.client.get(speech["url"], headers=voice.headers)
    assert audio.status_code == 200 and audio.headers["content-type"] == "audio/wav"
    assert audio.headers["cache-control"] == "no-store" and audio.content[:4] == b"RIFF"
    other = voice.client.get(speech["url"], headers={"x-test-persona": keys.USERS.ARJUN})
    assert other.status_code == 404
    frozen_clock.advance(minutes=6)
    expired = voice.client.get(speech["url"], headers=voice.headers)
    assert expired.status_code == 404 and expired.json()["code"] == "speech_expired"
    with UnitOfWork(world.actor(keys.USERS.MEERA)) as uow:
        row = uow.session.get(VoiceSpeech, uuid.UUID(speech["id"]))
        assert row is not None and not hasattr(row, "text")  # only the text's hash is stored


def test_audio_is_purged_after_seven_days(voice: Voice, world: World, media_storage: object, frozen_clock: FrozenClock) -> None:
    utterance = voice.transcribe(fixture_audio("usual_oak_tray")).json()
    speech = voice.client.post(f"{API}/voice/speech", json={"text": "hello"}, headers=voice.headers).json()
    with UnitOfWork(world.actor(keys.USERS.MEERA)) as uow:
        row = uow.session.get(VoiceUtterance, uuid.UUID(utterance["id"]))
        assert row is not None
        key = row.audio_key
    assert key is not None and media_storage.exists(key)  # type: ignore[attr-defined]
    frozen_clock.advance(days=6)
    from app.platform.authz.context import ActorContext

    with UnitOfWork(ActorContext.system(world.company_id)) as uow:
        assert voice_service.purge_due(uow) == 0
    frozen_clock.advance(days=1, minutes=1)
    with UnitOfWork(ActorContext.system(world.company_id)) as uow:
        assert voice_service.purge_due(uow) == 2
    with UnitOfWork(world.actor(keys.USERS.MEERA)) as uow:
        row = uow.session.get(VoiceUtterance, uuid.UUID(utterance["id"]))
        spoken = uow.session.get(VoiceSpeech, uuid.UUID(speech["id"]))
        assert row is not None and row.audio_key is None and row.audio_purged_at is not None and row.transcript
        assert spoken is not None and spoken.audio_key is None
    assert not media_storage.exists(key)  # type: ignore[attr-defined]


def test_browser_fallback_is_off_by_default_and_labelled_when_on(voice: Voice, monkeypatch: pytest.MonkeyPatch) -> None:
    body = {"id": str(uuid.uuid7()), "text": "Prepare Nordhaus's usual oak tray quote", "language": "en-IN"}
    off = voice.client.post(f"{API}/voice/utterances", json=body, headers=voice.headers)
    assert off.status_code == 409 and off.json()["code"] == "not_configured"
    monkeypatch.setattr(get_voice_settings(), "browser_fallback", True)
    on = voice.client.post(f"{API}/voice/utterances", json=body, headers=voice.headers)
    assert on.status_code == 201, on.text
    assert on.json()["provider_label"] == "Browser fallback" and on.json()["source"] == "browser"
    sent = voice.submit(on.json()["id"], on.json()["text"])
    assert sent.status_code == 202


def test_vendor_adapter_fails_visibly_and_production_needs_more_than_the_browser(
    voice: Voice, monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_voice_settings()
    monkeypatch.setattr(settings, "stt_provider", "vendor")
    response = voice.transcribe(fixture_audio("usual_oak_tray"))
    assert response.status_code == 409 and response.json()["code"] == "not_configured"
    assert voice_service.readiness() == ("not_configured", True)
    monkeypatch.setattr(settings, "stt_provider", "none")
    monkeypatch.setattr(settings, "browser_fallback", True)
    from app.core.config import get_settings

    assert voice_service.readiness() == ("browser_fallback_only", True)  # not production
    monkeypatch.setattr(get_settings(), "env", "production")
    assert voice_service.readiness() == ("browser_fallback_only", False)
    from app.platform.system.readiness import run_checks

    checks, healthy = run_checks()
    assert checks["voice"] == "browser_fallback_only" and healthy is False


def test_another_users_utterance_is_not_found(voice: Voice) -> None:
    utterance = voice.transcribe(fixture_audio("usual_oak_tray")).json()
    other = voice.client.get(f"{API}/voice/utterances/{utterance['id']}", headers={"x-test-persona": keys.USERS.ARJUN})
    assert other.status_code == 404
    mine = voice.client.get(f"{API}/voice/utterances/{utterance['id']}", headers=voice.headers)
    assert mine.status_code == 200 and mine.json()["status"] == "transcribed"
