"""Commercial services: versioned rule sets and calculations through the pure engine.

The engine itself has no database access; this service loads the active rule set and, for the
``calculate_quote`` tool, the resolved price-list items (prices never come from a model). It also contributes the
catalogue's price columns (price plus order-value recommendation, UI-35/UI-39) through
``catalogue.register_price_columns``: pricing and commercial depend on the catalogue, never the reverse.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date
from typing import Any

from sqlalchemy import func, select

from app.core.db.base import new_id
from app.core.errors import Conflict, NotConfigured, NotFound, ValidationFailed
from app.core.http.pagination import MAX_LIMIT, Page
from app.core.money import Money, Quantity
from app.modules.catalogue import service as catalogue
from app.modules.catalogue.schemas import (
    OrderValueRecommendationRead,
    ProductPriceColumn,
    quantity_entry_problem,
)
from app.modules.commercial import engine
from app.modules.commercial.models import RuleSet
from app.modules.commercial.schemas import (
    QUOTE_COMMERCIAL,
    CalculatedLineRef,
    CalculateQuoteInput,
    CalculateQuoteOutput,
    CalculationResultOut,
    Capability,
    QuoteCommercialRulesV1,
    RuleSetDetail,
    RuleSetRead,
    RuleSetStatus,
    TransitionRead,
)
from app.modules.pricing import service as pricing
from app.modules.pricing.schemas import PricedItem, PriceType
from app.platform.service import query
from app.platform.uow import UnitOfWork

READ = "commercial.rule_set.read"
MANAGE = "commercial.rule_set.manage"
RULE_SET_ACTIVATED = "commercial.rule_set.activated"


def _read(row: RuleSet) -> RuleSetRead:
    return RuleSetRead(
        id=row.id,
        code=row.code,
        version_no=row.version_no,
        status=RuleSetStatus(row.status),
        effective_from=row.effective_from,
        params=QuoteCommercialRulesV1.model_validate(row.params),
        description=row.description,
        activated_at=row.activated_at,
        version=row.version,
    )


def find_rule_set(uow: UnitOfWork, code: str, version_no: int) -> RuleSet | None:
    return uow.session.scalars(
        select(RuleSet).where(
            RuleSet.company_id == uow.actor.company_id, RuleSet.code == code, RuleSet.version_no == version_no
        )
    ).first()


def create_rule_set(
    uow: UnitOfWork,
    *,
    code: str,
    version_no: int,
    params: QuoteCommercialRulesV1,
    effective_from: date,
    description: str | None = None,
) -> RuleSet:
    uow.actor.require(MANAGE)
    if find_rule_set(uow, code, version_no) is not None:
        raise Conflict("This rule-set version already exists", code="rule_set_version_exists")
    row = RuleSet(
        id=new_id(),
        company_id=uow.actor.company_id,
        code=code,
        version_no=version_no,
        status=RuleSetStatus.DRAFT.value,
        effective_from=effective_from,
        params=params.model_dump(mode="json"),
        engine_version=engine.ENGINE_VERSION,
        description=description,
    )
    uow.add(row)
    uow.flush()
    uow.audit("commercial.rule_set.created", resource_type="commercial.rule_set", resource_id=row.id,
              resource_label=f"{code} v{version_no}")
    return row


def activate_rule_set(uow: UnitOfWork, rule_set_id: uuid.UUID, *, origin: str | None = None) -> RuleSet:
    """Activate a draft version; the previously active version of the same code is retired in the same transaction."""
    uow.actor.require(MANAGE)
    row = uow.repo(RuleSet).get(rule_set_id, for_update=True)
    if row.status != RuleSetStatus.DRAFT.value:
        raise Conflict(f"The rule set is {row.status}", code="rule_set_not_draft")
    today = pricing.business_date(uow)
    if row.effective_from > today:
        # activation retires the current version at once, so a future version is activated on its effective date
        raise Conflict(
            f"{row.code} v{row.version_no} is effective from {row.effective_from.isoformat()}; activate it on or "
            f"after that date (today is {today.isoformat()})",
            code="rule_set_not_yet_effective",
        )
    QuoteCommercialRulesV1.model_validate(row.params)
    current = uow.session.scalars(
        select(RuleSet)
        .where(RuleSet.company_id == row.company_id, RuleSet.code == row.code, RuleSet.status == RuleSetStatus.ACTIVE.value)
        .with_for_update()
    ).all()
    for old in current:
        old.status = RuleSetStatus.RETIRED.value
        old.retired_at = uow.now()
    uow.flush()
    row.status = RuleSetStatus.ACTIVE.value
    row.activated_at = uow.now()
    row.activated_by = uow.actor.user_id
    uow.flush()
    payload: dict[str, Any] = {"rule_set_id": str(row.id), "code": row.code, "version_no": row.version_no}
    if origin:
        payload["origin"] = origin
    uow.emit(RULE_SET_ACTIVATED, aggregate_id=row.id, aggregate_version=row.version, payload=payload)
    uow.audit("commercial.rule_set.activated", resource_type="commercial.rule_set", resource_id=row.id,
              resource_label=f"{row.code} v{row.version_no}")
    return row


def active_rules(uow: UnitOfWork, code: str = QUOTE_COMMERCIAL) -> engine.RuleSet:
    """The active rule set as engine rules (configuration read by services; 409 ``not_configured`` when absent)."""
    row = uow.session.scalars(
        select(RuleSet).where(
            RuleSet.company_id == uow.actor.company_id, RuleSet.code == code, RuleSet.status == RuleSetStatus.ACTIVE.value
        )
    ).first()
    if row is None:
        raise NotConfigured(f"No active {code} rule set", code="not_configured")
    params = QuoteCommercialRulesV1.model_validate(row.params).model_dump(mode="json")
    return engine.rules_from_params(code=row.code, version_no=row.version_no, params=params, rule_set_id=row.id)


def calculate(uow: UnitOfWork, inputs: engine.CalculationInput, *, code: str = QUOTE_COMMERCIAL) -> engine.CalculationResult:
    """Run the pure engine with the company's active rule set (the sales module persists the result)."""
    return engine.calculate(inputs, active_rules(uow, code))


@query(READ)
def list_rule_sets(
    uow: UnitOfWork, *, code: str | None = None, limit: int = 50, offset: int = 0
) -> Page[RuleSetRead]:
    conds = [uow.repo(RuleSet).clause("read")]
    if code:
        conds.append(RuleSet.code == code)
    total = uow.session.scalar(select(func.count(RuleSet.id)).where(*conds)) or 0
    limit = max(1, min(limit, MAX_LIMIT))
    offset = max(0, offset)
    rows = uow.session.scalars(
        select(RuleSet).where(*conds).order_by(RuleSet.code, RuleSet.version_no.desc(), RuleSet.id).limit(limit).offset(offset)
    )
    return Page[RuleSetRead](items=[_read(r) for r in rows], total=int(total), limit=limit, offset=offset)


@query(READ)
def get_rule_set(uow: UnitOfWork, rule_set_id: uuid.UUID) -> RuleSetDetail:
    row = uow.repo(RuleSet).get(rule_set_id)
    can_manage = uow.actor.can(MANAGE)
    is_draft = row.status == RuleSetStatus.DRAFT.value
    effective = row.effective_from <= pricing.business_date(uow)
    if not can_manage:
        activate = Capability(allowed=False, reason_code="permission_denied")
    elif not is_draft:
        activate = Capability(allowed=False, reason_code="rule_set_not_draft")
    elif not effective:
        activate = Capability(allowed=False, reason_code="rule_set_not_yet_effective")
    else:
        activate = Capability(allowed=True)
    return RuleSetDetail(
        **_read(row).model_dump(),
        capabilities={"activate": activate},
        allowed_transitions=(
            [TransitionRead(action="activate", to_status=RuleSetStatus.ACTIVE.value, requires_reason=False)]
            if can_manage and is_draft
            else []
        ),
    )


def _not_current(item: PricedItem, on: date) -> str:
    if item.list_status != "active":
        return f"{item.price_list_code} is {item.list_status}; only active price lists price a calculation"
    if item.list_valid_from > on or (item.list_valid_to is not None and item.list_valid_to < on):
        until = item.list_valid_to.isoformat() if item.list_valid_to else "open"
        return f"{item.price_list_code} is valid {item.list_valid_from.isoformat()} to {until}, not on {on.isoformat()}"
    if item.status != "active":
        return f"the {item.price_list_code} price is {item.status}"
    until = item.valid_to.isoformat() if item.valid_to else "open"
    return f"the {item.price_list_code} price is effective {item.valid_from.isoformat()} to {until}, not on {on.isoformat()}"


@query("pricing.price.read")
def calculate_resolved_lines(uow: UnitOfWork, data: CalculateQuoteInput) -> CalculateQuoteOutput:
    """Totals over lines that reference resolved price-list items (``calculate_quote`` tool).

    The unit price and currency come from the item; the carton quantity from the catalogue packaging; the item's
    MOQ is the product MOQ. A line is rejected (422) when its item is in another currency (a price is never
    relabelled), when the item's list is not active or the list or item is not effective on the business date
    (``price_not_current``: a draft, retired or expired price is never totalled), or when the quantity breaks the
    unit's entry rule (whole numbers for integer units, at most 4 decimal places otherwise).
    """
    items = pricing.priced_items(uow, [line.price_list_item_id for line in data.lines])
    day = pricing.business_date(uow)
    problems: list[dict[str, Any]] = []
    for i, line in enumerate(data.lines):
        item = items.get(line.price_list_item_id)
        if item is None:
            raise NotFound(code="not_found", resource_type="pricing.price_list_item")
        loc = ["body", "lines", i]
        if item.currency != data.currency:
            problems.append({
                "loc": [*loc, "price_list_item_id"],
                "msg": f"The item is priced in {item.currency}; prices are never relabelled to {data.currency}",
                "code": "currency_mismatch",
            })
        if not item.is_current(day):
            problems.append({"loc": [*loc, "price_list_item_id"], "msg": _not_current(item, day), "code": "price_not_current"})
        entry = quantity_entry_problem(line.quantity, item.unit_code)
        if entry is not None:
            problems.append({"loc": [*loc, "quantity"], "msg": entry[1], "code": entry[0]})
    if problems:
        raise ValidationFailed("Some lines cannot be calculated", errors=problems)
    products = catalogue.product_refs(uow, [item.product_id for item in items.values()])
    line_inputs: list[engine.LineInput] = []
    refs: list[CalculatedLineRef] = []
    for i, line in enumerate(data.lines):
        item = items[line.price_list_item_id]
        product = products.get(item.product_id)
        if product is None:
            raise NotFound(code="not_found", resource_type="catalogue.product")
        key = line.line_key or f"L{i + 1}"
        moq = item.moq if item.moq_unit_code in (None, item.unit_code) else None
        try:
            line_inputs.append(
                engine.LineInput(
                    line_key=key,
                    line_type="catalog",
                    quantity=line.quantity,
                    unit_price=item.unit_price,
                    uom=item.unit_code,
                    carton_qty=product.carton_qty if item.unit_code == (product.unit_of_sale or item.unit_code) else None,
                    product_moq=moq,
                )
            )
        except (TypeError, ValueError) as exc:
            raise ValidationFailed(str(exc), errors=[{"loc": ["body", "lines", i], "msg": str(exc), "code": "invalid_line"}]) from exc
        refs.append(
            CalculatedLineRef(
                line_key=key,
                price_list_item_id=item.item_id,
                price_list_code=item.price_list_code,
                product_id=item.product_id,
                product_key=item.product_key,
                unit_code=item.unit_code,
            )
        )
    try:
        inputs = engine.CalculationInput(
            currency=data.currency, lines=tuple(line_inputs), surcharge_requested=data.surcharge_requested
        )
        result = calculate(uow, inputs)
    except (ValueError, ArithmeticError) as exc:  # e.g. duplicate line keys; never an unhandled decimal error
        raise ValidationFailed(f"The lines cannot be calculated: {exc}", code="validation_failed") from exc
    return CalculateQuoteOutput(
        calculation=CalculationResultOut.model_validate(result.as_dict()),
        lines=refs,
        warnings=list(result.warnings),
    )


# =====================================================================================================
# catalogue price columns (UI-35 list, UI-39 overview): resolved list prices + the order-value recommendation
# =====================================================================================================
def _active_rules_or_none(uow: UnitOfWork) -> engine.RuleSet | None:
    try:
        return active_rules(uow)
    except NotConfigured:
        return None


def _recommendation_read(rec: engine.Recommendation, currency: str) -> OrderValueRecommendationRead:
    return OrderValueRecommendationRead(
        status=rec.status,
        quantity=Quantity(value=rec.quantity, uom=rec.uom) if rec.quantity is not None else None,
        minimum_order_value=(
            Money(amount=rec.minimum_order_value, currency=currency)  # type: ignore[arg-type]
            if rec.minimum_order_value is not None
            else None
        ),
        carton_qty=rec.carton_qty,
        explanation=rec.explanation,
        label=rec.label,
    )


def product_price_columns(
    uow: UnitOfWork, product_ids: Sequence[uuid.UUID], currencies: Sequence[str], price_type: str | None = None
) -> dict[uuid.UUID, list[ProductPriceColumn]]:
    """Batch price columns for catalogue reads: ``pricing.display_prices`` (one query) plus the engine's order-value
    recommendation with the active rule set, per product and currency. Requires ``pricing.price.read``.

    Without an active rule set the recommendation is NOT_EVALUATED; without a positive price it is UNAVAILABLE
    (no division); a currency without a configured threshold is NOT_EVALUATED (no FX equivalent is invented)."""
    kind = PriceType(price_type) if price_type else None
    prices = pricing.display_prices(uow, product_ids, currencies=currencies, price_type=kind)
    products = catalogue.product_refs(uow, list(prices))
    rules = _active_rules_or_none(uow)
    out: dict[uuid.UUID, list[ProductPriceColumn]] = {}
    for product_id, per_currency in prices.items():
        product = products.get(product_id)
        columns: list[ProductPriceColumn] = []
        for currency, price in per_currency.items():
            uom = price.unit_code or (product.unit_of_sale if product else None)
            recommendation: OrderValueRecommendationRead | None = None
            if uom is not None:
                if rules is None:
                    rec = engine.Recommendation(
                        "NOT_EVALUATED", None, uom, None, None, None,
                        f"No active {QUOTE_COMMERCIAL} rule set; no recommendation is calculated.",
                    )
                else:
                    carton = product.carton_qty if product and uom == (product.unit_of_sale or uom) else None
                    rec = engine.order_value_recommendation(
                        rules,
                        currency=currency,
                        unit_price=price.unit_price.amount if price.unit_price is not None else None,
                        carton_qty=carton,
                        uom=uom,
                    )
                recommendation = _recommendation_read(rec, currency)
            columns.append(
                ProductPriceColumn(
                    currency=price.currency,
                    status=price.status,
                    unit_price=price.unit_price,
                    unit_code=price.unit_code,
                    price_list_code=price.price_list_code,
                    item_id=price.item_id,
                    product_moq=price.product_moq,
                    recommendation=recommendation,
                )
            )
        out[product_id] = columns
    return out
