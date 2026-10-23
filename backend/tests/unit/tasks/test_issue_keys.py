"""Stable issue identity and fingerprints (conventions §4; briefing design acceptance unit/tasks/test_issue_keys)."""

from __future__ import annotations

import uuid

from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.tasks import issue_keys as keys

COMPANY = uuid.UUID("01929b2e-0000-7000-8000-000000000001")


def test_namespace_is_pinned() -> None:
    # every stored issue id derives from this namespace; changing it would orphan acks, snoozes and pins
    assert keys.NS_LK_ISSUE == uuid.UUID("0b6f2c1e-7a54-4d3e-9b8a-5c2e1f7d9a63")
    assert keys.issue_id(COMPANY, "msg:abc", 1) == uuid.uuid5(keys.NS_LK_ISSUE, f"{COMPANY}|msg:abc|1")


@settings(derandomize=True, max_examples=100)
@given(key=st.text(min_size=1, max_size=60), occurrence=st.integers(min_value=1, max_value=50))
def test_issue_id_is_stable_and_occurrence_specific(key: str, occurrence: int) -> None:
    first = keys.issue_id(COMPANY, key, occurrence)
    assert first == keys.issue_id(COMPANY, key, occurrence)
    assert first != keys.issue_id(COMPANY, key, occurrence + 1)
    assert first != keys.issue_id(uuid.uuid7(), key, occurrence)
    assert first.version == 5


def test_occurrence_must_be_positive() -> None:
    import pytest

    with pytest.raises(ValueError):
        keys.issue_id(COMPANY, "x", 0)


def test_key_builders_name_the_root_cause() -> None:
    rid = uuid.UUID(int=7)
    assert keys.message_key(rid) == f"msg:{rid}"
    assert keys.quote_expiry_key(rid) == f"quote:{rid}:expiry"
    assert keys.quote_review_key(rid) == f"quote:{rid}:review"
    assert keys.approval_key(rid) == f"approval:{rid}"
    assert keys.party_info_key(rid) == f"info:party:{rid}"
    assert keys.onboarding_key(rid, "checkin") == f"onboarding:{rid}:checkin"
    assert keys.manual_key(rid) == f"manual:{rid}"


@settings(derandomize=True, max_examples=100)
@given(facts=st.dictionaries(st.text(max_size=10), st.one_of(st.integers(), st.text(max_size=10), st.none()), max_size=6))
def test_fingerprint_ignores_key_order(facts: dict) -> None:
    reordered = dict(reversed(list(facts.items())))
    assert keys.fingerprint(facts) == keys.fingerprint(reordered)


def test_fingerprint_changes_with_material_facts() -> None:
    a = {"status": "sent", "valid_until": "2026-10-12"}
    assert keys.fingerprint(a) != keys.fingerprint({**a, "valid_until": "2026-10-19"})
