"""The document engine: the only way Lamikraft One produces PDFs (ReportLab Platypus + embedded Noto).

Typical use from a module's ``documents/pdf.py``::

    story = [address_columns([...]), line_table(...), totals_block([...]), terms_block([...])]
    pdf = build_pdf("Quotation", identity, [("Number", number), ("Date", format_date(d))], story,
                    watermark=None if issued else "DRAFT", reference=number)

Money and quantities are formatted with ``format_money`` / ``format_quantity`` from Decimals;
user text goes in as plain ``str`` and is escaped and script-routed automatically.
"""

from app.core.documents.drawings import Placement, board_drawing
from app.core.documents.fonts import coverage_gaps, needs_shaping, register_fonts, script_markup
from app.core.documents.format import (
    format_date,
    format_datetime,
    format_money,
    format_quantity,
    format_unit_price,
    group_digits,
)
from app.core.documents.layout import (
    CONTENT_WIDTH,
    Markup,
    address_columns,
    bold,
    join_markup,
    para,
    plain,
    section_heading,
    style,
)
from app.core.documents.tables import (
    DEFAULT_SIGNATURES,
    line_table,
    signature_boxes,
    terms_block,
    totals_block,
)
from app.core.documents.template import CompanyIdentity, build_pdf

__all__ = [
    "CONTENT_WIDTH",
    "DEFAULT_SIGNATURES",
    "CompanyIdentity",
    "Markup",
    "Placement",
    "address_columns",
    "board_drawing",
    "bold",
    "build_pdf",
    "coverage_gaps",
    "format_date",
    "format_datetime",
    "format_money",
    "format_quantity",
    "format_unit_price",
    "group_digits",
    "join_markup",
    "line_table",
    "needs_shaping",
    "para",
    "plain",
    "register_fonts",
    "script_markup",
    "section_heading",
    "signature_boxes",
    "style",
    "terms_block",
    "totals_block",
]
