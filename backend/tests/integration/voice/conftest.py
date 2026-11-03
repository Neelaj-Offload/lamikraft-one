"""Voice/vision lane fixtures: the agents lane's world, client and Assistant driver, plus a throw-away storage root
and helpers that drive the voice API as a persona."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.modules.voice.adapters.demo import FIXTURE_FILES
from tests.integration.agents.conftest import Assistant, app, client, meera, sales_tools  # noqa: F401
from tests.integration.catalogue.world import media_storage, member_actors, personas, world  # noqa: F401

API = "/api/v1"


def fixture_audio(name: str) -> bytes:
    return Path(FIXTURE_FILES[name]).read_bytes()


class Voice:
    """The voice API as one persona: transcribe a recording, submit the final transcript, ask for speech."""

    def __init__(self, assistant: Assistant) -> None:
        self.assistant = assistant
        self.client: TestClient = assistant.client
        self.headers = assistant.headers

    def conversation_id(self) -> uuid.UUID:
        if self.assistant.conversation_id is None:
            self.assistant.start()
        assert self.assistant.conversation_id is not None
        return self.assistant.conversation_id

    def transcribe(self, audio: bytes, *, utterance_id: uuid.UUID | None = None, mime: str = "audio/wav",
                   **params: Any) -> Any:
        query = {"utterance_id": str(utterance_id or uuid.uuid7()), **{k: str(v) for k, v in params.items()}}
        return self.client.post(f"{API}/voice/transcriptions", params=query, headers=self.headers,
                                files={"file": ("rec.wav", audio, mime)})

    def submit(self, utterance_id: str, text: str, **extra: Any) -> Any:
        body = {"conversation_id": str(self.conversation_id()), "text": text, **extra}
        return self.client.post(f"{API}/voice/utterances/{utterance_id}/submit", json=body, headers=self.headers)


@pytest.fixture
def voice(meera: Assistant, media_storage: object) -> Voice:  # noqa: F811
    return Voice(meera)
