"""Vision units: the per-kind JSON schemas, result parsing (unknown keys dropped, confidences clamped, missing
values null with confidence 0) and the deterministic Demo adapter."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app.modules.agents.providers.demo_vision import DEMO_DELIVERY_NOTE, FIXTURES, DemoVisionProvider
from app.modules.vision.contract import (
    EXTRACTION_KINDS,
    HEADER_FIELDS,
    LINE_FIELDS,
    MAX_LINES,
    ScreenFacts,
    extraction_schema,
    parse_extraction,
)


@pytest.mark.parametrize("kind", EXTRACTION_KINDS)
def test_every_kind_has_a_schema_with_a_confidence_per_field(kind: str) -> None:
    schema = extraction_schema(kind)  # type: ignore[arg-type]
    header = schema["properties"]["header"]
    assert set(header["required"]) == {f.key for f in HEADER_FIELDS[kind]}  # type: ignore[index]
    for prop in header["properties"].values():
        assert prop["required"] == ["value", "confidence"]
        assert prop["properties"]["value"]["type"] == ["string", "null"]
    lines = schema["properties"]["lines"]
    assert lines["maxItems"] == MAX_LINES
    assert set(lines["items"]["required"]) == {f.key for f in LINE_FIELDS[kind]}  # type: ignore[index]


def test_parse_drops_unknown_clamps_and_nulls() -> None:
    header, lines = parse_extraction("bill", {
        "header": {"document_number": {"value": " B-1 ", "confidence": 2}, "evil": {"value": "x", "confidence": 1},
                   "vendor_name": {"value": "", "confidence": 0.9}, "tax_amount": "not an object"},
        "lines": [{"amount": {"value": "10", "confidence": "nan"}}, "junk"] + [{}] * 60,
    })
    assert header["document_number"].value == "B-1" and header["document_number"].confidence == 1.0
    assert "evil" not in header and header["vendor_name"].value is None and header["vendor_name"].confidence == 0.0
    assert header["tax_amount"].value is None
    assert lines[0]["amount"].value == "10" and lines[0]["amount"].confidence == 0.0
    assert len(lines) == MAX_LINES - 1  # the first 50 rows, minus the one that is not an object


def test_demo_extracts_the_seeded_delivery_note() -> None:
    data = Path(DEMO_DELIVERY_NOTE).read_bytes()
    assert hashlib.sha256(data).hexdigest() in FIXTURES, "the fixture image and its hash must stay in step"
    result = DemoVisionProvider().extract(data, "image/png", None)
    assert result.kind == "delivery_note" and result.detected_kind == "delivery_note" and result.provider == "demo"
    assert result.header["document_number"].value == "DN-4471"
    assert result.header["vehicle_number"].confidence < 0.8
    assert [line["quantity"].value for line in result.lines] == ["40", "25", "3"]


def test_demo_never_invents_values_for_unknown_images() -> None:
    result = DemoVisionProvider().extract(b"\x89PNG unknown", "image/png", "purchase_order")
    assert result.kind == "purchase_order" and result.lines == ()
    assert all(v.value is None and v.confidence == 0 for v in result.header.values())


def test_demo_screen_answer_uses_only_reread_facts_and_hands_off_actions() -> None:
    facts = ScreenFacts("/sales/quotes/[quoteId]", "sales", ({"label": "LK-QT-2026-0008 · Nordhaus Interiors GmbH"},))
    answer = DemoVisionProvider().answer_screen(b"", "image/webp", "what is this?", facts)
    assert answer.needs_handoff is False and "LK-QT-2026-0008" in answer.text and "sales" in answer.text
    assert DemoVisionProvider().answer_screen(b"", "image/webp", "prepare a quote for Berg", facts).needs_handoff is True
    assert DemoVisionProvider().answer_screen(b"", "image/webp", "kitna stock hai", facts).needs_handoff is True
