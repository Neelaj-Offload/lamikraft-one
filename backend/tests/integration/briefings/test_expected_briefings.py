"""Expected Slice-1 briefings at D0 08:55 for every persona (fixtures.md §9; tests A-02 … A-15).

Ids, names and sentences come from the world refs and ``keys.EXPECTED``; nothing is a literal.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from app.modules.briefings import service
from app.modules.briefings.models import BriefingItem, BriefingVersion
from app.modules.tasks import issue_keys
from app.modules.tasks.models import ChangeLog
from app.platform.identity.models import AppUser
from app.seed.world import keys
from tests.integration.briefings.world import FakeWorld, d0

pytestmark = pytest.mark.db


def today(world: FakeWorld, person: str, **kw: object):  # type: ignore[no-untyped-def]
    with world.uow(person) as uow:
        return service.get_today(uow, **kw)  # type: ignore[arg-type]


def key_id(world: FakeWorld, issue_key: str):  # type: ignore[no-untyped-def]
    return issue_keys.issue_id(world.company_id, issue_key, 1)


def test_meera_sales_briefing_sections_and_sentence(world: FakeWorld) -> None:
    """A-03/A-06: computed overview, five items in rank order, empty sections omitted."""
    view = today(world, keys.USERS.MEERA)
    assert view.status == "ready" and not view.fallback
    assert view.overview is not None
    assert view.overview.greeting == keys.EXPECTED.MEERA_S1_GREETING
    assert view.overview.sentence == keys.EXPECTED.MEERA_S1_SENTENCE
    assert view.overview.facts == {"customer_replies": 2, "quotes_expiring_today": 1}
    expected_order = [
        key_id(world, issue_keys.message_key(world.refs[keys.MESSAGES.BERG])),
        key_id(world, issue_keys.quote_expiry_key(world.refs["Q_BERG_EXPIRING"])),
        key_id(world, issue_keys.message_key(world.refs[keys.MESSAGES.NORDHAUS])),
        key_id(world, issue_keys.party_info_key(world.refs["MAISON"])),
    ]
    assert [i.issue_id for i in view.items][:4] == expected_order
    assert view.items[4].is_reminder and view.items[4].due_label == "Tomorrow 10:00"
    sections = {s.code: s.total for s in view.sections}
    assert sections == {"needs_you_now": 2, "plan_for_today": 1, "changes_since_last_visit": 1, "coming_next": 1}
    assert "handled_for_you" not in sections and "recommendations" not in sections
    assert len(view.initial_view) == 5 and len(view.items) == 5
    reply, expiry, nordhaus = view.items[:3]
    assert (reply.score, reply.band, expiry.score, expiry.band, nordhaus.score, nordhaus.band) == (75, "P1", 75, "P1", 65, "P2")
    assert reply.due_label == "Today 18:30" and reply.due_at == datetime(2026, 10, 12, 13, 0, tzinfo=UTC)
    assert expiry.due_label == "Expires today"
    assert nordhaus.blocked and keys.QUOTES.NORDHAUS_DRAFT in nordhaus.title
    assert nordhaus.blocked_by[0]["label"].startswith("Review " + keys.QUOTES.NORDHAUS_DRAFT)
    assert nordhaus.recommendation is not None and nordhaus.recommendation.action_code == "FOLLOW_UP_REVIEW"
    maison = view.items[3]
    assert maison.title == f"{keys.PARTY_NAMES['MAISON']} shipping address updated by Priya"
    assert [m.amount for m in expiry.money] and expiry.money[0].currency == "EUR"


def test_first_open_persists_once(world: FakeWorld) -> None:
    """A-02: the first GET generates and persists v1 (trigger first_open); the second writes nothing."""
    first = today(world, keys.USERS.MEERA)
    assert (first.version, first.trigger) == (1, "first_open") and first.first_opened_at is not None
    with world.uow() as uow:
        counts = (uow.session.scalar(select(func.count()).select_from(BriefingVersion)),
                  uow.session.scalar(select(func.count()).select_from(BriefingItem)))
    second = today(world, keys.USERS.MEERA)
    with world.uow() as uow:
        assert (uow.session.scalar(select(func.count()).select_from(BriefingVersion)),
                uow.session.scalar(select(func.count()).select_from(BriefingItem))) == counts
    assert (second.briefing_id, second.version) == (first.briefing_id, 1)
    assert [i.issue_id for i in second.items] == [i.issue_id for i in first.items]


def test_sahil_three_decisions(world: FakeWorld) -> None:
    """A-08: three approval items with proposal_ref v1; sentence; the check-in in Coming next."""
    view = today(world, keys.USERS.SAHIL)
    assert view.overview is not None
    assert view.overview.greeting == keys.EXPECTED.SAHIL_S1_GREETING
    assert view.overview.sentence == keys.EXPECTED.SAHIL_S1_SENTENCE
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


def test_sahil_overdue_item_changes_the_second_clause(world: FakeWorld) -> None:
    """A-08 variant: an overdue obligation for Sahil gives "One item is overdue."."""
    from app.modules.tasks import service as tasks
    from app.modules.tasks.schemas import TaskCreate

    world.at(d0(8, 50))
    with world.uow(keys.USERS.SAHIL) as uow:
        tasks.create_task(uow, TaskCreate(title="Sign the export licence renewal", due_at=d0(8, 0).replace(day=11), due_kind="hard"))
    world.at(d0(8, 55))
    view = today(world, keys.USERS.SAHIL)
    assert view.overview is not None and view.overview.sentence == keys.EXPECTED.SAHIL_A08_SENTENCE


def test_revoked_price_approval_removes_two_decisions(world: FakeWorld) -> None:
    """A-09: without sales.quote_price.approve Sahil is no longer eligible for the two price overrides."""
    first = today(world, keys.USERS.SAHIL)
    world.overrides[keys.USERS.SAHIL] = {"sales.quote_price.approve": None}
    view = today(world, keys.USERS.SAHIL)
    assert view.overview is not None and view.overview.sentence == keys.EXPECTED.SAHIL_A09_SENTENCE
    assert view.version == 2 and view.briefing_id == first.briefing_id
    with world.uow() as uow:
        cause = uow.session.scalar(select(BriefingVersion.cause).where(BriefingVersion.briefing_id == view.briefing_id,
                                                                       BriefingVersion.version == 2))
    assert cause == "permission_change"
    assert [i.issue_id for i in view.items if i.section == "needs_you_now"] == [
        key_id(world, issue_keys.approval_key(world.refs[keys.PROPOSALS.NORDHAUS]))]


@pytest.mark.parametrize(
    ("person", "sentence"),
    [
        (keys.USERS.NEHA, keys.EXPECTED.NEHA_S1_SENTENCE),
        (keys.USERS.ARJUN, keys.EXPECTED.ARJUN_S1_SENTENCE),
        (keys.USERS.KABIR, keys.EXPECTED.KABIR_S1_SENTENCE),
        (keys.USERS.RAVI, keys.EXPECTED.RAVI_S1_SENTENCE),
        (keys.USERS.PRIYA, keys.EXPECTED.PRIYA_S1_SENTENCE),
        (keys.USERS.ANANYA, keys.EXPECTED.ANANYA_S1_SENTENCE),
    ],
)
def test_other_personas(world: FakeWorld, person: str, sentence: str) -> None:
    view = today(world, person)
    assert view.overview is not None and view.overview.sentence == sentence
    sections = {s.code: s.total for s in view.sections}
    if person == keys.USERS.NEHA:  # v1 generated 08:49 and acknowledged 08:50 by the seed
        assert view.version == 1 and view.up_to_date and view.last_ack is not None
        assert view.generated_at == d0(8, 49) and view.last_ack.acknowledged_at == d0(8, 50)
        assert sections == {"needs_you_now": 1} and view.items[0].title == f"{keys.QUOTES.THORNBURY_EXPIRING} expires today"
        assert (view.items[0].score, view.items[0].band) == (75, "P1")
    elif person == keys.USERS.ARJUN:
        assert sections == {"plan_for_today": 3, "coming_next": 1}
    elif person in (keys.USERS.KABIR, keys.USERS.RAVI):
        assert sections == {"plan_for_today": 1}
        assert view.items[0].score == (50 if person == keys.USERS.KABIR else 40)
    elif person == keys.USERS.PRIYA:
        assert sections == {"needs_you_now": 3}
    else:
        assert view.sections == [] and view.items == []


def test_new_employee_onboarding(world: FakeWorld) -> None:
    """A-15: no changes or handled sections; the change-log cutoff is the activation time."""
    view = today(world, keys.USERS.ARJUN)
    assert {s.code for s in view.sections} == {"plan_for_today", "coming_next"}
    with world.uow() as uow:
        cutoff = uow.session.scalar(select(BriefingVersion.cutoff_at).where(BriefingVersion.briefing_id == view.briefing_id))
    assert cutoff == d0(8, 0)
    steps = [i for i in view.items if i.kind == "onboarding_step"]
    assert len(steps) == 3 and all(s.due_label == "Today 18:30" for s in steps)
    assert [i.title for i in view.items if i.section == "coming_next"] == ["Complete product catalogue walkthrough"]


def test_due_dates_in_the_users_zone(world: FakeWorld) -> None:
    """A-05: Berg reply due 13:00Z is "Today 18:30" in Kolkata and "Today 15:00" for a Berlin-zone user."""
    with world.uow() as uow:
        user = uow.session.get(AppUser, world.refs[keys.USERS.MEERA])
        assert user is not None
        user.time_zone = "Europe/Berlin"
    view = today(world, keys.USERS.MEERA)
    reply = view.items[0]
    assert reply.due_at == datetime(2026, 10, 12, 13, 0, tzinfo=UTC)
    assert (view.time_zone, reply.due_label) == ("Europe/Berlin", "Today 15:00")
    assert view.items[1].due_label == "Expires today"


def test_only_authorised_sources_are_linked(world: FakeWorld) -> None:
    """A-04: Meera's payload links only records she can open; nothing about Thornbury, GBP or Neha."""
    view = today(world, keys.USERS.MEERA)
    payload = view.model_dump_json()
    for secret in (keys.PARTY_NAMES["THORNBURY"], "GBP", str(world.refs[keys.USERS.NEHA]),
                   str(world.refs["Q_THORNBURY_OVERRIDE"]), str(world.refs["Q_THORNBURY_EXPIRING"])):
        assert secret not in payload
    from app.modules.tasks.visibility import SourceCache, can_view_source

    with world.uow(keys.USERS.MEERA) as uow:
        cache = SourceCache()
        for item in view.items:
            for ref in item.source_refs:
                assert can_view_source(uow, ref.type, ref.id, cache=cache)


def test_kabir_sees_only_his_count_task(world: FakeWorld) -> None:
    """A-10: no customer names, amounts or foreign counts anywhere in Kabir's payload."""
    view = today(world, keys.USERS.KABIR)
    payload = json.loads(view.model_dump_json())
    text = json.dumps(payload)
    for name in keys.PARTY_NAMES.values():
        assert name not in text
    for token in ("EUR", "GBP", keys.QUOTES.BERG_EXPIRING, "5700", "decision"):
        assert token not in text
    assert payload["overview"]["facts"] == {"tasks_due_today": 1, "assigned_tasks": 1}  # his own item only
    assert [i["title"] for i in payload["items"]] == ["Count walnut boards in bin A-12"]


def test_changes_are_backed_by_events_after_the_ack(world: FakeWorld) -> None:
    """A-07: each change item maps to change-log rows with event ids after Meera's acknowledgement."""
    view = today(world, keys.USERS.MEERA)
    assert view.last_ack is not None
    change = next(i for i in view.items if i.section == "changes_since_last_visit")
    with world.uow() as uow:
        rows = uow.session.scalars(select(ChangeLog).where(ChangeLog.issue_id == change.issue_id)).all()
    assert rows and {str(r.event_id) for r in rows} == set(change.facts["event_ids"])
    assert all(r.fact_at > view.last_ack.acknowledged_at for r in rows)
    neha = today(world, keys.USERS.NEHA)
    assert "changes_since_last_visit" not in {s.code for s in neha.sections}
