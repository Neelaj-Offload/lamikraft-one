from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest

from tests.integration.org.platform_lane import ApiClient, api_client
from tests.support import create_company


@pytest.fixture
def company(db: None) -> tuple[uuid.UUID, uuid.UUID]:
    """(company_id, head-office branch_id) of a fresh test tenant."""
    return create_company()


@pytest.fixture
def api(db: None, monkeypatch: pytest.MonkeyPatch) -> Iterator[ApiClient]:
    with api_client(monkeypatch) as client:
        yield client
