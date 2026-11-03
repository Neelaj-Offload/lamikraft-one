"""Currency switching (Scenario E: SCN-E1, GAP-03, LP-05.4, FG-QUO-06, AVOID-08, UI-67): a quote changes currency only
with a price list in the new currency or an approved, dated FX rate; a pure relabel is impossible, also in SQL."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.errors import Conflict
from app.modules.pricing import service as pricing
from app.modules.pricing.schemas import FxDecision, FxRateCreate
from app.modules.sales import service as sales
from app.modules.sales.models import LINE_CURRENCY_FK
from app.modules.sales.schemas import CurrencyChange, QuoteLineCreate, QuoteUpdate
from app.seed.world import keys
from tests.integration.sales.world import SalesWorld

pytestmark = pytest.mark.db
MEERA, SAHIL, ANANYA = keys.USERS.MEERA, keys.USERS.SAHIL, keys.USERS.ANANYA


def _approved_rate(world: SalesWorld, rate: str, day: date, base: str = "EUR", quote: str = "USD") -> None:
    with world.uow(SAHIL) as uow:
        row = pricing.propose_fx_rate(uow, FxRateCreate.model_validate({
            "base_currency": base, "quote_currency": quote, "rate": rate, "rate_date": day.isoformat(),
            "source_kind": "bank", "source_reference": "Demo rate",
        }))
        row_id = row.id
    with world.uow(ANANYA) as uow:
        pricing.decide_fx_rate(uow, row_id, FxDecision(decision="approve"))


def _change(world: SalesWorld, quote_id, currency: str):  # type: ignore[no-untyped-def]
    with world.uow(MEERA) as uow:
        version = sales.get_quote(uow, quote_id).version
        detail, _ = sales.change_currency_command(uow, quote_id, CurrencyChange(to_currency=currency, expected_version=version))  # type: ignore[arg-type]
        return detail


def test_currency_change_with_approved_fx(world: SalesWorld) -> None:
    """Approved EUR->USD 1.0850 dated 2026-10-09 (proposer is not the approver): 26.04 USD per unit, total 6,249.60."""
    _approved_rate(world, "1.0850", date(2026, 10, 9))
    d = world.new_draft(MEERA, "NORDHAUS", ("OAK_TRAY", "240"))
    with world.uow(MEERA) as uow:
        preview = sales.preview_currency_change(uow, d.id, "USD")
    assert preview.applicable and preview.blocked_count == 0
    assert (preview.lines[0].method, preview.lines[0].to_unit_price, preview.lines[0].fx_rate) == ("fx", Decimal("26.0400"), "1.085")
    usd = _change(world, d.id, "USD")
    line = usd.lines[0]
    assert (usd.currency, line.currency, line.unit_price, line.default_unit_price) == ("USD", "USD", Decimal("26.0400"), Decimal("26.0400"))
    assert (line.source_currency, line.source_unit_price, line.fx_rate) == ("EUR", Decimal("24.0000"), "1.085") and line.fx_rate_id
    assert usd.totals.grand_total.amount == Decimal("6249.60") and usd.totals.grand_total.currency == "USD"  # type: ignore[union-attr]
    assert usd.totals.minimum.status == "NOT_EVALUATED" and usd.totals.surcharge_reason_code == "CURRENCY_NOT_EVALUATED"
    assert usd.version > d.version
    # a new catalog line on the USD quote converts too (Pass B), with provenance
    with world.uow(MEERA) as uow:
        quote, added = sales.add_line(uow, d.id, QuoteLineCreate(expected_version=usd.version, product_id=world.ref("MAPLE_TRIVET"), quantity=Decimal("10")))
    assert (added.currency, added.unit_price, added.source_currency, added.fx_rate_id is not None) == ("USD", Decimal("10.3100"), "EUR", True)
    with world.uow(MEERA) as uow:
        history = [h.action for h in sales.list_status_history(uow, d.id)]
    assert history == ["change_currency"]


def test_currency_change_blocked_without_fx(world: SalesWorld) -> None:
    d = world.new_draft(MEERA, "NORDHAUS", ("OAK_TRAY", "240"))
    with world.uow(MEERA) as uow:
        preview = sales.preview_currency_change(uow, d.id, "USD")
    assert not preview.applicable and preview.blocked_count == 1 and preview.lines[0].reason_code == "no_price_or_fx"
    with pytest.raises(Conflict) as exc:
        _change(world, d.id, "USD")
    assert exc.value.code == "currency_change_blocked" and exc.value.extra["lines"][0]["status"] == "blocked"
    with world.uow(MEERA) as uow:
        unchanged = sales.get_quote(uow, d.id)
        assert (unchanged.currency, unchanged.version, unchanged.totals.grand_total.amount) == ("EUR", d.version, Decimal("5760.00"))  # type: ignore[union-attr]
        sales.update_quote(uow, d.id, QuoteUpdate(expected_version=unchanged.version, remarks="still editable"))
    # a direct GBP list exists for the oak tray: the change uses it (no FX needed)
    gbp = _change(world, d.id, "GBP")
    assert (gbp.currency, gbp.lines[0].unit_price, gbp.lines[0].source_currency, gbp.lines[0].fx_rate_id) == ("GBP", Decimal(keys.PRICES.OAK_TRAY_GBP), "GBP", None)
    assert gbp.lines[0].commercial_snapshot.price_list_code == keys.PRICE_LISTS.EXP_GBP  # type: ignore[union-attr]
    assert gbp.totals.grand_total.amount == Decimal("5040.00")  # type: ignore[union-attr]
    # an overridden or manual price converts only at an approved rate (GBP -> EUR has none)
    with world.uow(MEERA) as uow:
        q = sales.get_quote(uow, d.id)
        sales.add_line(uow, d.id, QuoteLineCreate(expected_version=q.version, line_type="manual", manual_preset="freight", quantity=Decimal("1"),
                                                   unit_price=Decimal("150")))
        blocked = sales.preview_currency_change(uow, d.id, "EUR")
    assert [(ln.line_type.value, ln.status, ln.method) for ln in blocked.lines] == [("catalog", "ok", "list"), ("manual", "blocked", "none")]


def test_db_rejects_currency_relabel(world: SalesWorld) -> None:
    """The database makes a relabel impossible: a line's currency differs from its source currency only with an FX rate
    (CHECK), and the header currency cannot change without its lines (deferred FK checked at commit)."""
    d = world.new_draft(MEERA, "NORDHAUS", ("OAK_TRAY", "240"))
    with pytest.raises(DBAPIError, match="no_currency_relabel"), world.uow(SAHIL) as uow:
        uow.session.execute(text("UPDATE sales_quote_line SET currency = 'USD' WHERE quote_id = :q"), {"q": d.id})
        uow.session.execute(text(f"SET CONSTRAINTS {LINE_CURRENCY_FK} IMMEDIATE"))
    with pytest.raises(DBAPIError, match=LINE_CURRENCY_FK), world.uow(SAHIL) as uow:
        uow.session.execute(text("UPDATE sales_quote SET currency = 'USD', totals_currency = 'USD' WHERE id = :q"), {"q": d.id})
        uow.session.execute(text(f"SET CONSTRAINTS {LINE_CURRENCY_FK} IMMEDIATE"))
    with world.uow(MEERA) as uow:
        assert sales.get_quote(uow, d.id).currency == "EUR"
