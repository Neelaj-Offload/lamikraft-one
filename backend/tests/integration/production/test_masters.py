"""BOM and routing versions: separation of duties (service 403 and the database CHECK), immutability once approved,
one approved version per product (approving v2 retires v1), validation at approval (cycles, alternates, units),
work centres with calendar capacity and the protected hourly rate."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import text, update
from sqlalchemy.exc import IntegrityError

from app.core.errors import Conflict, Forbidden, ValidationFailed
from app.core.money import Money
from app.modules.production import service
from app.modules.production.models import Bom
from app.modules.production.schemas import (
    BomCreate,
    BomLineIn,
    BomUpdate,
    MasterCommand,
    RoutingCreate,
    RoutingOperationIn,
    WorkCenterCreate,
)
from app.seed.world import keys
from tests.integration.production.world import DEEPA, ProdWorld

pytestmark = pytest.mark.db
SAHIL, RAVI = keys.USERS.SAHIL, keys.USERS.RAVI


def _draft_bom(w: ProdWorld, qty: str = "5") -> object:
    with w.uow(DEEPA) as uow:
        return service.create_bom(uow, BomCreate(product_id=w.panel_set, copy_from_id=w.ref(keys.PRODUCTION_REFS.BOM_PANEL_SET),
                                                 lines=[BomLineIn(component_product_id=w.walnut, qty_per=Decimal(qty),
                                                                  uom_code="sheets", is_sheet_material=True)]))


def test_bom_approval_separation_of_duties_and_immutability(prod_world: ProdWorld) -> None:
    w = prod_world
    v2 = _draft_bom(w)
    assert v2.version_no == 2 and v2.status == "draft"
    assert v2.capabilities["approve"].allowed is False and v2.capabilities["approve"].reason_code == "separation_of_duties"
    with w.uow(DEEPA) as uow, pytest.raises(Forbidden) as exc:
        service.approve_bom(uow, v2.id, MasterCommand(expected_version=v2.version))
    assert exc.value.code == "separation_of_duties"
    # operations may read BOMs but not approve them
    with w.uow(RAVI) as uow, pytest.raises(Forbidden):
        service.approve_bom(uow, v2.id, MasterCommand(expected_version=v2.version))
    with w.uow(SAHIL) as uow:
        approved = service.approve_bom(uow, v2.id, MasterCommand(expected_version=v2.version))
    assert approved.status == "approved" and approved.approved_by and approved.approved_by.id == w.user_id(SAHIL)
    with w.uow(DEEPA) as uow:
        v1 = service.bom(uow, w.ref(keys.PRODUCTION_REFS.BOM_PANEL_SET))
        assert v1.status == "retired" and v1.retired_at is not None
        with pytest.raises(Conflict) as c:
            service.update_bom(uow, approved.id, BomUpdate(expected_version=approved.version, notes="change"))
        assert c.value.code == "version_approved"


def test_database_rejects_an_author_approving_their_own_version(prod_world: ProdWorld) -> None:
    w = prod_world
    v2 = _draft_bom(w)
    with w.system() as uow:
        uow.session.execute(text("SAVEPOINT sod"))
        with pytest.raises(IntegrityError) as exc:
            uow.session.execute(update(Bom).where(Bom.id == v2.id).values(status="approved", approved_by=w.user_id(DEEPA)))
        uow.session.execute(text("ROLLBACK TO SAVEPOINT sod"))
    assert "approver_not_author" in str(exc.value)


def test_one_approved_version_per_product_in_the_database(prod_world: ProdWorld) -> None:
    w = prod_world
    v2 = _draft_bom(w)
    with w.system() as uow:
        uow.session.execute(text("SAVEPOINT one"))
        with pytest.raises(IntegrityError) as exc:
            uow.session.execute(update(Bom).where(Bom.id == v2.id).values(status="approved", approved_by=w.user_id(SAHIL)))
        uow.session.execute(text("ROLLBACK TO SAVEPOINT one"))
    assert "uq_production_bom_one_approved" in str(exc.value)


def test_bom_cycle_and_bad_alternate_rejected_at_approval(prod_world: ProdWorld) -> None:
    w = prod_world
    # the walnut board made from the panel set: a cycle through the approved panel-set BOM
    with w.uow(DEEPA) as uow:
        cyc = service.create_bom(uow, BomCreate(product_id=w.walnut, lines=[
            BomLineIn(component_product_id=w.panel_set, qty_per=Decimal("0.2"), uom_code="set"),
            BomLineIn(line_no=5, component_product_id=w.ref("ASH_BOARD"), qty_per=Decimal(1), alternate_for_line_no=9)]))
    with w.uow(SAHIL) as uow, pytest.raises(ValidationFailed) as exc:
        service.approve_bom(uow, cyc.id, MasterCommand(expected_version=cyc.version))
    codes = {e["code"] for e in exc.value.extra["errors"]}
    assert {"bom_cycle", "alternate_without_primary"} <= codes


def test_routing_approval_separation_and_retirement(prod_world: ProdWorld) -> None:
    w = prod_world
    with w.uow(DEEPA) as uow:
        r2 = service.create_routing(uow, RoutingCreate(product_id=w.panel_set, operations=[
            RoutingOperationIn(seq=10, name="Cut", work_center_id=w.ref(keys.WORK_CENTER_REFS.PANEL_SAW),
                               setup_minutes=Decimal(20), run_minutes_per_unit=Decimal(15), is_board_cutting=True)]))
        with pytest.raises(Forbidden):
            service.approve_routing(uow, r2.id, MasterCommand(expected_version=r2.version))
    with w.uow(SAHIL) as uow:
        approved = service.approve_routing(uow, r2.id, MasterCommand(expected_version=r2.version))
        old = service.routing(uow, w.ref(keys.PRODUCTION_REFS.ROUTING_PANEL_SET))
    assert approved.status == "approved" and old.status == "retired"


def test_work_center_capacity_from_calendar_and_rate_redaction(prod_world: ProdWorld) -> None:
    w = prod_world
    with w.uow(DEEPA) as uow:
        saw = service.work_center(uow, w.ref(keys.WORK_CENTER_REFS.PANEL_SAW))
        created = service.create_work_center(uow, WorkCenterCreate(code="CNC-1", name="CNC router", machine_count=2,
                                                                   efficiency_pct=Decimal(50),
                                                                   rate_per_hour=Money(amount=Decimal("1500"), currency="INR")))
    # default company calendar: one 09:30-18:30 shift = 540 min; x 1 saw x 85 % = 459
    assert saw.standard_day_minutes == Decimal("459.0000") and saw.calendar.source in ("company_default", "built_in")
    assert saw.rate_per_hour == Money(amount=Decimal("1200.0000"), currency="INR")
    assert created.standard_day_minutes == Decimal("540.0000")
    with w.uow(RAVI) as uow:
        seen = service.work_center(uow, w.ref(keys.WORK_CENTER_REFS.PANEL_SAW))
        with pytest.raises(Forbidden):
            service.create_work_center(uow, WorkCenterCreate(code="X", name="X"))
    assert seen.rate_per_hour is None and "rate_per_hour" in seen.redacted_fields
