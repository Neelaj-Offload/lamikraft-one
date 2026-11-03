"""Voice service (design section 14): utterances, transcription, submission as an assistant turn, spoken replies,
read-backs, purge, capabilities and readiness.

Rules carried here:
- The utterance id is the client's UUIDv7 (created on press). Upload retries, resends and offline drafts reuse it;
  the row and the agents turn are idempotent on it, so a corrected transcript never submits twice.
- Partial transcripts never reach the server; only a final transcript (``transcribed``) can be submitted, and the
  submitted text may be the person's edit of it (``edited``). A correction after submission is a new utterance and a
  new turn carrying ``corrects_turn_id``.
- No transaction is held across an adapter call: the row and its audio are committed first, the adapter runs, then
  the outcome is recorded in a second unit of work.
- Audio (uploaded and synthesised) is purged after 7 days; speech URLs are valid for 5 minutes and only for the
  owner's session (no token in the URL).
"""

from __future__ import annotations

import hashlib
import tempfile
import uuid
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from app.core.config import get_settings
from app.core.errors import Conflict, Forbidden, NotConfigured, NotFound, ValidationFailed
from app.core.logging import get_logger
from app.modules.voice import adapters
from app.modules.voice.adapters.base import AdapterUnavailable, Transcription
from app.modules.voice.audio import MAX_AUDIO_BYTES, MAX_AUDIO_MS, MIME_TYPES, check_audio
from app.modules.voice.models import (
    UtteranceSource,
    UtteranceStatus,
    VoiceReadback,
    VoiceSpeech,
    VoiceUtterance,
)
from app.modules.voice.schemas import (
    AdapterInfo,
    BrowserUtteranceCreate,
    LanguageOption,
    ReadbackOut,
    Segment,
    SpeechCreate,
    SpeechOut,
    UtteranceOut,
    UtteranceSubmit,
    UtteranceSubmitted,
    VoiceCapabilities,
)
from app.platform.files.storage import get_storage, new_storage_key, staging_dir
from app.platform.uow import UnitOfWork

if TYPE_CHECKING:
    from app.platform.authz.context import ActorContext

log = get_logger("lk.voice")

ASSISTANT_USE = "agents.assistant.use"
SPEECH_USE = "voice.speech.use"
AUDIO_RETENTION = timedelta(days=7)
SPEECH_URL_TTL = timedelta(minutes=5)
LANGUAGES = (
    LanguageOption(code="en-IN", label="English (India)", tested=True, status_label="Demo phrases only"),
    LanguageOption(code="hi-IN", label="Hindi", tested=False, status_label="Untested"),
    LanguageOption(code="hinglish", label="Hinglish", tested=False, status_label="Untested"),
)
UNTESTED = {lang.code for lang in LANGUAGES if not lang.tested}


# ---- access and preferences ------------------------------------------------------------------------------------
def _require(uow: UnitOfWork, permission: str = ASSISTANT_USE) -> uuid.UUID:
    uow.actor.require(permission)
    if uow.actor.user_id is None:
        raise Forbidden(code="permission_denied", permission=permission)
    return uow.actor.user_id


def _voice_preferences(uow: UnitOfWork) -> dict[str, Any]:
    from app.platform.identity.models import UserPreference
    from app.platform.identity.preferences import VoicePreferences

    row = uow.session.get(UserPreference, uow.actor.user_id) if uow.actor.user_id else None
    return VoicePreferences.model_validate((row.voice if row is not None else None) or {}).model_dump()


def _require_uuid7(value: uuid.UUID) -> None:
    if value.version != 7:
        raise ValidationFailed(
            "The utterance id must be a UUIDv7 created when push-to-talk was pressed.", code="invalid_utterance_id",
            errors=[{"loc": ["utterance_id"], "msg": "not a UUIDv7", "type": "invalid_utterance_id"}],
        )


# ---- capabilities and readiness --------------------------------------------------------------------------------
def _info(adapter: Any, fallback_label: str) -> AdapterInfo:
    if adapter is None:
        return AdapterInfo(provider="none", label=fallback_label, status="off")
    return AdapterInfo(provider=adapter.name, label=adapter.label, status=adapter.status())


def stt_available() -> bool:
    """A usable speech-to-text path exists (Demo, an implemented vendor, or the enabled browser fallback)."""
    stt = adapters.stt_adapter()
    return (stt is not None and stt.status() in ("demo", "configured")) or adapters.browser_fallback().enabled


def capabilities(uow: UnitOfWork) -> VoiceCapabilities:
    _require(uow)
    prefs = _voice_preferences(uow)
    browser = adapters.browser_fallback()
    return VoiceCapabilities(
        available=stt_available(),
        stt=_info(adapters.stt_adapter(), "Speech-to-text off"),
        tts=_info(adapters.tts_adapter(), "Spoken replies off"),
        browser_fallback=AdapterInfo(provider=browser.name, label=browser.label, status=browser.status()),
        can_speak=uow.actor.can(SPEECH_USE),
        languages=list(LANGUAGES),
        max_seconds=MAX_AUDIO_MS // 1000,
        max_bytes=MAX_AUDIO_BYTES,
        accepted_types=sorted(MIME_TYPES.values()) + ["audio/ogg;codecs=opus", "audio/webm;codecs=opus"],
        speech_language=prefs["speech_language"],
        speak_responses=prefs["speak_responses"],
        read_back_values=prefs["read_back_values"],
    )


def readiness() -> tuple[str, bool]:
    """``/health/ready`` check ``voice``: production fails when the browser fallback is the only STT path."""
    stt = adapters.stt_adapter()
    server_stt = stt is not None and stt.status() in ("demo", "configured")
    browser_only = not server_stt and adapters.browser_fallback().enabled
    if browser_only:
        return "browser_fallback_only", not get_settings().is_production
    if stt is not None and stt.status() == "not_configured":
        return "not_configured", True
    return ("ok" if server_stt else "off"), True


# ---- utterances ------------------------------------------------------------------------------------------------
def _out(row: VoiceUtterance, *, replayed: bool = False) -> UtteranceOut:
    label = {"demo": "Demo", "browser": "Browser fallback", "vendor": "Speech vendor"}.get(row.provider, row.provider)
    return UtteranceOut(
        id=row.id, status=row.status, source=row.source, provider_label=label,  # type: ignore[arg-type]
        text=row.transcript or "", language=row.language, confidence=row.confidence,
        segments=[Segment(**s) for s in row.segments or []], simulated=row.simulated,
        untested_language=row.language in UNTESTED, duration_ms=row.duration_ms, error_code=row.error_code,
        turn_id=row.turn_id, run_id=row.run_id, corrects_turn_id=row.corrects_turn_id, replayed=replayed,
    )


def _own_utterance(uow: UnitOfWork, utterance_id: uuid.UUID, *, for_update: bool = False) -> VoiceUtterance | None:
    stmt = select(VoiceUtterance).where(
        VoiceUtterance.company_id == uow.actor.company_id, VoiceUtterance.id == utterance_id,
    )
    row = uow.session.scalars(stmt.with_for_update() if for_update else stmt).first()
    if row is not None and row.user_id != uow.actor.user_id:
        raise NotFound(code="not_found", resource_type="voice.utterance")
    return row


def get_utterance(uow: UnitOfWork, utterance_id: uuid.UUID) -> UtteranceOut:
    _require(uow)
    row = _own_utterance(uow, utterance_id)
    if row is None:
        raise NotFound(code="not_found", resource_type="voice.utterance")
    return _out(row)


@dataclass(frozen=True)
class _Pending:
    utterance_id: uuid.UUID
    audio: bytes
    mime: str
    language: str
    sha256: str


def transcribe_upload(
    actor: ActorContext, *, utterance_id: uuid.UUID, path: Path, sha256: str, size: int, declared_duration_ms: int | None,
    conversation_id: uuid.UUID | None, language: str,
) -> UtteranceOut:
    """Store the recording and its utterance row, run the STT adapter outside the transaction, record the result.

    A second upload with the same utterance id returns the stored outcome (``replayed``) without transcribing again.
    """
    _require_uuid7(utterance_id)
    if size > MAX_AUDIO_BYTES:
        raise ValidationFailed("The recording is larger than 10 MB.", code="audio_too_large")
    data = path.read_bytes()
    kind, duration = check_audio(data, declared_duration_ms=declared_duration_ms)
    stt = adapters.stt_adapter()
    if stt is None or stt.status() not in ("demo", "configured"):
        reason = "browser_fallback_client_side" if adapters.browser_fallback().enabled else "not_configured"
        raise NotConfigured("Server speech-to-text is not configured.", integration="voice.stt", reason=reason)
    pending: _Pending | None = None
    with UnitOfWork(actor) as uow:
        user_id = _require(uow)
        existing = _own_utterance(uow, utterance_id, for_update=True)
        if existing is not None and existing.status in (UtteranceStatus.TRANSCRIBED.value, UtteranceStatus.SUBMITTED.value):
            return _out(existing, replayed=True)
        key = existing.audio_key if existing is not None and existing.audio_key else new_storage_key(uow.actor.company_id)  # type: ignore[arg-type]
        if existing is None:
            storage = get_storage()
            storage.put_file(key, path)
            try:
                uow.add(VoiceUtterance(
                    id=utterance_id, user_id=user_id, conversation_id=conversation_id,
                    status=UtteranceStatus.RECEIVED.value, source=UtteranceSource.SERVER.value, provider=stt.name,
                    language=language, duration_ms=duration, audio_key=key, audio_sha256=sha256,
                    audio_mime=MIME_TYPES[kind], audio_bytes=size, purge_at=uow.now() + AUDIO_RETENTION, segments=[],
                ))
                uow.flush()
            except Exception:
                storage.delete(key)
                raise
        pending = _Pending(utterance_id, data, MIME_TYPES[kind], language, sha256)
    assert pending is not None
    try:
        result: Transcription | None = stt.transcribe(pending.audio, pending.mime, pending.language, pending.sha256)
        error: str | None = None
    except AdapterUnavailable as exc:
        result, error = None, exc.code
    with UnitOfWork(actor) as uow:
        row = _own_utterance(uow, utterance_id, for_update=True)
        assert row is not None
        if row.status in (UtteranceStatus.TRANSCRIBED.value, UtteranceStatus.SUBMITTED.value):
            return _out(row, replayed=True)  # a concurrent upload of the same utterance finished first
        if result is None or not result.text.strip():
            row.status = UtteranceStatus.FAILED.value
            row.error_code = error or "no_speech"
        else:
            row.status = UtteranceStatus.TRANSCRIBED.value
            row.transcript = result.text.strip()
            row.language = result.language
            row.confidence = result.confidence
            row.segments = [{"start_ms": s.start_ms, "end_ms": s.end_ms, "text": s.text} for s in result.segments]
            row.simulated = result.simulated
            row.error_code = None
        uow.flush()
        return _out(row)


def create_browser_utterance(uow: UnitOfWork, data: BrowserUtteranceCreate) -> UtteranceOut:
    """The browser fallback's final transcript (off by default; labelled "Browser fallback")."""
    user_id = _require(uow)
    _require_uuid7(data.id)
    if not adapters.browser_fallback().enabled:
        raise NotConfigured("The browser fallback is switched off.", integration="voice.stt", reason="browser_fallback_off")
    existing = _own_utterance(uow, data.id, for_update=True)
    if existing is not None:
        return _out(existing, replayed=True)
    row = VoiceUtterance(
        id=data.id, user_id=user_id, conversation_id=data.conversation_id, status=UtteranceStatus.TRANSCRIBED.value,
        source=UtteranceSource.BROWSER.value, provider="browser", language=data.language, confidence=data.confidence,
        duration_ms=data.duration_ms, transcript=data.text, segments=[], purge_at=uow.now() + AUDIO_RETENTION,
    )
    uow.add(row)
    uow.flush()
    return _out(row)


def submit_utterance(uow: UnitOfWork, utterance_id: uuid.UUID, data: UtteranceSubmit) -> UtteranceSubmitted:
    """Send the final (possibly edited) transcript as one agents turn with ``client_utterance_id`` = the utterance
    id. Resending — the same button twice, a retry after a network blip, a queued offline draft — returns the same
    turn and run."""
    from app.modules.agents import service as agents
    from app.modules.agents.models import Turn
    from app.modules.agents.schemas import TurnCreate

    _require(uow)
    row = _own_utterance(uow, utterance_id, for_update=True)
    if row is None:
        raise NotFound(code="not_found", resource_type="voice.utterance")
    if row.status not in (UtteranceStatus.TRANSCRIBED.value, UtteranceStatus.SUBMITTED.value):
        raise Conflict("Only a final transcript can be sent.", code="utterance_not_final", status=row.status)
    if row.conversation_id is not None and row.conversation_id != data.conversation_id:
        raise Conflict("This utterance belongs to another conversation.", code="utterance_conversation_mismatch")
    conversation = agents.own_conversation(uow, data.conversation_id)
    if row.status == UtteranceStatus.SUBMITTED.value and row.turn_id is not None:
        accepted = agents.create_turn(uow, conversation.id, TurnCreate(text=row.submitted_text or data.text,
                                                                        client_utterance_id=row.id))
        return UtteranceSubmitted(utterance=_out(row, replayed=True), turn=accepted)
    if data.corrects_turn_id is not None:
        corrected = uow.session.scalars(select(Turn).where(
            Turn.id == data.corrects_turn_id, Turn.conversation_id == conversation.id, Turn.role == "user",
        )).first()
        if corrected is None:
            raise ValidationFailed("The corrected turn is not in this conversation.", code="invalid_correction",
                                   errors=[{"loc": ["body", "corrects_turn_id"], "msg": "unknown turn", "type": "invalid_correction"}])
    accepted = agents.create_turn(uow, conversation.id, TurnCreate(text=data.text, context=data.context,
                                                                    client_utterance_id=row.id))
    row.conversation_id = conversation.id
    row.status = UtteranceStatus.SUBMITTED.value
    row.submitted_text = data.text
    row.edited = data.text != (row.transcript or "")
    row.turn_id = accepted.turn_id
    row.run_id = accepted.run_id
    row.corrects_turn_id = data.corrects_turn_id
    row.submitted_at = uow.now()
    uow.flush()
    return UtteranceSubmitted(utterance=_out(row, replayed=accepted.replayed), turn=accepted)


# ---- spoken replies ----------------------------------------------------------------------------------------------
def speak(actor: ActorContext, data: SpeechCreate) -> SpeechOut:
    with UnitOfWork(actor) as uow:
        _require(uow, SPEECH_USE)
        language = data.language or _voice_preferences(uow)["speech_language"]
    tts = adapters.tts_adapter()
    if tts is None or tts.status() not in ("demo", "configured"):
        raise NotConfigured("Spoken replies are not configured.", integration="voice.tts")
    try:
        speech = tts.speak(data.text, language)
    except AdapterUnavailable as exc:
        raise NotConfigured(str(exc), integration="voice.tts", reason=exc.code) from exc
    with UnitOfWork(actor) as uow:
        user_id = _require(uow, SPEECH_USE)
        storage = get_storage()
        key = new_storage_key(uow.actor.company_id)  # type: ignore[arg-type]
        fd, tmp = tempfile.mkstemp(prefix="speech-", suffix=".part", dir=staging_dir())
        try:
            with open(fd, "wb") as fh:
                fh.write(speech.audio)
            storage.put_file(key, Path(tmp))
        finally:
            Path(tmp).unlink(missing_ok=True)
        now = uow.now()
        row = VoiceSpeech(
            id=uuid.uuid7(), user_id=user_id, provider=tts.name, language=language,
            text_sha256=hashlib.sha256(data.text.encode()).hexdigest(), chars=len(data.text), audio_key=key,
            audio_mime=speech.mime_type, audio_bytes=len(speech.audio), duration_ms=speech.duration_ms,
            url_expires_at=now + SPEECH_URL_TTL, purge_at=now + AUDIO_RETENTION,
        )
        uow.add(row)
        try:
            uow.flush()
        except Exception:
            storage.delete(key)
            raise
        return SpeechOut(id=row.id, url=f"/api/v1/voice/speech/{row.id}/audio", expires_at=row.url_expires_at,
                         mime_type=row.audio_mime, duration_ms=row.duration_ms, provider_label=tts.label)


def speech_audio(uow: UnitOfWork, speech_id: uuid.UUID) -> tuple[bytes, str]:
    user_id = _require(uow, SPEECH_USE)
    row = uow.session.scalars(select(VoiceSpeech).where(
        VoiceSpeech.company_id == uow.actor.company_id, VoiceSpeech.id == speech_id, VoiceSpeech.user_id == user_id,
    )).first()
    if row is None or row.audio_key is None:
        raise NotFound(code="not_found", resource_type="voice.speech")
    if row.url_expires_at <= uow.now():
        raise NotFound("This spoken reply has expired.", code="speech_expired", resource_type="voice.speech")
    with get_storage().open(row.audio_key) as fh:
        return fh.read(), row.audio_mime


# ---- read-back ---------------------------------------------------------------------------------------------------
def present_readback(uow: UnitOfWork, subject_type: str, subject_id: uuid.UUID) -> ReadbackOut:
    from app.modules.voice import readback

    _require(uow)
    row: VoiceReadback = readback.present(uow, subject_type, subject_id)
    return ReadbackOut(id=row.id, subject_type=row.subject_type, subject_id=row.subject_id,
                       subject_version=row.subject_version, text=row.text, presented_at=row.presented_at,
                       expires_at=row.expires_at)


# ---- purge -------------------------------------------------------------------------------------------------------
def purge_due(uow: UnitOfWork) -> int:
    """``voice.audio.purge``: recordings and synthesised replies older than 7 days lose their audio (one company)."""
    now = uow.now()
    storage = get_storage()
    count = 0
    for model in (VoiceUtterance, VoiceSpeech):
        rows = list(uow.session.scalars(
            select(model).where(model.company_id == uow.actor.company_id, model.audio_key.is_not(None),
                                model.purge_at <= now).limit(500).with_for_update(skip_locked=True)
        ))
        for row in rows:
            key = row.audio_key
            row.audio_key = None
            row.audio_purged_at = now
            if key:
                uow.after_commit(lambda k=key: storage.delete(k))
            count += 1
    return count


# ---- WhatsApp voice notes (channels seam) ------------------------------------------------------------------------
def whatsapp_transcriber(data: bytes, mime_type: str | None, sha256: str) -> Any:
    """``channels.whatsapp.stt.register_transcriber`` target: the configured STT adapter, with the channel's own
    Demo transcriber as the fallback for recordings this adapter does not know (Demo) or cannot handle."""
    from app.modules.channels.whatsapp import stt as wa_stt  # type: ignore[import-not-found]

    adapter = adapters.stt_adapter()
    if adapter is None or adapter.status() not in ("demo", "configured"):
        return wa_stt.demo_transcriber(data, mime_type, sha256)
    try:
        result = adapter.transcribe(data, mime_type or "audio/ogg", "en-IN", sha256)
    except AdapterUnavailable:
        return wa_stt.demo_transcriber(data, mime_type, sha256)
    if result.simulated:
        return wa_stt.demo_transcriber(data, mime_type, sha256)
    return wa_stt.Transcript(text=result.text, language=result.language, confidence=result.confidence,
                             provider_label=adapter.label, empty=not result.text.strip())


__all__ = [
    "capabilities",
    "create_browser_utterance",
    "get_utterance",
    "present_readback",
    "purge_due",
    "readiness",
    "speak",
    "speech_audio",
    "stt_available",
    "submit_utterance",
    "transcribe_upload",
    "whatsapp_transcriber",
]
