"""The quote list (LM-58, UI-50/51/53/56): search by number/customer/country, status tabs, scope mine/all, paging,
totals from the persisted result, metacharacters literal."""

from __future__ import annotations

import pytest

from app.modules.sales import service as sales
from app.modules.sales.schemas import QuoteFilters, QuoteStatus
from app.seed.world import keys
from tests.integration.sales.world import SalesWorld

pytestmark = pytest.mark.db


def test_filters_scope_and_paging_totals(sales_world: SalesWorld) -> None:
    w = sales_world
    with w.uow(keys.USERS.SAHIL) as uow:
        page = sales.list_quotes(uow, QuoteFilters(), limit=3, offset=0)
        second = sales.list_quotes(uow, QuoteFilters(), limit=3, offset=3)
        by_number = sales.list_quotes(uow, QuoteFilters(q="0003"))
        by_name = sales.list_quotes(uow, QuoteFilters(q="thornbury"))
        by_country = sales.list_quotes(uow, QuoteFilters(q="GB", status=[QuoteStatus.SENT]))
        won = sales.list_quotes(uow, QuoteFilters(status=[QuoteStatus.WON, QuoteStatus.LOST]))
        mine = sales.list_quotes(uow, QuoteFilters(scope="mine"))
        meera = sales.list_quotes(uow, QuoteFilters(owner_user_id=w.user_id(keys.USERS.MEERA)))
        nordhaus = sales.list_quotes(uow, QuoteFilters(party_id=w.ref("NORDHAUS")))
    assert page.total == 8 and len(page.items) == 3 and page.limit == 3 and len(second.items) == 3
    assert [q.quote_number for q in page.items] == [keys.QUOTES.NORDHAUS_DRAFT, keys.QUOTES.THORNBURY_OVERRIDE, keys.QUOTES.BERG_EXPIRING]
    assert [q.quote_number for q in by_number.items] == [keys.QUOTES.PRIOR_WON]
    assert {q.quote_number for q in by_name.items} == {keys.QUOTES.THORNBURY_LOST, keys.QUOTES.THORNBURY_EXPIRING, keys.QUOTES.THORNBURY_OVERRIDE}
    assert [q.quote_number for q in by_country.items] == [keys.QUOTES.THORNBURY_EXPIRING]
    assert {q.status for q in won.items} == {"won", "lost"} and won.total == 3
    assert mine.total == 0 and meera.total == 5 and nordhaus.total == 2
    row = next(q for q in page.items if q.quote_number == keys.QUOTES.NORDHAUS_DRAFT)
    assert row.grand_total is not None and str(row.grand_total.amount) == keys.EXPECTED.SCENARIO_C_TOTAL and row.currency == "EUR"
    assert row.line_count == 1 and row.party.display_name == keys.PARTY_NAMES["NORDHAUS"] and row.party.country_code == "DE"
    assert row.owner.id == w.user_id(keys.USERS.MEERA) and row.origin == "agent" and row.status == "internal_review"
    sent = next(q for q in second.items if q.quote_number == keys.QUOTES.THORNBURY_EXPIRING)
    assert sent.valid_until is not None and sent.valid_until.isoformat() == "2026-10-12" and sent.revision_no == 1
    with w.uow(keys.USERS.MEERA) as uow:  # scope=all is still bounded by own scope
        assert sales.list_quotes(uow, QuoteFilters(scope="all")).total == 5
        assert sales.list_quotes(uow, QuoteFilters(scope="mine")).total == 5
        assert sales.list_quotes(uow, QuoteFilters(q="thornbury")).total == 0


def test_search_metacharacters_literal(sales_world: SalesWorld) -> None:
    with sales_world.uow(keys.USERS.SAHIL) as uow:
        assert sales.list_quotes(uow, QuoteFilters(q="%")).total == 0
        assert sales.list_quotes(uow, QuoteFilters(q="_")).total == 0
        assert sales.list_quotes(uow, QuoteFilters(q="LK-QT-2026-000_")).total == 0
        assert sales.list_quotes(uow, QuoteFilters(q="(Berg|Maison)")).total == 0
        berg = sales.list_quotes(uow, QuoteFilters(q="Berg &"))
    assert {q.quote_number for q in berg.items} == {keys.QUOTES.BERG_WON, keys.QUOTES.BERG_EXPIRING}


def test_status_tabs_include_revised_cancelled_archived(sales_world: SalesWorld) -> None:
    with sales_world.uow(keys.USERS.SAHIL) as uow:
        counts = sales.status_counts(uow, QuoteFilters())
    assert set(counts) == {s.value for s in QuoteStatus} and counts["cancelled"] == 0 and counts["archived"] == 0 and counts["revised"] == 0
    d = sales_world.new_draft(keys.USERS.MEERA, "NORDHAUS", ("OAK_TRAY", "24"))
    sales_world.transition(keys.USERS.MEERA, d.id, "cancel", reason="test")
    with sales_world.uow(keys.USERS.SAHIL) as uow:
        assert sales.status_counts(uow, QuoteFilters())["cancelled"] == 1
        assert sales.status_counts(uow, QuoteFilters(q="nordhaus"))["cancelled"] == 1


def test_archived_and_revised_tabs_count_and_filter(sales_world: SalesWorld) -> None:
    """UI-50: revised and archived quotes appear in their own tabs with server counts; currency filters too."""
    w = sales_world
    d = w.new_draft(keys.USERS.MEERA, "NORDHAUS", ("OAK_TRAY", "240"))
    w.transition(keys.USERS.MEERA, d.id, "mark_sent")
    w.transition(keys.USERS.MEERA, d.id, "revise")
    lost = w.new_draft(keys.USERS.MEERA, "NORDHAUS", ("OAK_TRAY", "240"))
    w.transition(keys.USERS.MEERA, lost.id, "mark_sent")
    w.transition(keys.USERS.MEERA, lost.id, "mark_lost", reason_code="price")
    w.transition(keys.USERS.MEERA, lost.id, "archive")
    with w.uow(keys.USERS.MEERA) as uow:
        counts = sales.status_counts(uow, QuoteFilters())
        archived = sales.list_quotes(uow, QuoteFilters(status=[QuoteStatus.ARCHIVED]))
        revised = sales.list_quotes(uow, QuoteFilters(status=[QuoteStatus.REVISED]))
        gbp = sales.list_quotes(uow, QuoteFilters(currency="GBP"))
    assert (counts["revised"], counts["archived"]) == (1, 1)
    assert [q.id for q in archived.items] == [lost.id] and [q.id for q in revised.items] == [d.id]
    assert gbp.total == 0
