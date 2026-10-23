"""Slice-0 spike for the document engine: renders a demanding sample PDF and checks it.

Run from ``backend/``::

    uv run python -m app.core.documents.spike            # writes docs/evidence/slice-0/pdf-spike.pdf
    uv run python -m app.core.documents.spike --out x.pdf

It exercises a Unicode legal name, € ₹ £ Ł Ω Ж, shaped Devanagari, a 150-row line table with long
wrapping descriptions spanning many pages, totals, terms, signature boxes and a cut-plan board.
All data is demo data and the document is watermarked DEMO. The verification pass (needs the dev
dependency ``pypdf``) prints a JSON report used by ``docs/evidence/slice-0/pdf-spike.md``.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sys
import time
from collections import Counter
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from reportlab.platypus import Flowable, PageBreak, Spacer

from app.core.documents import (
    CONTENT_WIDTH,
    DEFAULT_SIGNATURES,
    CompanyIdentity,
    Markup,
    address_columns,
    board_drawing,
    bold,
    build_pdf,
    format_date,
    format_money,
    format_quantity,
    format_unit_price,
    join_markup,
    line_table,
    para,
    plain,
    section_heading,
    signature_boxes,
    terms_block,
    totals_block,
)
from app.core.documents.fonts import FONT_DIR
from app.core.documents.layout import MARGIN_LEFT
from app.core.money import quantize_money

REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_OUT = REPO_ROOT / "docs" / "evidence" / "slice-0" / "pdf-spike.pdf"

DOCUMENT_NUMBER = "SPIKE-0001"
LINE_COUNT = 150
LONG_DESCRIPTION_ROWS = (40, 95)
GLYPH_LINE = "€ ₹ £ Ł Ω Ж"
LATIN_NAMES = ("Nordhaus Møbler ÅB", "Łódź", "Ελλάδα", "Москва")
DEVANAGARI_SAMPLES = ("क्राउन डेकोर", "नमस्ते", "श्रीमती प्रिया शर्मा", "हिन्दी", "द्वार कृष्ण ट्रक क्षमा त्रिकोण ज्ञान")
MIXED_SAMPLE = "Crown क्राउन-Decor, ₹१,२३,४५६"
BOLD_SAMPLE = "प्राइवेट ट्रक"
TABLE_COLUMNS = ("#", "Product", "Details", "Unit price", "Qty", "Total")
TABLE_WEIGHTS = (5, 30, 25, 12, 11, 13)

_DECORS = ("Oak", "Walnut", "Teak", "Ash", "Maple", "Cherry", "Wenge", "Birch", "Elm", "Sapele")
_FINISHES = (
    "Natural Matt",
    "Super Gloss",
    "Suede Touch",
    "Brushed Linen",
    "Hi-Gloss Acrylic",
    "Rustic Grain",
)
_ITEMS = (
    "serving tray",
    "laminate sheet 1.0 mm",
    "post-forming sheet",
    "compact panel",
    "edge band roll",
    "door skin",
)


def demo_logo_png() -> bytes:
    """A generated monogram so the logo path is exercised without shipping a brand asset."""
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (240, 240), (33, 76, 60))
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(str(FONT_DIR / "NotoSans-Bold.ttf"), 112)
    draw.text((120, 122), "CD", font=font, fill=(237, 242, 234), anchor="mm")
    out = io.BytesIO()
    image.save(out, format="PNG", optimize=False)
    return out.getvalue()


def demo_identity() -> CompanyIdentity:
    return CompanyIdentity(
        legal_name="Crown Décor Private Limited · क्राउन डेकोर प्राइवेट लिमिटेड",
        display_name="Crown Decor Pvt. Ltd. (Demo)",
        address_lines=("Bhiwandi, Maharashtra, India", "भिवंडी, महाराष्ट्र"),
        gstin="not configured (demo)",
        email="sales@crowndecor.example",
        website="crowndecor.example",
        logo_png=demo_logo_png(),
        footer_terms="Demo document from the Lamikraft One PDF spike. Prices exclude taxes & duties. E&OE.",
    )


def _long_description(row: int) -> str:
    sentence = (
        f"Row {row} long specification: decorative high-pressure laminate with balanced core, "
        "anti-fingerprint surface, FSC-certified kraft layers, edge-matched grain for continuous "
        "runs, packed flat on pallets with corner protectors and moisture barrier film. "
    )
    text = (sentence * 20)[:2980]
    return f"{text} END-OF-ROW-{row}."


def demo_lines() -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = [
        {
            "sku": "LK-OT-0450",
            "name": "Oak tray, natural matt",
            "details": "Carton of 24 · price list EXP-EUR-2026",
            "price": Decimal("24.0000"),
            "qty": Decimal("240"),
            "uom": "pcs",
        }
    ]
    for row in range(2, LINE_COUNT + 1):
        decor = _DECORS[row % len(_DECORS)]
        finish = _FINISHES[row % len(_FINISHES)]
        item = _ITEMS[row % len(_ITEMS)]
        name = f"{decor} {item}, {finish} finish with matching edge band and protective film"
        if row % 7 == 0:
            name += f"\nGrain direction along length; batch reserve {row:03d}"
        details = (
            _long_description(row) if row in LONG_DESCRIPTION_ROWS else f"Decor {decor[:3].upper()}-{row:04d}"
        )
        price = Decimal(f"{(row * 37) % 900 + 12}.{(row * 13) % 100:02d}") / Decimal(10)
        qty = Decimal((row * 11) % 180 + 6) if row % 9 else Decimal("12.5")
        lines.append(
            {
                "sku": f"SPK-{row:04d}",
                "name": name,
                "details": details,
                "price": price,
                "qty": qty,
                "uom": "sqm" if row % 9 == 0 else "pcs",
            }
        )
    return lines


def demo_placements() -> list[dict[str, Any]]:
    placements: list[dict[str, Any]] = []
    for i, x in enumerate((5, 811, 1617)):
        placements.append({"x": x, "y": 5, "w": 800, "h": 600, "label": f"A{i + 1} 800×600", "kind": "piece"})
    for i, x in enumerate((5, 311, 617, 923)):
        placements.append({"x": x, "y": 611, "w": 300, "h": 450, "label": f"B{i + 1}", "rotated": True})
    placements.append({"x": 1229, "y": 611, "w": 600, "h": 300, "label": "C1 extra", "kind": "extra"})
    placements.append({"x": 1229, "y": 917, "w": 120, "h": 80, "label": "D1"})
    placements.append({"x": 1835, "y": 611, "w": 600, "h": 604, "label": "Offcut 600×604", "kind": "offcut"})
    return placements


def build_spike_pdf() -> bytes:
    identity = demo_identity()
    lines = demo_lines()
    rows: list[list[str | Markup]] = []
    subtotal = Decimal(0)
    for no, line in enumerate(lines, start=1):
        total = quantize_money(line["price"] * line["qty"], "EUR")
        subtotal += total
        rows.append(
            [
                str(no),
                join_markup([bold(line["sku"]), line["name"]]),
                line["details"],
                format_unit_price(line["price"], "EUR"),
                format_quantity(line["qty"], line["uom"]),
                format_money(total, "EUR"),
            ]
        )
    surcharge_base = Decimal("4800.00")
    surcharge = Decimal("400.00")

    story: list[Flowable] = [
        address_columns(
            [
                ("Bill to", ["Nordhaus Interiors GmbH", "Hamburg, Germany"]),
                ("Ship to", [LATIN_NAMES[0], " · ".join(LATIN_NAMES[1:])]),
            ]
        ),
        *section_heading("Unicode coverage"),
        para(f"Currency and extended glyphs: {GLYPH_LINE}"),
        para("Names: " + ", ".join(LATIN_NAMES)),
        para(
            "Indian digit grouping: "
            f"{format_money(Decimal('123456'), 'INR')}  ·  {format_money(Decimal('12345678.9'), 'INR')}"
        ),
        *section_heading("Devanagari (HarfBuzz shaping)"),
        *[para(sample) for sample in DEVANAGARI_SAMPLES],
        para(f"Mixed script in one word: {MIXED_SAMPLE}"),
        para(join_markup([plain("Bold Devanagari:"), bold(BOLD_SAMPLE)], separator=" ")),
        Spacer(1, 4),
        *section_heading(f"Line items ({LINE_COUNT})"),
        line_table(TABLE_COLUMNS, rows, TABLE_WEIGHTS, numeric_cols=(0, 3, 4, 5)),
        totals_block(
            [("Net subtotal", format_money(subtotal, "EUR")), ("Grand total", format_money(subtotal, "EUR"))]
        ),
        *section_heading("Surcharge rule example (EUR, toggle on, subtotal below 5,000)"),
        totals_block(
            [
                ("Net subtotal", format_money(surcharge_base, "EUR")),
                ("Small-order surcharge", format_money(surcharge, "EUR")),
                ("Grand total", format_money(surcharge_base + surcharge, "EUR")),
            ]
        ),
        terms_block(
            [
                "Prices are in EUR, ex-works Bhiwandi, and exclude taxes & duties.",
                "Quotation valid for 30 days from the date of issue.",
                "Colour shades may vary between production batches; approve samples before bulk orders.",
            ]
        ),
        signature_boxes(DEFAULT_SIGNATURES),
        PageBreak(),
        *section_heading("Cut plan board 1 of 1 (2440 × 1220 mm)"),
        board_drawing(2440, 1220, demo_placements(), CONTENT_WIDTH, margin_mm=5),
    ]
    return build_pdf(
        "Quotation",
        identity,
        [
            ("Number", DOCUMENT_NUMBER),
            ("Date", format_date(date(2026, 10, 12))),
            ("Customer", "Nordhaus Interiors GmbH"),
            ("Currency", "EUR"),
        ],
        story,
        watermark="DEMO",
        reference=DOCUMENT_NUMBER,
        subject="PDF engine spike",
    )


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _column_text(reader: Any, column: int) -> str:
    """Text drawn inside one line-table column on every page, in drawing order."""
    total = sum(TABLE_WEIGHTS)
    x0 = MARGIN_LEFT + CONTENT_WIDTH * sum(TABLE_WEIGHTS[:column]) / total
    x1 = x0 + CONTENT_WIDTH * TABLE_WEIGHTS[column] / total
    parts: list[str] = []

    def visit(text: str, cm: Any, tm: Any, _font: Any, _size: Any) -> None:
        x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
        if x0 - 1 <= x < x1:
            parts.append(text)

    for page in reader.pages:
        page.extract_text(visitor_text=visit)
    return "".join(parts)


def verify(pdf: bytes) -> dict[str, Any]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(pdf))
    pages = [page.extract_text() or "" for page in reader.pages]
    total = len(pages)
    everything = "\n".join(pages)
    table_pages = [i for i, text in enumerate(pages, start=1) if re.search(r"SPK-\d{4}|LK-OT-0450", text)]
    header_on_table_pages = all(all(col in pages[i - 1] for col in TABLE_COLUMNS[1:]) for i in table_pages)
    # A row split across pages is interleaved with the overlay watermark and the repeated header.
    details = _squash(_column_text(reader, 2)).replace("DEMO", "").replace(TABLE_COLUMNS[2], "")
    fonts: dict[str, bool] = {}
    for page in reader.pages:
        for ref in page["/Resources"]["/Font"].values():
            font = ref.get_object()
            descriptor = font.get("/FontDescriptor")
            embedded = bool(descriptor and "/FontFile2" in descriptor.get_object())
            fonts[str(font["/BaseFont"])] = embedded
    first_page_lines = [line.strip() for line in pages[0].splitlines()]
    devanagari: dict[str, dict[str, Any]] = {}
    for sample in DEVANAGARI_SAMPLES:
        wanted = Counter(_squash(sample))
        line = next((ln for ln in first_page_lines if Counter(_squash(ln)) == wanted), None)
        devanagari[sample] = {
            "exact": sample in everything,
            "all_characters_recovered": line is not None,
            "extracted": line,
        }
    lines = demo_lines()
    return {
        "bytes": len(pdf),
        "sha256": hashlib.sha256(pdf).hexdigest(),
        "pages": total,
        "page_x_of_y_on_every_page": all(
            f"Page {i} of {total}" in text for i, text in enumerate(pages, start=1)
        ),
        "table_pages": [table_pages[0], table_pages[-1]] if table_pages else [],
        "header_row_on_every_table_page": header_on_table_pages,
        "all_skus_present": all(line["sku"] in everything for line in lines),
        "long_descriptions_complete": all(
            _squash(_long_description(row)) in details for row in LONG_DESCRIPTION_ROWS
        ),
        "glyphs_present": {g: g in everything for g in GLYPH_LINE.split()},
        "latin_names_present": {n: n in everything for n in LATIN_NAMES},
        "devanagari": devanagari,
        "private_use_characters_in_text": sorted(
            {f"U+{ord(ch):04X}" for ch in everything if 0xE000 <= ord(ch) <= 0xF8FF}
        ),
        "mixed_word_extracted_ignoring_spaces": _squash(MIXED_SAMPLE) in _squash(everything),
        "bold_devanagari_extracted": BOLD_SAMPLE in everything,
        "inr_grouping_present": "₹1,23,456.00" in everything and "₹1,23,45,678.90" in everything,
        "watermark_on_every_page": all("DEMO" in text for text in pages),
        "fonts_embedded": fonts,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--no-verify", action="store_true")
    args = parser.parse_args(argv)

    started = time.perf_counter()
    pdf = build_spike_pdf()
    first_build = time.perf_counter() - started
    started = time.perf_counter()
    again = build_spike_pdf()
    second_build = time.perf_counter() - started

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(pdf)
    report: dict[str, Any] = {
        "output": str(args.out),
        "first_build_seconds": round(first_build, 3),
        "second_build_seconds": round(second_build, 3),
        "deterministic": pdf == again,
    }
    if not args.no_verify:
        report.update(verify(pdf))
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))  # noqa: T201 - CLI output
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
