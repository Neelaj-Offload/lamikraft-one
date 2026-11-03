"""The vision provider contract (ai-routing.md sections 2, 3 and 5.2): request/result types shared by the Gemini
adapter (``agents/providers/gemini_vision.py``) and the Demo adapter (``agents/providers/demo_vision.py``), and the
JSON response schema per extraction kind.

Every extracted value is a **string or null with its own confidence** (0..1). The adapters never compute money,
never fill a missing field and never write records: the vision service turns the result into an ``ExtractionCard``
whose uncertain or missing fields are confirmation fields (empty until the person confirms them). The output is
untrusted data (``provenance=external``); a run that consumes it is tainted.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

ExtractionKind = Literal["purchase_order", "bill", "delivery_note", "handwritten_list"]
EXTRACTION_KINDS: tuple[ExtractionKind, ...] = ("purchase_order", "bill", "delivery_note", "handwritten_list")

#: section 5.2 timeouts (seconds) and section 2 output caps
SCREEN_TIMEOUT_SECONDS = 8
EXTRACTION_TIMEOUT_SECONDS = 20
SCREEN_MAX_OUTPUT_TOKENS = 512
EXTRACTION_MAX_OUTPUT_TOKENS = 2_048
#: below this a value is a confirmation field (never a default)
CONFIDENCE_THRESHOLD = 0.8
UNAVAILABLE_MESSAGE = "Vision unavailable — enter details"


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    #: presentation hint only; values stay strings (money and quantities are never parsed by the model)
    type: Literal["text", "date", "number", "money", "currency"] = "text"


HEADER_FIELDS: dict[ExtractionKind, tuple[FieldSpec, ...]] = {
    "purchase_order": (
        FieldSpec("document_number", "PO number"),
        FieldSpec("document_date", "PO date", "date"),
        FieldSpec("buyer_name", "Buyer"),
        FieldSpec("supplier_name", "Supplier"),
        FieldSpec("currency", "Currency", "currency"),
        FieldSpec("delivery_date", "Delivery date", "date"),
        FieldSpec("total_amount", "Total (as printed)", "money"),
    ),
    "bill": (
        FieldSpec("document_number", "Bill number"),
        FieldSpec("document_date", "Bill date", "date"),
        FieldSpec("vendor_name", "Vendor"),
        FieldSpec("vendor_gstin", "Vendor GSTIN"),
        FieldSpec("currency", "Currency", "currency"),
        FieldSpec("tax_amount", "Tax (as printed)", "money"),
        FieldSpec("total_amount", "Total (as printed)", "money"),
    ),
    "delivery_note": (
        FieldSpec("document_number", "Delivery note number"),
        FieldSpec("document_date", "Date", "date"),
        FieldSpec("from_party", "From"),
        FieldSpec("to_party", "To"),
        FieldSpec("vehicle_number", "Vehicle number"),
    ),
    "handwritten_list": (
        FieldSpec("title", "Title"),
        FieldSpec("party_name", "Customer or supplier named"),
    ),
}

LINE_FIELDS: dict[ExtractionKind, tuple[FieldSpec, ...]] = {
    "purchase_order": (
        FieldSpec("description", "Item"),
        FieldSpec("quantity", "Quantity", "number"),
        FieldSpec("uom", "Unit"),
        FieldSpec("unit_price", "Unit price (as printed)", "money"),
    ),
    "bill": (
        FieldSpec("description", "Item"),
        FieldSpec("quantity", "Quantity", "number"),
        FieldSpec("uom", "Unit"),
        FieldSpec("amount", "Amount (as printed)", "money"),
    ),
    "delivery_note": (
        FieldSpec("description", "Item"),
        FieldSpec("quantity", "Quantity", "number"),
        FieldSpec("uom", "Unit"),
    ),
    "handwritten_list": (
        FieldSpec("description", "Item"),
        FieldSpec("quantity", "Quantity", "number"),
        FieldSpec("uom", "Unit"),
    ),
}
MAX_LINES = 50


@dataclass(frozen=True)
class ExtractedValue:
    value: str | None
    confidence: float


@dataclass(frozen=True)
class VisionExtraction:
    kind: ExtractionKind
    header: Mapping[str, ExtractedValue]
    lines: tuple[Mapping[str, ExtractedValue], ...]
    provider: str
    model: str
    latency_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    request_id: str | None = None
    #: the kind the provider recognised when the caller let it choose (``None`` = as requested)
    detected_kind: ExtractionKind | None = None


@dataclass(frozen=True)
class VisionAnswer:
    """An instant answer about the masked screenshot; ``needs_handoff`` sends the question on to Claude."""

    text: str
    needs_handoff: bool
    handoff_reason: str | None
    confidence: float
    provider: str
    model: str
    latency_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    request_id: str | None = None


@dataclass(frozen=True)
class ScreenFacts:
    """The re-read screen context the answer may use (labels and paths of visible records, never client text)."""

    route_path: str | None
    area: str | None
    records: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)


class VisionUnavailable(Exception):
    """The provider could not answer (timeout, outage, quota, refusal, unparseable output, missing key)."""

    def __init__(self, message: str = UNAVAILABLE_MESSAGE, *, code: str = "vision_unavailable",
                 request_id: str | None = None, latency_ms: int = 0) -> None:
        super().__init__(message)
        self.code = code
        self.request_id = request_id
        self.latency_ms = latency_ms


class VisionProvider(Protocol):
    name: str
    label: str
    model: str

    def answer_screen(self, image: bytes, mime_type: str, question: str, facts: ScreenFacts) -> VisionAnswer: ...

    def extract(self, image: bytes, mime_type: str, kind: ExtractionKind | None) -> VisionExtraction: ...


# ---- JSON response schemas (Gemini structured output; supported keywords only) -------------------------------
def _value_schema(description: str) -> dict[str, Any]:
    return {
        "type": "object",
        "description": description,
        "properties": {
            "value": {"type": ["string", "null"], "description": "exactly as printed or written; null if not legible"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
        "required": ["value", "confidence"],
    }


def extraction_schema(kind: ExtractionKind) -> dict[str, Any]:
    header = {f.key: _value_schema(f.label) for f in HEADER_FIELDS[kind]}
    line = {f.key: _value_schema(f.label) for f in LINE_FIELDS[kind]}
    return {
        "type": "object",
        "properties": {
            "header": {"type": "object", "properties": header, "required": list(header)},
            "lines": {
                "type": "array",
                "maxItems": MAX_LINES,
                "items": {"type": "object", "properties": line, "required": list(line)},
            },
        },
        "required": ["header", "lines"],
    }


CLASSIFY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"kind": {"type": "string", "enum": list(EXTRACTION_KINDS)}},
    "required": ["kind"],
}

SCREEN_ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "answer": {"type": "string", "description": "at most two sentences about what is visible"},
        "needs_data_or_action": {
            "type": "boolean",
            "description": "true when answering needs data not on the screenshot or an action (create, change, send)",
        },
        "reason": {"type": ["string", "null"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["answer", "needs_data_or_action", "confidence"],
}


def _clamp(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if number != number else max(0.0, min(1.0, number))  # NaN -> 0


def _value(raw: Any) -> ExtractedValue:
    if not isinstance(raw, Mapping):
        return ExtractedValue(None, 0.0)
    value = raw.get("value")
    text = str(value).strip()[:500] if value is not None else None
    return ExtractedValue(text or None, _clamp(raw.get("confidence")) if text else 0.0)


def parse_extraction(kind: ExtractionKind, data: Mapping[str, Any]) -> tuple[dict[str, ExtractedValue], tuple[dict[str, ExtractedValue], ...]]:
    """Validate a provider result against the kind's fields: unknown keys dropped, missing ones become null/0."""
    raw_header = data.get("header") if isinstance(data.get("header"), Mapping) else {}
    header = {f.key: _value(raw_header.get(f.key)) for f in HEADER_FIELDS[kind]}
    raw_lines = data.get("lines") if isinstance(data.get("lines"), list) else []
    lines = tuple(
        {f.key: _value(row.get(f.key)) for f in LINE_FIELDS[kind]}
        for row in raw_lines[:MAX_LINES]
        if isinstance(row, Mapping)
    )
    return header, lines


__all__ = [
    "CLASSIFY_SCHEMA",
    "CONFIDENCE_THRESHOLD",
    "EXTRACTION_KINDS",
    "EXTRACTION_MAX_OUTPUT_TOKENS",
    "EXTRACTION_TIMEOUT_SECONDS",
    "HEADER_FIELDS",
    "LINE_FIELDS",
    "SCREEN_ANSWER_SCHEMA",
    "SCREEN_MAX_OUTPUT_TOKENS",
    "SCREEN_TIMEOUT_SECONDS",
    "UNAVAILABLE_MESSAGE",
    "ExtractedValue",
    "ExtractionKind",
    "FieldSpec",
    "ScreenFacts",
    "VisionAnswer",
    "VisionExtraction",
    "VisionProvider",
    "VisionUnavailable",
    "extraction_schema",
    "parse_extraction",
]
