"""SCN-A2: management sees the authorised cross-team decisions (fixtures 9.2)."""

from __future__ import annotations

import pytest

from app.modules.tasks import issue_keys
from app.seed.world import keys
from tests.integration.briefings.test_expected_briefings import key_id, today
from tests.integration.briefings.world import FakeWorld

pytestmark = pytest.mark.db


def test_sahil_three_decisions_sentence(world: FakeWorld) -> None:
    """A-08: three approval items with proposal_ref v1; sentence; the check-in in Coming next."""
    view = today(world, keys.USERS.SAHIL)
    assert view.overview is not None
    assert view.overview.greeting == keys.EXPECTED.SAHIL_S1_GREETING
    assert view.overview.sentence == keys.EXPECTED.SAHIL_S1_SENTENCE
    assert view.overview.facts == {"decisions_pending": 3, "rest_moving": True}  # fixtures 9.2
    decisions = [i for i in view.items if i.section == "needs_you_now"]
    assert [i.issue_id for i in decisions] == [
        key_id(world, issue_keys.approval_key(world.refs[keys.PROPOSALS.MAISON])),
        key_id(world, issue_keys.approval_key(world.refs[keys.PROPOSALS.THORNBURY])),
        key_id(world, issue_keys.approval_key(world.refs[keys.PROPOSALS.NORDHAUS])),
    ]
    for item in decisions:
        assert (item.score, item.band, item.reason_codes) == (55, "P2", ["DUE_TODAY", "YOUR_DECISION"])
        assert item.proposal_ref is not None and item.proposal_ref["version"] == 1 and len(item.proposal_ref["content_hash"]) == 64
        actions = {a.action for a in item.allowed_actions}
        assert {"review", "approve", "reject", "snooze", "explain"} <= actions and "mark_handled" not in actions
    assert decisions[0].title.startswith(f"Approve price override on {keys.QUOTES.MAISON_OVERRIDE}")
    assert decisions[2].title == f"Review {keys.QUOTES.NORDHAUS_DRAFT} ({keys.PARTY_NAMES['NORDHAUS']})"
    checkin = [i for i in view.items if i.section == "coming_next"]
    assert len(checkin) == 1 and checkin[0].due_label == "Wed 18:30" and checkin[0].reason_codes[-1] == "YOU_OWN"
    assert checkin[0].issue_id == key_id(world, issue_keys.onboarding_key(world.refs[keys.USERS.ARJUN], "checkin"))
