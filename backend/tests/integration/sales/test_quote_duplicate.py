"""Duplicate (LM-55, API-45, BUG-02, LP-06.7): a new draft with a new number and real totals (never 0), the customer
reference cleared, no review/outcome state, the owner per policy, keep or refresh price modes, from a revision."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.errors import NotFound
from app.modules.pricing import service as pricing
from app.modules.pricing.schemas import SupersedeItem
from app.modules.sales import service as sales
from app.modules.sales.schemas import DuplicateQuote, QuoteSettingsUpdate
from app.platform.events.models import DomainEvent
from app.seed.context import D0
from app.seed.world import keys
from app.seed.world.pricing import item_ref
from tests.integration.sales.world import SalesWorld

pytestmark = pytest.mark.db
MEERA, NEHA, SAHIL, PRIYA = keys.USERS.MEERA, keys.USERS.NEHA, keys.USERS.SAHIL, keys.USERS.PRIYA


def _dup(world: SalesWorld, person: str, quote_id, **kw):  # type: ignore[no-untyped-def]
    with world.uow(person) as uow:
        detail, _ = sales.duplicate_quote_command(uow, quote_id, DuplicateQuote(**kw))
        return detail


def test_duplicate_real_totals_reference_cleared_owner_policy(world: SalesWorld) -> None:
    src = world.new_draft(MEERA, "NORDHAUS", ("OAK_TRAY", "240"), customer_reference="PO-NH-77", remarks="Repeat of spring order")
    copy = _dup(world, MEERA, src.id)
    assert copy.quote_number != src.quote_number and copy.status == "draft" and copy.revision_no == 0
    assert copy.grand_total is not None and copy.grand_total.amount == Decimal("5760.00")  # BUG-02: never 0
    assert copy.totals.grand_total.amount == src.totals.grand_total.amount and copy.line_count == 1  # type: ignore[union-attr]
    assert copy.customer_reference is None and copy.remarks == "Repeat of spring order" and copy.duplicated_from_quote_id == src.id
    assert copy.owner.id == world.user_id(MEERA) and copy.lines[0].line_key != src.lines[0].line_key
    assert copy.review.review_proposal_id is None and copy.valid_until is None
    # management duplicating Meera's quote keeps Meera as the owner (policy on, Sahil may assign)
    by_manager = _dup(world, SAHIL, src.id)
    assert by_manager.owner.id == world.user_id(MEERA)
    with world.uow(PRIYA, recent_auth_at=D0) as uow:
        settings = sales.get_quote_settings(uow)
        sales.update_quote_settings(uow, QuoteSettingsUpdate(
            defaults={**settings.defaults, "duplicate_copies_assignee": False}, expected_version=settings.version))
    assert _dup(world, SAHIL, src.id).owner.id == world.user_id(SAHIL)
    # Neha cannot see Meera's quote, so she cannot duplicate it
    with pytest.raises(NotFound):
        _dup(world, NEHA, src.id)
    with world.uow(SAHIL) as uow:
        names = [r[0] for r in uow.session.execute(select(DomainEvent.event_type).where(DomainEvent.aggregate_id == copy.id)
                                                   .order_by(DomainEvent.seq)).all()]
    assert names == ["sales.quote.created", "sales.quote.duplicated"]


def test_duplicate_price_modes_and_from_revision(world: SalesWorld) -> None:
    src = world.new_draft(MEERA, "NORDHAUS", ("OAK_TRAY", "240"))
    world.transition(MEERA, src.id, "mark_sent")
    with world.uow(PRIYA) as uow:  # the list price changes today
        pricing.supersede_item(uow, world.ref(item_ref(keys.PRICE_LIST_REFS.EXP_EUR, "OAK_TRAY")),
                               SupersedeItem(unit_price=Decimal("26"), valid_from=date(2026, 10, 12)))
    kept = _dup(world, MEERA, src.id)
    assert kept.lines[0].unit_price == Decimal("24.0000") and "PRICE_CHANGED_SINCE_SNAPSHOT" in kept.lines[0].advisories
    refreshed = _dup(world, MEERA, src.id, price_mode="refresh")
    assert refreshed.lines[0].unit_price == Decimal("26.0000") and refreshed.totals.grand_total.amount == Decimal("6240.00")  # type: ignore[union-attr]
    from_rev = _dup(world, MEERA, src.id, from_revision_no=1)
    assert from_rev.lines[0].quantity == Decimal("240") and from_rev.status == "draft"
