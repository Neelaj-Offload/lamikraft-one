"""Revisions (LM-53, LM-54, FG-QRV-03, LP-06.10): revise opens a working copy of a sent quote, re-issue creates the next
immutable revision; compare reports header, lines by line_key and totals; restore copies a revision into a new working
copy without rewriting history; discard drops the working copy."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.core.errors import Conflict, NotFound
from app.modules.sales import service as sales
from app.modules.sales.models import QuoteRevision, QuoteStatusHistory
from app.modules.sales.schemas import QuoteLineCreate, QuoteLineUpdate, RestoreRevision
from app.platform.events.models import DomainEvent
from app.seed.world import keys
from tests.integration.sales.world import SalesWorld

pytestmark = pytest.mark.db
MEERA, NEHA, SAHIL = keys.USERS.MEERA, keys.USERS.NEHA, keys.USERS.SAHIL


def _set_qty(world: SalesWorld, quote_id, qty: str):  # type: ignore[no-untyped-def]
    with world.uow(MEERA) as uow:
        q = sales.get_quote(uow, quote_id)
        quote, _line = sales.update_line(uow, quote_id, q.lines[0].id, QuoteLineUpdate(expected_version=q.version, quantity=Decimal(qty)))
        return sales.detail(uow, quote)


def _add(world: SalesWorld, quote_id, product: str, qty: str):  # type: ignore[no-untyped-def]
    with world.uow(MEERA) as uow:
        q = sales.get_quote(uow, quote_id)
        quote, _line = sales.add_line(uow, quote_id, QuoteLineCreate(expected_version=q.version, product_id=world.ref(product), quantity=Decimal(qty)))
        return sales.detail(uow, quote)


def _history(world: SalesWorld, quote_id) -> list[tuple[str, str, str]]:  # type: ignore[no-untyped-def]
    with world.uow(SAHIL) as uow:
        rows = uow.session.scalars(select(QuoteStatusHistory).where(QuoteStatusHistory.quote_id == quote_id)
                                   .order_by(QuoteStatusHistory.occurred_at, QuoteStatusHistory.id)).all()
        return [(r.action, r.from_status, r.to_status) for r in rows]


def test_revise_creates_working_copy(world: SalesWorld) -> None:
    d = world.new_draft(MEERA, "NORDHAUS", ("OAK_TRAY", "240"))
    sent = world.transition(MEERA, d.id, "mark_sent")
    assert (sent.status, sent.revision_no, sent.capabilities["update"].allowed) == ("sent", 1, False)
    revised = world.transition(MEERA, d.id, "revise")
    assert (revised.status, revised.revision_no) == ("revised", 1)
    assert revised.capabilities["update"].allowed and revised.capabilities["add_line"].allowed
    assert [t.action for t in revised.allowed_transitions] == ["submit_review", "mark_sent", "discard_revision", "mark_lost", "cancel"]
    edited = _set_qty(world, d.id, "264")
    assert edited.status == "revised" and edited.totals.grand_total.amount == Decimal("6336.00")  # type: ignore[union-attr]
    reissued = world.transition(MEERA, d.id, "mark_sent")
    assert (reissued.status, reissued.revision_no) == ("sent", 2)
    with world.uow(MEERA) as uow:
        revisions = sales.list_revisions(uow, d.id)
        first = sales.get_revision(uow, d.id, 1)
    assert [r.revision_no for r in revisions] == [1, 2]
    assert first.snapshot["lines"][0]["quantity"] == "240.000000" and first.snapshot["totals"]["grand_total"] == "5760.0000"
    # discard: a second working copy is dropped and the quote is the latest issued revision again
    world.transition(MEERA, d.id, "revise")
    _set_qty(world, d.id, "480")
    discarded = world.transition(MEERA, d.id, "discard_revision")
    assert discarded.status == "sent" and discarded.lines[0].quantity == Decimal("264") and discarded.revision_no == 2
    assert discarded.totals.grand_total.amount == Decimal("6336.00")  # type: ignore[union-attr]
    assert _history(world, d.id) == [
        ("mark_sent", "draft", "sent"), ("revise", "sent", "revised"), ("mark_sent", "revised", "sent"),
        ("revise", "sent", "revised"), ("discard_revision", "revised", "sent"),
    ]
    with world.uow(SAHIL) as uow:
        revised_events = [p for n, p in uow.session.execute(
            select(DomainEvent.event_type, DomainEvent.payload).where(DomainEvent.aggregate_id == d.id).order_by(DomainEvent.seq)
        ).all() if n == "sales.quote.revised"]
    assert [p["revision_no"] for p in revised_events] == [2, 3]
    # issued revisions stay immutable in the database
    with pytest.raises(DBAPIError, match="append-only|permission denied"), world.uow(SAHIL) as uow:
        uow.session.execute(text("UPDATE sales_quote_revision SET content_hash = 'x' WHERE quote_id = :q"), {"q": d.id})


def test_compare_and_restore_keep_history(world: SalesWorld) -> None:
    d = world.new_draft(MEERA, "NORDHAUS", ("OAK_TRAY", "240"))
    world.transition(MEERA, d.id, "mark_sent")
    world.transition(MEERA, d.id, "revise")
    _set_qty(world, d.id, "264")
    v2 = _add(world, d.id, "MAPLE_TRIVET", "100")
    oak_key = str(v2.lines[0].line_key)
    world.transition(MEERA, d.id, "mark_sent")
    with world.uow(MEERA) as uow:
        cmp = sales.compare_revisions(uow, d.id, 1, 2)
    by_key = {line.line_key: line for line in cmp.lines}
    assert by_key[oak_key].change == "changed"
    assert [(c.field, c.before, c.after) for c in by_key[oak_key].changes if c.field == "quantity"] == [("quantity", "240.000000", "264.000000")]
    added = [line for line in cmp.lines if line.change == "added"]
    assert len(added) == 1 and added[0].line_no_after == 2
    grand = next(t for t in cmp.totals if t.field == "grand_total")
    assert (grand.before, grand.after, grand.delta) == (Decimal("5760.00"), Decimal("7286.00"), Decimal("1526.00"))
    assert "1 line added" in cmp.summary and "1 line changed" in cmp.summary and "+1526.00 EUR" in cmp.summary
    with world.uow(MEERA) as uow:
        assert sales.compare_revisions(uow, d.id, 2).summary == "No differences"  # revision 2 vs the working copy
    # restore revision 1 from sent: an implicit revise, then a new working copy; issued revisions untouched
    with world.uow(MEERA) as uow:
        current = sales.get_quote(uow, d.id)
        restored, _ = sales.restore_revision_command(uow, d.id, 1, RestoreRevision(expected_version=current.version, reason="Customer took the first offer"))
    assert restored.status == "revised" and restored.restored_from_revision_no == 1 and len(restored.lines) == 1
    assert str(restored.lines[0].line_key) == oak_key and restored.lines[0].quantity == Decimal("240")
    assert restored.lines[0].restored_from_revision_no == 1 and restored.totals.grand_total.amount == Decimal("5760.00")  # type: ignore[union-attr]
    with world.uow(MEERA) as uow:
        after = sales.compare_revisions(uow, d.id, 2)
    assert {line.change for line in after.lines} == {"changed", "removed"}
    with world.uow(SAHIL) as uow:
        hashes = [r.content_hash for r in uow.session.scalars(select(QuoteRevision).where(QuoteRevision.quote_id == d.id).order_by(QuoteRevision.revision_no))]
    assert len(hashes) == 2 and hashes[0] != hashes[1]
    assert _history(world, d.id)[-2:] == [("revise", "sent", "revised"), ("restore", "revised", "revised")]
    third = world.transition(MEERA, d.id, "mark_sent")
    assert third.revision_no == 3 and third.totals.grand_total.amount == Decimal("5760.00")  # type: ignore[union-attr]
    # never on a closed quote, never outside scope
    world.transition(MEERA, d.id, "mark_won")
    with pytest.raises(Conflict), world.uow(MEERA) as uow:
        sales.restore_revision(uow, d.id, 1, RestoreRevision(expected_version=sales.get_quote(uow, d.id).version))
    with pytest.raises(NotFound), world.uow(NEHA) as uow:
        sales.compare_revisions(uow, d.id, 1, 2)
