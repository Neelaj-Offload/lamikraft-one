"""CSV and XLSX readers for the import workbench (no pandas: its type inference caused the legacy "120.0" damage).

Every cell becomes text exactly as the sheet shows it:
- CSV: decoded as UTF-8 (BOM stripped), strict UTF-8, then cp1252 with a warning; the delimiter is sniffed from
  ``, ; TAB |``; all values stay strings.
- XLSX: openpyxl ``read_only=True, data_only=True`` behind a zip-bomb guard. Text cells are kept verbatim; integral
  numbers become integer strings (``120.0`` -> ``"120"``), zero-pattern formats are zero-padded (``120`` with
  ``0000`` -> ``"0120"``), other numbers keep their exact decimal text, dates become ISO dates. A formula without a
  cached value is reported (``FORMULA_NO_VALUE``).
Limits: 50 000 rows, 200 columns, 10 000 characters per cell.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from app.core.errors import ValidationFailed

MAX_ROWS = 50_000
MAX_COLUMNS = 200
MAX_CELL = 10_000
MAX_UNCOMPRESSED = 200 * 1024 * 1024
MAX_RATIO = 100
_ZERO_FORMAT = re.compile(r"^0+$")


@dataclass
class ParsedSheet:
    headers: list[str]
    #: (physical row number, original header -> cell text); blank rows are skipped
    rows: list[tuple[int, dict[str, str]]]
    file_format: str
    encoding: str | None = None
    delimiter: str | None = None
    sheet_name: str | None = None
    #: (row number or None, column or None, code, message)
    notes: list[tuple[int | None, str | None, str, str]] = field(default_factory=list)


def _fail(code: str, message: str) -> ValidationFailed:
    return ValidationFailed(message, errors=[{"loc": ["body", "file"], "msg": message, "code": code}])


def _unique_headers(raw: list[Any]) -> list[str]:
    out: list[str] = []
    seen: dict[str, int] = {}
    for i, value in enumerate(raw):
        text = "" if value is None else str(value).replace("﻿", "").strip()
        text = text or f"column_{i + 1}"
        if text in seen:
            seen[text] += 1
            text = f"{text} ({seen[text]})"
        else:
            seen[text] = 1
        out.append(text)
    return out


def _decode(data: bytes, notes: list[tuple[int | None, str | None, str, str]]) -> tuple[str, str]:
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8"), "utf-8-sig"
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        notes.append((None, None, "ENCODING_FALLBACK", "The file is not UTF-8; it was read as Windows-1252"))
        return data.decode("cp1252", errors="replace"), "cp1252"


def read_csv(data: bytes) -> ParsedSheet:
    notes: list[tuple[int | None, str | None, str, str]] = []
    text, encoding = _decode(data, notes)
    sample = text[:20_000]
    try:
        delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        delimiter = ","
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    try:
        header_row = next(reader)
    except StopIteration as exc:
        raise _fail("empty_file", "The file has no header row") from exc
    if len(header_row) > MAX_COLUMNS:
        raise _fail("too_many_columns", f"The file has more than {MAX_COLUMNS} columns")
    headers = _unique_headers(header_row)
    rows: list[tuple[int, dict[str, str]]] = []
    for line_no, cells in enumerate(reader, start=2):
        if not any(c.strip() for c in cells):
            continue
        if len(rows) >= MAX_ROWS:
            raise _fail("too_many_rows", f"The file has more than {MAX_ROWS} rows")
        row: dict[str, str] = {}
        for i, header in enumerate(headers):
            value = cells[i] if i < len(cells) else ""
            if len(value) > MAX_CELL:
                notes.append((line_no, header, "CELL_TOO_LONG", f"Cell longer than {MAX_CELL} characters was cut"))
                value = value[:MAX_CELL]
            row[header] = value
        if len(cells) > len(headers) and any(c.strip() for c in cells[len(headers):]):
            notes.append((line_no, None, "EXTRA_CELLS", "The row has more cells than the header; extras were ignored"))
        rows.append((line_no, row))
    return ParsedSheet(headers=headers, rows=rows, file_format="csv", encoding=encoding, delimiter=delimiter, notes=notes)


def _plain(d: Decimal) -> str:
    text = format(d, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".") if not text.endswith(".") else text[:-1]
    return text


def _cell_text(value: Any, number_format: str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, datetime):
        return value.date().isoformat() if value.time() == time(0, 0) else value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, int):
        text = str(value)
        if number_format and _ZERO_FORMAT.match(number_format):
            text = text.zfill(len(number_format))
        return text
    if isinstance(value, float):
        d = Decimal(repr(value))
        if d == d.to_integral_value():
            # a float cell holding a whole number ("120.0") is passed on as such: the field's identifier rule
            # strips the artefact with a warning (decor fields) or keeps it (product_key), never silently
            return f"{int(d)}.0"
        return _plain(d)
    return str(value)


def _guard_zip(data: bytes) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            infos = zf.infolist()
            total = sum(i.file_size for i in infos)
            compressed = sum(i.compress_size for i in infos) or 1
            if total > MAX_UNCOMPRESSED or total / compressed > MAX_RATIO:
                raise _fail("zip_bomb", "The workbook expands to an unsafe size")
            if any(i.filename.lower().endswith("vbaproject.bin") for i in infos):
                raise _fail("macro_workbook", "Workbooks with macros are not accepted")
    except zipfile.BadZipFile as exc:
        raise _fail("not_xlsx", "The file is not a valid XLSX workbook") from exc


def read_xlsx(data: bytes, sheet_name: str | None = None) -> ParsedSheet:
    from openpyxl import load_workbook

    _guard_zip(data)
    workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        if sheet_name and sheet_name not in workbook.sheetnames:
            raise _fail("sheet_not_found", f"The workbook has no sheet named {sheet_name!r}")
        sheet = workbook[sheet_name] if sheet_name else workbook.worksheets[0]
        notes: list[tuple[int | None, str | None, str, str]] = []
        iterator = sheet.iter_rows()
        try:
            header_cells = next(iterator)
        except StopIteration as exc:
            raise _fail("empty_file", "The sheet has no header row") from exc
        raw_headers = [c.value for c in header_cells]
        while raw_headers and (raw_headers[-1] is None or str(raw_headers[-1]).strip() == ""):
            raw_headers.pop()
        if len(raw_headers) > MAX_COLUMNS:
            raise _fail("too_many_columns", f"The sheet has more than {MAX_COLUMNS} columns")
        headers = _unique_headers(raw_headers)
        rows: list[tuple[int, dict[str, str]]] = []
        for row_no, cells in enumerate(iterator, start=2):
            values = [
                _cell_text(c.value, getattr(c, "number_format", None)) if hasattr(c, "value") else ""
                for c in cells[: len(headers)]
            ]
            if not any(v.strip() for v in values):
                continue
            if len(rows) >= MAX_ROWS:
                raise _fail("too_many_rows", f"The sheet has more than {MAX_ROWS} rows")
            row = {h: (values[i] if i < len(values) else "")[:MAX_CELL] for i, h in enumerate(headers)}
            for i, c in enumerate(cells[: len(headers)]):
                if getattr(c, "data_type", None) == "f" and c.value is None:
                    notes.append((row_no, headers[i], "FORMULA_NO_VALUE", "A formula has no cached value"))
            rows.append((row_no, row))
        return ParsedSheet(headers=headers, rows=rows, file_format="xlsx", sheet_name=sheet.title, notes=notes)
    finally:
        workbook.close()


def read_file(data: bytes, file_name: str, *, sheet_name: str | None = None) -> ParsedSheet:
    if data[:4] == b"PK\x03\x04" or file_name.lower().endswith(".xlsx"):
        return read_xlsx(data, sheet_name)
    return read_csv(data)
