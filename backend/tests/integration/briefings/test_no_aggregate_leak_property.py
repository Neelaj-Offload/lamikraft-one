"""SCN-A4 / A-13 on real data: for random permission subsets, every overview number equals the count of
visible items, every linked source and every member is openable, and the served member count counts
visible members only."""

from __future__ import annotations

import uuid

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.modules.briefings import service
from app.modules.briefings.engine.priority import due_today, is_overdue
from app.modules.tasks.responsibility import user_calendar
from app.modules.tasks.visibility import SourceCache, can_view_source
from app.seed.world import keys
from tests.integration.briefings.world import FakeWorld

pytestmark = pytest.mark.db

REVOCABLE = (
    "sales.customer_message.read",
    "sales.quote.read",
    "parties.party.read",
    "approvals.proposal.read",
    "sales.quote.approve",
    "sales.quote_price.approve",
)


@settings(max_examples=16, deadline=None, derandomize=True, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(person=st.sampled_from((keys.USERS.MEERA, keys.USERS.SAHIL, keys.USERS.PRIYA)), revoked=st.sets(st.sampled_from(REVOCABLE)))
def test_overview_numbers_equal_visible_counts(world: FakeWorld, person: str, revoked: set[str]) -> None:
    world.overrides = {person: dict.fromkeys(revoked)}
    user_id = world.refs[person]
    with world.uow(person) as uow:
        cal = user_calendar(uow, user_id)
        work_date = cal.work_date(uow.now())
        ctx = service.build_context(cal, work_date)
        result = service.build(uow, user_id, work_date, cal)
        served = service.get_today(uow)
        cache = SourceCache()
        for item in result.items:
            for ref in item.candidate.source_refs:
                assert can_view_source(uow, ref["type"], uuid.UUID(ref["id"]), cache=cache)
            for member in item.candidate.members:
                assert can_view_source(uow, member["ref_type"], uuid.UUID(member["ref_id"]), cache=cache)
        for view in served.items + served.snoozed:
            visible = [m for m in view.members if can_view_source(uow, m["ref_type"], uuid.UUID(m["ref_id"]), cache=cache)]
            assert view.member_count == len(visible) == len(view.members)
    facts = result.overview["facts"]
    obligations = [i.candidate for i in result.items if i.candidate.category == "obligation"]
    assert facts.get("decisions_pending", 0) == sum(1 for c in obligations if c.is_decision)
    assert facts.get("customer_replies", 0) == sum(1 for c in obligations if c.overview_class == "customer_reply")
    assert facts.get("quotes_expiring_today", 0) == sum(
        1 for c in obligations if c.overview_class == "quote_expiry" and due_today(c, ctx) and not is_overdue(c, ctx)
    )
    assert served.overview is not None and served.overview.facts == facts  # the served sentence is this build's
    if "sales.customer_message.read" in revoked:
        assert all(c.kind != "reply_needed" for c in obligations)
    if "approvals.proposal.read" in revoked:
        assert facts.get("decisions_pending", 0) == 0
    if "sales.quote.approve" in revoked and person != keys.USERS.MEERA:
        assert facts.get("decisions_pending", 0) == 0
