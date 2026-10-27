"""The actor's work calendar (GET /org/calendar/me) and the org fixture seed (HO-GEN, Demo holiday, units)."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select

from app.core.errors import Forbidden
from app.platform.authz.context import ActorContext
from app.platform.authz.permissions import Scope
from app.platform.org import calendar_service
from app.platform.org import service as settings_service
from app.platform.org.models import Uom
from app.platform.org.reference import DEFAULT_UOMS
from app.platform.org.workcal import WorkAssignment, WorkCalendar, WorkHoliday, WorkShift
from app.platform.uow import UnitOfWork
from app.registry import get_registry
from app.seed.context import SeedContext
from app.seed.world import keys
from app.seed.world.org import (
    DEMO_TERMS,
    GEN_SHIFT,
    HOLIDAY_NAME,
    HOLIDAY_OFFSET_DAYS,
    PRECOMPUTE_MINUTES,
    seed_org,
)
from tests.integration.org.platform_lane import ApiClient, member, problem

pytestmark = pytest.mark.db
IST = ZoneInfo(keys.ZONE)


@pytest.fixture
def seeded(company, frozen_clock):  # type: ignore[no-untyped-def]
    company_id, _ = company
    ctx = SeedContext(company_id=company_id, clock=frozen_clock)
    seed_org(ctx)
    frozen_clock.set(keys.CLOCK_D0)
    return ctx


@pytest.fixture
def meera(seeded):  # type: ignore[no-untyped-def]
    return member(seeded.company_id, keys.PEOPLE["MEERA"].name, "sales")


#: D0 (Monday) as a local date; every date below is an offset from the fixture clock, never a literal
D0_DATE = keys.CLOCK_D0.astimezone(IST).date()
GEN_CODE, GEN_NAME, GEN_START, GEN_END = GEN_SHIFT


def _day(offset: int) -> date:
    return D0_DATE + timedelta(days=offset)


def _at(offset: int, hh: int, mm: int) -> datetime:
    return datetime.combine(_day(offset), time(hh, mm), tzinfo=IST)


def _z(at: datetime) -> str:
    return at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_my_calendar_at_d0(api: ApiClient, meera) -> None:  # type: ignore[no-untyped-def]
    r = api.as_(meera.actor()).get("/api/v1/org/calendar/me")
    assert r.status_code == 200, r.text
    cal = r.json()
    assert cal["source"] == "company_default"
    assert cal["calendar_code"] == keys.CALENDARS.HO_GEN
    assert cal["time_zone"] == keys.ZONE
    assert cal["server_now"] == _z(keys.CLOCK_D0)
    assert cal["work_date"] == D0_DATE.isoformat()
    assert cal["day_type"] == "working" and cal["is_working_day"] is True
    assert cal["rollover_local"] == "04:00:00"
    assert cal["workweek"] == [1, 2, 3, 4, 5, 6]
    shift_start = datetime.combine(D0_DATE, GEN_START, tzinfo=IST)
    assert cal["shift"] == {
        "code": GEN_CODE,
        "name": GEN_NAME,
        "start_local": "09:30:00",
        "end_local": "18:30:00",
        "starts_at": _z(shift_start),
        "ends_at": _z(datetime.combine(D0_DATE, GEN_END, tzinfo=IST)),
    }
    assert cal["precompute_at"] == _z(shift_start - timedelta(minutes=PRECOMPUTE_MINUTES))
    assert cal["next_working_day"] == _day(1).isoformat()
    holiday = _day(HOLIDAY_OFFSET_DAYS).isoformat()
    assert cal["upcoming_holidays"] == [{"date": holiday, "name": HOLIDAY_NAME, "kind": "full"}]


def test_just_after_midnight_still_belongs_to_the_previous_work_date(meera, frozen_clock) -> None:  # type: ignore[no-untyped-def]
    frozen_clock.set(_at(1, 0, 10))  # Tuesday 00:10, before the 04:00 rollover
    cal = calendar_service.my_calendar(meera.actor())
    assert cal.work_date == D0_DATE
    frozen_clock.set(_at(1, 4, 0))
    assert calendar_service.my_calendar(meera.actor()).work_date == _day(1)


def test_sunday_and_the_demo_holiday_are_not_working_days(meera, frozen_clock) -> None:  # type: ignore[no-untyped-def]
    frozen_clock.set(_at(6, 10, 0))  # D0 is a Monday: +6 is Sunday
    sunday = calendar_service.my_calendar(meera.actor())
    assert sunday.day_type == "non_working" and sunday.next_working_day == _day(7)
    frozen_clock.set(_at(HOLIDAY_OFFSET_DAYS, 10, 0))
    holiday = calendar_service.my_calendar(meera.actor())
    assert holiday.day_type == "holiday" and holiday.is_working_day is False
    assert holiday.next_working_day == _day(HOLIDAY_OFFSET_DAYS + 1)


def test_built_in_default_without_any_calendar(api: ApiClient, company) -> None:  # type: ignore[no-untyped-def]
    company_id, _ = company
    someone = member(company_id, "Fresh Member", "employee")
    cal = api.as_(someone.actor()).get("/api/v1/org/calendar/me").json()
    assert cal["source"] == "built_in" and cal["calendar_code"] is None
    assert cal["shift"]["start_local"] == "09:30:00" and cal["shift"]["end_local"] == "18:30:00"
    assert cal["upcoming_holidays"] == []


def test_assignment_with_a_night_shift_and_its_own_rollover(seeded, meera, frozen_clock) -> None:  # type: ignore[no-untyped-def]
    company_id = seeded.company_id
    system = ActorContext.system(company_id, reason="test-setup")
    with UnitOfWork(system) as uow:
        cal_id = calendar_service.upsert_calendar(uow, code="NIGHT", name="Night", rollover=time(4, 0))
        shift_id = calendar_service.upsert_shift(
            uow, cal_id, code="NGT", name="Night shift", start_local=time(22, 0), end_local=time(6, 0),
            rollover_local=time(8, 0),
        )
        uow.add(WorkAssignment(user_id=meera.user_id, calendar_id=cal_id, shift_id=shift_id,
                               effective_from=_day(-11)))
    frozen_clock.set(_at(1, 7, 0))  # Tuesday 07:00, before the 08:00 rollover
    cal = calendar_service.my_calendar(meera.actor())
    assert cal.source == "assignment" and cal.calendar_code == "NIGHT"
    assert cal.work_date == D0_DATE
    assert cal.shift.code == "NGT"
    assert cal.shift.starts_at == _at(0, 22, 0)
    assert cal.shift.ends_at == _at(1, 6, 0)  # ends the next morning


def test_calendar_needs_the_read_permission(api: ApiClient, company) -> None:  # type: ignore[no-untyped-def]
    company_id, _ = company
    nobody = member(company_id, "No Calendar", extra={"search.global.use": Scope.COMPANY})
    r = api.as_(nobody.actor()).get("/api/v1/org/calendar/me")
    assert r.status_code == 403 and problem(r)["code"] == "permission_denied"


def test_calendar_maintenance_needs_manage(company) -> None:  # type: ignore[no-untyped-def]
    company_id, _ = company
    emp = member(company_id, "Clerk", "employee").actor()
    with pytest.raises(Forbidden):
        calendar_service.upsert_calendar(emp, code="X", name="X")


# ---- the org seed (SeedDef order 12) ------------------------------------------------------------------------
def test_org_seed_is_registered_after_identity() -> None:
    seeds = {s.name: s for s in get_registry().seeds}
    assert seeds["org.reference_calendar_settings"].order == 12


def test_org_seed_creates_the_fixture_world_and_is_idempotent(seeded, frozen_clock) -> None:  # type: ignore[no-untyped-def]
    company_id = seeded.company_id
    seed_org(seeded)  # second run: nothing new
    with UnitOfWork(ActorContext.system(company_id)) as uow:
        calendars = list(uow.session.scalars(select(WorkCalendar)))
        assert [(c.code, c.is_default, c.time_zone, c.workweek_mask) for c in calendars] == [
            (keys.CALENDARS.HO_GEN, True, keys.ZONE, 0b0111111)
        ]
        assert calendars[0].branch_id is not None
        shifts = list(uow.session.scalars(select(WorkShift)))
        assert [(s.code, s.start_local, s.end_local, s.precompute_offset_min) for s in shifts] == [
            (GEN_CODE, GEN_START, GEN_END, PRECOMPUTE_MINUTES)
        ]
        holidays = list(uow.session.scalars(select(WorkHoliday)))
        assert [(h.holiday_date, h.name) for h in holidays] == [(_day(HOLIDAY_OFFSET_DAYS), HOLIDAY_NAME)]
        assert uow.session.scalar(select(func.count()).select_from(Uom)) == len(DEFAULT_UOMS)
        terms = settings_service.get_setting(uow, "document_terms")
    assert terms.version == 1 and terms.value["quote"] == DEMO_TERMS["quote"]
    assert seeded.refs[keys.CALENDARS.HO_GEN] == calendars[0].id
    # identity, bank details and logo stay "not configured" in the demo world
    with UnitOfWork(ActorContext.system(company_id)) as uow:
        identity = settings_service.get_setting(uow, "company_identity")
        bank = settings_service.get_setting(uow, "bank_details")
    assert identity.configured is False and {"gstin", "pan", "iec", "logo_file_id"} <= set(identity.not_configured_fields)
    assert bank.configured is False


def test_seed_holiday_follows_the_anchor(company, frozen_clock) -> None:  # type: ignore[no-untyped-def]
    company_id, _ = company
    ctx = SeedContext(company_id=company_id, clock=frozen_clock, facts={"anchor_d0": keys.CLOCK_D0 + timedelta(days=21)})
    seed_org(ctx)
    with UnitOfWork(ActorContext.system(company_id)) as uow:
        assert list(uow.session.scalars(select(WorkHoliday.holiday_date))) == [_day(21 + HOLIDAY_OFFSET_DAYS)]
