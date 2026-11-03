"""Voice units: audio containers by magic bytes and the 60 s / 10 MB bounds, Demo STT/TTS, read-back money words."""

from __future__ import annotations

import io
import wave
from decimal import Decimal
from pathlib import Path

import pytest

from app.core.errors import ValidationFailed
from app.modules.voice.adapters.base import AdapterUnavailable
from app.modules.voice.adapters.demo import DEMO_PHRASE, FIXTURE_FILES, DemoSTT, DemoTTS
from app.modules.voice.adapters.vendor import VendorSTT
from app.modules.voice.audio import check_audio, sniff_audio, wav_duration_ms
from app.modules.voice.readback import money_words
from app.platform.files.errors import UnsupportedMediaType


def _wav(seconds: float) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(8000)
        out.writeframes(b"\x00\x00" * int(8000 * seconds))
    return buffer.getvalue()


@pytest.mark.parametrize(
    ("head", "kind"),
    [
        (b"\x1a\x45\xdf\xa3\x9f\x42\x86\x81\x01\x42\x82\x84webm", "webm"),
        (b"OggS\x00\x02" + b"\x00" * 22 + b"OpusHead\x01", "ogg"),
        (b"\x00\x00\x00\x20ftypM4A \x00\x00\x00\x00", "mp4"),
        (b"RIFF\x24\x00\x00\x00WAVEfmt ", "wav"),
    ],
)
def test_containers_are_recognised_by_magic_bytes(head: bytes, kind: str) -> None:
    assert sniff_audio(head) == kind


@pytest.mark.parametrize("head", [b"ID3\x03", b"OggS" + b"\x00" * 24 + b"vorbis", b"\x1a\x45\xdf\xa3matroska", b"<html>"])
def test_other_bytes_are_rejected(head: bytes) -> None:
    with pytest.raises(UnsupportedMediaType):
        sniff_audio(head)


def test_wav_duration_is_measured_and_bounded() -> None:
    assert wav_duration_ms(_wav(1.5)) == 1500
    assert check_audio(_wav(59.9), declared_duration_ms=None) == ("wav", 59900)
    with pytest.raises(ValidationFailed) as long:
        check_audio(_wav(60.5), declared_duration_ms=1000)  # the measured duration wins over the client's
    assert long.value.code == "audio_too_long"
    with pytest.raises(ValidationFailed) as big:
        check_audio(b"RIFF" + b"\x00" * (10 * 1024 * 1024), declared_duration_ms=None)
    assert big.value.code == "audio_too_large"


def test_demo_stt_uses_fixture_hashes_and_labels_unknown_recordings() -> None:
    import hashlib

    data = Path(FIXTURE_FILES["usual_oak_tray"]).read_bytes()
    known = DemoSTT().transcribe(data, "audio/wav", "en-IN", hashlib.sha256(data).hexdigest())
    assert known.text == DEMO_PHRASE and known.simulated is False and known.confidence and known.confidence > 0.9
    assert [s.text for s in known.segments][:2] == ["Prepare", "Nordhaus's"]
    unknown = DemoSTT().transcribe(b"x", "audio/webm", "en-IN", "0" * 64)
    assert unknown.simulated is True and unknown.confidence == 0.0
    hinglish = Path(FIXTURE_FILES["hinglish_usual_oak_tray"]).read_bytes()
    assert DemoSTT().transcribe(hinglish, "audio/wav", "hinglish", hashlib.sha256(hinglish).hexdigest()).language == "hinglish"


def test_demo_tts_is_a_silent_wav_sized_to_the_text() -> None:
    speech = DemoTTS().speak("Draft ready, not sent.", "en-IN")
    assert speech.mime_type == "audio/wav" and speech.audio[:4] == b"RIFF"
    assert speech.duration_ms == 1200 and wav_duration_ms(speech.audio) == 1200
    assert DemoTTS().speak("word " * 100, "en-IN").duration_ms == 8000


def test_vendor_adapter_is_not_configured() -> None:
    adapter = VendorSTT()
    assert adapter.status() == "not_configured"
    with pytest.raises(AdapterUnavailable) as caught:
        adapter.transcribe(b"", "audio/wav", "en-IN", "0" * 64)
    assert caught.value.code == "not_configured"


@pytest.mark.parametrize(
    ("amount", "currency", "unit", "expected"),
    [
        (Decimal("5760.0000"), "EUR", False, "EUR 5,760.00"),
        (Decimal("24.0000"), "EUR", True, "EUR 24.00"),
        (Decimal("0.0450"), "EUR", True, "EUR 0.045"),
        (Decimal("123456.5"), "INR", False, "INR 1,23,456.50"),
        (Decimal("-12.5"), "USD", False, "USD -12.50"),
        (None, "EUR", True, "not priced"),
    ],
)
def test_readback_money_words(amount: Decimal | None, currency: str, unit: bool, expected: str) -> None:
    assert money_words(amount, currency, unit_price=unit) == expected
