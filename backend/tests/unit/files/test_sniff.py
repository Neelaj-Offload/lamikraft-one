"""Content sniffing, filename handling and storage keys (no database)."""

from __future__ import annotations

import io
import uuid
import warnings
import zipfile
from pathlib import Path

import pytest
from openpyxl import Workbook
from PIL import Image

from app.platform.files import sniff as sniff_module
from app.platform.files.errors import UnsupportedMediaType
from app.platform.files.models import FileKind
from app.platform.files.service import content_disposition
from app.platform.files.sniff import HEAD_BYTES, sanitize_filename, sniff
from app.platform.files.storage import LocalFsStorage, new_storage_key


def image_bytes(fmt: str, size: tuple[int, int] = (8, 6)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (180, 120, 60)).save(buf, fmt)
    return buf.getvalue()


def xlsx_bytes() -> bytes:
    wb = Workbook()
    wb.active["A1"] = "product_key"  # type: ignore[index]
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def xlsm_bytes() -> bytes:
    src = zipfile.ZipFile(io.BytesIO(xlsx_bytes()))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as dst:
        for info in src.infolist():
            dst.writestr(info, src.read(info.filename))
        dst.writestr("xl/vbaProject.bin", b"\x00attribute vb_name")
    return out.getvalue()


def docx_like_bytes() -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("[Content_Types].xml", '<Types><Override ContentType="application/vnd.openxmlformats-'
                   'officedocument.wordprocessingml.document.main+xml"/></Types>')
        z.writestr("word/document.xml", "<w:document/>")
    return out.getvalue()


PDF = b"%PDF-1.7\n1 0 obj << /Type /Catalog >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n"


def _sniff(tmp_path: Path, data: bytes, name: str) -> FileKind:
    path = tmp_path / uuid.uuid4().hex
    path.write_bytes(data)
    return sniff(path, data[:HEAD_BYTES], name)


@pytest.mark.parametrize(
    ("data", "name", "kind"),
    [
        (image_bytes("PNG"), "logo.png", FileKind.PNG),
        (image_bytes("JPEG"), "photo.JPG", FileKind.JPEG),
        (image_bytes("JPEG"), "photo.jpeg", FileKind.JPEG),
        (image_bytes("GIF"), "anim.gif", FileKind.GIF),
        (image_bytes("WEBP"), "swatch.webp", FileKind.WEBP),
        (PDF, "quote.pdf", FileKind.PDF),
        (xlsx_bytes(), "products.xlsx", FileKind.XLSX),
        (b"product_key,qty\nLK-OT-0450,240\n", "lines.csv", FileKind.CSV),
        ("\ufeffNamasté\n".encode(), "notes.txt", FileKind.TXT),
    ],
)
def test_accepted_kinds_are_recognised_from_their_bytes(tmp_path, data, name, kind) -> None:  # type: ignore[no-untyped-def]
    assert _sniff(tmp_path, data, name) == kind


@pytest.mark.parametrize(
    ("data", "name", "reason"),
    [
        (b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"><script/></svg>', "logo.svg", "svg_not_allowed"),
        (b"  <SVG onload=alert(1)>", "logo.png", "svg_not_allowed"),
        (b"<!DOCTYPE html><html><body>x</body></html>", "page.html", "html_not_allowed"),
        (b"<script>alert(1)</script>", "notes.txt", "html_not_allowed"),
        (xlsm_bytes(), "macro.xlsx", "macro_document_not_allowed"),
        (xlsm_bytes(), "macro.xlsm", "macro_document_not_allowed"),
        (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 600, "legacy.xls", "macro_document_not_allowed"),
        (docx_like_bytes(), "letter.docx", "type_not_supported"),
        (b"PK\x03\x04broken", "broken.xlsx", "unrecognised_content"),
        (image_bytes("PNG"), "logo.jpg", "extension_mismatch"),
        (image_bytes("PNG"), "logo.png.exe", "extension_mismatch"),
        (PDF, "quote.png", "extension_mismatch"),
        (b"MZ\x90\x00\x03", "tool.exe", "unrecognised_content"),
        (b"plain words", "words.pdf", "unrecognised_content"),
        ("café".encode("latin-1"), "latin.csv", "not_utf8_text"),
        (b"a,b\x00c", "nul.csv", "binary_content"),
        (image_bytes("PNG")[:40], "cut.png", "image_invalid"),
    ],
)
def test_dangerous_or_mismatched_files_are_rejected(tmp_path, data, name, reason) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(UnsupportedMediaType) as exc:
        _sniff(tmp_path, data, name)
    assert exc.value.status == 415 and exc.value.code == "unsupported_media_type"
    assert exc.value.extra["reason"] == reason


def test_decompression_bombs_are_rejected(tmp_path) -> None:  # type: ignore[no-untyped-def]
    big = image_bytes("PNG", (12_000, 12_000))  # 144 Mpx > Pillow's bomb limit x2
    with pytest.raises(UnsupportedMediaType) as exc:
        _sniff(tmp_path, big, "huge.png")
    assert exc.value.extra["reason"] in {"image_too_large", "image_invalid"}


def test_the_pixel_limit_does_not_depend_on_warning_filters(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Images between the limit and Pillow's hard 2x error are refused by an explicit pixel count, whatever
    the process-wide warning filters say (they are not thread-safe to change per upload)."""
    monkeypatch.setattr(sniff_module, "MAX_IMAGE_PIXELS", 20 * 20)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # a concurrent request may have left any filter in place
        with pytest.raises(UnsupportedMediaType) as exc:
            _sniff(tmp_path, image_bytes("PNG", (21, 20)), "wide.png")
        assert exc.value.extra["reason"] == "image_too_large"
        assert _sniff(tmp_path, image_bytes("PNG", (20, 20)), "fits.png") == FileKind.PNG


@pytest.mark.parametrize("ext", ["csv", "txt"])
@pytest.mark.parametrize(
    ("markup", "reason"),
    [
        (b"<svg onload=alert(1)>", "svg_not_allowed"),
        (b"<html><script>alert(1)</script>", "html_not_allowed"),
        (b"<  SCRIPT src=//x>", "html_not_allowed"),
    ],
)
#: after the sniffed head; straddling the first 64 KiB read (16-byte header + padding puts "<" 5 bytes before
#: the boundary); deep in the file
@pytest.mark.parametrize("padding", [HEAD_BYTES, 65536 - 16 - 5, 3 * 65536])
def test_markup_anywhere_in_a_text_file_is_rejected(tmp_path, ext, markup, reason, padding) -> None:  # type: ignore[no-untyped-def]
    """Not only the first 4 KiB: markup after padding, and split across two 64 KiB reads, is found."""
    data = b"product_key,qty\n" + b"x" * padding + markup + b"\n"
    with pytest.raises(UnsupportedMediaType) as exc:
        _sniff(tmp_path, data, f"list.{ext}")
    assert exc.value.extra["reason"] == reason


def test_long_plain_text_without_markup_is_accepted(tmp_path) -> None:  # type: ignore[no-untyped-def]
    data = b"product_key,note\n" + b"LK-OT-0450,size < 450 mm and > 300 mm\n" * 5000
    assert _sniff(tmp_path, data, "notes.csv") == FileKind.CSV


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("../../etc/passwd", "passwd"),
        ("C:\\Users\\me\\Desktop\\logo.png", "logo.png"),
        ("in\x00voice\x1f.pdf", "invoice.pdf"),
        ('a<b>c:d"e|f?g*.csv', "a_b_c_d_e_f_g_.csv"),
        ("", "file"),
        ("...", "file"),
        (None, "file"),
        ("Résumé 2026.pdf", "Résumé 2026.pdf"),
    ],
)
def test_sanitize_filename(raw, expected) -> None:  # type: ignore[no-untyped-def]
    assert sanitize_filename(raw) == expected


def test_long_names_keep_their_extension() -> None:
    name = sanitize_filename("x" * 400 + ".xlsx")
    assert len(name) == 255 and name.endswith(".xlsx")


def test_content_disposition_is_rfc_6266() -> None:
    assert content_disposition("Résumé 2026.pdf", inline=True) == (
        "inline; filename=\"Resume 2026.pdf\"; filename*=UTF-8''R%C3%A9sum%C3%A9%202026.pdf"
    )
    assert content_disposition('quote"; evil=1.csv', inline=False).startswith('attachment; filename="quote__ evil=1.csv"')
    assert content_disposition("मूल्य.csv", inline=False).startswith("attachment; filename=")


def test_storage_keys_are_random_and_cannot_escape_the_root(tmp_path) -> None:  # type: ignore[no-untyped-def]
    company = uuid.uuid7()
    a, b = new_storage_key(company), new_storage_key(company)
    assert a != b and a.startswith(f"{company}/")
    storage = LocalFsStorage(tmp_path)
    source = tmp_path / "staged.part"
    source.write_bytes(b"hello")
    storage.put_file(a, source)
    assert storage.exists(a) and not source.exists()
    with storage.open(a) as fh:
        assert fh.read() == b"hello"
    storage.delete(a)
    assert not storage.exists(a)
    for bad in ("../outside", f"{company}/../../x", "logo.png", f"{company}/ab/../../../etc"):
        with pytest.raises(ValueError):
            storage.open(bad)
