"""Fixture commercial rule set (docs/architecture/fixtures.md §6): ``quote_commercial`` v1, active.

EUR minimum order value 5,000.00, surcharge 400.00, applicable line types catalog/custom/manual. No threshold for
any other currency (no invented FX equivalent). Created and activated by Priya at D-115; idempotent on
(code, version).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.modules.commercial import service as commercial
from app.modules.commercial.schemas import QuoteCommercialRulesV1, RuleSetStatus, ThresholdParams
from app.seed.context import SeedContext
from app.seed.world import keys
from app.seed.world.parties import CREATOR, as_member, at_ist

RULE_SET_REF = "RULE_SET_QUOTE_COMMERCIAL"
RULE_SET_V1 = QuoteCommercialRulesV1(
    thresholds={
        "EUR": ThresholdParams(
            minimum_order_value=Decimal(keys.COMMERCIAL.EUR_MINIMUM), surcharge_amount=Decimal(keys.COMMERCIAL.SURCHARGE)
        )
    },
    applicable_line_types=["catalog", "custom", "manual"],
    surcharge_label="Shipping surcharge",
    min_invoice_note_template="Minimum invoice value: EUR 5,000",
)


def seed_commercial(ctx: SeedContext) -> None:
    ctx.at(at_ist(-115, 11))
    with as_member(ctx, CREATOR) as uow:
        row = commercial.find_rule_set(uow, keys.COMMERCIAL.RULE_SET, 1)
        if row is None:
            row = commercial.create_rule_set(
                uow,
                code=keys.COMMERCIAL.RULE_SET,
                version_no=1,
                params=RULE_SET_V1,
                effective_from=date(2026, 1, 1),
                description="Legacy EUR minimum order value and shipping surcharge",
            )
        if row.status == RuleSetStatus.DRAFT.value:
            commercial.activate_rule_set(uow, row.id)
        ctx.refs[RULE_SET_REF] = row.id
