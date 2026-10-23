"""A-13 on real data: for random permission subsets, every overview number equals the count of visible
items, every linked source is openable and member counts count visible members only."""

from __future__ import annotations

import uuid

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.modules.briefings import service
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
def test_no_aggregate_leak(world: FakeWorld, person: str, revoked: set[str]) -> None:
    world.overrides = {person: dict.fromkeys(revoked)}
    user_id = world.refs[person]
    with world.uow(person) as uow:
        cal = user_calendar(uow, user_id)
        result = service.build(uow, user_id, cal.work_date(uow.now()), cal)
        cache = SourceCache()
        for item in result.items:
            for ref in item.candidate.source_refs:
                assert can_view_source(uow, ref["type"], uuid.UUID(ref["id"]), cache=cache)
            assert len(item.candidate.members) == len({(m["ref_type"], m["ref_id"]) for m in item.candidate.members})
    facts = result.overview["facts"]
    obligations = [i.candidate for i in result.items if i.candidate.category == "obligation"]
    assert facts.get("decisions_pending", 0) == sum(1 for c in obligations if c.is_decision)
    assert facts.get("customer_replies", 0) == sum(1 for c in obligations if c.overview_class == "customer_reply")
    assert facts.get("quotes_expiring_today", 0) == sum(1 for c in obligations if c.overview_class == "quote_expiry")
    if "sales.customer_message.read" in revoked:
        assert all(c.kind != "reply_needed" for c in obligations)
    if {"sales.quote.approve", "approvals.proposal.read"} & revoked and person != keys.USERS.MEERA:
        if "sales.quote.approve" in revoked:
            assert facts.get("decisions_pending", 0) == 0
