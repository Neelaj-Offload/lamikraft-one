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



# =====================================================================================================
# Slice 4: the movement policy (LP-10.5, LP-10.6, SCN-I3) — the world adds WH-MAIN, the opening batch and go-live
# =====================================================================================================
from tests.integration.inventory.world import InvWorld, assert_ledger_consistent  # noqa: E402


def _order_with_reservation(w: InvWorld, qty: str = "240") -> tuple[object, object]:
    from app.modules.orders import service as orders

    order_id = w.order(keys.USERS.MEERA, w.won_quote(keys.USERS.MEERA, "NORDHAUS", ("OAK_TRAY", qty)))
    w.reserve(keys.USERS.MEERA, order_id)
    return order_id, orders


def test_issue_posts_exactly_one_movement(inv_world: InvWorld) -> None:
    """Issue twice with the same key, then with a new key, then a replayed movement hook (the logistics dispatch path):
    exactly one posting; on-hand decremented once; the SO line delivered 100, remaining 140."""
    from app.core.errors import InvalidTransition
    from app.modules.challans import movement
    from app.modules.challans.models import Challan, ChallanLine
    from app.modules.orders.schemas import ChallanFromOrder

    w = inv_world
    order_id, orders = _order_with_reservation(w)
    line_id = w.get_order(keys.USERS.MEERA, order_id).lines[0].id
    with w.uow(RAVI) as uow:
        challan_id = orders.create_challan_for_order(uow, order_id, ChallanFromOrder(quantities={line_id: Decimal(100)}))
    from app.modules.challans.schemas import ChallanTransition
    from app.modules.challans.transitions import transition_challan_command

    body = ChallanTransition(action="issue", expected_version=w.challan(RAVI, challan_id).version)
    with w.uow(RAVI, idempotency_key="issue-once") as uow:
        first, replayed = transition_challan_command(uow, challan_id, body)
    with w.uow(RAVI, idempotency_key="issue-once") as uow:  # the same Idempotency-Key: the stored answer
        replay, replayed = transition_challan_command(uow, challan_id, body)
    assert replayed and replay.issue_posting_id == first.issue_posting_id
    with pytest.raises(InvalidTransition):
        w.transition_challan(RAVI, challan_id, "issue")  # a new key: an issued challan is never issued again
    with w.uow(RAVI) as uow:  # a re-delivered dispatch calls the same hook: the ledger returns the same posting
        c = uow.session.get(Challan, challan_id)
        lines = list(uow.session.scalars(select(ChallanLine).where(ChallanLine.challan_id == challan_id)))
        assert movement.on_issue(uow, c, lines) == first.issue_posting_id  # type: ignore[arg-type]
    assert w.postings("challan", challan_id) == 1
    assert first.inventory_effect == "posting" and first.lines[0].sales_order_line_id == line_id
    assert w.summary("OAK_TRAY") == (Decimal(500), Decimal(140))
    line = w.get_order(keys.USERS.MEERA, order_id).lines[0]
    assert (line.qty_delivered, line.qty_remaining) == (Decimal(100), Decimal(140))
    issued_events = [e for e in _events(w, "challans.challan.issued") if str(e.payload["challan_id"]) == str(challan_id)]
    assert len(issued_events) == 1 and issued_events[0].payload["posting_id"] == str(first.issue_posting_id)
    assert issued_events[0].payload["inventory_effect"] == "posting"
    assert_ledger_consistent(w)


def test_job_work_stays_company_owned_and_partial_return_reconciles(inv_world: InvWorld) -> None:
    """Job Work moves to the fabricator's holding (company-owned, not available); a partial return of 4 of 10 moves
    back from the holding, a further 7 is excess, and issuing the return again posts nothing."""
    from app.core.errors import InvalidTransition
    from app.modules.inventory.models import Location, StockBalance

    w = inv_world
    out = w.new_challan(RAVI, ("ASH_BOARD", "10"), challan_type=ChallanType.JOB_WORK, destination_type=DestinationType.FABRICATOR,
                        party_id=w.ref("PRECISION_EDGE"))
    issued = w.transition_challan(RAVI, out.id, "issue")
    assert issued.inventory_effect == "posting" and w.summary("ASH_BOARD")[0] == Decimal(190)
    with w.system() as uow:
        holding = uow.session.scalars(select(StockBalance).join(Location, Location.id == StockBalance.location_id).where(
            StockBalance.company_id == w.company_id, Location.location_type == "external_holding",
            StockBalance.product_id == w.ref("ASH_BOARD"))).one()
        assert holding.quantity == Decimal(10) and holding.owner_party_id is None  # still company-owned
    with w.uow(RAVI) as uow:
        ret = challans.create_challan(uow, ChallanCreate(
            challan_type=ChallanType.RETURN, destination_type=DestinationType.FABRICATOR, original_challan_id=out.id,
            lines=[ChallanLineCreate(line_type=LineType.CATALOG, product_id=w.ref("ASH_BOARD"), quantity=Decimal(4), original_line_id=issued.lines[0].id)]))
        ret_id = ret.id
    back = w.transition_challan(RAVI, ret_id, "issue")
    assert back.inventory_effect == "posting" and w.summary("ASH_BOARD")[0] == Decimal(194)
    after = w.challan(RAVI, out.id)
    assert after.lines[0].outstanding_quantity == Decimal(6) and after.outstanding_by_unit == {"pcs": Decimal(6)}
    with pytest.raises(ValidationFailed), w.uow(RAVI) as uow:
        challans.create_challan(uow, ChallanCreate(
            challan_type=ChallanType.RETURN, destination_type=DestinationType.FABRICATOR, original_challan_id=out.id,
            lines=[ChallanLineCreate(line_type=LineType.CATALOG, product_id=w.ref("ASH_BOARD"), quantity=Decimal(7), original_line_id=issued.lines[0].id)]))
    with pytest.raises(InvalidTransition):
        w.transition_challan(RAVI, ret_id, "issue")
    assert w.postings("challan", ret_id) == 1 and len(w.challan(RAVI, ret_id).return_links) == 1
    assert_ledger_consistent(w)


def test_cancel_issued_creates_reversal(inv_world: InvWorld) -> None:
    """A reversal posting with reverses_posting_id; the original is kept; on-hand and SO delivered are restored; a
    second cancel or a cancel with returns linked is rejected; history records actor and reason; needs a recent sign-in."""
    from app.core.errors import InvalidTransition
    from app.modules.challans.schemas import ChallanTransition
    from app.modules.challans.transitions import transition_challan_command
    from app.modules.inventory.models import StockPosting
    from app.modules.orders.schemas import ChallanFromOrder
    from app.platform.authz.stepup import ReauthRequired

    w = inv_world
    order_id, orders = _order_with_reservation(w)
    line_id = w.get_order(keys.USERS.MEERA, order_id).lines[0].id
    with w.uow(RAVI) as uow:
        challan_id = orders.create_challan_for_order(uow, order_id, ChallanFromOrder(quantities={line_id: Decimal(60)}))
    issued = w.transition_challan(RAVI, challan_id, "issue")
    assert w.summary("OAK_TRAY")[0] == Decimal(540)
    with pytest.raises(ReauthRequired), w.uow(RAVI, idempotency_key="no-step-up") as uow:
        transition_challan_command(uow, challan_id, ChallanTransition(action="cancel", expected_version=issued.version, reason_code="wrong_items"))
    cancelled = w.transition_challan(RAVI, challan_id, "cancel", reason_code="wrong_items", reason="Wrong pallet")
    assert cancelled.status == "cancelled" and cancelled.reversal_posting_id and cancelled.issue_posting_id == issued.issue_posting_id
    with w.system() as uow:
        rev = uow.session.get(StockPosting, cancelled.reversal_posting_id)
        orig = uow.session.get(StockPosting, issued.issue_posting_id)
        assert rev is not None and orig is not None and rev.reverses_posting_id == orig.id
        assert (rev.source_type, rev.purpose) == ("challan", "cancel")
    assert w.summary("OAK_TRAY")[0] == Decimal(600)
    assert w.get_order(keys.USERS.MEERA, order_id).lines[0].qty_delivered == Decimal(0)
    last = cancelled.history[-1]
    assert (last.action, last.reason_code, last.reason) == ("cancel", "wrong_items", "Wrong pallet") and last.actor is not None
    cancel_events = [e for e in _events(w, "challans.challan.cancelled") if str(e.payload["challan_id"]) == str(challan_id)]
    assert cancel_events[0].payload["reversal_posting_id"] == str(cancelled.reversal_posting_id)
    with pytest.raises(InvalidTransition):
        w.transition_challan(RAVI, challan_id, "cancel", reason_code="wrong_items")
    # a challan with a return linked cannot be cancelled
    sample = w.new_challan(RAVI, ("MAPLE_TRIVET", "10"), challan_type=ChallanType.SAMPLE, destination_type=DestinationType.CUSTOMER,
                           party_id=w.ref("MAISON"), return_type=ReturnType.RETURNABLE)
    sent = w.transition_challan(RAVI, sample.id, "issue")
    with w.uow(RAVI) as uow:
        ret = challans.create_challan(uow, ChallanCreate(
            challan_type=ChallanType.RETURN, destination_type=DestinationType.CUSTOMER, original_challan_id=sample.id,
            lines=[ChallanLineCreate(line_type=LineType.CATALOG, product_id=w.ref("MAPLE_TRIVET"), quantity=Decimal(4), original_line_id=sent.lines[0].id)]))
        ret_id = ret.id
    w.transition_challan(RAVI, ret_id, "issue")
    with pytest.raises(Conflict) as exc:
        w.transition_challan(RAVI, sample.id, "cancel", reason_code="wrong_items")
    assert exc.value.code == "has_return_links"
    assert_ledger_consistent(w)


def test_legacy_and_pre_go_live_challans_never_move_stock(inv_world: InvWorld) -> None:
    w = inv_world
    legacy = w.challan(RAVI, w.ref(keys.CHALLAN_REFS.JOB_WORK))  # issued D-7, before go-live
    assert legacy.inventory_effect == "none" and legacy.issue_posting_id is None
    with w.uow(RAVI) as uow:
        imported = challans.create_challan(
            uow,
            ChallanCreate(party_id=w.ref("NORDHAUS"), lines=[ChallanLineCreate(line_type=LineType.CATALOG, product_id=w.ref("OAK_TRAY"), quantity=Decimal(5))]),
            origin="migration",
        )
        imported_id = imported.id
    done = w.transition_challan(RAVI, imported_id, "issue")
    assert done.inventory_effect == "none" and w.postings("challan", imported_id) == 0
    assert w.summary("OAK_TRAY")[0] == Decimal(600)
