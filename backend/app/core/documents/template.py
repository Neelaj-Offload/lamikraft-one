"""The A4 document frame shared by quotes, challans, cut plans, invoices and packing lists.

Every page carries the same header band (logo, company identity, document title and its
label/value block), a footer with the company's footer terms and "Page X of Y", and optionally a
diagonal watermark ("DRAFT", "DEMO"). Page totals come from a deferred-drawing canvas: pages are
kept until the document is complete and numbered on save, so no second layout pass is needed.

Output is byte-for-byte deterministic for identical inputs (ReportLab invariant mode: fixed file
ID and timestamps), which lets tests and the issued-revision sha256 compare documents.
"""

from __future__ import annotations

import io
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from functools import partial
from typing import Any

from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import BaseDocTemplate, Flowable, Frame, Image, PageTemplate, Table, TableStyle

from app.core.documents.fonts import (
    RENDER_LOCK,
    SANS,
    SANS_BOLD,
    coverage_gaps,
    needs_shaping,
    register_fonts,
)
from app.core.documents.layout import (
    BAND_GAP,
    BORDER,
    CONTENT_WIDTH,
    FOREST,
    MARGIN_BOTTOM,
    MARGIN_LEFT,
    MARGIN_RIGHT,
    MARGIN_TOP,
    PAGE_HEIGHT,
    PAGE_WIDTH,
    base_table_style,
    para,
)

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_LOGO_MAX_WIDTH = 38 * mm
_LOGO_MAX_HEIGHT = 16 * mm
_META_COLUMN_WIDTH = 74 * mm
_FOOTER_TERMS_WIDTH = CONTENT_WIDTH * 0.68
_WATERMARK_MAX_CHARS = 40


@dataclass(frozen=True, slots=True)
class CompanyIdentity:
    """The issuing company as printed on documents (from company settings, never hard-coded)."""

    legal_name: str
    display_name: str
    address_lines: tuple[str, ...] = ()
    gstin: str | None = None
    phone: str | None = None
    email: str | None = None
    website: str | None = None
    logo_png: bytes | None = field(default=None, repr=False)
    footer_terms: str | None = None
    #: Further statutory identifiers printed beside the GSTIN, e.g. (("IEC", "0512345678"),).
    registrations: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not self.legal_name.strip():
            raise ValueError("legal_name is required")
        if not self.display_name.strip():
            raise ValueError("display_name is required")
        object.__setattr__(self, "address_lines", tuple(self.address_lines))
        object.__setattr__(self, "registrations", tuple(tuple(r) for r in self.registrations))
        if self.logo_png is not None and not self.logo_png.startswith(_PNG_SIGNATURE):
            raise ValueError("logo_png must be PNG data")


def _logo(png: bytes) -> Image:
    reader = ImageReader(io.BytesIO(png))
    px_w, px_h = reader.getSize()
    if px_w <= 0 or px_h <= 0:
        raise ValueError("logo has no pixels")
    scale = min(_LOGO_MAX_WIDTH / px_w, _LOGO_MAX_HEIGHT / px_h)
    image = Image(io.BytesIO(png), width=px_w * scale, height=px_h * scale)
    image.hAlign = "LEFT"
    return image


def _identity_block(identity: CompanyIdentity) -> list[Flowable]:
    block: list[Flowable] = [para(identity.display_name, "identity_name")]
    if identity.legal_name.strip() != identity.display_name.strip():
        block.append(para(identity.legal_name, "identity_line"))
    block.extend(para(line, "identity_line") for line in identity.address_lines if line.strip())
    contacts = [c for c in (identity.phone, identity.email, identity.website) if c and c.strip()]
    if contacts:
        block.append(para("  ·  ".join(contacts), "identity_line"))
    ids = ([("GSTIN", identity.gstin)] if identity.gstin else []) + list(identity.registrations)
    if ids:
        block.append(para("  ·  ".join(f"{label} {value}" for label, value in ids), "identity_line"))
    return block


def _meta_block(title: str, meta: Sequence[tuple[str, str]]) -> list[Flowable]:
    block: list[Flowable] = [para(title, "doc_title")]
    if meta:
        rows = [[para(label, "meta_label"), para(value, "meta_value")] for label, value in meta]
        table = Table(rows, colWidths=[_META_COLUMN_WIDTH * 0.42, _META_COLUMN_WIDTH * 0.58], hAlign="RIGHT")
        table.setStyle(
            TableStyle(
                base_table_style()
                + [
                    ("RIGHTPADDING", (0, 0), (0, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 1),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                ]
            )
        )
        block.append(table)
    return block


def _header(title: str, identity: CompanyIdentity, meta: Sequence[tuple[str, str]]) -> Table:
    left: Any = _identity_block(identity)
    left_width = CONTENT_WIDTH - _META_COLUMN_WIDTH
    if identity.logo_png is not None:
        logo = _logo(identity.logo_png)
        inner = Table([[logo, left]], colWidths=[logo.drawWidth + 4 * mm, None], hAlign="LEFT")
        inner.setStyle(TableStyle(base_table_style()))
        left = inner
    header = Table([[left, _meta_block(title, meta)]], colWidths=[left_width, _META_COLUMN_WIDTH])
    header.setStyle(TableStyle(base_table_style() + [("RIGHTPADDING", (0, 0), (0, 0), 4 * mm)]))
    return header


class _NumberedCanvas(Canvas):
    """Defers every page until save so each footer can say "Page X of Y"."""

    def __init__(self, *args: Any, overlay_painter: Callable[[Canvas, int, int], None], **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._lk_pages: list[dict[str, Any]] = []
        self._lk_paint_overlay = overlay_painter

    def showPage(self) -> None:  # noqa: N802 - ReportLab API name
        self._lk_pages.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        total = len(self._lk_pages)
        for state in self._lk_pages:
            self.__dict__.update(state)
            self._lk_paint_overlay(self, self._pageNumber, total)
            super().showPage()
        super().save()


@dataclass(slots=True)
class _Furniture:
    """What every page draws around the frame."""

    header: Table
    header_height: float
    footer_terms: Flowable | None
    footer_height: float
    reference: str | None
    watermark: str | None

    @property
    def header_bottom(self) -> float:
        return PAGE_HEIGHT - MARGIN_TOP - self.header_height - 2 * mm

    @property
    def footer_top(self) -> float:
        return MARGIN_BOTTOM + self.footer_height + 2 * mm

    def frame(self) -> Frame:
        top = self.header_bottom - BAND_GAP
        bottom = self.footer_top + BAND_GAP
        if top - bottom < 60 * mm:
            raise ValueError("header and footer leave too little room for content; shorten identity or terms")
        return Frame(
            MARGIN_LEFT,
            bottom,
            CONTENT_WIDTH,
            top - bottom,
            leftPadding=0,
            rightPadding=0,
            topPadding=0,
            bottomPadding=0,
            id="content",
        )

    def paint_page(self, canv: Canvas, _doc: BaseDocTemplate) -> None:
        canv.saveState()
        self.header.drawOn(canv, MARGIN_LEFT, PAGE_HEIGHT - MARGIN_TOP - self.header_height)
        canv.setStrokeColor(FOREST)
        canv.setLineWidth(1.2)
        canv.line(MARGIN_LEFT, self.header_bottom, PAGE_WIDTH - MARGIN_RIGHT, self.header_bottom)
        canv.setStrokeColor(BORDER)
        canv.setLineWidth(0.6)
        canv.line(MARGIN_LEFT, self.footer_top, PAGE_WIDTH - MARGIN_RIGHT, self.footer_top)
        if self.footer_terms is not None:
            _, height = self.footer_terms.wrap(_FOOTER_TERMS_WIDTH, self.footer_height)
            self.footer_terms.drawOn(canv, MARGIN_LEFT, MARGIN_BOTTOM + self.footer_height - height)
        canv.restoreState()

    def _paint_watermark(self, canv: Canvas) -> None:
        text = self.watermark or ""
        diagonal = math.hypot(PAGE_WIDTH, PAGE_HEIGHT)
        size = min(110.0, 0.62 * diagonal / pdfmetrics.stringWidth(text, SANS_BOLD, 1))
        canv.saveState()
        canv.translate(PAGE_WIDTH / 2, PAGE_HEIGHT / 2)
        canv.rotate(math.degrees(math.atan2(PAGE_HEIGHT, PAGE_WIDTH)))
        canv.setFillColor(FOREST)
        canv.setFillAlpha(0.07)
        canv.setFont(SANS_BOLD, size)
        canv.drawCentredString(0, -size * 0.35, text)
        canv.restoreState()

    def paint_overlay(self, canv: Canvas, number: int, total: int) -> None:
        """Drawn over the finished page once the page count is known: the watermark (translucent
        over content, so opaque tables or drawings cannot hide it) and "Page X of Y"."""
        if self.watermark:
            self._paint_watermark(canv)
        label = f"Page {number} of {total}"
        if self.reference:
            label = f"{self.reference}  ·  {label}"
        number_para = para(label, "footer_right")
        width = CONTENT_WIDTH - _FOOTER_TERMS_WIDTH - 4 * mm
        _, height = number_para.wrap(width, self.footer_height)
        canv.saveState()
        number_para.drawOn(
            canv, PAGE_WIDTH - MARGIN_RIGHT - width, MARGIN_BOTTOM + self.footer_height - height
        )
        canv.restoreState()


def _validate_watermark(watermark: str | None) -> str | None:
    if watermark is None:
        return None
    text = " ".join(watermark.split())
    if not text:
        raise ValueError("watermark must not be blank")
    if len(text) > _WATERMARK_MAX_CHARS:
        raise ValueError(f"watermark must be at most {_WATERMARK_MAX_CHARS} characters")
    if needs_shaping(text) or coverage_gaps(text):
        raise ValueError("watermark must use Latin, Greek or Cyrillic text")
    return text


def build_pdf(
    title: str,
    identity: CompanyIdentity,
    meta: Sequence[tuple[str, str]],
    story: Sequence[Flowable],
    watermark: str | None = None,
    *,
    reference: str | None = None,
    subject: str | None = None,
) -> bytes:
    """Render an A4 document and return the PDF bytes.

    ``title`` is the document kind printed in the header ("Quotation", "Delivery challan").
    ``meta`` is the label/value block under it (number, date, validity...). ``reference`` (usually
    the document number) is repeated in every footer. ``story`` is consumed by the layout: build a
    fresh list for each call.
    """
    if not title.strip():
        raise ValueError("title is required")
    if not story:
        raise ValueError("story is empty")
    for item in meta:
        if len(item) != 2:
            raise ValueError("meta entries are (label, value) pairs")
    mark = _validate_watermark(watermark)
    register_fonts()
    with RENDER_LOCK:
        header = _header(title, identity, meta)
        _, header_height = header.wrap(CONTENT_WIDTH, PAGE_HEIGHT)
        terms = (
            para(identity.footer_terms, "footer")
            if identity.footer_terms and identity.footer_terms.strip()
            else None
        )
        footer_height = 9.0
        if terms is not None:
            footer_height = max(footer_height, terms.wrap(_FOOTER_TERMS_WIDTH, PAGE_HEIGHT)[1])
        furniture = _Furniture(header, header_height, terms, footer_height, reference, mark)

        buffer = io.BytesIO()
        doc = BaseDocTemplate(
            buffer,
            pagesize=(PAGE_WIDTH, PAGE_HEIGHT),
            leftMargin=MARGIN_LEFT,
            rightMargin=MARGIN_RIGHT,
            topMargin=MARGIN_TOP,
            bottomMargin=MARGIN_BOTTOM,
            title=f"{title} {reference}" if reference else title,
            author=identity.legal_name,
            subject=subject or "",
            creator="Lamikraft One",
            invariant=1,
            initialFontName=SANS,
            initialFontSize=9,
            displayDocTitle=1,
        )
        doc.addPageTemplates(
            [PageTemplate(id="document", frames=[furniture.frame()], onPage=furniture.paint_page)]
        )
        doc.build(list(story), canvasmaker=partial(_NumberedCanvas, overlay_painter=furniture.paint_overlay))
        return buffer.getvalue()
