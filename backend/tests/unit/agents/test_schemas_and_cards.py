"""Screen-context validation limits, turn validation and the card models (discriminated by ``kind``)."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from pydantic import TypeAdapter, ValidationError

from app.modules.agents import cards
from app.modules.agents.schemas import MAX_CONTEXT_BYTES, MAX_VISIBLE_ITEMS, ScreenContext, TurnCreate


def _item(i: int) -> dict:
    return {"ref": f"i{i}", "list_key": "quote_lines", "ordinal": i, "type": "sales.quote_line", "id": str(uuid.uuid7()), "version": 3}


def test_screen_context_payload_of_section_4_1_validates() -> None:
    quote_id = str(uuid.uuid7())
    context = ScreenContext.model_validate({
        "schema_version": 1,
        "captured_at": "2026-10-12T03:31:04Z",
        "route": {"path": "/sales/quotes/[quoteId]", "params": {"quoteId": quote_id}, "area": "sales"},
        "focus": {"type": "sales.quote", "id": quote_id, "version": 7},
        "records": [{"type": "sales.quote", "id": quote_id, "version": 7, "role": "primary"}],
        "visible_items": [_item(2)],
        "selection": ["i2"],
        "filters": {"status": "draft"},
        "draft": {"form_key": "quote_header", "record_ref": quote_id, "dirty_fields": ["remarks"], "values": {"remarks": "..."}},
        "briefing_pin": {"pin_id": str(uuid.uuid7()), "version": 2},
        "viewport": {"width": 1440, "height": 900},
    })
    assert context.focus is not None and context.focus.type == "sales.quote"
    assert context.for_storage()["draft"]["values"] == {}, "draft values are never persisted"


def test_screen_context_limits() -> None:
    with pytest.raises(ValidationError, match="50"):
        ScreenContext.model_validate({"visible_items": [_item(i) for i in range(1, MAX_VISIBLE_ITEMS + 2)]})
    with pytest.raises(ValidationError, match=str(MAX_CONTEXT_BYTES)):
        ScreenContext.model_validate({"filters": {"blob": "x" * (MAX_CONTEXT_BYTES + 1)}})
    with pytest.raises(ValidationError):
        ScreenContext.model_validate({"records": [{"type": "not a type", "id": str(uuid.uuid7())}]})
    assert ScreenContext.model_validate({"visible_items": [_item(i) for i in range(1, MAX_VISIBLE_ITEMS + 1)]})


def test_turn_create_rules() -> None:
    assert TurnCreate(text="  hello ").text == "hello"
    with pytest.raises(ValidationError):
        TurnCreate(text="x" * 4001)
    with pytest.raises(ValidationError):
        TurnCreate(text="   ")
    assert TurnCreate(text="", selected_option={"slot": "party", "value": str(uuid.uuid7())}).selected_option is not None
    with pytest.raises(ValidationError):
        TurnCreate(text="hi", extra_field=1)  # type: ignore[call-arg]


def test_cards_are_discriminated_by_kind_and_carry_the_provider_label() -> None:
    adapter = TypeAdapter(cards.Card)
    for card in (
        cards.error_card("x", "y", provider_label="Demo", tainted=True),
        cards.record_link_card("Quotes", "/sales/quotes", provider_label="Demo", tainted=False),
        cards.clarification_card("party", "Which?", cards.party_options([
            {"party_id": uuid.uuid7(), "display_name": "A", "party_number": "P-00001", "country_code": "DE", "default_currency": "EUR"},
            {"party_id": uuid.uuid7(), "display_name": "B", "party_number": "P-00005", "country_code": "CH", "default_currency": "EUR"},
        ]), provider_label="Demo", tainted=False),
    ):
        dumped = card.model_dump(mode="json")
        assert dumped["provider_label"] == "Demo" and adapter.validate_python(dumped).kind == card.kind
    with pytest.raises(ValidationError):
        adapter.validate_python({"kind": "proposal", "provider_label": "Demo"})


def test_quote_draft_card_reads_persisted_totals_in_money_shape() -> None:
    quote_id, line_id, product_id = uuid.uuid7(), uuid.uuid7(), uuid.uuid7()
    output = {
        "quote_id": str(quote_id), "quote_number": "LK-QT-2026-0009", "status": "draft", "party_id": str(uuid.uuid7()),
        "party_name": "Nordhaus Interiors GmbH", "currency": "EUR",
        "totals": {
            "currency": "EUR", "gross_subtotal": {"amount": "5760.00", "currency": "EUR"},
            "discount_total": {"amount": "0.00", "currency": "EUR"}, "applicable_subtotal": {"amount": "5760.00", "currency": "EUR"},
            "grand_total": {"amount": "5760.00", "currency": "EUR"}, "minimum": {"status": "MEETS"},
            "surcharge": {"applied": False, "amount": {"amount": "0.00", "currency": "EUR"}},
            "lines": [{"line_key": str(line_id), "recommendation": {"quantity": {"value": "216", "uom": "pcs"}}}], "warnings": [],
        },
        "lines": [{"line_id": str(line_id), "product_id": str(product_id), "product_key": "LK-OT-0450", "quantity": {"value": "240", "uom": "pcs"},
                   "unit_price": {"amount": "24.0000", "currency": "EUR"}, "line_total": {"amount": "5760.00", "currency": "EUR"}}],
        "capabilities": {"update": {"allowed": True}},
    }
    card = cards.quote_draft_card(output, provider_label="Demo", tainted=False)
    assert card.totals is not None and card.totals.grand_total == Decimal("5760.00") and card.totals.recommended_quantity == 216
    assert card.lines[0].quantity == Decimal("240") and card.lines[0].uom == "pcs" and card.lines[0].unit_price == Decimal("24.0000")
    assert card.review is not None and card.review.path == f"/sales/quotes/{quote_id}"
    assert card.capabilities["update"].allowed and not card.requires_confirmation
    tainted = cards.quote_draft_card(output, provider_label="Demo", tainted=True)
    assert tainted.requires_confirmation and tainted.tainted


def test_clarification_options_are_exactly_the_candidates() -> None:
    candidates = [{"party_id": uuid.uuid7(), "display_name": n, "party_number": f"P-0000{i}", "country_code": "DE", "default_currency": "EUR"}
                  for i, n in enumerate(("Nordhaus Interiors GmbH", "Nordhaus Logistik AG"), start=1)]
    options = cards.party_options(candidates)
    assert [o.action.value for o in options] == [str(c["party_id"]) for c in candidates]
    assert all(o.action.kind == "select_option" and o.action.slot == "party" for o in options)


def test_quote_draft_card_reads_the_sales_quote_detail_shape() -> None:
    """``draft_quote`` returns sales ``QuoteDetail``: ``id``, ``party{}``, ``version``, ``QuoteLineRead`` lines with a
    ``product_snapshot`` and ``unit_code``, persisted ``totals`` and the engine ``calculation``."""
    quote_id, line_id, product_id, party_id = uuid.uuid7(), uuid.uuid7(), uuid.uuid7(), uuid.uuid7()
    money = lambda a: {"amount": a, "currency": "EUR"}  # noqa: E731
    output = {
        "id": str(quote_id), "quote_number": "LK-QT-2026-0009", "status": "draft", "currency": "EUR", "version": 3,
        "party": {"id": str(party_id), "party_number": "P-00001", "display_name": "Nordhaus Interiors GmbH", "country_code": "DE"},
        "lines": [{"id": str(line_id), "line_no": 1, "line_key": str(line_id), "line_type": "catalog", "product_id": str(product_id),
                   "description": "Oak tray", "quantity": "240", "unit_code": "pcs", "unit_price": "24.0000", "line_total": "5760.00",
                   "price_list_item_id": str(uuid.uuid7()),
                   "product_snapshot": {"product_id": str(product_id), "product_key": "LK-OT-0450", "display_sku": "OT-0450", "product_name": "Oak tray"}}],
        "totals": {"currency": "EUR", "gross_subtotal": money("5760.00"), "surcharge": money("0.00"), "surcharge_applied": False,
                   "grand_total": money("5760.00"), "minimum": {"status": "MEETS"}},
        "calculation": {
            "currency": "EUR", "gross_subtotal": money("5760.00"), "discount_total": money("0.00"), "applicable_subtotal": money("5760.00"),
            "grand_total": money("5760.00"), "minimum": {"status": "MEETS"}, "surcharge": {"applied": False, "amount": money("0.00")},
            "lines": [{"line_key": str(line_id), "recommendation": {"quantity": {"value": "216", "uom": "pcs"}}}], "warnings": [],
        },
        "capabilities": {"update": {"allowed": True}},
    }
    card = cards.quote_draft_card(output, provider_label="Demo", tainted=False)
    assert card.quote_id == quote_id and card.version == 3 and card.party_id == party_id
    assert card.party_label == "Nordhaus Interiors GmbH"
    line = card.lines[0]
    assert line.line_id == line_id and line.product_key == "LK-OT-0450" and line.uom == "pcs" and line.line_total == Decimal("5760.00")
    assert card.totals is not None and card.totals.grand_total == Decimal("5760.00") and card.totals.recommended_quantity == 216
    assert card.review is not None and card.review.path == f"/sales/quotes/{quote_id}"


def test_bare_ids_are_typed_by_the_shape_that_carries_them() -> None:
    from app.modules.agents.context import typed_refs_from_output

    quote_id, line_id, party_id = uuid.uuid7(), uuid.uuid7(), uuid.uuid7()
    refs = typed_refs_from_output({
        "id": str(quote_id), "quote_number": "LK-QT-2026-0009",
        "party": {"id": str(party_id), "party_number": "P-00001", "display_name": "Nordhaus"},
        "lines": [{"id": str(line_id), "line_key": str(line_id)}],
        "owner": {"id": str(uuid.uuid7()), "display_name": "Meera"},  # untyped: not object context
    })
    assert {(r.resource_type, r.resource_id) for r in refs} == {
        ("sales.quote", quote_id), ("parties.party", party_id), ("sales.quote_line", line_id),
    }
