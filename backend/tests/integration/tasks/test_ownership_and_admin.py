"""Review-fix regressions for tasks: the briefing's Dismiss touches only the caller's own obligations, a
person's (re)assignment survives re-derivation, owners are checked like assignees, counts need
tasks.task.read, blank free text is a 422, offboarding re-homes a departed member's work, immaterial party
updates create nothing, and onboarding finds the role template without an identity reader."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from app.core.errors import Forbidden, ValidationFailed
from app.modules.tasks import issue_keys, responsibility
from app.modules.tasks import service as tasks
from app.modules.tasks.errors import NotComplete
from app.modules.tasks.models import ChangeLog, Issue, Reminder, Task
from app.modules.tasks.rules import consumer, families
from app.modules.tasks.schemas import ReminderCreate, TaskAssignment, TaskCreate, TaskTransition
from app.modules.tasks.visibility import SourceCache
from app.platform import sources
from app.platform.identity.models import Membership
from app.seed.world import keys
from tests.integration.briefings.world import FakeWorld, d0

pytestmark = pytest.mark.db


def open_tasks(world: FakeWorld, issue_key: str) -> list[Task]:
    with world.uow() as uow:
        rows = list(uow.session.scalars(
            select(Task).join(Issue, Issue.id == Task.issue_id).where(Issue.issue_key == issue_key).order_by(Task.created_at, Task.id)))
        for r in rows:
            uow.session.expunge(r)
        return rows


def test_briefing_dismiss_leaves_other_peoples_obligations_open(world: FakeWorld) -> None:
    """Review major 2: Sahil dismisses his assigned review; Meera's reply on the same issue stays open."""
    world.at(d0(9, 0))
    q = world.change_quote("Q_NORDHAUS_DRAFT", status="draft")
    world.emit_quote(keys.USERS.MEERA, "sales.quote.status_changed", "Q_NORDHAUS_DRAFT", version=q.version,
                     action="withdraw_review", from_status="internal_review", to_status="draft")
    world.drain()
    key = issue_keys.message_key(world.refs[keys.MESSAGES.NORDHAUS])
    review = next(t for t in open_tasks(world, key) if t.kind == "review_draft" and t.state == "open")
    with world.uow(keys.USERS.MEERA) as uow:
        tasks.assign_task(uow, review.id, assignee_user_id=world.refs[keys.USERS.SAHIL], expected_version=review.version)
    with world.uow(keys.USERS.SAHIL) as uow:
        out = tasks.dismiss_issue(uow, review.issue_id, reason_code="duplicate")
    assert out.task_ids == (review.id,)
    states = {t.kind: t.state for t in open_tasks(world, key)}
    assert states["review_draft"] == "dismissed" and states["reply_needed"] == "open"


def test_manual_assignment_survives_rederivation_and_source_events(world: FakeWorld) -> None:
    """Review major 3: Meera's Berg reply assigned to Sahil stays with Sahil through the access-change job
    and a new source event; when Sahil loses access the rule's responsibility applies again."""
    key = issue_keys.message_key(world.refs[keys.MESSAGES.BERG])
    (reply,) = [t for t in open_tasks(world, key) if t.kind == "reply_needed"]
    with world.uow(keys.USERS.MEERA) as uow:
        tasks.assign_task(uow, reply.id, assignee_user_id=world.refs[keys.USERS.SAHIL], expected_version=reply.version)
    with world.uow() as uow:
        assert consumer.rederive_open(uow) >= 1
    m = world.messages[keys.MESSAGES.BERG]
    m.version += 1
    world.at(d0(9, 30))
    world.emit(keys.USERS.MEERA, "sales.customer_message.received", m.id, {
        "message_id": str(m.id), "party_id": str(world.refs["BERG"]), "contact_id": None, "channel": "email",
        "assignee_user_id": str(world.refs[keys.USERS.MEERA]), "enquiry_id": None, "quote_id": None}, version=m.version)
    world.drain()
    (kept,) = [t for t in open_tasks(world, key) if t.kind == "reply_needed"]
    assert (kept.assignee_user_id, kept.owner_user_id, kept.queue_code) == (
        world.refs[keys.USERS.SAHIL], world.refs[keys.USERS.MEERA], None)
    world.override(keys.USERS.SAHIL, {"sales.customer_message.read": None})
    with world.uow() as uow:
        consumer.rederive_open(uow)
    (back,) = [t for t in open_tasks(world, key) if t.kind == "reply_needed"]
    assert back.assignee_user_id == world.refs[keys.USERS.MEERA] and back.assigned_by is None


def test_naming_an_owner_needs_assign_scope_over_that_owner(world: FakeWorld) -> None:
    """Review minor 14: Ravi (assign at branch scope) cannot make a member of another branch the owner, and
    a named owner must be able to open the linked record."""
    with world.uow() as uow:
        m = uow.session.scalars(select(Membership).where(Membership.id == world.refs[f"{keys.USERS.MEERA}_MEMBERSHIP"])).one()
        m.default_branch_id = world.branch_fac
    with world.uow(keys.USERS.RAVI) as uow, pytest.raises(Forbidden):
        tasks.create_task(uow, TaskCreate(title="Check samples", owner_user_id=world.refs[keys.USERS.MEERA]))
    with world.uow(keys.USERS.SAHIL) as uow, pytest.raises(ValidationFailed) as err:
        tasks.create_task(uow, TaskCreate(title="Look at the Berg quote", owner_user_id=world.refs[keys.USERS.KABIR],
                                          assignee_user_id=world.refs[keys.USERS.SAHIL], linked_ref_type="sales.quote",
                                          linked_ref_id=world.refs["Q_BERG_EXPIRING"]))
    assert err.value.code == "assignee_cannot_view"
    with world.uow(keys.USERS.RAVI) as uow:  # same branch: allowed
        out = tasks.create_task(uow, TaskCreate(title="Count oak boards", owner_user_id=world.refs[keys.USERS.KABIR]))
    assert out.owner_user_id == world.refs[keys.USERS.KABIR]


def test_inbox_counts_need_task_read(world: FakeWorld) -> None:
    """Review minor 13."""
    world.override(keys.USERS.KABIR, {"tasks.task.read": None})
    with world.uow(keys.USERS.KABIR) as uow, pytest.raises(Forbidden):
        tasks.inbox_counts(uow)


def test_blank_text_is_a_validation_error(world: FakeWorld) -> None:
    """Review minor 9: whitespace-only reminder text and task titles are 422s, never constraint errors."""
    with pytest.raises(ValidationError):
        ReminderCreate(text="   ", remind_at=d0(17, 0))
    with pytest.raises(ValidationError):
        TaskCreate(title=" \t ")
    with world.uow(keys.USERS.MEERA) as uow:
        created = tasks.create_reminder(uow, ReminderCreate(text="  Call Berg  ", remind_at=d0(17, 0)))
        assert created.text == "Call Berg"
        with pytest.raises(ValidationFailed):
            tasks.create_reminder(uow, ReminderCreate.model_construct(text="   ", remind_at=d0(17, 0)))


def test_commands_require_the_expected_version() -> None:
    """Spec minor 9 (api-conventions 6): transitions and assignments carry the version acted on."""
    with pytest.raises(ValidationError):
        TaskTransition(action="complete")  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        TaskAssignment(assignee_user_id=uuid.uuid4())  # type: ignore[call-arg]


def test_deactivation_rehomes_work_and_cancels_reminders(world: FakeWorld) -> None:
    """Spec major 4 (events.md 3.1): Kabir leaves; his reminder is cancelled and his manual count task
    becomes "Reassign 1 open task" for his manager Ravi, done once the task has moved."""
    world.at(d0(9, 0))
    kabir = world.refs[keys.USERS.KABIR]
    with world.uow(keys.USERS.KABIR) as uow:
        tasks.create_reminder(uow, ReminderCreate(text="Ask about gloves", remind_at=d0(16, 0)))
    with world.uow() as uow:
        m = uow.session.scalars(select(Membership).where(Membership.id == world.refs[f"{keys.USERS.KABIR}_MEMBERSHIP"])).one()
        m.status = "deactivated"
    world.emit(keys.USERS.PRIYA, "identity.membership.deactivated", world.refs[f"{keys.USERS.KABIR}_MEMBERSHIP"], {
        "membership_id": str(world.refs[f"{keys.USERS.KABIR}_MEMBERSHIP"]), "user_id": str(kabir), "reassign_to_membership_id": None},
        version=2)
    world.drain()
    with world.uow() as uow:
        states = set(uow.session.scalars(select(Reminder.state).where(Reminder.user_id == kabir)))
    assert states == {"cancelled"}
    (offboard,) = open_tasks(world, issue_keys.offboarding_key(kabir))
    assert offboard.kind == "reassign_work" and offboard.state == "open"
    assert offboard.owner_user_id == world.refs[keys.USERS.RAVI] and offboard.title.startswith("Reassign 1 open task")
    with world.uow(keys.USERS.RAVI) as uow, pytest.raises(NotComplete):  # Kabir still does the count
        tasks.transition_task(uow, offboard.id, action="complete")
    count = world.refs[keys.TASKS.KABIR_COUNT]
    with world.uow(keys.USERS.RAVI) as uow:
        detail = tasks.get_task(uow, count)
        tasks.assign_task(uow, count, assignee_user_id=world.refs[keys.USERS.RAVI], expected_version=detail.version)
    with world.uow(keys.USERS.RAVI) as uow:
        assert tasks.transition_task(uow, offboard.id, action="complete").state == "done"


def test_immaterial_party_update_creates_no_change(world: FakeWorld) -> None:
    """Spec minor 7: a notes-only party update writes no change row and no briefing version."""
    maison = world.refs["MAISON"]
    with world.uow() as uow:
        before = uow.session.scalar(select(func.count()).select_from(ChangeLog))
    world.at(d0(9, 0))
    # the parties module has no notes field: the event carries the party's current version, so the rule re-reads a
    # party that is up to date with the event and only the changed fields decide
    world.emit(keys.USERS.PRIYA, "parties.party.updated", maison, {"party_id": str(maison), "party_number": keys.PARTIES.MAISON,
               "changed_fields": ["notes"]}, version=world.party_version("MAISON"))
    world.drain()
    with world.uow() as uow:
        assert uow.session.scalar(select(func.count()).select_from(ChangeLog)) == before
    assert families.material_party_fields(["addresses.shipping", "notes", "tags"]) == ["addresses.shipping"]


def test_onboarding_role_template_without_an_identity_reader(world: FakeWorld) -> None:
    """Spec major 2: with no identity.membership reader the sales template is still found from grants."""
    sources._READERS.pop("identity.membership", None)  # world.uninstall restores it
    with world.uow() as uow:
        roles = families.member_role_keys(uow, world.refs[keys.USERS.ARJUN], world.refs[f"{keys.USERS.ARJUN}_MEMBERSHIP"], SourceCache())
        template = families.onboarding_template_for(uow, world.refs[f"{keys.USERS.ARJUN}_MEMBERSHIP"], SourceCache(),
                                                    world.refs[keys.USERS.ARJUN])
    assert roles[0] == "sales" and roles[-1] == "employee"
    assert template is not None and template.role_key == "sales"


def test_reply_closes_through_origin_message_link_only(world: FakeWorld) -> None:
    """Review major 7: the message does not list the draft; the draft's origin_message_id links it."""
    with world.uow() as uow:
        facts = sources.read(uow, "sales.customer_message", world.refs[keys.MESSAGES.NORDHAUS])
    assert facts is not None and str(world.refs["Q_NORDHAUS_DRAFT"]) not in facts.facts["linked_quote_ids"]
    world.at(d0(10, 0))
    world.change_quote("Q_NORDHAUS_DRAFT", status="sent", sent_at=d0(10, 0))
    world.emit_quote(keys.USERS.MEERA, "sales.quote.marked_sent", "Q_NORDHAUS_DRAFT", revision_id=str(uuid.uuid7()),
                     dispatch_id=str(uuid.uuid7()))
    world.drain()
    (reply,) = [t for t in open_tasks(world, issue_keys.message_key(world.refs[keys.MESSAGES.NORDHAUS])) if t.kind == "reply_needed"]
    assert reply.state == "done" and reply.completion_evidence["reason"] == "linked_quote_sent"


def test_member_actor_is_cached_per_transaction(world: FakeWorld) -> None:
    """Review minor 11: reconciliation evaluates each member's context once per transaction."""
    calls: list[uuid.UUID] = []
    from app.platform.authz import actors

    with world.uow() as uow:
        original = actors._builder  # identity's real member-actor builder
        assert original is not None

        def counting(company_id: uuid.UUID, user_id: uuid.UUID, channel: str):  # type: ignore[no-untyped-def]
            calls.append(user_id)
            return original(company_id, user_id, channel)  # type: ignore[arg-type]

        actors.register_member_actor_builder(counting)
        try:
            responsibility.queue_managers(uow)
            responsibility.queue_managers(uow)
        finally:
            actors.register_member_actor_builder(original)
    assert len(calls) == len(set(calls))
