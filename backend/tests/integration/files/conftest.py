from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.platform.files.storage import LocalFsStorage, set_storage
from tests.integration.org.platform_lane import ApiClient, api_client
from tests.support import create_company


@pytest.fixture
def company(db: None) -> tuple[uuid.UUID, uuid.UUID]:
    return create_company()


@pytest.fixture
def api(db: None, monkeypatch: pytest.MonkeyPatch) -> Iterator[ApiClient]:
    with api_client(monkeypatch) as client:
        yield client


@pytest.fixture(autouse=True)
def storage(tmp_path: Path) -> Iterator[LocalFsStorage]:
    """A throw-away local storage root per test (LK_STORAGE_DIR is never touched)."""
    backend = LocalFsStorage(tmp_path / "storage")
    set_storage(backend)
    yield backend
    set_storage(None)
