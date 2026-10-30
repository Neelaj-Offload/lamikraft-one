"""SCN-C2: an agent-drafted quote creates a correctly scoped next action (Meera only)."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.modules.tasks import issue_keys
from app.modules.tasks.models import Task
from app.seed.world import keys
from tests.integration.briefings.test_versions_and_actions import (
    current_version,
    issue,
    today,
)
from tests.integration.briefings.world import FakeWorld, d0

pytestmark = pytest.mark.db


def test_review_task_for_meera_only(world: FakeWorld) -> None:
    """[C] Meera's assistant drafts LK-QT-2026-0009: a review_draft for Meera due Today 18:30; Neha and
    Kabir are unaffected; Meera's open briefing gains a version."""
    meera = today(world, keys.USERS.MEERA)
    neha = today(world, keys.USERS.NEHA)
    kabir = today(world, keys.USERS.KABIR)
    world.at(d0(9, 10))
    q = world._quote("Q_SCENARIO_C", keys.QUOTES.SCENARIO_C_NEW, "NORDHAUS", keys.USERS.MEERA, "draft", "5760.00", "EUR", d0(9, 10))
    world.emit_quote(keys.USERS.MEERA, "sales.quote.created", "Q_SCENARIO_C", agent=True, quote_number=q.number,
                     owner_user_id=str(world.refs[keys.USERS.MEERA]), party_id=str(world.refs["NORDHAUS"]))
    world.drain()
    review = issue(world, issue_keys.quote_review_key(q.id))
    with world.uow() as uow:
        (task,) = uow.session.scalars(select(Task).where(Task.issue_id == review)).all()
    assert (task.kind, task.owner_user_id, task.assignee_user_id) == ("review_draft",) + (world.refs[keys.USERS.MEERA],) * 2
    after = today(world, keys.USERS.MEERA)
    item = next(i for i in after.items if i.issue_id == review)
    assert after.version == meera.version + 1 and item.section == "plan_for_today" and item.due_label == "Today 18:30"
    assert item.recommendation is not None and set(item.recommendation.alternatives) <= {a.action for a in item.allowed_actions}
    assert current_version(world, neha.briefing_id) == neha.version  # type: ignore[arg-type]
    assert current_version(world, kabir.briefing_id) == kabir.version  # type: ignore[arg-type]
