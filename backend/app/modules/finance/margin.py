"""Margin policy: a quote's margin from the **costs of record** (``pricing_product_cost``, the latest version effective
on the day), compared with ``finance_policy.margin_threshold_percent``.

Margin values are restricted (``pricing.cost.read``): read models mark them with ``COST_GUARD`` and are redacted on
every output path; ``model_exposure="deny"`` keeps them out of any model context even for permitted users; the
event ``sales.quote.margin_below_threshold`` and the briefing reader carry ids only. A line is costed only when its
product has a cost in the quote's currency and unit (no conversions are invented); margin is computed over the
costed lines and the rest are counted, so a quote with no costed line is never flagged.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select

from app.core.money import quantize_money
from app.modules.finance import common as c
from app.modules.finance import events as ev
from app.modules.finance.enums import MarginExceptionStatus
from app.modules.finance.models import MarginException
from app.modules.finance.schemas import MarginExceptionRead, MarginLine, QuoteMargin
from app.platform.authz.context import ActorContext
from app.platform.authz.redaction import redact
from app.platform.uow import UnitOfWork

HUNDRED = Decimal(100)


def _costs(uow: UnitOfWork, product_ids: set[uuid.UUID], on_date: Any) -> dict[uuid.UUID, Any]:
    from app.modules.pricing.models import ProductCost

    if not product_ids:
        return {}
    latest = (
        select(ProductCost.product_id, func.max(ProductCost.cost_version).label("v"))
        .where(ProductCost.company_id == uow.actor.company_id, ProductCost.product_id.in_(product_ids),
               ProductCost.effective_from <= on_date)
        .group_by(ProductCost.product_id)
        .subquery()
    )
    rows = uow.session.scalars(
        select(ProductCost).join(latest, (latest.c.product_id == ProductCost.product_id) & (latest.c.v == ProductCost.cost_version))
        .where(ProductCost.company_id == uow.actor.company_id)
    )
    return {r.product_id: r for r in rows}


def compute(uow: UnitOfWork, quote: Any) -> QuoteMargin:
    """Unredacted margin of ``quote`` (callers redact before anything leaves the service)."""
    from app.modules.sales.models import QuoteLine

    lines = list(uow.session.scalars(select(QuoteLine).where(QuoteLine.quote_id == quote.id).order_by(QuoteLine.line_no)))
    costs = _costs(uow, {ln.product_id for ln in lines if ln.product_id}, c.today(uow))
    cur = quote.currency
    out_lines: list[MarginLine] = []
    revenue = cost = c.ZERO
    missing = 0
    for ln in lines:
        rev = Decimal(ln.line_total) if ln.line_total is not None else None
        status = "ok"
        line_cost: Decimal | None = None
        pc = costs.get(ln.product_id) if ln.product_id else None
        if ln.product_id is None:
            status = "no_product"
        elif pc is None:
            status = "missing"
        elif pc.unit_cost_currency != cur:
            status = "currency_mismatch"
        elif pc.unit_code != ln.unit_code:
            status = "unit_mismatch"
        else:
            line_cost = quantize_money(Decimal(pc.unit_cost_amount) * Decimal(ln.quantity), cur)
        if status == "ok" and rev is not None and line_cost is not None:
            revenue += rev
            cost += line_cost
        elif status != "no_product" or rev:
            missing += 1
        out_lines.append(MarginLine(line_no=ln.line_no, description=ln.description, quantity=Decimal(ln.quantity),
                                    uom_code=ln.unit_code, revenue=c.money(rev, cur), cost=c.money(line_cost, cur), cost_status=status))  # type: ignore[arg-type]
    threshold = Decimal(_policy(uow).margin_threshold_percent)
    pct = ((revenue - cost) * HUNDRED / revenue).quantize(Decimal("0.0001")) if revenue > 0 else None
    return QuoteMargin(
        quote_id=quote.id, quote_number=quote.quote_number, currency=cur,
        revenue=c.m(revenue, cur) if revenue > 0 else None, cost=c.m(cost, cur) if revenue > 0 else None,
        margin_percent=pct, threshold_percent=threshold, below_threshold=(pct < threshold) if pct is not None else None,
        lines_without_cost=missing, lines=out_lines,
    )


def _policy(uow: UnitOfWork) -> Any:
    from app.platform.org.service import stored_or_default

    return stored_or_default(uow, "finance_policy")


def quote_margin(uow: UnitOfWork, quote_id: uuid.UUID) -> QuoteMargin:
    """The margin of a visible quote, redacted for the caller (null figures without ``pricing.cost.read``)."""
    from app.modules.sales.models import Quote

    uow.actor.require("sales.quote.read")
    quote = uow.repo(Quote).get(quote_id)  # 404 outside the actor's quote scope
    result = compute(uow, quote)
    if uow.actor.can("pricing.cost.read"):
        uow.audit("finance.margin.read", resource_type="sales.quote", resource_id=quote.id, resource_label=quote.quote_number,
                  restricted_fields=["revenue", "cost", "margin_percent"])
    return redact(result, uow.actor)  # type: ignore[no-any-return]


def check_quote(uow: UnitOfWork, event: Any) -> None:
    """The ``finance.margin_check`` consumer: on ``sales.quote.issued`` record a margin exception when the issued
    quote's margin is below the threshold (once per quote revision) and clear older open ones otherwise."""
    from app.modules.sales.models import Quote

    quote_id = uuid.UUID(str((event.payload or {}).get("quote_id") or event.aggregate_id))
    quote = uow.session.get(Quote, quote_id)
    if quote is None or quote.company_id != uow.actor.company_id:
        return
    result = compute(uow, quote)
    revision_no = int((event.payload or {}).get("revision_no") or quote.revision_no or 0)
    open_rows = list(uow.session.scalars(select(MarginException).where(
        MarginException.company_id == uow.actor.company_id, MarginException.quote_id == quote.id,
        MarginException.status == MarginExceptionStatus.OPEN.value).with_for_update()))
    below = bool(result.below_threshold)
    for row in open_rows:
        if row.revision_no != revision_no or not below:
            row.status, row.cleared_at = MarginExceptionStatus.CLEARED.value, uow.now()
    if not below or result.margin_percent is None:
        return
    exists = uow.session.scalar(select(MarginException.id).where(
        MarginException.company_id == uow.actor.company_id, MarginException.quote_id == quote.id,
        MarginException.revision_no == revision_no))
    if exists:
        return
    row = MarginException(
        company_id=uow.actor.company_id, quote_id=quote.id, quote_number=quote.quote_number, revision_no=revision_no,
        party_name=quote.party_name, owner_user_id=quote.owner_user_id, currency=quote.currency,
        revenue_amount=result.revenue.amount if result.revenue else c.ZERO,
        cost_amount=result.cost.amount if result.cost else c.ZERO, margin_percent=result.margin_percent,
        threshold_percent=result.threshold_percent, lines_without_cost=result.lines_without_cost,
        status=MarginExceptionStatus.OPEN.value, detected_at=uow.now(),
    )
    uow.add(row)
    uow.flush()
    uow.emit(ev.MARGIN_BELOW_THRESHOLD, aggregate_id=quote.id, aggregate_version=quote.version,
             payload={"quote_id": str(quote.id), "exception_id": str(row.id), "revision_no": revision_no})


def exception_read(uow: UnitOfWork, row: MarginException, actor: ActorContext, people: dict) -> MarginExceptionRead:
    out = MarginExceptionRead(
        id=row.id, quote_id=row.quote_id, quote_number=row.quote_number, revision_no=row.revision_no,
        party_name=row.party_name, owner=people.get(row.owner_user_id), status=row.status,  # type: ignore[arg-type]
        detected_at=row.detected_at, lines_without_cost=row.lines_without_cost, threshold_percent=row.threshold_percent,
        margin_percent=row.margin_percent, revenue=c.m(row.revenue_amount, row.currency), cost=c.m(row.cost_amount, row.currency),
    )
    return redact(out, actor)  # type: ignore[no-any-return]


def list_exceptions(uow: UnitOfWork, *, include_cleared: bool = False) -> list[MarginExceptionRead]:
    uow.actor.require(c.INVOICE_READ)
    conds = [uow.repo(MarginException).clause("read")]
    if not include_cleared:
        conds.append(MarginException.status == MarginExceptionStatus.OPEN.value)
    rows = list(uow.session.scalars(select(MarginException).where(*conds).order_by(MarginException.detected_at.desc()).limit(200)))
    people = c.users(uow, [r.owner_user_id for r in rows])
    return [exception_read(uow, r, uow.actor, people) for r in rows]
