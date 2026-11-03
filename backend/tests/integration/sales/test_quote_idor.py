"""IDOR matrix (SEC-02, SCN-F1, PERM-20/21): Meera and Neha (sales, own scope) against each other's quotes, lines,
revisions, history and PDFs; Sahil (management) sees everything; exports are bounded by read scope."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.core.errors import Forbidden, NotFound
from app.modules.sales import service as sales
from app.modules.sales.schemas import (
    ChangeOwner,
    CurrencyChange,
    DuplicateQuote,
    QuoteFilters,
    QuoteLineCreate,
    QuoteLineUpdate,
    QuoteTransition,
    QuoteUpdate,
    RestoreRevision,
)
from app.seed.world import keys
from tests.integration.sales.world import SalesWorld

pytestmark = pytest.mark.db
MEERA, NEHA, SAHIL, RAVI, KABIR = keys.USERS.MEERA, keys.USERS.NEHA, keys.USERS.SAHIL, keys.USERS.RAVI, keys.USERS.KABIR


def test_quote_idor_matrix(sales_world: SalesWorld) -> None:
    w = sales_world
    mine, theirs = w.ref("Q_BERG_EXPIRING"), w.ref("Q_THORNBURY_EXPIRING")  # Meera's and Neha's sent quotes
    draft_theirs = w.ref("Q_THORNBURY_OVERRIDE")  # Neha's internal_review quote
    with w.uow(NEHA) as uow:
        neha_line = sales.get_quote(uow, draft_theirs).lines[0]
    probes = [
        lambda uow: sales.get_quote(uow, theirs),
        lambda uow: sales.list_status_history(uow, theirs),
        lambda uow: sales.list_revisions(uow, theirs),
        lambda uow: sales.get_revision(uow, theirs, 1),
        lambda uow: sales.revision_document(uow, theirs, 1),
        lambda uow: sales.update_quote(uow, draft_theirs, QuoteUpdate(expected_version=1, remarks="x")),
        lambda uow: sales.add_line(uow, draft_theirs, QuoteLineCreate(expected_version=1, product_id=w.ref("OAK_TRAY"), quantity=Decimal("1"))),
        lambda uow: sales.update_line(uow, draft_theirs, neha_line.id, QuoteLineUpdate(expected_version=1, quantity=Decimal("2"))),
        lambda uow: sales.remove_line(uow, draft_theirs, neha_line.id, expected_version=1),
        lambda uow: sales.transition_quote(uow, theirs, QuoteTransition(action="mark_won", expected_version=1)),
        lambda uow: sales.transition_quote(uow, draft_theirs, QuoteTransition(action="cancel", expected_version=1, reason="x")),
        lambda uow: sales.delete_quote(uow, draft_theirs, expected_version=1),
        # Slice 2 children and commands: every path is authorised through the quote
        lambda uow: sales.transition_quote(uow, theirs, QuoteTransition(action="revise", expected_version=1)),
        lambda uow: sales.duplicate_quote(uow, theirs, DuplicateQuote()),
        lambda uow: sales.compare_revisions(uow, theirs, 1),
        lambda uow: sales.restore_revision(uow, theirs, 1, RestoreRevision(expected_version=1)),
        lambda uow: sales.preview_currency_change(uow, theirs, "GBP"),
        lambda uow: sales.change_currency(uow, draft_theirs, CurrencyChange(to_currency="EUR", expected_version=1)),
        lambda uow: sales.change_owner(uow, theirs, ChangeOwner(owner_user_id=w.user_id(MEERA), expected_version=1)),
        lambda uow: sales.export_quote_lines_csv(uow, theirs),
    ]
    for probe in probes:  # invisible -> 404, never 403 (no existence leak)
        with pytest.raises(NotFound):
            with w.uow(MEERA) as uow:
                probe(uow)
    with pytest.raises(NotFound):
        with w.uow(NEHA) as uow:
            sales.get_quote(uow, mine)
    with w.uow(MEERA) as uow:  # own records are visible
        assert sales.get_quote(uow, mine).quote_number == keys.QUOTES.BERG_EXPIRING
        assert sales.list_revisions(uow, mine)[0].revision_no == 1
        own = {q.quote_number for q in sales.list_quotes(uow, QuoteFilters(), limit=200).items}
    assert own == {keys.QUOTES.BERG_WON, keys.QUOTES.PRIOR_WON, keys.QUOTES.MAISON_OVERRIDE, keys.QUOTES.BERG_EXPIRING, keys.QUOTES.NORDHAUS_DRAFT}
    with w.uow(SAHIL) as uow:  # management: everything, with company-wide transition rights
        every = {q.quote_number for q in sales.list_quotes(uow, QuoteFilters(), limit=200).items}
        detail = sales.get_quote(uow, theirs)
    assert len(every) == 8 and detail.capabilities["transition"].allowed and detail.capabilities["export"].allowed
    with w.uow(RAVI) as uow:  # operations: reads company-wide, cannot edit or export
        ops = sales.get_quote(uow, theirs)
    assert ops.capabilities["update"].reason_code == "permission_denied" and ops.capabilities["export"].reason_code == "permission_denied"
    with pytest.raises(Forbidden):
        with w.uow(RAVI) as uow:
            sales.revision_document(uow, theirs, 1)
    with pytest.raises(Forbidden):  # visible but forbidden -> 403
        with w.uow(RAVI) as uow:
            sales.transition_quote(uow, theirs, QuoteTransition(action="mark_won", expected_version=ops.version))
    with pytest.raises(NotFound):  # unknown ids are 404 for everyone
        with w.uow(SAHIL) as uow:
            sales.get_quote(uow, uuid.uuid7())
    with pytest.raises(Forbidden):  # Kabir (warehouse) has no sales.quote.read at all
        with w.uow(KABIR) as uow:
            sales.get_quote(uow, mine)


def test_exports_bounded_by_read_scope(sales_world: SalesWorld) -> None:
    """Export = the scoped list and the issued revision document in Slice 1 (CSV/print are Slice 2)."""
    w = sales_world
    with w.uow(NEHA) as uow:
        rows = sales.list_quotes(uow, QuoteFilters(scope="all"), limit=200).items
    assert {q.quote_number for q in rows} == {keys.QUOTES.THORNBURY_LOST, keys.QUOTES.THORNBURY_EXPIRING, keys.QUOTES.THORNBURY_OVERRIDE}
    with w.uow(NEHA) as uow:
        snapshot, sha = sales.revision_document(uow, w.ref("Q_THORNBURY_EXPIRING"), 1)
    assert snapshot["header"]["quote_number"] == keys.QUOTES.THORNBURY_EXPIRING and len(sha) == 64
    with pytest.raises(NotFound):
        with w.uow(NEHA) as uow:
            sales.revision_document(uow, w.ref("Q_BERG_EXPIRING"), 1)
    with w.uow(SAHIL) as uow:
        counts = sales.status_counts(uow, QuoteFilters())
    assert counts == {"draft": 0, "internal_review": 3, "sent": 2, "revised": 0, "won": 2, "lost": 1, "cancelled": 0, "archived": 0}
