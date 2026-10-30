"""SCN-B1: a source change invalidates the recommendation and keeps the stable issue id."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.modules.briefings.models import Recommendation
from app.modules.tasks import issue_keys
from app.modules.tasks.models import ChangeLog
from app.seed.world import keys
from tests.integration.briefings.test_versions_and_actions import (
    issue,
    today,
)
from tests.integration.briefings.world import FakeWorld, d0

pytestmark = pytest.mark.db


def test_stable_issue_id_and_stale_recommendation(world: FakeWorld) -> None:
    v1 = today(world, keys.USERS.MEERA)
    expiry_issue = issue(world, issue_keys.quote_expiry_key(world.refs[keys.QUOTE_REFS.BERG_EXPIRING]))
    with world.uow() as uow:
        r1 = uow.session.scalars(select(Recommendation).where(Recommendation.issue_id == expiry_issue)).one()
    world.at(d0(9, 5))
    quote = world.slice2_quote_change(keys.QUOTE_REFS.BERG_EXPIRING, revision_no=3)
    revised = world.emit_quote(keys.USERS.MEERA, "sales.quote.revised", keys.QUOTE_REFS.BERG_EXPIRING, revision_no=3)
    world.drain()
    v2 = today(world, keys.USERS.MEERA)
    assert v2.version == 2 and v2.briefing_id == v1.briefing_id
    item = next(i for i in v2.items if i.issue_id == expiry_issue)
    assert item.change_kind == "changed"  # Meera revised it herself, so it is not a "change since your visit"
    with world.uow() as uow:
        recs = {r.id: r for r in uow.session.scalars(select(Recommendation).where(Recommendation.issue_id == expiry_issue))}
        row = uow.session.scalars(select(ChangeLog).where(ChangeLog.issue_id == expiry_issue)).one()
    assert recs[r1.id].status == "stale" and recs[r1.id].invalidated_by_event_id == revised
    assert [r.status for r in recs.values() if r.id != r1.id] == ["active"]
    assert item.recommendation is not None and item.recommendation.id != r1.id
    assert (row.ref_id, row.ref_version, row.after, row.event_id) == (quote.id, quote.version, {"revision_no": 3}, revised)
