"""Commercial services: versioned rule sets and calculations through the pure engine.

The engine itself has no database access; this service loads the active rule set and, for the
``calculate_quote`` tool, the resolved price-list items (prices never come from a model).
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import select

from app.core.db.base import new_id
from app.core.errors import Conflict, NotConfigured, NotFound, ValidationFailed
from app.modules.catalogue import service as catalogue
from app.modules.commercial import engine
from app.modules.commercial.models import RuleSet
from app.modules.commercial.schemas import (
    QUOTE_COMMERCIAL,
    CalculatedLineRef,
    CalculateQuoteInput,
    CalculateQuoteOutput,
    CalculationResultOut,
    QuoteCommercialRulesV1,
    RuleSetRead,
    RuleSetStatus,
)
from app.modules.pricing import service as pricing
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
def list_rule_sets(uow: UnitOfWork, *, code: str | None = None) -> list[RuleSetRead]:
    stmt = uow.repo(RuleSet).select()
    if code:
        stmt = stmt.where(RuleSet.code == code)
    return [_read(r) for r in uow.session.scalars(stmt.order_by(RuleSet.code, RuleSet.version_no.desc()))]


@query(READ)
def get_rule_set(uow: UnitOfWork, rule_set_id: uuid.UUID) -> RuleSetRead:
    return _read(uow.repo(RuleSet).get(rule_set_id))


@query("pricing.price.read")
def calculate_resolved_lines(uow: UnitOfWork, data: CalculateQuoteInput) -> CalculateQuoteOutput:
    """Totals over lines that reference resolved price-list items (``calculate_quote`` tool).

    The unit price and currency come from the item; the carton quantity from the catalogue packaging; the item's
    MOQ is the product MOQ. An item in another currency is rejected (a price is never relabelled).
    """
    items = pricing.priced_items(uow, [line.price_list_item_id for line in data.lines])
    problems: list[dict[str, Any]] = []
    for i, line in enumerate(data.lines):
        item = items.get(line.price_list_item_id)
        if item is None:
            raise NotFound(code="not_found", resource_type="pricing.price_list_item")
        if item.currency != data.currency:
            problems.append({
                "loc": ["body", "lines", i, "price_list_item_id"],
                "msg": f"The item is priced in {item.currency}; prices are never relabelled to {data.currency}",
                "code": "currency_mismatch",
            })
    if problems:
        raise ValidationFailed("Some lines do not match the quote currency", errors=problems)
    products = catalogue.product_refs(uow, [item.product_id for item in items.values()])
    day = pricing.business_date(uow)
    warnings: list[str] = []
    line_inputs: list[engine.LineInput] = []
    refs: list[CalculatedLineRef] = []
    for i, line in enumerate(data.lines):
        item = items[line.price_list_item_id]
        product = products.get(item.product_id)
        if product is None:
            raise NotFound(code="not_found", resource_type="catalogue.product")
        key = line.line_key or f"L{i + 1}"
        current = item.status == "active" and item.valid_from <= day and (item.valid_to is None or item.valid_to >= day)
        if not current:
            warnings.append(f"line:{key}:PRICE_NOT_CURRENT")
        moq = item.moq if item.moq_unit_code in (None, item.unit_code) else None
        line_inputs.append(
            engine.LineInput(
                line_key=key,
                line_type="catalog",
                quantity=line.quantity,
                unit_price=item.unit_price,
                carton_qty=product.carton_qty if item.unit_code == (product.unit_of_sale or item.unit_code) else None,
                product_moq=moq,
            )
        )
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
    except ValueError as exc:
        raise ValidationFailed(str(exc), code="validation_failed") from exc
    result = calculate(uow, inputs)
    return CalculateQuoteOutput(
        calculation=CalculationResultOut.model_validate(result.as_dict()),
        lines=refs,
        warnings=warnings + list(result.warnings),
    )
