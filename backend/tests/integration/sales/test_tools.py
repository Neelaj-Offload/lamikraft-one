"""Sales agent tools: ``draft_quote`` honours the runtime's per-step Idempotency-Key (``requires_idempotency``)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.modules.sales.models import Quote
from app.modules.sales.schemas import DraftQuoteInput, DraftQuoteLine
from app.modules.sales.tools import DRAFT_QUOTE
from app.seed.world import keys
from tests.integration.sales.world import SalesWorld

pytestmark = pytest.mark.db


def test_draft_quote_tool_replays_a_retried_step(sales_world: SalesWorld) -> None:
    w = sales_world
    assert DRAFT_QUOTE.requires_idempotency
    data = DraftQuoteInput(party_id=w.ref("NORDHAUS"), lines=[DraftQuoteLine(product_id=w.ref("OAK_TRAY"),
                                                                             quantity=Decimal(keys.EXPECTED.SCENARIO_C_QTY))])
    with w.uow(keys.USERS.MEERA, idempotency_key="agent-run-1:step-3") as uow:
        before = uow.session.scalar(select(func.count()).select_from(Quote))
        first = DRAFT_QUOTE.handler(uow, data)
    with w.uow(keys.USERS.MEERA, idempotency_key="agent-run-1:step-3") as uow:  # the same step retried
        again = DRAFT_QUOTE.handler(uow, data)
        after = uow.session.scalar(select(func.count()).select_from(Quote))
    assert again.id == first.id and again.quote_number == first.quote_number == keys.QUOTES.SCENARIO_C_NEW
    assert after == before + 1
    with w.uow(keys.USERS.MEERA, idempotency_key="agent-run-2:step-3") as uow:  # a new step drafts a new quote
        other = DRAFT_QUOTE.handler(uow, data)
    assert other.id != first.id
