"""Issue, return reconciliation as document links, cancel of issued documents and the events (LM-94, events.md §3.9).

No stock moves in Slice 2: ``inventory_effect`` stays ``none`` and the posting ids stay null; the return links and the
``returned_qty`` counters are document figures that Slice 4 attaches movements to."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.errors import Conflict, ValidationFailed
from app.modules.challans import service as challans
from app.modules.challans.schemas import (
    ChallanCreate,
    ChallanLineCreate,
    ChallanType,
    DestinationType,
    LineType,
    ReturnType,
)
from app.platform.events.models import DomainEvent
from app.seed.world import keys
from tests.integration.challans.world import ChallanWorld

pytestmark = pytest.mark.db
RAVI = keys.USERS.RAVI


def _events(w: ChallanWorld, name: str) -> list[DomainEvent]:
    with w.uow(RAVI) as uow:
        return list(uow.session.scalars(select(DomainEvent).where(DomainEvent.company_id == w.company_id, DomainEvent.event_type == name).order_by(DomainEvent.occurred_at)))


def test_partial_return_linked_to_original_line(challan_world: ChallanWorld) -> None:
    w = challan_world
    original = w.challan(RAVI, keys.CHALLAN_REFS.JOB_WORK)  # 12 boards out, returnable
    [out_line] = original.lines
    assert out_line.outstanding_quantity == Decimal("12") and original.inventory_effect == "none"
    sample_line_id = w.challan(RAVI, keys.CHALLAN_REFS.SAMPLE_MAISON).lines[0].id  # read outside the unit of work below
    with w.uow(RAVI) as uow:
        ret = challans.create_challan(uow, ChallanCreate(
            challan_type=ChallanType.RETURN, destination_type=DestinationType.FABRICATOR, original_challan_id=original.id,
            lines=[ChallanLineCreate(line_type=LineType.CATALOG, product_id=w.ref("WALNUT_BOARD"), quantity=Decimal("5"), original_line_id=out_line.id)],
        ))
        d = challans.detail(uow, ret)
        assert d.return_type == ReturnType.RETURNABLE and d.party and d.party.id == original.party.id  # inherited from the original
        assert d.destination_party == original.destination_party and d.original_challan and d.original_challan.id == original.id
        assert d.direction == "inward" and d.capabilities["issue"].allowed is True
        with pytest.raises(ValidationFailed) as exc:  # more than is out
            challans.create_challan(uow, ChallanCreate(
                challan_type=ChallanType.RETURN, destination_type=DestinationType.FABRICATOR, original_challan_id=original.id,
                lines=[ChallanLineCreate(line_type=LineType.MANUAL, item_name="boards", quantity=Decimal("13"), original_line_id=out_line.id)],
            ))
        assert "excess_return" in {e["code"] for e in exc.value.extra["errors"]}
        with pytest.raises(ValidationFailed) as exc:  # a line of another challan is not an original line
            challans.create_challan(uow, ChallanCreate(
                challan_type=ChallanType.RETURN, destination_type=DestinationType.FABRICATOR, original_challan_id=original.id,
                lines=[ChallanLineCreate(line_type=LineType.MANUAL, item_name="x", quantity=Decimal("1"), original_line_id=sample_line_id)],
            ))
        assert "not_an_original_line" in {e["code"] for e in exc.value.extra["errors"]}
        with pytest.raises(ValidationFailed) as exc:  # a Return against a draft is refused
            challans.create_challan(uow, ChallanCreate(challan_type=ChallanType.RETURN, destination_type=DestinationType.CUSTOMER,
                                                        original_challan_id=w.ref(keys.CHALLAN_REFS.OUTWARD_DRAFT)))
        assert "original_not_issued" in {e["code"] for e in exc.value.extra["errors"]}
    received = w.transition(RAVI, ret.id, "issue")
    assert received.status == "issued" and len(received.return_links) == 1
    link = received.return_links[0]
    assert (link.original_challan.id, link.original_line_id, link.quantity, link.kind) == (original.id, out_line.id, Decimal("5"), "returned")
    after = w.challan(RAVI, keys.CHALLAN_REFS.JOB_WORK)
    assert after.status == "issued" and after.lines[0].returned_quantity == Decimal("5") and after.lines[0].outstanding_quantity == Decimal("7")
    assert after.outstanding_by_unit == {"sheets": Decimal("7")} and after.return_links[0].return_challan.id == ret.id
    # events: issued (with the catalogued payload) and return.received naming the original lines
    issued_events = [e for e in _events(w, "challans.challan.issued") if str(e.payload["challan_id"]) == str(ret.id)]
    assert len(issued_events) == 1
    payload = issued_events[0].payload
    assert set(payload) >= {"challan_id", "challan_number", "challan_type", "return_type", "destination_type", "party_id", "inventory_effect", "posting_id", "sample_id"}
    assert payload["inventory_effect"] == "none" and payload["posting_id"] is None and payload["challan_type"] == "return"
    returns = _events(w, "challans.return.received")
    assert len(returns) == 1 and returns[0].payload["original_challan_id"] == str(original.id) and returns[0].payload["original_line_ids"] == [str(out_line.id)]
    # the rest comes back: the original auto-closes when every line is fully returned
    with w.uow(RAVI) as uow:
        rest = challans.create_challan(uow, ChallanCreate(
            challan_type=ChallanType.RETURN, destination_type=DestinationType.FABRICATOR, original_challan_id=original.id,
            lines=[ChallanLineCreate(line_type=LineType.MANUAL, item_name="Walnut boards", quantity=Decimal("7"), original_line_id=out_line.id)],
        ))
    w.transition(RAVI, rest.id, "issue")
    closed = w.challan(RAVI, keys.CHALLAN_REFS.JOB_WORK)
    assert closed.status == "closed" and closed.lines[0].outstanding_quantity == Decimal("0") and closed.outstanding_by_unit == {}
    assert closed.history[-1].reason_code == "all_returned"
    assert any(str(e.payload["challan_id"]) == str(original.id) for e in _events(w, "challans.challan.closed"))
    # the original can no longer be cancelled (returns reference it); the return challan can, which gives the outstanding back
    with w.uow(RAVI) as uow:
        assert challans.get_challan(uow, rest.id).capabilities["reverse"].allowed is True
    cancelled = w.transition(RAVI, rest.id, "cancel", reason_code="wrong_challan", reason="Logged against the wrong challan")
    assert cancelled.status == "cancelled" and cancelled.cancel_reason_code == "wrong_challan" and cancelled.return_links[0].reversed_at is not None
    reopened = w.challan(RAVI, keys.CHALLAN_REFS.JOB_WORK)
    assert reopened.lines[0].returned_quantity == Decimal("5") and reopened.status == "closed"  # closed is terminal; the figure is corrected
    cancel_events = _events(w, "challans.challan.cancelled")
    assert cancel_events[-1].payload == {"challan_id": str(rest.id), "reason_code": "wrong_challan", "reversal_posting_id": None, "origin": "user"}


def test_cancel_issued_is_document_only_and_blocked_by_returns(challan_world: ChallanWorld) -> None:
    w = challan_world
    sample = w.challan(RAVI, keys.CHALLAN_REFS.SAMPLE_MAISON)
    with w.uow(RAVI) as uow:
        d = challans.get_challan(uow, sample.id)
        assert d.capabilities["reverse"].allowed is True and {t.action for t in d.allowed_transitions} == {"close", "cancel"}
    cancelled = w.transition(RAVI, sample.id, "cancel", reason="Samples never left the office")
    assert cancelled.status == "cancelled" and cancelled.cancel_reason_code == "other" and cancelled.inventory_effect == "none"
    assert cancelled.revision_no == 1 and cancelled.allowed_transitions == []  # the issued revision stays on record
    # a challan with live returns cannot be cancelled
    original = w.challan(RAVI, keys.CHALLAN_REFS.JOB_WORK)
    with w.uow(RAVI) as uow:
        ret = challans.create_challan(uow, ChallanCreate(
            challan_type=ChallanType.RETURN, destination_type=DestinationType.FABRICATOR, original_challan_id=original.id,
            lines=[ChallanLineCreate(line_type=LineType.MANUAL, item_name="boards", quantity=Decimal("1"), original_line_id=original.lines[0].id)],
        ))
    w.transition(RAVI, ret.id, "issue")
    with w.uow(RAVI) as uow:
        d = challans.get_challan(uow, original.id)
        assert d.capabilities["reverse"].allowed is False and d.capabilities["reverse"].reason_code == "has_return_links"
        assert {t.action for t in d.allowed_transitions} == {"close"}
    with pytest.raises(Conflict) as exc:
        w.transition(RAVI, original.id, "cancel", reason="x")
    assert exc.value.code == "has_return_links"
