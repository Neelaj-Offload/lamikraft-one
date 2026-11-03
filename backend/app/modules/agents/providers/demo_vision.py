"""The deterministic Demo vision adapter (``LK_AI_MODE=demo``): no key, no network, labelled "Demo".

Extraction answers from a fixture table keyed by the image's SHA-256: the seeded delivery-note image
(``app/modules/vision/fixtures/demo-delivery-note.png``) yields known fields, one of them deliberately uncertain so
the confirmation path is always exercised. Any other image yields every field empty with confidence 0 — all of them
confirmation fields — because the Demo adapter cannot read images and never invents values.

Screen answers are built only from the re-read screen facts (labels of visible records), never from the pixels or
the client's text; a question that needs data or an action is handed off to the orchestrator.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from app.modules.agents.providers.base import Stopwatch
from app.modules.vision.contract import (
    ExtractionKind,
    ScreenFacts,
    VisionAnswer,
    VisionExtraction,
    parse_extraction,
)

PROVIDER_NAME = "demo"
PROVIDER_LABEL = "Demo"
DEMO_MODEL = "demo-vision-v1"
FIXTURE_DIR = Path(__file__).resolve().parents[2] / "vision" / "fixtures"
DEMO_DELIVERY_NOTE = FIXTURE_DIR / "demo-delivery-note.png"


def _v(value: str | None, confidence: float) -> dict[str, object]:
    return {"value": value, "confidence": confidence}


#: sha256 -> (kind, provider-shaped result). The vehicle number is printed but deliberately uncertain (0.55).
FIXTURES: dict[str, tuple[ExtractionKind, dict[str, object]]] = {
    "4ae1770d8efdf2f1fde28177d043756ec86d1b5516e4c336f1afe8fb6e2544c8": (
        "delivery_note",
        {
            "header": {
                "document_number": _v("DN-4471", 0.97),
                "document_date": _v("08/10/2026", 0.93),
                "from_party": _v("Shree Timber Traders, Jodhpur", 0.95),
                "to_party": _v("Lamikraft Works, Jodhpur", 0.94),
                "vehicle_number": _v("RJ19 GB 4471", 0.55),
            },
            "lines": [
                {"description": _v("Oak board 18 mm 2440x1220", 0.92), "quantity": _v("40", 0.96), "uom": _v("sheet", 0.9)},
                {"description": _v("Ash board 12 mm 2440x1220", 0.91), "quantity": _v("25", 0.95), "uom": _v("sheet", 0.9)},
                {"description": _v("Walnut veneer roll", 0.88), "quantity": _v("3", 0.62), "uom": _v("roll", 0.86)},
            ],
        },
    ),
}

#: words that mean the question needs records the screenshot does not show, or an action
_HANDOFF = re.compile(
    r"\b(how many|how much|total|sum|price|cost|stock|create|draft|make|prepare|change|update|send|approve|cancel|"
    r"delete|issue|order|quote for|bana|karo|kitna|kitne)\b",
    re.IGNORECASE,
)


class DemoVisionProvider:
    name = PROVIDER_NAME
    label = PROVIDER_LABEL
    model = DEMO_MODEL

    def answer_screen(self, image: bytes, mime_type: str, question: str, facts: ScreenFacts) -> VisionAnswer:  # noqa: ARG002
        watch = Stopwatch()
        if _HANDOFF.search(question):
            return VisionAnswer(
                text="That needs records or an action, so the assistant will handle it.",
                needs_handoff=True, handoff_reason="data_or_action", confidence=1.0,
                provider=self.name, model=self.model, latency_ms=watch.elapsed_ms,
            )
        labels = [str(r.get("label")) for r in facts.records if r.get("label")][:3]
        where = f"the {facts.area} area" if facts.area else "this page"
        if labels:
            shown = "; ".join(labels)
            text = f"You are in {where}. The screen shows {shown}."
        else:
            text = f"You are in {where}. No records on it are shared with the assistant."
        return VisionAnswer(text=text, needs_handoff=False, handoff_reason=None, confidence=1.0,
                            provider=self.name, model=self.model, latency_ms=watch.elapsed_ms)

    def extract(self, image: bytes, mime_type: str, kind: ExtractionKind | None) -> VisionExtraction:  # noqa: ARG002
        watch = Stopwatch()
        digest = hashlib.sha256(image).hexdigest()
        fixture = FIXTURES.get(digest)
        if fixture is not None and (kind is None or kind == fixture[0]):
            fixture_kind, data = fixture
            header, lines = parse_extraction(fixture_kind, data)
            return VisionExtraction(kind=fixture_kind, header=header, lines=lines, provider=self.name, model=self.model,
                                    latency_ms=watch.elapsed_ms, detected_kind=fixture_kind if kind is None else None)
        chosen: ExtractionKind = kind or "delivery_note"
        header, lines = parse_extraction(chosen, {"header": {}, "lines": []})
        return VisionExtraction(kind=chosen, header=header, lines=lines, provider=self.name, model=self.model,
                                latency_ms=watch.elapsed_ms)


__all__ = ["DEMO_DELIVERY_NOTE", "DEMO_MODEL", "FIXTURES", "PROVIDER_LABEL", "PROVIDER_NAME", "DemoVisionProvider"]
