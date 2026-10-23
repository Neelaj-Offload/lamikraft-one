"""Document engine: fonts and shaping, formatting, page furniture, tables, drawings, determinism."""

from __future__ import annotations

import io
import re
from collections import Counter
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from pypdf import PdfReader
from reportlab.graphics.shapes import Drawing

from app.core.documents import (
    DEFAULT_SIGNATURES,
    CompanyIdentity,
    Markup,
    board_drawing,
    build_pdf,
    coverage_gaps,
    format_date,
    format_datetime,
    format_money,
    format_quantity,
    format_unit_price,
    line_table,
    para,
    register_fonts,
    script_markup,
    section_heading,
    signature_boxes,
    terms_block,
    totals_block,
)
from app.core.documents.fonts import DEVA, DEVA_BOLD, SANS
from app.core.documents.layout import style

GLYPHS = ("€", "₹", "£", "Ł", "Ω", "Ж")
LATIN_NAMES = ("Nordhaus Møbler ÅB", "Łódź", "Ελλάδα", "Москва")
DEVANAGARI_EXACT = ("क्राउन डेकोर", "नमस्ते", "श्रीमती")
COLUMNS = ("#", "Product", "Details", "Unit price", "Qty", "Total")
ROW_COUNT = 150


def _identity(**overrides: object) -> CompanyIdentity:
    values: dict[str, object] = {
        "legal_name": "Crown Décor Private Limited",
        "display_name": "Crown Decor",
        "address_lines": ("Bhiwandi, Maharashtra", "भिवंडी, महाराष्ट्र"),
        "gstin": "TEST-GSTIN-0001",
        "email": "sales@crowndecor.example",
        "footer_terms": "Test footer terms & conditions.",
    }
    values.update(overrides)
    return CompanyIdentity(**values)  # type: ignore[arg-type]


def _pages(pdf: bytes) -> list[str]:
    return [page.extract_text() or "" for page in PdfReader(io.BytesIO(pdf)).pages]


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _rows(count: int) -> list[list[str | Markup]]:
    rows: list[list[str | Markup]] = []
    for n in range(1, count + 1):
        price = Decimal(n) + Decimal("0.25")
        qty = Decimal(n % 40 + 1)
        rows.append(
            [
                str(n),
                f"ROW-{n:04d} decorative laminate with a deliberately long product name that must wrap",
                f"Decor D-{n:04d}\nsecond line of details",
                format_unit_price(price, "EUR"),
                format_quantity(qty, "pcs"),
                format_money(price * qty, "EUR"),
            ]
        )
    return rows


def _table_pdf(rows: list[list[str | Markup]], watermark: str | None = None) -> bytes:
    story = [
        *section_heading("Lines"),
        line_table(COLUMNS, rows, (5, 30, 25, 12, 11, 13), numeric_cols=(0, 3, 4, 5)),
        totals_block([("Net subtotal", "€1.00"), ("Grand total", "€1.00")]),
    ]
    return build_pdf(
        "Quotation",
        _identity(),
        [("Number", "TEST-0001"), ("Date", "12 Oct 2026")],
        story,
        watermark,
        reference="TEST-0001",
    )


@pytest.fixture(scope="module")
def long_table_pdf() -> bytes:
    return _table_pdf(_rows(ROW_COUNT))


# --------------------------------------------------------------------------- fonts and scripts


def test_register_fonts_is_idempotent() -> None:
    register_fonts()
    register_fonts()
    assert style("cell").fontName == SANS


def test_script_markup_escapes_and_routes_devanagari() -> None:
    markup = script_markup("A <b> & नमस्ते\nline two")
    assert "&lt;b&gt; &amp;" in markup
    assert f'<font face="{DEVA}">नमस्ते</font>' in markup
    assert markup.endswith("<br/>line two")
    assert f'<font face="{DEVA_BOLD}">' in script_markup("नमस्ते", bold=True)


def test_user_markup_is_printed_literally() -> None:
    pdf = build_pdf("Note", _identity(), [], [para("<b>not bold</b> & <i>co</i>")])
    assert "<b>not bold</b> & <i>co</i>" in _pages(pdf)[0]


def test_coverage_gaps_reports_scripts_without_a_font() -> None:
    assert coverage_gaps("Crown € ₹ नमस्ते Москва") == frozenset()
    assert coverage_gaps("தமிழ்") == frozenset("தமிழ்") - {" "}


def test_glyphs_names_and_devanagari_extract_with_embedded_fonts() -> None:
    story = [para(" ".join(GLYPHS)), para(", ".join(LATIN_NAMES)), *[para(s) for s in DEVANAGARI_EXACT]]
    pdf = build_pdf("Glyphs", _identity(legal_name="Crown Décor · क्राउन डेकोर"), [], story)
    text = "\n".join(_pages(pdf))
    for glyph in GLYPHS:
        assert glyph in text
    for name in LATIN_NAMES:
        assert name in text
    for sample in DEVANAGARI_EXACT:
        assert sample in text
    assert not [ch for ch in text if 0xE000 <= ord(ch) <= 0xF8FF], "private-use code points leaked"
    reader = PdfReader(io.BytesIO(pdf))
    fonts = {
        str(ref.get_object()["/BaseFont"]): "/FontFile2" in ref.get_object()["/FontDescriptor"].get_object()
        for ref in reader.pages[0]["/Resources"]["/Font"].values()
    }
    assert any("NotoSansDevanagari" in name for name in fonts)
    assert all(fonts.values()), f"every font must be embedded: {fonts}"


def test_devanagari_is_shaped_into_conjunct_glyphs() -> None:
    assert style("body", True).shaping == 1
    pdf = build_pdf("Shaping", _identity(), [], [para("क्राउन")])
    reader = PdfReader(io.BytesIO(pdf))
    cmaps = []
    for ref in reader.pages[0]["/Resources"]["/Font"].values():
        font = ref.get_object()
        if "NotoSansDevanagari" in str(font["/BaseFont"]):
            cmaps.append(font["/ToUnicode"].get_object().get_data().decode("latin-1"))
    # One glyph (the k_ra conjunct) maps back to the three characters क ् र.
    assert any("<0915094D0930>" in cmap for cmap in cmaps)


def test_mixed_script_word_keeps_both_fonts_intact() -> None:
    pdf = build_pdf("Mixed", _identity(), [], [para("Crown क्राउन-Decor ₹१२३")])
    assert _squash("Crown क्राउन-Decor ₹१२३") in _squash(_pages(pdf)[0])


def test_pre_base_matra_characters_are_all_recovered() -> None:
    pdf = build_pdf("Matra", _identity(), [], [para("हिन्दी")])
    line = next(ln for ln in _pages(pdf)[0].splitlines() if "न्द" in ln)
    # Extraction follows visual order (ि before ह); every character is still present.
    assert Counter(_squash(line)) == Counter("हिन्दी")


# --------------------------------------------------------------------------- formatting


@pytest.mark.parametrize(
    ("amount", "currency", "expected"),
    [
        (Decimal("5760"), "EUR", "€5,760.00"),
        (Decimal("123456"), "INR", "₹1,23,456.00"),
        (Decimal("12345678.905"), "INR", "₹1,23,45,678.91"),
        (Decimal("999"), "INR", "₹999.00"),
        (Decimal("1234.5"), "USD", "$1,234.50"),
        (Decimal("-12.345"), "GBP", "-£12.35"),
        (Decimal("-0.001"), "EUR", "€0.00"),
        (240, "EUR", "€240.00"),
    ],
)
def test_format_money(amount: Decimal | int, currency: str, expected: str) -> None:
    assert format_money(amount, currency) == expected


@pytest.mark.parametrize("bad", [5760.0, True, "5760"])
def test_format_money_rejects_non_decimal_input(bad: object) -> None:
    with pytest.raises(TypeError):
        format_money(bad, "EUR")  # type: ignore[arg-type]


def test_format_money_rejects_unknown_currency_and_nan() -> None:
    with pytest.raises(ValueError, match="currency"):
        format_money(Decimal(1), "JPY")
    with pytest.raises(ValueError):
        format_money(Decimal("NaN"), "EUR")


def test_format_unit_price_keeps_meaningful_decimals() -> None:
    assert format_unit_price(Decimal("24.0000"), "EUR") == "€24.00"
    assert format_unit_price(Decimal("0.0450"), "EUR") == "€0.045"
    assert format_unit_price(Decimal("123456.12345"), "INR") == "₹1,23,456.1235"
    with pytest.raises(TypeError):
        format_unit_price(24.0, "EUR")  # type: ignore[arg-type]


def test_format_quantity_trims_zeros() -> None:
    assert format_quantity(Decimal("240.000000"), "pcs") == "240 pcs"
    assert format_quantity(Decimal("12.500"), "sqm") == "12.5 sqm"
    assert format_quantity(Decimal("1200")) == "1,200"
    assert format_quantity(Decimal("0.12345"), "m") == "0.1235 m"
    assert format_quantity(Decimal("123456"), indian=True) == "1,23,456"
    with pytest.raises(TypeError):
        format_quantity(1.5, "pcs")  # type: ignore[arg-type]


def test_format_date_uses_the_company_zone() -> None:
    assert format_date(date(2026, 10, 12)) == "12 Oct 2026"
    late_utc = datetime(2026, 10, 11, 20, 0, tzinfo=UTC)
    assert format_date(late_utc, "Asia/Kolkata") == "12 Oct 2026"
    assert format_datetime(late_utc, "Asia/Kolkata") == "12 Oct 2026, 01:30"
    with pytest.raises(ValueError):
        format_date(datetime(2026, 10, 12, 9, 0))
    with pytest.raises(ValueError):
        format_date(late_utc)


# --------------------------------------------------------------------------- pages and tables


def test_long_table_spans_pages_with_one_header_per_page(long_table_pdf: bytes) -> None:
    pages = _pages(long_table_pdf)
    total = len(pages)
    assert total > 1
    for number, text in enumerate(pages, start=1):
        assert f"Page {number} of {total}" in text
        assert text.count("Unit price") == 1, f"header row missing or duplicated on page {number}"
        assert "Crown Decor" in text and "TEST-0001" in text
    everything = "\n".join(pages)
    assert all(f"ROW-{n:04d}" in everything for n in range(1, ROW_COUNT + 1))
    assert "Page 1 of" in pages[0]


def test_tall_cell_is_split_across_pages_without_loss() -> None:
    tokens = [f"tok{n:04d}" for n in range(1, 451)]
    rows: list[list[str | Markup]] = [["1", "Tall row", " ".join(tokens), "€1.00", "1 pcs", "€1.00"]]
    pages = _pages(_table_pdf(rows))
    assert len(pages) > 1
    found = re.findall(r"tok\d{4}", "\n".join(pages))
    assert found == tokens


def test_line_table_validates_shape() -> None:
    with pytest.raises(ValueError, match="row 1"):
        line_table(("A", "B"), [["only one"]], (1, 1))
    with pytest.raises(ValueError, match="column widths"):
        line_table(("A", "B"), [], (1,))
    with pytest.raises(ValueError, match="out of range"):
        line_table(("A", "B"), [], (1, 1), numeric_cols=(2,))


def test_output_is_deterministic(long_table_pdf: bytes) -> None:
    assert _table_pdf(_rows(ROW_COUNT)) == long_table_pdf
    assert _table_pdf(_rows(ROW_COUNT), watermark="DRAFT") != long_table_pdf


_DETERMINISM_SCRIPT = """
import hashlib, sys
from app.core.documents import CompanyIdentity, build_pdf, para
identity = CompanyIdentity(legal_name="Crown Décor · क्राउन डेकोर", display_name="Crown Decor")
if "--warm" in sys.argv:
    build_pdf("Warm-up", identity, [], [para("ज्ञान त्रिकोण क्षमा ट्रक कृष्ण द्वार हिन्दी")])
pdf = build_pdf("Quotation", identity, [("Number", "Q-1")], [para("श्रीमती प्रिया शर्मा, नमस्ते, क्राउन")])
print(hashlib.sha256(pdf).hexdigest())
"""


def test_shaped_output_does_not_depend_on_render_history() -> None:
    """Private glyph numbering depends on what a process shaped first; the bytes must not."""
    import subprocess
    import sys

    from app.core.config import BACKEND_DIR

    digests = {
        subprocess.run(
            [sys.executable, "-c", _DETERMINISM_SCRIPT, *flags],
            cwd=BACKEND_DIR,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        for flags in ([], ["--warm"])
    }
    assert len(digests) == 1, digests


def test_watermark_is_printed_on_every_page_and_validated() -> None:
    pages = _pages(_table_pdf(_rows(40), watermark="DRAFT"))
    assert len(pages) > 1
    assert all("DRAFT" in text for text in pages)
    with pytest.raises(ValueError):
        build_pdf("X", _identity(), [], [para("x")], watermark="   ")
    with pytest.raises(ValueError):
        build_pdf("X", _identity(), [], [para("x")], watermark="मसौदा")


def test_signatures_terms_and_totals_render() -> None:
    story = [
        totals_block([("Net subtotal", "€4,800.00"), ("Surcharge", "€400.00"), ("Grand total", "€5,200.00")]),
        terms_block(["Prices exclude taxes.", "  ", "Valid for 30 days."]),
        signature_boxes(),
    ]
    text = _pages(build_pdf("Delivery challan", _identity(), [("Number", "DC-2026-0001")], story))[0]
    for label in (*DEFAULT_SIGNATURES, "Grand total", "€5,200.00", "1.", "2.", "Valid for 30 days."):
        assert label in text
    assert "3." not in text


def test_identity_validation() -> None:
    with pytest.raises(ValueError):
        _identity(legal_name="  ")
    with pytest.raises(ValueError, match="PNG"):
        _identity(logo_png=b"GIF89a")


def test_logo_is_embedded() -> None:
    from app.core.documents.spike import demo_logo_png

    pdf = build_pdf("Logo", _identity(logo_png=demo_logo_png()), [], [para("x")])
    page = PdfReader(io.BytesIO(pdf)).pages[0]
    assert page["/Resources"]["/XObject"]


def test_build_pdf_rejects_empty_story() -> None:
    with pytest.raises(ValueError, match="story"):
        build_pdf("X", _identity(), [], [])


# --------------------------------------------------------------------------- drawings

SAMPLE_PLACEMENTS = [
    {"x": 5, "y": 5, "w": 800, "h": 600, "label": "A1"},
    {"x": 811, "y": 5, "w": 300, "h": 450, "label": "B1", "rotated": True},
    {"x": 1117, "y": 5, "w": 120, "h": 80, "label": "tiny piece label that cannot fit", "kind": "extra"},
    {"x": Decimal("1800.5"), "y": 611, "w": 600, "h": 604, "label": "Offcut", "kind": "offcut"},
]


def test_board_drawing_builds_at_true_proportion() -> None:
    drawing = board_drawing(2440, 1220, SAMPLE_PLACEMENTS, 480, margin_mm=5)
    assert isinstance(drawing, Drawing)
    assert drawing.width == pytest.approx(480)
    board_height = drawing.height - 14.0
    assert board_height == pytest.approx(480 * 1220 / 2440)
    capped = board_drawing(2440, 1220, SAMPLE_PLACEMENTS, 480, max_height_pt=150)
    assert capped.height <= 150 + 1e-6
    pdf = build_pdf("Cut plan", _identity(), [("Plan", "CUT-2026-0001")], [drawing])
    text = _pages(pdf)[0]
    assert "A1" in text and "B1" in text and "2440 × 1220 mm" in text


def test_board_drawing_rejects_bad_geometry() -> None:
    with pytest.raises(ValueError, match="outside"):
        board_drawing(2440, 1220, [{"x": 2400, "y": 0, "w": 100, "h": 100, "label": "X"}], 400)
    with pytest.raises(ValueError, match="kind"):
        board_drawing(2440, 1220, [{"x": 0, "y": 0, "w": 10, "h": 10, "label": "X", "kind": "scrap"}], 400)
    with pytest.raises(ValueError, match="positive"):
        board_drawing(2440, 1220, [{"x": 0, "y": 0, "w": 0, "h": 10, "label": "X"}], 400)
    with pytest.raises(TypeError):
        board_drawing(2440, 1220, [{"x": "0", "y": 0, "w": 10, "h": 10, "label": "X"}], 400)
    with pytest.raises(ValueError, match="margin"):
        board_drawing(100, 100, [], 400, margin_mm=50)
