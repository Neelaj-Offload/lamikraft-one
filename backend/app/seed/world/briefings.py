"""Fixture seed for briefings (fixtures.md §3, order 81, after the tasks seed (80)): Meera's last
acknowledgement on Sat D-2 18:05 and Neha's Monday briefing v1 generated at 08:49 and acknowledged at
08:50. Prior briefings are produced by the real engine at the seeded clock times (no back-filled rows).
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.platform.uow import UnitOfWork
from app.seed.context import SeedContext, SeedDef
from app.seed.world import keys
from app.seed.world.tasks import as_member, seed_clock

IST = ZoneInfo(keys.ZONE)
MEERA_ACK_AT = keys.TIMES.MEERA_LAST_ACK_AT  # Sat D-2 18:05
NEHA_GENERATED_AT = keys.TIMES.NEHA_BRIEFING_AT  # D0 08:49
NEHA_ACK_AT = keys.TIMES.NEHA_ACK_AT  # D0 08:50


def open_and_acknowledge(ctx: SeedContext, person: str, opened_at: datetime, acked_at: datetime) -> None:
    from app.modules.briefings import service
    from app.modules.briefings.models import BriefingTrigger

    ctx.at(opened_at)
    with UnitOfWork(as_member(ctx, person), clock=ctx.clock) as uow:
        briefing = service.generate_as_of(uow, trigger=BriefingTrigger.FIRST_OPEN.value)
        briefing_id, version = briefing.id, briefing.current_version
    ctx.at(acked_at)
    with UnitOfWork(as_member(ctx, person), clock=ctx.clock) as uow:
        service.acknowledge(uow, briefing_id, version=version, method="viewed")
    ctx.facts[f"BRIEFING_{person}_ACKED"] = {"briefing_id": str(briefing_id), "version": version}


def seed_briefings(ctx: SeedContext) -> None:
    from app.platform.jobs.worker import drain

    with seed_clock(ctx):
        drain()
        open_and_acknowledge(ctx, keys.USERS.MEERA, MEERA_ACK_AT, MEERA_ACK_AT)
        open_and_acknowledge(ctx, keys.USERS.NEHA, NEHA_GENERATED_AT, NEHA_ACK_AT)
        drain()


SEEDS = [SeedDef(name="briefings", order=81, run=seed_briefings, slice_no=1)]  # after tasks (80)
