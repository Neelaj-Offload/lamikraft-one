"""Margin policy: an issued quote's margin from the costs of record against ``finance_policy.margin_threshold_percent``.
Cost redaction canary: margin, revenue and cost are null for anyone without ``pricing.cost.read``, never in model
context, never in the ``sales.quote.margin_below_threshold`` payload (ids only), the source reader or briefing facts."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.modules.finance import margin
from app.modules.finance.models import MarginException
from app.modules.pricing import service as pricing
from app.modules.pricing.schemas import ProductCostCreate
from app.modules.sales.models import Quote
from app.modules.tasks.models import Issue
from app.platform import sources
from app.platform.authz.redaction import redact
from tests.integration.finance.world import ANANYA, MEERA, SAHIL, FinWorld
from tests.support import drain

pytestmark = pytest.mark.db
SECRET_COST = Decimal("22.3700")


def _cost(w: FinWorld, product: str, amount: Decimal) -> None:
    with w.uow(ANANYA) as uow:
        pricing.record_product_cost(uow, w.ref(product), ProductCostCreate(
            unit_cost_amount=amount, unit_cost_currency="EUR", unit_code="pcs", effective_from=date(2026, 1, 1)))


def test_margin_exception_ids_only_and_cost_redaction_canary(fin_world: FinWorld) -> None:
    w = fin_world
    _cost(w, "OAK_TRAY", SECRET_COST)
    quote_id = w.won_quote(MEERA, "NORDHAUS", ("OAK_TRAY", "240"))  # EUR 24 x 240; cost 22.37 -> 6.79 % < 15 %
    drain()
    [row] = [r for r in w.events("sales.quote.margin_below_threshold") if r.payload["quote_id"] == str(quote_id)]
    assert set(row.payload) - {"origin"} == {"quote_id", "exception_id", "revision_no"}
    with w.system() as uow:
        exc = uow.session.scalars(select(MarginException).where(MarginException.quote_id == quote_id)).one()
        assert exc.margin_percent < Decimal(15) and exc.status == "open"
        facts = sources.read(uow, "finance.margin_exception", exc.id)
    assert facts is not None and "margin" not in json.dumps(facts.facts) and str(SECRET_COST) not in json.dumps(facts.facts, default=str)

    # sales may read the quote but not its margin figures
    with w.uow(MEERA) as uow:
        seen = margin.quote_margin(uow, quote_id)
    assert seen.margin_percent is None and seen.cost is None and seen.revenue is None and seen.below_threshold is None
    assert {"margin_percent", "cost", "revenue"} <= set(seen.redacted_fields)
    assert all(ln.cost is None for ln in seen.lines)
    assert str(SECRET_COST.normalize()) not in seen.model_dump_json()
    # management (cost read) sees them; the same value is still denied to a model
    with w.uow(SAHIL) as uow:
        full = margin.quote_margin(uow, quote_id)
        model_view = redact(margin.compute(uow, uow.repo(Quote).get(quote_id)), uow.actor, for_model=True)
    assert full.margin_percent is not None and full.cost is not None and full.cost.amount == Decimal("5368.8000")
    assert model_view.margin_percent is None and model_view.cost is None

    # the exceptions list: figures for finance, ids and names for the briefing issue
    with w.uow(ANANYA) as uow:
        [listed] = [x for x in margin.list_exceptions(uow) if x.quote_id == quote_id]
    assert listed.margin_percent is not None
    with w.system() as uow:
        issue = uow.session.scalars(select(Issue).where(Issue.family == "mgmt.margin_exceptions")).one()
    assert str(SECRET_COST) not in json.dumps(issue.title_facts or {}, default=str)


def test_quote_above_threshold_or_without_costs_is_not_flagged(fin_world: FinWorld) -> None:
    w = fin_world
    no_cost = w.won_quote(MEERA, "NORDHAUS", ("MAPLE_TRIVET", "600"))
    _cost(w, "OAK_TRAY", Decimal("10"))
    healthy = w.won_quote(MEERA, "NORDHAUS", ("OAK_TRAY", "240"))
    drain()
    with w.system() as uow:
        rows = list(uow.session.scalars(select(MarginException.quote_id)))
    assert no_cost not in rows and healthy not in rows
    with w.uow(SAHIL) as uow:
        m = margin.quote_margin(uow, no_cost)
    assert m.margin_percent is None and m.lines_without_cost == 1 and m.lines[0].cost_status == "missing"
