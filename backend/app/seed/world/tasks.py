"""Fixture seed for tasks (fixtures.md §7.5, order 80): the sales onboarding template, fallback queues,
Meera's private reminder and the two manual tasks. Created through services at their fixture times, as
the acting persona; re-running is idempotent on business keys.

Requires the identity seed (persona refs ``SAHIL``, ``MEERA``, ``RAVI``, ``KABIR``, ``ARJUN``) and the
member actor builder registered by identity.
"""

from __future__ import annotations

from datetime import timedelta
from zoneinfo import ZoneInfo

from app.core.clock import FrozenClock, get_clock, set_global_clock
from app.platform.authz.actors import actor_for_member
from app.platform.authz.context import ActorContext
from app.platform.uow import UnitOfWork
from app.seed.context import SeedContext, SeedDef
from app.seed.world import keys

IST = ZoneInfo(keys.ZONE)

#: texts, step keys and times of fixtures.md §7.5 (all from keys.py)
REMINDER_MEERA_TEXT = keys.TEXTS.REMINDER_MEERA
TASK_KABIR_COUNT_TITLE = keys.TEXTS.TASK_KABIR_COUNT
TASK_ARJUN_WALKTHROUGH_TITLE = keys.TEXTS.TASK_ARJUN_WALKTHROUGH
#: the completion check each sales onboarding step runs (tasks module; readers registered by their owners)
_STEP_CHECKS = {
    "language_and_detail": "pref_briefing_saved",
    "open_product": "recent_record_exists",
    "global_search": "recent_search_exists",
}
SALES_ONBOARDING_STEPS: list[dict[str, str]] = [
    {"step_key": step, "title": keys.ONBOARDING_STEP_TITLES[step], "completion_check": _STEP_CHECKS[step]}
    for step in keys.ONBOARDING_STEPS
]
QUEUES = (("sales", "Sales (unassigned)", "sales"), ("operations", "Operations (unassigned)", "ops"),
          ("admin", "Administration (unassigned)", "admin"))

REMINDER_CREATED = keys.TIMES.REMINDER_MEERA_CREATED_AT  # D-2 17:30
REMINDER_AT = keys.TIMES.REMINDER_MEERA_AT  # D0+1 10:00
ARJUN_ACTIVATED = keys.TIMES.ARJUN_ACTIVATED_AT  # D0 08:00
WALKTHROUGH_CREATED = keys.TIMES.TASK_ARJUN_WALKTHROUGH_CREATED_AT
WALKTHROUGH_DUE = keys.TIMES.TASK_ARJUN_WALKTHROUGH_DUE_AT  # D0+2 18:30
COUNT_CREATED = keys.TIMES.TASK_KABIR_COUNT_CREATED_AT
COUNT_DUE = keys.TIMES.TASK_KABIR_COUNT_DUE_AT


class seed_clock:  # noqa: N801 - context manager used as a statement
    """Process events and stamp rows with the seed's clock (restored afterwards)."""

    def __init__(self, ctx: SeedContext) -> None:
        self.ctx = ctx
        self.previous = get_clock()

    def __enter__(self) -> None:
        set_global_clock(self.ctx.clock)

    def __exit__(self, *_exc: object) -> None:
        set_global_clock(self.previous if isinstance(self.previous, FrozenClock) else None)


def as_member(ctx: SeedContext, key: str) -> ActorContext:
    return actor_for_member(ctx.company_id, ctx.ref(key), channel="cli")


def seed_tasks(ctx: SeedContext) -> None:
    from app.modules.tasks import service
    from app.modules.tasks.schemas import ReminderCreate, TaskCreate
    from app.platform.jobs.worker import drain

    with seed_clock(ctx):
        drain()  # earlier seeds' events (activation, quotes, proposals) become tasks at their own times
        ctx.at(ARJUN_ACTIVATED - timedelta(days=30))
        with UnitOfWork(ActorContext.system(ctx.company_id, reason="seed"), clock=ctx.clock) as uow:
            service.ensure_onboarding_template(uow, role_key="sales", name="Sales onboarding", steps=SALES_ONBOARDING_STEPS)
            for code, name, prefix in QUEUES:
                service.ensure_queue(uow, code=code, name=name, family_prefix=prefix)

        ctx.at(REMINDER_CREATED)
        with UnitOfWork(as_member(ctx, keys.USERS.MEERA), clock=ctx.clock) as uow:
            reminder_id = service.find_reminder(uow, user_id=ctx.ref(keys.USERS.MEERA), text=REMINDER_MEERA_TEXT)
            if reminder_id is None:
                linked = ctx.refs.get("MAISON")
                reminder_id = service.create_reminder(
                    uow,
                    ReminderCreate(text=REMINDER_MEERA_TEXT, remind_at=REMINDER_AT,
                                   linked_ref_type="parties.party" if linked else None, linked_ref_id=linked),
                ).id
        ctx.refs[keys.REMINDERS.MEERA] = reminder_id

        ctx.at(ARJUN_ACTIVATED)
        with UnitOfWork(ActorContext.system(ctx.company_id, reason="seed"), clock=ctx.clock) as uow:
            service.apply_onboarding(uow, ctx.ref(keys.USERS.ARJUN), activated_at=ARJUN_ACTIVATED)

        ctx.at(WALKTHROUGH_CREATED)
        with UnitOfWork(as_member(ctx, keys.USERS.SAHIL), clock=ctx.clock) as uow:
            task_id = service.find_open_manual_task(uow, owner_user_id=ctx.ref(keys.USERS.ARJUN), title=TASK_ARJUN_WALKTHROUGH_TITLE)
            if task_id is None:
                task_id = service.create_task(
                    uow,
                    TaskCreate(title=TASK_ARJUN_WALKTHROUGH_TITLE, owner_user_id=ctx.ref(keys.USERS.ARJUN),
                               assignee_user_id=ctx.ref(keys.USERS.ARJUN), due_at=WALKTHROUGH_DUE, due_kind="soft"),
                    origin="seed",
                ).id
        ctx.refs[keys.TASKS.ARJUN_WALKTHROUGH] = task_id

        ctx.at(COUNT_CREATED)
        with UnitOfWork(as_member(ctx, keys.USERS.RAVI), clock=ctx.clock) as uow:
            task_id = service.find_open_manual_task(uow, owner_user_id=ctx.ref(keys.USERS.RAVI), title=TASK_KABIR_COUNT_TITLE)
            if task_id is None:
                task_id = service.create_task(
                    uow,
                    TaskCreate(title=TASK_KABIR_COUNT_TITLE, assignee_user_id=ctx.ref(keys.USERS.KABIR), due_at=COUNT_DUE,
                               due_kind="hard"),
                    origin="seed",
                ).id
        ctx.refs[keys.TASKS.KABIR_COUNT] = task_id
        drain()


SEEDS = [SeedDef(name="tasks", order=80, run=seed_tasks, slice_no=1)]
