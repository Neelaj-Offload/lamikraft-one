"""The fixture challans (fixtures.md §8), the ``draft_challan`` tool and the returnables sweep (scheduled events)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.errors import Forbidden
from app.modules.challans import jobs
from app.modules.challans import service as challans
from app.modules.challans.schemas import (
    ChallanType,
    DestinationType,
    DraftChallanInput,
    DraftChallanLine,
    ReturnType,
)
from app.modules.challans.tools import draft_challan
from app.platform.authz.context import ActorContext
from app.platform.events.models import DomainEvent
from app.platform.sources import read as read_source
from app.platform.uow import UnitOfWork
from app.seed.context import D0
from app.seed.world import keys
from app.seed.world.challans import seed_challans
from tests.integration.challans.world import ChallanWorld

pytestmark = pytest.mark.db
RAVI, MEERA, KABIR = keys.USERS.RAVI, keys.USERS.MEERA, keys.USERS.KABIR


def test_seed_world_matches_fixtures_and_is_idempotent(challan_world: ChallanWorld) -> None:
    w = challan_world
    job_work = w.challan(RAVI, keys.CHALLAN_REFS.JOB_WORK)
    assert job_work.challan_number == keys.CHALLANS.JOB_WORK and job_work.status == "issued"
    assert (job_work.challan_type, job_work.return_type, job_work.destination_type) == (ChallanType.JOB_WORK, ReturnType.RETURNABLE, DestinationType.FABRICATOR)
    assert job_work.destination_party == keys.PARTY_NAMES["PRECISION_EDGE"] and job_work.party and job_work.party.id == w.ref("PRECISION_EDGE")
    assert job_work.challan_date == (D0 - timedelta(days=7)).date() and job_work.expected_return_date == (D0 + timedelta(days=1)).date()
    assert job_work.issued_by and job_work.issued_by.id == w.user_id(RAVI) and job_work.origin == "seed"
    assert [(ln.item_code, ln.quantity, ln.unit) for ln in job_work.lines] == [(keys.PRODUCTS.WALNUT_BOARD, Decimal("12"), "sheets")]
    sample = w.challan(RAVI, keys.CHALLAN_REFS.SAMPLE_MAISON)
    assert sample.challan_number == keys.CHALLANS.SAMPLE_MAISON and sample.status == "issued" and sample.challan_type == ChallanType.SAMPLE
    assert [(ln.item_code, ln.quantity) for ln in sample.lines] == [(keys.PRODUCTS.ASH_BOARD, Decimal("2"))]
    draft = w.challan(RAVI, keys.CHALLAN_REFS.OUTWARD_DRAFT)
    assert draft.challan_number == keys.CHALLANS.OUTWARD_DRAFT and draft.status == "draft" and draft.created_at == D0 - timedelta(minutes=25)
    before = {k: v for k, v in w.ctx.refs.items() if k.startswith("DC_")}
    seed_challans(w.ctx)  # a second run creates nothing new
    assert {k: v for k, v in w.ctx.refs.items() if k.startswith("DC_")} == before
    with w.uow(RAVI) as uow:
        from app.modules.challans.schemas import ChallanFilters

        assert challans.list_challans(uow, ChallanFilters()).total == 3
    w.at(D0)


def test_draft_challan_tool_creates_an_owned_draft_only(challan_world: ChallanWorld) -> None:
    w = challan_world
    data = DraftChallanInput(
        challan_type=ChallanType.OUTWARD, destination_type=DestinationType.CUSTOMER, party_id=w.ref("NORDHAUS"), reference_no="WA-2211",
        lines=[DraftChallanLine(product_key=keys.PRODUCTS.OAK_TRAY, quantity=Decimal("40")), DraftChallanLine(item_name="Pallet wrap", quantity=Decimal("2"), unit="roll")],
    )
    with w.uow(RAVI, actor_type="agent", idempotency_key="step-1") as uow:
        d = draft_challan(uow, data)
    assert d.status == "draft" and d.origin == "agent" and d.owner.id == w.user_id(RAVI) and d.inventory_effect == "none"
    assert [(ln.line_type, ln.item_code, ln.quantity, ln.unit) for ln in d.lines] == [("catalog", keys.PRODUCTS.OAK_TRAY, Decimal("40"), "pcs"), ("manual", None, Decimal("2"), "roll")]
    assert d.destination_party == keys.PARTY_NAMES["NORDHAUS"]
    with pytest.raises(Forbidden):  # no create right: the tool can do no more than the user
        with w.uow(KABIR) as uow:
            draft_challan(uow, data)
    with w.uow(RAVI) as uow:  # the source reader exposes the facts the rules and briefings need, never the note
        facts = read_source(uow, "challans.challan", d.id)
        assert facts is not None and facts.facts["challan_number"] == d.challan_number and facts.facts["quantity_by_unit"] == {"pcs": "40", "roll": "2"}
        assert facts.canonical_path == f"/operations/challans/{d.id}" and facts.required_permission == "challans.challan.read"
    with w.uow(MEERA) as uow:
        assert read_source(uow, "challans.challan", d.id) is None  # invisible reads as None


def test_returnables_sweep_emits_due_then_overdue_once(challan_world: ChallanWorld) -> None:
    w = challan_world

    def events(name: str) -> list[DomainEvent]:
        with w.uow(RAVI) as uow:
            return list(uow.session.scalars(select(DomainEvent).where(DomainEvent.company_id == w.company_id, DomainEvent.event_type == name)))

    def sweep() -> int:
        with UnitOfWork(ActorContext.system(w.company_id, reason="test"), clock=w.ctx.clock) as uow:
            return jobs.sweep_returnables(uow)

    assert sweep() == 0 and events("challans.returnable.became_due") == []  # D0: the job-work return is due D0+1
    w.at(D0 + timedelta(days=1))
    assert sweep() == 1
    due = events("challans.returnable.became_due")
    assert len(due) == 1 and due[0].payload["challan_id"] == str(w.ref(keys.CHALLAN_REFS.JOB_WORK))
    assert due[0].payload["expected_return_date"] == (D0 + timedelta(days=1)).date().isoformat()
    assert sweep() == 0  # idempotent on the same day
    w.at(D0 + timedelta(days=2))
    assert sweep() == 1
    overdue = events("challans.returnable.became_overdue")
    assert len(overdue) == 1 and overdue[0].payload["challan_id"] == due[0].payload["challan_id"]
    assert sweep() == 0 and len(events("challans.returnable.became_due")) == 1
    # a returned (closed) challan is never swept again
    w.at(D0 + timedelta(days=40))
    assert sweep() == 2  # the sample challan (expected return D-3 + 30 = D0+27) becomes due and overdue
    w.at(D0)
