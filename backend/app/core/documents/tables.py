"""Tables for line items, totals, signatures and terms.

Every cell is a Paragraph, so long product names and descriptions wrap instead of being cut off;
``LongTable`` repeats the header row on every page. Tables split between rows; a single row is
split across pages only when it is taller than an empty page (see ``LineTable``).
"""

from __future__ import annotations

from collections.abc import Collection, Sequence

from reportlab.lib.units import mm
from reportlab.platypus import Flowable, KeepTogether, ListFlowable, ListItem, LongTable, Table, TableStyle

from app.core.documents.fonts import SANS
from app.core.documents.layout import (
    BORDER,
    BORDER_CONTROL,
    CONTENT_WIDTH,
    FOREST,
    SAGE,
    WHITE,
    ZEBRA,
    Markup,
    base_table_style,
    para,
    section_heading,
)

Cell = str | Markup | Flowable | None

_CELL_PADDING = 4


class LineTable(LongTable):
    """A LongTable that splits inside a row only when that row cannot fit on an empty frame.

    ReportLab's stock ``splitByRow + splitInRow`` first splits between rows and then, for the
    remainder, splits the next row into the space left on the same page - which prints the
    repeated header a second time mid-page. Here a row that does not fit moves to the next page
    whole, and only a row taller than a whole page is broken.
    """

    def split(self, availWidth: float, availHeight: float) -> list[LongTable]:  # noqa: N803 - ReportLab API
        self._calc(availWidth, availHeight)
        parts = self._splitRows(availHeight, doInRowSplit=False)
        if parts:
            return parts
        frame = getattr(self, "_frame", None)
        if frame is not None and getattr(frame, "_atTop", False):
            return self._splitRows(availHeight, doInRowSplit=True)
        return []


def _widths(weights: Sequence[float], count: int, total: float) -> list[float]:
    if len(weights) != count:
        raise ValueError(f"{count} columns but {len(weights)} column widths")
    if any(w <= 0 for w in weights):
        raise ValueError("column widths must be positive")
    scale = total / sum(weights)
    return [w * scale for w in weights]


def _cell(value: Cell, style_name: str) -> Flowable:
    if value is None:
        return para("", style_name)
    if isinstance(value, Flowable):
        return value
    return para(value, style_name)


def line_table(
    columns: Sequence[str],
    rows: Sequence[Sequence[Cell]],
    col_widths: Sequence[float],
    numeric_cols: Collection[int] = (),
    *,
    width: float = CONTENT_WIDTH,
) -> LineTable:
    """A multi-page line-item table.

    ``col_widths`` are relative weights scaled to ``width``. Columns in ``numeric_cols`` (0-based)
    are right-aligned, header included. Plain strings are escaped; pass ``Markup`` for rich cells.
    """
    if not columns:
        raise ValueError("a line table needs columns")
    count = len(columns)
    bad = [i for i in numeric_cols if not 0 <= i < count]
    if bad:
        raise ValueError(f"numeric column index out of range: {bad}")
    numeric = frozenset(numeric_cols)
    data: list[list[Flowable]] = [
        [_cell(name, "cell_head_num" if i in numeric else "cell_head") for i, name in enumerate(columns)]
    ]
    for row_no, row in enumerate(rows, start=1):
        if len(row) != count:
            raise ValueError(f"row {row_no} has {len(row)} cells, expected {count}")
        data.append([_cell(value, "cell_num" if i in numeric else "cell") for i, value in enumerate(row)])
    table = LineTable(
        data,
        colWidths=_widths(col_widths, count, width),
        repeatRows=1,
        splitByRow=1,
        splitInRow=1,
        hAlign="LEFT",
    )
    commands = base_table_style() + [
        ("LEFTPADDING", (0, 0), (-1, -1), _CELL_PADDING),
        ("RIGHTPADDING", (0, 0), (-1, -1), _CELL_PADDING),
        ("TOPPADDING", (0, 0), (-1, -1), _CELL_PADDING),
        ("BOTTOMPADDING", (0, 0), (-1, -1), _CELL_PADDING),
        ("BACKGROUND", (0, 0), (-1, 0), SAGE),
        ("LINEBELOW", (0, 0), (-1, 0), 0.9, FOREST),
    ]
    if len(data) > 1:
        commands += [
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, ZEBRA]),
            ("LINEBELOW", (0, 1), (-1, -1), 0.5, BORDER),
        ]
    table.setStyle(TableStyle(commands))
    return table


def totals_block(
    rows: Sequence[tuple[str, str]],
    *,
    emphasise_last: bool = True,
    width: float = CONTENT_WIDTH * 0.48,
) -> Flowable:
    """Right-aligned label/value rows (subtotal, surcharge, tax, total) that never split."""
    if not rows:
        raise ValueError("totals_block needs at least one row")
    data: list[list[Flowable]] = []
    last = len(rows) - 1
    for i, (label, value) in enumerate(rows):
        grand = emphasise_last and i == last
        data.append(
            [
                para(label, "totals_grand_label" if grand else "totals_label"),
                para(value, "totals_grand_value" if grand else "totals_value"),
            ]
        )
    table = Table(data, colWidths=[width * 0.58, width * 0.42], hAlign="RIGHT")
    commands = base_table_style() + [
        ("LEFTPADDING", (0, 0), (-1, -1), _CELL_PADDING),
        ("RIGHTPADDING", (0, 0), (-1, -1), _CELL_PADDING),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW", (0, 0), (-1, -2), 0.5, BORDER),
    ]
    if emphasise_last:
        commands += [
            ("LINEABOVE", (0, last), (-1, last), 1, FOREST),
            ("BACKGROUND", (0, last), (-1, last), SAGE),
        ]
    table.setStyle(TableStyle(commands))
    table.spaceBefore = 3 * mm
    return KeepTogether([table])


DEFAULT_SIGNATURES: tuple[str, ...] = ("Delivered by", "Received by", "Authorised signatory")


def signature_boxes(
    labels: Sequence[str] = DEFAULT_SIGNATURES,
    *,
    height: float = 22 * mm,
    width: float = CONTENT_WIDTH,
) -> Flowable:
    """Equal signing boxes with the role printed under each; kept together on one page."""
    if not labels:
        raise ValueError("signature_boxes needs at least one label")
    count = len(labels)
    gutter = 5 * mm
    box = (width - gutter * (count - 1)) / count
    widths: list[float] = []
    boxes: list[object] = []
    captions: list[object] = []
    for i, label in enumerate(labels):
        if i:
            widths.append(gutter)
            boxes.append("")
            captions.append("")
        widths.append(box)
        boxes.append("")
        captions.append(para(label, "signature_label"))
    table = Table([boxes, captions], colWidths=widths, rowHeights=[height, None], hAlign="LEFT")
    commands = base_table_style() + [("TOPPADDING", (0, 1), (-1, 1), 4)]
    for col in range(0, len(widths), 2):
        commands.append(("BOX", (col, 0), (col, 0), 0.7, BORDER_CONTROL))
    table.setStyle(TableStyle(commands))
    table.spaceBefore = 8 * mm
    return KeepTogether([table])


def terms_block(lines: Sequence[str], *, heading: str = "Terms and conditions") -> Flowable:
    """A numbered list of terms under a heading that stays with the first term."""
    items = [line for line in lines if line.strip()]
    if not items:
        raise ValueError("terms_block needs at least one non-blank line")
    numbered = ListFlowable(
        [ListItem(para(line, "body"), value=i) for i, line in enumerate(items, start=1)],
        bulletType="1",
        bulletFontName=SANS,
        bulletFontSize=8.5,
        bulletFormat="%s.",
        leftIndent=5 * mm,
        bulletDedent=5 * mm,
    )
    return KeepTogether([*section_heading(heading, min_space_below=0), numbered])
