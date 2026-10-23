"""Fixture seed for tasks (fixtures.md §7.5, order 80): the sales onboarding template, fallback queues,
Meera's private reminder and the two manual tasks. Created through services at their fixture times, as
the acting persona; re-running is idempotent on business keys.

Requires the identity seed (persona refs ``SAHIL``, ``MEERA``, ``RAVI``, ``KABIR``, ``ARJUN``) and the
member actor builder registered by identity.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.core.clock import FrozenClock, get_clock, set_global_clock
from app.platform.authz.actors import actor_for_member
from app.platform.authz.context import ActorContext
from app.platform.uow import UnitOfWork
from app.seed.context import D0, SeedContext, SeedDef
from app.seed.world import keys

IST = ZoneInfo(keys.ZONE)

#: requested for keys.py (fixture steward report): texts and step keys of §7.5
REMINDER_MEERA_TEXT = "Call Maison about finish preferences"
TASK_KABIR_COUNT_TITLE = "Count walnut boards in bin A-12"
TASK_ARJUN_WALKTHROUGH_TITLE = "Complete product catalogue walkthrough"
SALES_ONBOARDING_STEPS: list[dict[str, str]] = [
    {"step_key": "language_and_detail", "title": "Choose your language and briefing detail",
     "completion_check": "pref_briefing_saved"},
    {"step_key": "open_product", "title": "Open a product record", "completion_check": "recent_record_exists"},
    {"step_key": "global_search", "title": "Use global search", "completion_check": "recent_search_exists"},
]
QUEUES = (("sales", "Sales (unassigned)", "sales"), ("operations", "Operations (unassigned)", "ops"),
          ("admin", "Administration (unassigned)", "admin"))

REMINDER_CREATED = datetime(2026, 10, 10, 17, 30, tzinfo=IST)  # D-2 17:30
REMINDER_AT = datetime(2026, 10, 13, 10, 0, tzinfo=IST)  # D0+1 10:00
ARJUN_ACTIVATED = D0.replace(hour=8, minute=0)  # D0 08:00
WALKTHROUGH_CREATED = D0.replace(hour=8, minute=5)
WALKTHROUGH_DUE = datetime(2026, 10, 14, 18, 30, tzinfo=IST)  # D0+2 18:30
COUNT_CREATED = D0.replace(hour=8, minute=10)
COUNT_DUE = D0.replace(hour=14, minute=0)


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
