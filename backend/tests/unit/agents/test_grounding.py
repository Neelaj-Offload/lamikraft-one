"""Number literals (digits, Indian grouping, English and Hinglish words), ID/numeric provenance, the price guard,
the numeric-claim checker and taint detection — all pure."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.modules.agents import numbers
from app.modules.agents.grounding import (
    GroundingError,
    Provenance,
    check_claims,
    decimals_in,
    ground_input,
    is_untrusted,
    uuids_in,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("change it to 300", {Decimal(300)}),
        ("1,00,000 trays and 5,760.00 total", {Decimal(100000), Decimal("5760.00")}),
        ("1,000 or 12,500.50", {Decimal(1000), Decimal("12500.50")}),
        ("two hundred forty", {Decimal(240)}),
        ("five thousand seven hundred and sixty", {Decimal(5760)}),
        ("twenty-four pieces", {Decimal(24)}),
        ("teen sau", {Decimal(300)}),
        ("do sau chaalis", {Decimal(240)}),
        ("ek hazaar", {Decimal(1000)}),
        ("LK-QT-2026-0009 is the number", set()),
        ("on 2026-10-12", set()),
        ("P-00001", set()),
    ],
)
def test_number_literals(text: str, expected: set[Decimal]) -> None:
    assert numbers.literals(text) == expected


def test_mentions_compares_numerically_across_groupings() -> None:
    assert numbers.mentions("quote 1,00,000", Decimal("100000"))
    assert numbers.mentions("three hundred", "300")
    assert not numbers.mentions("three hundred", "30")
    assert numbers.first_quantity("make it twelve") == Decimal(12)


def _prov(**kw: object) -> Provenance:
    defaults: dict = {"known_ids": frozenset(), "user_text": ""}
    defaults.update(kw)
    return Provenance(**defaults)


def test_uuids_and_decimals_are_collected_recursively() -> None:
    a, b = uuid.uuid7(), uuid.uuid7()
    value = {"party_id": str(a), "lines": [{"product_id": b, "quantity": "240", "unit_price": {"amount": "24.0000", "currency": "EUR"}}], "n": 3, "flag": True}
    assert uuids_in(value) == {a, b}
    assert decimals_in(value) == {Decimal("240"), Decimal("24.0000"), Decimal(3)}


def test_id_provenance_rejects_unknown_ids_before_any_call() -> None:
    known, unknown = uuid.uuid7(), uuid.uuid7()
    prov = _prov(known_ids=frozenset({known}))
    assert ground_input({"party_id": str(known)}, prov).data == {"party_id": str(known)}
    with pytest.raises(GroundingError) as exc:
        ground_input({"party_id": str(known), "lines": [{"product_id": str(unknown)}]}, prov)
    assert exc.value.code == "id_provenance"


def test_quantity_provenance_sidecars_are_verified_and_stripped() -> None:
    prov = _prov(user_text="make it two hundred forty", record_values=frozenset({Decimal(500)}), clarification_values=frozenset({Decimal(7)}))
    grounded = ground_input({"lines": [{"quantity": "240", "quantity_source": "user_turn"}]}, prov)
    assert grounded.data == {"lines": [{"quantity": "240"}]} and grounded.quantity_sources == {"lines[0].quantity": "user_turn"}
    assert ground_input({"quantity": "500", "quantity_source": "record"}, prov).data == {"quantity": "500"}
    assert ground_input({"quantity": "7", "quantity_source": "clarification"}, prov).data == {"quantity": "7"}
    for bad in (
        {"quantity": "240"},
        {"quantity": "241", "quantity_source": "user_turn"},
        {"quantity": "501", "quantity_source": "record"},
        {"quantity": "8", "quantity_source": "clarification"},
        {"quantity": "240", "quantity_source": "model"},
    ):
        with pytest.raises(GroundingError) as exc:
            ground_input(bad, prov)
        assert exc.value.code == "quantity_provenance", bad


def test_prices_are_rejected_unless_an_explicit_permitted_override() -> None:
    prov = _prov(user_text="quote at 26 because of the volume", can_override_price=True)
    for field in ("unit_price", "amount", "grand_total", "discount_rate"):
        with pytest.raises(GroundingError) as exc:
            ground_input({field: "26"}, prov)
        assert exc.value.code == "price_not_model_input"
    item_id = uuid.uuid7()
    identifiers = ground_input({"price_list_item_id": str(item_id), "price_type": "export"}, _prov(known_ids=frozenset({item_id})))
    assert identifiers.data == {"price_list_item_id": str(item_id), "price_type": "export"}, "ids and types are not prices"
    override = ground_input({"price_override": {"value": "26", "reason": "volume", "source": "user_turn"}}, prov)
    assert override.price_override == {"value": "26", "reason": "volume", "source": "user_turn"}
    with pytest.raises(GroundingError) as denied:
        ground_input({"price_override": {"value": "26", "reason": "volume", "source": "user_turn"}}, _prov(user_text="quote at 26"))
    assert denied.value.code == "permission_denied"
    with pytest.raises(GroundingError) as not_said:
        ground_input({"price_override": {"value": "27", "reason": "volume", "source": "user_turn"}}, prov)
    assert not_said.value.code == "price_not_model_input"
    with pytest.raises(GroundingError):
        ground_input({"price_override": {"value": "26", "reason": "volume", "source": "record"}}, prov)


@pytest.mark.parametrize(
    ("text", "allowed", "expected", "count"),
    [
        ("240 pcs at EUR 24.00, total EUR 5,760.00", ["240", "24.0000", "5760.00"], "240 pcs at EUR 24.00, total EUR 5,760.00", 0),
        ("about 250 pcs, total EUR 6,000.00", ["240", "5760.00"], "about see card, total see card", 2),
        ("Draft LK-QT-2026-0009 for P-00001 on 2026-10-12 is ready", [], "Draft LK-QT-2026-0009 for P-00001 on 2026-10-12 is ready", 0),
        ("the note said 500 trays", [], "the note said see card trays", 1),
        ("recommended 216 (carton 24)", ["216", "24"], "recommended 216 (carton 24)", 0),
        ("₹3,450 each", ["3450.0000"], "₹3,450 each", 0),
        ("₹3,451 each", ["3450.0000"], "see card each", 1),
    ],
)
def test_numeric_claims_without_tool_source_are_stripped(text: str, allowed: list[str], expected: str, count: int) -> None:
    assert check_claims(text, [Decimal(a) for a in allowed]) == (expected, count)


def test_untrusted_detection() -> None:
    assert is_untrusted({"output": {"notes": [{"untrusted": True, "source": "customer_message", "text": "x"}]}})
    assert not is_untrusted({"output": {"untrusted": False, "text": "x"}})
    assert not is_untrusted({"status": "unique"})
