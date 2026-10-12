"""The only CSV writer in Lamikraft One.

Every CSV output (quotes, challans, custom products, import error reports, lookups, migration
reports) goes through :func:`write_csv`. Text cells that a spreadsheet could interpret as a
formula are prefixed with an apostrophe (OWASP CSV-injection guidance), including the full-width
variants and values hidden behind leading whitespace. Numeric cells (int/Decimal) stay numeric.
Output is UTF-8 with BOM, QUOTE_ALL, CRLF line endings, so Excel opens ₹ and € correctly.
A contract test forbids ``csv.writer`` anywhere else in the codebase.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any

_TRIGGERS = frozenset("=+-@\t\r\n＝＋－＠")
GUARD = "'"


def escape_cell(value: Any) -> Any:
    """Return a spreadsheet-inert representation of one cell."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, Decimal)):
        return format(value, "f") if isinstance(value, Decimal) else str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value)
    stripped = text.lstrip("  　")
    if text and (text[0] in _TRIGGERS or (stripped and stripped[0] in _TRIGGERS)):
        return GUARD + text
    return text


def strip_guard(value: str) -> str:
    """Undo our own guard on re-import so round-trips are lossless."""
    if len(value) >= 2 and value[0] == GUARD:
        rest = value[1:]
        stripped = rest.lstrip("  　")
        if rest[0] in _TRIGGERS or (stripped and stripped[0] in _TRIGGERS):
            return rest
    return value


def write_csv(headers: Sequence[str], rows: Iterable[Sequence[Any]]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    writer.writerow([escape_cell(h) for h in headers])
    for row in rows:
        writer.writerow([escape_cell(cell) for cell in row])
    return ("﻿" + buffer.getvalue()).encode("utf-8")
