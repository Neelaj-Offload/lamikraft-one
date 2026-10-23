"""Page geometry, brand palette, paragraph styles and safe paragraph construction.

All text reaches ReportLab through ``para``: plain strings are escaped and script-routed, only
``Markup`` (trusted, already escaped) passes through untouched. Styles shape text with HarfBuzz
only when it contains Devanagari, so long Latin tables stay fast.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from functools import cache

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import CondPageBreak, Flowable, Paragraph, Table, TableStyle

from app.core.documents.fonts import (
    RENDER_LOCK,
    SANS,
    SANS_BOLD,
    needs_shaping,
    register_fonts,
    script_markup,
)

# --------------------------------------------------------------------------- palette (design tokens)

INK = colors.HexColor("#202723")
INK_MUTED = colors.HexColor("#55605A")
FOREST = colors.HexColor("#214C3C")
SAND = colors.HexColor("#C8A064")
BORDER = colors.HexColor("#E0E4DC")
BORDER_CONTROL = colors.HexColor("#7D8780")
SAGE = colors.HexColor("#EDF2EA")
ZEBRA = colors.HexColor("#F7F8F5")
WHITE = colors.white

# --------------------------------------------------------------------------- page geometry (A4 portrait)

PAGE_WIDTH, PAGE_HEIGHT = A4
MARGIN_LEFT = 15 * mm
MARGIN_RIGHT = 15 * mm
MARGIN_TOP = 12 * mm
MARGIN_BOTTOM = 10 * mm
CONTENT_WIDTH = PAGE_WIDTH - MARGIN_LEFT - MARGIN_RIGHT
#: Gap between the header band rule and the first line of content, and above the footer rule.
BAND_GAP = 5 * mm


class Markup(str):
    """Trusted ReportLab paragraph markup. Build it with ``fonts.script_markup`` for user text."""

    __slots__ = ()


@dataclass(frozen=True, slots=True)
class _StyleSpec:
    font: str
    size: float
    leading: float
    color: colors.Color
    align: int = TA_LEFT
    space_before: float = 0
    space_after: float = 0
    #: Numbers and amounts must never break mid-value ("€1,2" / "34" reads as two amounts).
    split_long_words: bool = True


_SPECS: dict[str, _StyleSpec] = {
    "body": _StyleSpec(SANS, 9, 12.5, INK, space_after=3),
    "small": _StyleSpec(SANS, 7.5, 10, INK_MUTED),
    "small_right": _StyleSpec(SANS, 7.5, 10, INK_MUTED, TA_RIGHT),
    "heading": _StyleSpec(SANS_BOLD, 10.5, 14, FOREST, space_before=8, space_after=4),
    "label": _StyleSpec(SANS_BOLD, 7, 9.5, FOREST),
    "cell": _StyleSpec(SANS, 8.5, 11.5, INK),
    "cell_num": _StyleSpec(SANS, 8.5, 11.5, INK, TA_RIGHT, split_long_words=False),
    "cell_head": _StyleSpec(SANS_BOLD, 8, 10.5, FOREST),
    "cell_head_num": _StyleSpec(SANS_BOLD, 8, 10.5, FOREST, TA_RIGHT, split_long_words=False),
    "doc_title": _StyleSpec(SANS_BOLD, 15, 19, FOREST, TA_RIGHT),
    "identity_name": _StyleSpec(SANS_BOLD, 11, 14.5, INK),
    "identity_line": _StyleSpec(SANS, 7.5, 10, INK_MUTED),
    "meta_label": _StyleSpec(SANS, 7.5, 10, INK_MUTED, TA_RIGHT),
    "meta_value": _StyleSpec(SANS_BOLD, 8, 10.5, INK, TA_RIGHT),
    "totals_label": _StyleSpec(SANS, 8.5, 11.5, INK_MUTED, TA_RIGHT),
    "totals_value": _StyleSpec(SANS, 8.5, 11.5, INK, TA_RIGHT, split_long_words=False),
    "totals_grand_label": _StyleSpec(SANS_BOLD, 9.5, 13, FOREST, TA_RIGHT),
    "totals_grand_value": _StyleSpec(SANS_BOLD, 9.5, 13, FOREST, TA_RIGHT, split_long_words=False),
    "signature_label": _StyleSpec(SANS_BOLD, 8, 10.5, INK, TA_CENTER),
    "footer": _StyleSpec(SANS, 7, 9, INK_MUTED),
    "footer_right": _StyleSpec(SANS, 7, 9, INK_MUTED, TA_RIGHT),
}

STYLE_NAMES = frozenset(_SPECS)


@cache
def style(name: str, shaped: bool = False) -> ParagraphStyle:
    """A named document style; ``shaped=True`` returns the HarfBuzz-shaping variant."""
    register_fonts()
    try:
        spec = _SPECS[name]
    except KeyError:
        raise KeyError(f"unknown document style {name!r}; known: {sorted(_SPECS)}") from None
    return ParagraphStyle(
        f"lk-{name}{'-shaped' if shaped else ''}",
        fontName=spec.font,
        fontSize=spec.size,
        leading=spec.leading,
        textColor=spec.color,
        alignment=spec.align,
        spaceBefore=spec.space_before,
        spaceAfter=spec.space_after,
        shaping=1 if shaped else 0,
        splitLongWords=1 if spec.split_long_words else 0,
        allowWidows=0,
        allowOrphans=0,
    )


def para(text: str, style_name: str = "body") -> Paragraph:
    """A Paragraph from plain text (escaped, script-routed) or ``Markup`` (used as is).

    ``Markup`` for a bold style must name bold Devanagari itself (``script_markup(..., bold=True)``).
    """
    base = style(style_name)
    markup = text if isinstance(text, Markup) else script_markup(text, bold=base.fontName == SANS_BOLD)
    return Paragraph(markup, style(style_name, needs_shaping(text)))


def bold(text: str) -> Markup:
    """Bold inline markup for plain text, Devanagari included (``Markup`` is wrapped as is)."""
    inner = text if isinstance(text, Markup) else script_markup(text, bold=True)
    return Markup(f"<b>{inner}</b>")


def plain(text: str) -> Markup:
    return Markup(script_markup(text))


def join_markup(parts: Sequence[str], separator: str = "<br/>") -> Markup:
    """Join plain strings and ``Markup`` pieces; plain pieces are escaped first."""
    return Markup(separator.join(p if isinstance(p, Markup) else script_markup(p) for p in parts))


def section_heading(text: str, *, min_space_below: float = 25 * mm) -> list[Flowable]:
    """A heading that starts a new page when less than ``min_space_below`` would follow it.

    (``keepWithNext`` is not used: it pushes a long table whole onto the next page.)
    """
    heading = para(text, "heading")
    with RENDER_LOCK:
        _, height = heading.wrap(CONTENT_WIDTH, PAGE_HEIGHT)
    room = height + heading.getSpaceBefore() + heading.getSpaceAfter() + min_space_below
    return [CondPageBreak(room), heading]


def base_table_style() -> list[tuple[object, ...]]:
    """Commands every engine table starts from: zero padding, top alignment, and an embedded
    font for empty cells (ReportLab would otherwise reference a non-embedded Helvetica)."""
    return [
        ("FONT", (0, 0), (-1, -1), SANS, 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]


def address_columns(blocks: Sequence[tuple[str, Sequence[str]]], *, width: float = CONTENT_WIDTH) -> Flowable:
    """Side-by-side labelled blocks: FROM / TO on challans, Bill to / Ship to on quotes and invoices."""
    if not blocks:
        raise ValueError("address_columns needs at least one block")
    cells: list[list[Flowable]] = []
    for label, lines in blocks:
        cell: list[Flowable] = [para(label.upper(), "label")]
        printed = [line for line in lines if line.strip()]
        cell.extend(para(line, "body" if i == 0 else "small") for i, line in enumerate(printed))
        cells.append(cell)
    gutter = 4 * mm
    col = (width - gutter * (len(blocks) - 1)) / len(blocks)
    widths: list[float] = []
    row: list[object] = []
    for i, cell in enumerate(cells):
        if i:
            widths.append(gutter)
            row.append("")
        widths.append(col)
        row.append(cell)
    table = Table([row], colWidths=widths, hAlign="LEFT")
    commands = base_table_style()
    for i in range(0, len(row), 2):
        commands += [
            ("LINEABOVE", (i, 0), (i, 0), 1, FOREST),
            ("TOPPADDING", (i, 0), (i, 0), 4),
        ]
    table.setStyle(TableStyle(commands))
    table.spaceAfter = 4 * mm
    return table
