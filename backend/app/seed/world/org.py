"""Org part of the canonical fixture world (fixtures.md §2 and §6), seed order 12 (after identity's company).

Creates, through the org services and as the seed system actor:
- the unit-of-measure master (codes, aliases, standard conversions);
- calendar HO-GEN: Asia/Kolkata, Monday-Saturday, shift GEN 09:30-18:30, rollover 04:00, precompute
  30 minutes before shift start, the company default (on the HO branch when it exists);
- the "Demo holiday" on D0+10;
- neutral demo document terms labelled Demo (company identity, bank details and logo stay not configured).

Re-running is idempotent on business keys (unit codes, calendar and shift codes, holiday date, unchanged
settings write nothing).
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.platform.authz.context import ActorContext
from app.platform.org import calendar_service
from app.platform.org import service as settings_service
from app.platform.org.models import Branch
from app.platform.org.reference import ensure_default_uoms
from app.platform.org.workcal import MON_TO_SAT_MASK
from app.platform.uow import UnitOfWork
from app.seed.context import SeedContext
from app.seed.world import keys

HO_GEN_NAME = "Head office general"
GEN_SHIFT = ("GEN", "General shift", time(9, 30), time(18, 30))
ROLLOVER = time(4, 0)
PRECOMPUTE_MINUTES = 30
HOLIDAY_OFFSET_DAYS = 10
HOLIDAY_NAME = "Demo holiday"
DEMO_TERMS = {
    "quote": (
        "Demo terms. Prices are ex-works unless the quote states an incoterm. The quote is valid for the "
        "validity period shown. Replace this text in Settings > Company before issuing real documents."
    ),
    "challan": (
        "Demo terms. Goods are sent for the purpose stated on this challan. Returnable items must come back "
        "in the same condition. Replace this text in Settings > Company."
    ),
    "footer": "Demo company. Documents generated in the demo are not valid for trade.",
}


def anchor_d0(ctx: SeedContext) -> datetime:
    """The seed anchor (D0): ``ctx.facts['anchor_d0']`` when the runner shifts the world, else the test D0."""
    anchor = ctx.facts.get("anchor_d0")
    return anchor if isinstance(anchor, datetime) else keys.CLOCK_D0


def holiday_date(ctx: SeedContext):  # type: ignore[no-untyped-def]
    return anchor_d0(ctx).astimezone(ZoneInfo(keys.ZONE)).date() + timedelta(days=HOLIDAY_OFFSET_DAYS)


def seed_org(ctx: SeedContext) -> None:
    actor = ActorContext.system(ctx.company_id, reason="seed")
    with UnitOfWork(actor, clock=ctx.clock) as uow:
        ensure_default_uoms(uow)
        branch_id = uow.session.scalar(
            select(Branch.id).where(Branch.company_id == ctx.company_id, Branch.branch_code == keys.BRANCHES.HO)
        )
        calendar_id = calendar_service.upsert_calendar(
            uow,
            code=keys.CALENDARS.HO_GEN,
            name=HO_GEN_NAME,
            time_zone=keys.ZONE,
            workweek_mask=MON_TO_SAT_MASK,
            rollover=ROLLOVER,
            branch_id=branch_id,
            is_default=True,
        )
        code, name, start, end = GEN_SHIFT
        calendar_service.upsert_shift(
            uow,
            calendar_id,
            code=code,
            name=name,
            start_local=start,
            end_local=end,
            precompute_offset_min=PRECOMPUTE_MINUTES,
        )
        calendar_service.set_holiday(uow, calendar_id, holiday_date=holiday_date(ctx), name=HOLIDAY_NAME)
        current = settings_service.get_setting(uow, "document_terms")
        settings_service.update_setting(
            uow,
            "document_terms",
            value=DEMO_TERMS,
            expected_version=current.version,
            change_reason="Demo seed",
            origin="seed",
        )
    ctx.refs[keys.CALENDARS.HO_GEN] = calendar_id
