"""SCN-A3: a restricted employee's briefing carries nothing about other people's records."""

from __future__ import annotations

import json

import pytest

from app.seed.world import keys
from app.seed.world import tasks as seed_tasks
from tests.integration.briefings.test_expected_briefings import today
from tests.integration.briefings.world import FakeWorld

pytestmark = pytest.mark.db


def test_kabir_sees_only_his_task(world: FakeWorld) -> None:
    """A-10: no customer names, amounts or foreign counts anywhere in Kabir's payload."""
    view = today(world, keys.USERS.KABIR)
    payload = json.loads(view.model_dump_json())
    text = json.dumps(payload)
    for name in keys.PARTY_NAMES.values():
        assert name not in text
    for token in ("EUR", "GBP", keys.QUOTES.BERG_EXPIRING, "5700", "decision"):
        assert token not in text
    assert payload["overview"]["facts"] == {"tasks_due_today": 1, "assigned_tasks": 1}  # his own item only
    assert [i["title"] for i in payload["items"]] == [seed_tasks.TASK_KABIR_COUNT_TITLE]
