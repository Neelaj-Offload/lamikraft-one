"""Currency switching on a quote (Scenario E, LP-05.4, AVOID-08, UI-67).

A currency label never changes on its own. Every line gets a new price in the new currency from one of:
- ``list``: the line's product priced by a price list in that currency (customer agreement -> type -> standard);
- ``custom_price``: a custom product's own quoted price in that currency;
- ``fx``: the current price converted at an approved, dated rate for exactly ``from -> to`` (overridden prices,
  manual lines, and products without a list in the new currency).
If any line has no such price the change is refused (409 ``currency_change_blocked`` with per-line reasons) and the
quote is untouched. The database backs this up: a line whose currency differs from its source currency needs an FX
rate (CHECK), and the header currency cannot change without its lines (deferred FK on ``(quote_id, currency)``).
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from app.core.errors import Conflict, ValidationFailed
from app.core.money import quantize_unit_price
from app.modules.pricing import service as pricing
from app.modules.sales import events as ev
from app.modules.sales import quotes
from app.modules.sales.common import business_date, idempotent
from app.modules.sales.models import CustomProduct, Quote, QuoteLine
from app.modules.sales.schemas import (
    CurrencyChange,
    CurrencyChangePreview,
    CurrencyLinePreview,
    LineType,
    QuoteDetail,
    TransitionAction,
)
from app.platform.service import query
from app.platform.uow import UnitOfWork


def _fx_line(uow: UnitOfWork, line: QuoteLine, from_currency: str, to_currency: str, base: dict[str, Any], reason: str) -> dict[str, Any]:
    if line.unit_price is None:
        return {**base, "method": "none", "status": "blocked", "reason_code": "no_price", "explanation": "The line has no price to convert."}
    converted = pricing.convert_amount(uow, Decimal(line.unit_price), from_currency, to_currency, business_date(uow))
    if converted is None:
        return {
            **base, "method": "none", "status": "blocked", "reason_code": reason,
            "explanation": f"No {to_currency} price and no approved {from_currency}->{to_currency} rate within the FX policy's age limit.",
        }
    amount, fx = converted
    price = quantize_unit_price(amount)
    default = price if line.default_unit_price is None or line.default_unit_price == line.unit_price else (
        quantize_unit_price(pricing.convert_amount(uow, Decimal(line.default_unit_price), from_currency, to_currency, business_date(uow))[0])  # type: ignore[index]
    )
    return {
        **base, "method": "fx", "status": "ok", "reason_code": None, "to_unit_price": price, "to_default_unit_price": default,
        "explanation": f"{from_currency} {format(line.unit_price, 'f')} × {format(Decimal(fx.rate).normalize(), 'f')} "
                       f"(approved rate dated {fx.rate_date.isoformat()}, {fx.source_reference})",
        "fx_rate_id": fx.fx_rate_id, "fx_rate": format(Decimal(fx.rate).normalize(), "f"), "fx_rate_date": fx.rate_date,
        "_source": {"source_currency": from_currency, "source_unit_price": quantize_unit_price(Decimal(line.unit_price)),
                    "fx_rate_id": fx.fx_rate_id, "fx_rate": fx.rate},
    }


def _plan_line(uow: UnitOfWork, quote: Quote, line: QuoteLine, to_currency: str) -> dict[str, Any]:
    base: dict[str, Any] = {
        "line_id": line.id, "line_no": line.line_no, "line_type": LineType(line.line_type), "description": line.description,
        "from_unit_price": line.unit_price, "to_unit_price": None, "to_default_unit_price": None,
    }
    overridden = line.unit_price is not None and line.default_unit_price is not None and line.unit_price != line.default_unit_price
    if line.line_type == LineType.CATALOG.value and line.product_id is not None:
        resolution = quotes.resolve_line_price(
            uow, product_id=line.product_id, party_id=quote.party_id, currency=to_currency, unit_code=line.unit_code,
            price_type=quote.price_type,
        )
        if resolution.status == "ambiguous":
            return {**base, "method": "none", "status": "blocked", "reason_code": "price_ambiguous", "explanation": resolution.explanation}
        if resolution.status == "found" and resolution.unit_price is not None and not overridden:
            price = quantize_unit_price(resolution.unit_price.amount)
            method = "fx" if resolution.fx is not None else "list"
            return {
                **base, "method": method, "status": "ok", "reason_code": None, "to_unit_price": price, "to_default_unit_price": price,
                "explanation": resolution.explanation,
                "fx_rate_id": resolution.fx.fx_rate_id if resolution.fx else None,
                "fx_rate": format(Decimal(resolution.fx.rate).normalize(), "f") if resolution.fx else None,
                "fx_rate_date": resolution.fx.rate_date if resolution.fx else None,
                "_resolution": resolution,
            }
        if resolution.status == "found" and resolution.unit_price is not None and overridden:
            planned = _fx_line(uow, line, quote.currency, to_currency, base, "override_needs_fx")
            if planned["status"] == "ok":
                planned["to_default_unit_price"] = quantize_unit_price(resolution.unit_price.amount)
                planned["_resolution"] = resolution
            return planned
        return _fx_line(uow, line, quote.currency, to_currency, base, resolution.reason_code and "no_price_or_fx" or "no_price_or_fx")
    if line.line_type == LineType.CUSTOM.value and line.custom_product_id is not None:
        custom = uow.session.get(CustomProduct, line.custom_product_id)
        if custom is not None and custom.quoted_currency == to_currency and custom.quoted_price is not None and not overridden:
            price = quantize_unit_price(custom.quoted_price)
            return {
                **base, "method": "custom_price", "status": "ok", "reason_code": None, "to_unit_price": price,
                "to_default_unit_price": price, "explanation": f"{custom.custom_code} is quoted at {to_currency} {format(price, 'f')}",
                "_source": {"source_currency": to_currency, "source_unit_price": price, "fx_rate_id": None, "fx_rate": None},
            }
    return _fx_line(uow, line, quote.currency, to_currency, base, "no_price_or_fx")


def _plan(uow: UnitOfWork, quote: Quote, to_currency: str) -> tuple[list[QuoteLine], list[dict[str, Any]]]:
    lines = quotes.lines_of(uow, quote)
    return lines, [_plan_line(uow, quote, ln, to_currency) for ln in lines]


def _preview(quote: Quote, to_currency: str, planned: list[dict[str, Any]]) -> CurrencyChangePreview:
    rows = [CurrencyLinePreview(**{k: v for k, v in p.items() if not k.startswith("_")}) for p in planned]
    blocked = sum(1 for r in rows if r.status == "blocked")
    return CurrencyChangePreview(
        quote_id=quote.id, from_currency=quote.currency, to_currency=to_currency, applicable=blocked == 0 and quote.currency != to_currency,
        blocked_count=blocked, lines=rows,
    )


@query("sales.quote.read")
def preview_currency_change(uow: UnitOfWork, quote_id: uuid.UUID, to_currency: str) -> CurrencyChangePreview:
    quote = uow.repo(Quote).get(quote_id, include_archived=False)
    _lines, planned = _plan(uow, quote, to_currency.upper())
    return _preview(quote, to_currency.upper(), planned)


def change_currency(uow: UnitOfWork, quote_id: uuid.UUID, data: CurrencyChange, *, origin: str | None = None) -> Quote:
    """Apply the change atomically: header, every line's price and provenance, recalculated totals."""
    from app.modules.sales.transitions import write_history

    quote = uow.repo(Quote).get(quote_id, "update", for_update=True, include_archived=False)
    uow.expect_version(quote, data.expected_version)
    to_currency = data.to_currency
    if to_currency == quote.currency:
        raise ValidationFailed("The quote is already in this currency",
                               errors=[{"loc": ["body", "to_currency"], "msg": "same currency", "code": "same_currency"}])
    lines, planned = _plan(uow, quote, to_currency)
    preview = _preview(quote, to_currency, planned)
    if preview.blocked_count:
        raise Conflict(
            f"{preview.blocked_count} line(s) have no {to_currency} price and no approved FX rate; the quote stays in {quote.currency}",
            code="currency_change_blocked",
            lines=[r.model_dump(mode="json") for r in preview.lines if r.status == "blocked"],
        )
    from_currency = quote.currency
    for line, plan in zip(lines, planned, strict=True):
        line.currency = to_currency
        line.unit_price = plan["to_unit_price"]
        line.default_unit_price = plan["to_default_unit_price"]
        resolution = plan.get("_resolution")
        if plan["method"] in ("list",) or (resolution is not None and plan["method"] == "fx" and "_source" not in plan):
            quotes.apply_provenance(line, resolution)
            line.price_list_item_id = resolution.item_id
            line.commercial_snapshot = quotes.commercial_snapshot(resolution, line.unit_code).model_dump(mode="json")
        else:
            src = plan["_source"]
            line.source_currency = src["source_currency"]
            line.source_unit_price = src["source_unit_price"]
            line.fx_rate_id = src["fx_rate_id"]
            line.fx_rate = src["fx_rate"]
            snap = dict(line.commercial_snapshot or {})
            snap.update({"currency": to_currency, "unit_price": format(plan["to_default_unit_price"], "f") if plan["to_default_unit_price"] is not None else None})
            line.commercial_snapshot = snap
    quote.currency = to_currency
    quote.totals_currency = to_currency
    uow.flush()
    quotes.recalculate(uow, quote, lines)
    quotes.touch(uow, quote)
    uow.flush()
    write_history(uow, quote, action=TransitionAction.CHANGE_CURRENCY.value, from_status=quote.status, to_status=quote.status,
                  reason_code=f"{from_currency.lower()}_to_{to_currency.lower()}")
    uow.emit(ev.QUOTE_CURRENCY_CHANGED, aggregate_id=quote.id, aggregate_version=quote.version,
             payload=ev.payload(ev.QuoteCurrencyChangedPayload(quote_id=quote.id, from_currency=from_currency, to_currency=to_currency,
                                                               origin=origin)))
    quotes.emit_updated(uow, quote, ["currency", "lines"], ["changed"])
    uow.audit("sales.quote.currency_changed", resource_type="sales.quote", resource_id=quote.id, resource_label=quote.quote_number,
              details={"from_currency": from_currency, "to_currency": to_currency,
                       "methods": sorted({p["method"] for p in planned})})
    return quote


def change_currency_command(uow: UnitOfWork, quote_id: uuid.UUID, data: CurrencyChange) -> tuple[QuoteDetail, bool]:
    uow.repo(Quote).get(quote_id, "update", include_archived=False)
    return idempotent(uow, f"sales.change_currency:{quote_id}", data, lambda: quotes.detail(uow, change_currency(uow, quote_id, data)), QuoteDetail)
