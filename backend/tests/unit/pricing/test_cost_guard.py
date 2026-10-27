"""Restricted cost fields: absent without ``pricing.cost.read``, never in model context, never in logs."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from app.core.logging import redact_processor
from app.core.money import Money
from app.modules.pricing.schemas import COST_FIELD_NAMES, PriceListItemRead, ProductCostRead, ProductPrices
from app.platform.authz.context import ActorContext
from app.platform.authz.permissions import Scope
from app.platform.authz.redaction import redact, restricted_field_names

SENTINEL = Decimal("987654.3210")


def _actor(*keys: str) -> ActorContext:
    return ActorContext(
        actor_type="user", company_id=uuid.uuid7(), user_id=uuid.uuid7(), permissions={k: Scope.COMPANY for k in keys}
    )


def _cost() -> ProductCostRead:
    return ProductCostRead(
        id=uuid.uuid7(), product_id=uuid.uuid7(), cost_version=1, unit_cost=Money(amount=SENTINEL, currency="EUR"),
        unit_code="pcs", cost_components=[{"label": "veneer", "amount": "1.0000"}], source_kind="manual",
        effective_from=date(2026, 1, 1), recorded_at=datetime(2026, 6, 1, tzinfo=UTC),
    )


def _prices() -> ProductPrices:
    return ProductPrices(product_id=uuid.uuid7(), product_key="LK-OT-0450", on_date=date(2026, 10, 12), prices=[],
                         current_cost=_cost())


def test_cost_fields_are_declared_restricted() -> None:
    guarded = restricted_field_names(ProductCostRead)
    assert set(guarded) == {"unit_cost", "cost_components"}
    assert all(g.guard == "pricing.cost.read" and g.model_exposure == "deny" for g in guarded.values())
    assert restricted_field_names(ProductPrices)["current_cost"].guard == "pricing.cost.read"


def test_cost_is_nulled_for_actors_without_the_guard_key() -> None:
    out = redact(_prices(), _actor("pricing.price.read"))
    assert out.current_cost is None and out.redacted_fields == ["current_cost"]
    assert str(SENTINEL) not in out.model_dump_json()


def test_cost_never_reaches_model_context_even_for_permitted_users() -> None:
    finance = _actor("pricing.price.read", "pricing.cost.read")
    assert redact(_prices(), finance).current_cost is not None
    for_model = redact(_prices(), finance, for_model=True)
    assert for_model.current_cost is None and str(SENTINEL) not in for_model.model_dump_json()


def test_price_breakdown_needs_price_list_read() -> None:
    item = PriceListItemRead(
        id=uuid.uuid7(), price_list_id=uuid.uuid7(), price_list_code="EXP-EUR-2026", product_id=uuid.uuid7(),
        product_key="LK-OT-0450", display_sku="LK-OT-0450", unit_code="pcs",
        unit_price=Money(amount=Decimal("24.0000"), currency="EUR"), final_price=None,
        base_price=Money(amount=Decimal("20.0000"), currency="EUR"), base_price_label="board", addon_price=None,
        addon_price_label=None, price_basis="per piece", yield_qty_per_board=None, thickness_mm=None,
        source_kind="seed", source_ref=None, source_sheet=None, source_row=None, moq=None,
        notes=None, valid_from=date(2026, 1, 1), valid_to=None, status="active", superseded_by_item_id=None, version=1,
    )
    sales = redact(item, _actor("pricing.price.read"))
    assert sales.base_price is None and sales.price_basis is None
    assert sales.unit_price.model_dump(mode="json") == {"amount": "24.0000", "currency": "EUR"}
    assert sales.redacted_fields == ["base_price", "base_price_label", "price_basis", "source_kind"]
    management = redact(item, _actor("pricing.price.read", "pricing.price_list.read"))
    assert management.base_price is not None and management.base_price.amount == Decimal("20.0000")
    assert management.redacted_fields == []


def test_cost_field_names_are_scrubbed_from_logs() -> None:
    event = {"event": "pricing.debug", "unit_cost": {"amount": str(SENTINEL)}, "unit_cost_amount": str(SENTINEL),
             "nested": {"cost_components": [1, 2]}}
    out = redact_processor(None, "info", dict(event))
    assert out["unit_cost"] == out["unit_cost_amount"] == "[redacted]" and out["nested"]["cost_components"] == "[redacted]"
    assert set(COST_FIELD_NAMES) >= {"unit_cost", "unit_cost_amount", "cost_components"}
