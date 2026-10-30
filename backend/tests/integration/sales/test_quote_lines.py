"""Quote lines: catalog snapshots immune to catalogue change, manual presets, the override rule (LM-46/48/50,
FG-QLN-*, BR-05, ADR-046)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.core.errors import Conflict, Forbidden, ValidationFailed
from app.modules.catalogue import service as catalogue
from app.modules.catalogue.schemas import PackagingIn, ProductUpdate
from app.modules.pricing import service as pricing
from app.modules.pricing.schemas import SupersedeItem
from app.modules.sales import service as sales
from app.modules.sales.schemas import QuoteLineCreate, QuoteLineUpdate
from app.seed.world import keys
from app.seed.world.pricing import item_ref
from tests.integration.sales.world import SalesWorld

pytestmark = pytest.mark.db


def _line(world: SalesWorld, quote_id, version, **kw):  # type: ignore[no-untyped-def]
    with world.uow(kw.pop("person", keys.USERS.MEERA)) as uow:
        quote, line = sales.add_line(uow, quote_id, QuoteLineCreate(expected_version=version, **kw))
        return sales.detail(uow, quote)


def test_catalog_line_snapshot_immune_to_catalogue_change(world: SalesWorld) -> None:
    from datetime import date

    draft = world.new_draft(keys.USERS.MEERA, "NORDHAUS", ("OAK_TRAY", keys.EXPECTED.SCENARIO_C_QTY))
    line = draft.lines[0]
    assert line.line_type == "catalog" and line.product_snapshot is not None and line.packaging_snapshot is not None
    assert line.product_snapshot.product_key == keys.PRODUCTS.OAK_TRAY and line.product_snapshot.decor_no == keys.DECORS.NATURAL_OAK
    assert line.product_snapshot.product_name == "Oak serving tray 450" and line.description == "Oak serving tray 450"
    assert line.packaging_snapshot.carton_qty == 24 and str(line.packaging_snapshot.cbm) == "0.047520"
    assert line.media_snapshot is not None and line.media_snapshot.hint == f"decor:{keys.DECORS.NATURAL_OAK}"
    assert line.commercial_snapshot is not None and line.commercial_snapshot.price_list_code == keys.PRICE_LISTS.EXP_EUR
    assert (line.commercial_snapshot.tier, line.commercial_snapshot.resolved_on) == ("standard", date(2026, 10, 12))
    assert str(line.default_unit_price) == keys.PRICES.OAK_TRAY_EUR and line.unit_price == line.default_unit_price
    assert line.price_list_item_id == world.ref(item_ref("PL_EXP_EUR", "OAK_TRAY")) and line.advisories == []
    assert draft.totals.grand_total is not None and str(draft.totals.grand_total.amount) == keys.EXPECTED.SCENARIO_C_TOTAL

    # the catalogue and the price list change afterwards
    with world.uow(keys.USERS.PRIYA) as uow:
        product = catalogue.get_product(uow, world.ref("OAK_TRAY"))
        catalogue.update_product(
            uow, product.id,
            ProductUpdate(expected_version=product.version, product_name="Oak serving tray 450 (renamed)",
                          packaging=PackagingIn(carton_qty=12, unit_weight_g=Decimal("450"), packing_type="Poly bag")),
        )
        pricing.supersede_item(uow, line.price_list_item_id, SupersedeItem(unit_price=Decimal("26.0000"), valid_from=date(2026, 10, 12)))
    with world.uow(keys.USERS.MEERA) as uow:
        after = sales.get_quote(uow, draft.id)
    kept = after.lines[0]
    assert kept.product_snapshot.product_name == "Oak serving tray 450" and kept.packaging_snapshot.carton_qty == 24
    assert str(kept.unit_price) == keys.PRICES.OAK_TRAY_EUR and str(after.totals.grand_total.amount) == keys.EXPECTED.SCENARIO_C_TOTAL
    assert "PRICE_CHANGED_SINCE_SNAPSHOT" in kept.advisories and str(kept.current_unit_price) == "26.0000"
    assert after.version == draft.version  # reads never write

    # only an explicit refresh takes the new price and name
    with world.uow(keys.USERS.MEERA) as uow:
        from app.modules.sales.schemas import RefreshSnapshots

        refreshed = sales.detail(uow, sales.refresh_snapshots(uow, draft.id, RefreshSnapshots(expected_version=after.version)))
    fresh = refreshed.lines[0]
    assert str(fresh.unit_price) == "26.0000" and fresh.product_snapshot.product_name == "Oak serving tray 450 (renamed)"
    assert fresh.packaging_snapshot.carton_qty == 12 and str(refreshed.totals.grand_total.amount) == "6240.00"
    assert "PRICE_CHANGED_SINCE_SNAPSHOT" not in fresh.advisories and refreshed.version == after.version + 1


def test_manual_line_presets(world: SalesWorld) -> None:
    draft = world.new_draft(keys.USERS.MEERA, "NORDHAUS")
    d = _line(world, draft.id, draft.version, line_type="manual", manual_preset="tooling", quantity=Decimal("1"), unit_price=Decimal("250"))
    tooling = d.lines[0]
    assert (tooling.line_type, tooling.description, tooling.unit_code, tooling.manual_preset) == ("manual", "Tooling charges", "set", "tooling")
    assert str(tooling.unit_price) == "250.0000" and str(tooling.line_total) == "250.00" and tooling.product_id is None
    assert tooling.recommendation is not None and tooling.recommendation.status == "NOT_APPLICABLE"
    d = _line(world, draft.id, d.version, line_type="manual", manual_preset="freight", description="Sea freight to Hamburg",
              quantity=Decimal("2"), unit_price=Decimal("1200.5"), unit_code="pcs")
    freight = d.lines[1]
    assert (freight.description, freight.unit_code, str(freight.line_total)) == ("Sea freight to Hamburg", "pcs", "2401.00")
    assert d.totals.line_count == 2 and str(d.totals.grand_total.amount) == "2651.00"
    assert d.totals.minimum.status == "BELOW" and d.totals.surcharge_applied is False  # toggle off
    with pytest.raises(ValidationError):
        QuoteLineCreate(expected_version=1, line_type="manual", quantity=Decimal("1"))  # no price, no preset/description
    with pytest.raises(ValidationError):
        QuoteLineCreate(expected_version=1, line_type="manual", product_key="LK-OT-0450", quantity=Decimal("1"), unit_price=Decimal("1"), description="x")


def test_override_requires_permission_and_reason_for_sales(world: SalesWorld) -> None:
    """Sales (Meera) must give a reason; management (Sahil) may override freely; operations (Ravi) cannot."""
    draft = world.new_draft(keys.USERS.MEERA, "MAISON")
    with pytest.raises(ValidationFailed) as exc:
        _line(world, draft.id, draft.version, product_id=world.ref("ASH_BOARD"), quantity=Decimal("320"), unit_price=Decimal("16.5"))
    assert exc.value.extra["errors"][0]["code"] == "override_reason_required"
    d = _line(world, draft.id, draft.version, product_id=world.ref("ASH_BOARD"), quantity=Decimal("320"), unit_price=Decimal("16.5"),
              override_reason="Volume price agreed for launch order")
    line = d.lines[0]
    assert str(line.default_unit_price) == keys.PRICES.ASH_BOARD_EUR and str(line.unit_price) == "16.5000" and line.is_overridden
    assert line.override_reason == "Volume price agreed for launch order"
    assert str(d.totals.grand_total.amount) == "5280.00" and d.review.requires_approval and d.review.reasons == ["price_override"]

    # a discount is an override too; clearing the override restores the default and the review requirement drops
    with world.uow(keys.USERS.MEERA) as uow:
        with pytest.raises(ValidationFailed):
            sales.update_line(uow, d.id, line.id, QuoteLineUpdate(expected_version=d.version, clear_override=True, discount_pct=Decimal("5")))
    with world.uow(keys.USERS.MEERA) as uow:
        quote, _ = sales.update_line(uow, d.id, line.id, QuoteLineUpdate(expected_version=d.version, clear_override=True))
        cleared = sales.detail(uow, quote)
    assert str(cleared.lines[0].unit_price) == keys.PRICES.ASH_BOARD_EUR and not cleared.lines[0].is_overridden
    assert cleared.review.requires_approval is False and str(cleared.totals.grand_total.amount) == "5760.00"

    # management: no reason needed (sales.quote_price.approve waives it)
    with world.uow(keys.USERS.SAHIL) as uow:
        quote, _ = sales.update_line(uow, d.id, line.id, QuoteLineUpdate(expected_version=cleared.version, unit_price=Decimal("17")))
        mgmt = sales.detail(uow, quote)
    assert str(mgmt.lines[0].unit_price) == "17.0000" and mgmt.lines[0].is_overridden and mgmt.lines[0].override_reason is None

    # operations: reads company-wide but has neither update nor override
    with pytest.raises(Forbidden):
        with world.uow(keys.USERS.RAVI) as uow:
            sales.update_line(uow, d.id, line.id, QuoteLineUpdate(expected_version=mgmt.version, unit_price=Decimal("1")))
    # a sales user without the override key (test-local) gets permission_denied naming the key
    no_override = world.actor(keys.USERS.MEERA).with_(
        permissions={k: v for k, v in world.actor(keys.USERS.MEERA).permissions.items() if k != "sales.quote_price.override"}
    )
    from app.platform.uow import UnitOfWork

    with pytest.raises(Forbidden) as denied:
        with UnitOfWork(no_override, clock=world.ctx.clock) as uow:
            sales.update_line(uow, d.id, line.id, QuoteLineUpdate(expected_version=mgmt.version, unit_price=Decimal("1"), override_reason="x"))
    assert denied.value.extra["permission"] == "sales.quote_price.override"


def test_integer_uom_rejects_fractions(world: SalesWorld) -> None:
    draft = world.new_draft(keys.USERS.MEERA, "NORDHAUS")
    with pytest.raises(ValidationFailed) as exc:
        _line(world, draft.id, draft.version, product_id=world.ref("OAK_TRAY"), quantity=Decimal("240.5"))
    assert exc.value.extra["errors"][0]["code"] == "uom_integer_only"


def test_line_type_reference_checks(world: SalesWorld) -> None:
    with pytest.raises(ValidationError):
        QuoteLineCreate(expected_version=1, line_type="catalog", quantity=Decimal("1"))
    with pytest.raises(ValidationError):
        QuoteLineCreate(expected_version=1, line_type="catalog", product_id=world.ref("OAK_TRAY"), product_key="LK-OT-0450", quantity=Decimal("1"))
    draft = world.new_draft(keys.USERS.NEHA, "THORNBURY")  # GBP quote: the walnut board has no GBP price
    with pytest.raises(Conflict) as exc:
        _line(world, draft.id, draft.version, person=keys.USERS.NEHA, product_id=world.ref("WALNUT_BOARD"), quantity=Decimal("1"))
    assert exc.value.code == "price_unavailable"


def test_price_ambiguity_is_409(world: SalesWorld, monkeypatch: pytest.MonkeyPatch) -> None:
    """An ambiguous resolution never falls through: the line is refused with 409 ``price_ambiguous`` and the
    candidates (activation already prevents overlapping lists, so the resolver is stubbed here)."""
    from app.modules.pricing.schemas import PriceCandidate, PriceResolution
    from app.modules.sales import quotes

    def ambiguous(uow, *, product_id, party_id, currency, unit_code, price_type, on_date=None):  # type: ignore[no-untyped-def]
        real = quotes.pricing.resolve_price(uow, currency=currency, uom=unit_code, product_id=product_id, party_id=party_id)
        candidate = PriceCandidate(tier="standard", price_list_id=real.price_list_id, price_list_code=real.price_list_code,
                                   item_id=real.item_id, priority=None, unit_price=real.unit_price, unit_code="pcs",
                                   valid_from=real.on_date, valid_to=None)
        return PriceResolution(status="ambiguous", reason_code="PRICE_AMBIGUOUS", explanation="two lists", product_id=real.product_id,
                               product_key=real.product_key, party_id=real.party_id, customer_type=real.customer_type,
                               requested_currency="EUR", requested_uom="pcs", on_date=real.on_date, price_type=real.price_type,
                               candidates=[candidate, candidate])

    monkeypatch.setattr(quotes, "resolve_line_price", ambiguous)
    draft = world.new_draft(keys.USERS.MEERA, "NORDHAUS")
    with pytest.raises(Conflict) as exc:
        _line(world, draft.id, draft.version, product_id=world.ref("OAK_TRAY"), quantity=Decimal("24"))
    assert exc.value.code == "price_ambiguous" and len(exc.value.extra["candidates"]) == 2
