"""Content sniffing: the bytes decide what a file is, never the declared type or the filename alone.

Accepted kinds: PNG, JPEG, GIF, WEBP (each verified by decoding the header with Pillow), PDF, XLSX
(OOXML spreadsheet without macros) and UTF-8 CSV/TXT. Rejected: SVG and any HTML/XML markup (anywhere in a
text file), images over ``MAX_IMAGE_PIXELS``, macro-enabled
or legacy binary Office documents (OLE), everything unrecognised, and files whose extension disagrees with
the sniffed kind. Rejections raise 415 ``unsupported_media_type`` with a ``reason`` code.
"""

from __future__ import annotations

import codecs
import re
import unicodedata
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath

from app.platform.files.errors import UnsupportedMediaType
from app.platform.files.models import FileKind

CONTENT_TYPES: dict[FileKind, str] = {
    FileKind.PNG: "image/png",
    FileKind.JPEG: "image/jpeg",
    FileKind.GIF: "image/gif",
    FileKind.WEBP: "image/webp",
    FileKind.PDF: "application/pdf",
    FileKind.XLSX: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    FileKind.CSV: "text/csv; charset=utf-8",
    FileKind.TXT: "text/plain; charset=utf-8",
}
EXTENSIONS: dict[FileKind, frozenset[str]] = {
    FileKind.PNG: frozenset({"png"}),
    FileKind.JPEG: frozenset({"jpg", "jpeg"}),
    FileKind.GIF: frozenset({"gif"}),
    FileKind.WEBP: frozenset({"webp"}),
    FileKind.PDF: frozenset({"pdf"}),
    FileKind.XLSX: frozenset({"xlsx"}),
    FileKind.CSV: frozenset({"csv"}),
    FileKind.TXT: frozenset({"txt"}),
}
IMAGE_KINDS = frozenset({FileKind.PNG, FileKind.JPEG, FileKind.GIF, FileKind.WEBP})
#: served ``inline`` (everything else is ``attachment``)
INLINE_KINDS = IMAGE_KINDS | {FileKind.PDF}
_PILLOW_FORMATS = {FileKind.PNG: "PNG", FileKind.JPEG: "JPEG", FileKind.GIF: "GIF", FileKind.WEBP: "WEBP"}

HEAD_BYTES = 4096
_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_MARKUP = re.compile(
    rb"<\s*(svg|!doctype|html|head|body|script|iframe|object|embed|meta|link|style|\?xml|xsl)\b", re.IGNORECASE
)
_MAX_ZIP_ENTRIES = 10_000
#: bytes carried from one read into the next while scanning text for markup (longer than any tag opener)
_MARKUP_OVERLAP = 256
#: images with more pixels are rejected before decoding (Pillow's own default bomb threshold, ~89.5 Mpx)
MAX_IMAGE_PIXELS = 89_478_485


def reject(reason: str, detail: str) -> UnsupportedMediaType:
    return UnsupportedMediaType(detail, reason=reason)


def extension_of(filename: str) -> str:
    name = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    return name.rsplit(".", 1)[-1].lower() if "." in name.strip(".") else ""


def sanitize_filename(raw: str | None, *, fallback: str = "file") -> str:
    """A display/download name: no directories, control characters or reserved punctuation; <= 255 chars."""
    name = unicodedata.normalize("NFC", raw or "")
    name = PureWindowsPath(PurePosixPath(name).name).name  # strip both / and \ directory parts
    name = "".join(ch for ch in name if unicodedata.category(ch)[0] != "C")
    name = re.sub(r'[<>:"|?*]', "_", name).strip().strip(".")
    if not name:
        name = fallback
    if len(name) > 255:
        ext = extension_of(name)
        stem_max = 255 - (len(ext) + 1 if ext else 0)
        name = name[:stem_max] + (f".{ext}" if ext else "")
    return name


def _sniff_binary(head: bytes) -> FileKind | None:
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return FileKind.PNG
    if head.startswith(b"\xff\xd8\xff"):
        return FileKind.JPEG
    if head.startswith((b"GIF87a", b"GIF89a")):
        return FileKind.GIF
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return FileKind.WEBP
    if head.startswith(b"%PDF-"):
        return FileKind.PDF
    return None


def _inspect_zip(path: Path) -> FileKind:
    try:
        with zipfile.ZipFile(path) as zf:
            infos = zf.infolist()
            if len(infos) > _MAX_ZIP_ENTRIES:
                raise reject("archive_too_complex", "The spreadsheet has too many parts.")
            names = {i.filename for i in infos}
            lowered = {n.lower() for n in names}
            if any(n.endswith("vbaproject.bin") or n.endswith(".bin") and "vba" in n for n in lowered):
                raise reject("macro_document_not_allowed", "Spreadsheets with macros are not accepted.")
            if "[Content_Types].xml" not in names:
                raise reject("unrecognised_content", "This archive is not an Office document.")
            info = zf.getinfo("[Content_Types].xml")
            if info.file_size > 1_000_000:
                raise reject("archive_too_complex", "The spreadsheet manifest is too large.")
            content_types = zf.read(info).decode("utf-8", errors="replace").lower()
    except zipfile.BadZipFile:
        raise reject("unrecognised_content", "The file is a damaged archive.") from None
    if "macroenabled" in content_types or "vbaproject" in content_types:
        raise reject("macro_document_not_allowed", "Spreadsheets with macros are not accepted.")
    if "xl/workbook.xml" in lowered and "spreadsheetml.sheet.main+xml" in content_types:
        return FileKind.XLSX
    raise reject("type_not_supported", "Only .xlsx spreadsheets are accepted among Office files.")


def _markup_rejection(data: bytes) -> UnsupportedMediaType | None:
    if not _MARKUP.search(data):
        return None
    svg = re.search(rb"<\s*svg\b", data, re.IGNORECASE)
    return reject(
        "svg_not_allowed" if svg else "html_not_allowed",
        "SVG images are not accepted." if svg else "HTML and XML documents are not accepted.",
    )


def _check_text(path: Path) -> None:
    """Whole-file checks for CSV/TXT: strict UTF-8, no NUL bytes and no SVG/HTML markup anywhere (not only in
    the first bytes). Reads overlap by ``_MARKUP_OVERLAP`` bytes so a tag split across two reads is found."""
    decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")
    tail = b""
    try:
        with path.open("rb") as fh:
            while chunk := fh.read(65536):
                if b"\x00" in chunk:
                    raise reject("binary_content", "The file contains binary data and is not a text file.")
                decoder.decode(chunk)
                if (problem := _markup_rejection(tail + chunk)) is not None:
                    raise problem
                tail = chunk[-_MARKUP_OVERLAP:]
            decoder.decode(b"", final=True)
    except UnicodeDecodeError:
        raise reject("not_utf8_text", "Text files must be UTF-8 encoded.") from None


def _verify_image(path: Path, kind: FileKind) -> None:
    """Decode the header and check the pixel count explicitly.

    The limit is compared directly instead of relying on Pillow's ``DecompressionBombWarning``: turning that
    warning into an error needs ``warnings.catch_warnings``, which swaps process-global filters and is not
    thread-safe while uploads run in the threadpool. Pillow still raises ``DecompressionBombError`` on open
    for images beyond twice its own limit.
    """
    from PIL import Image

    try:
        with Image.open(path) as image:
            if image.format != _PILLOW_FORMATS[kind]:
                raise reject("image_invalid", "The image content does not match its format.")
            width, height = image.size
            if width * height > MAX_IMAGE_PIXELS:
                raise reject("image_too_large", "The image has too many pixels.")
            image.verify()
    except UnsupportedMediaType:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        # the warning only arrives as an exception when the process's filters say so; either way: too large
        raise reject("image_too_large", "The image has too many pixels.") from None
    except Exception:  # noqa: BLE001 - any decoder failure means the bytes are not a valid image
        raise reject("image_invalid", "The image is damaged or not a real image.") from None


def sniff(path: Path, head: bytes, filename: str) -> FileKind:
    """Return the verified kind of the file at ``path`` (``head`` = its first bytes) or raise 415."""
    ext = extension_of(filename)
    kind = _sniff_binary(head)
    if kind is None and head.startswith(b"PK\x03\x04"):
        kind = _inspect_zip(path)
    if kind is None and head.startswith(_OLE):
        raise reject("macro_document_not_allowed", "Legacy Office documents (.doc, .xls) are not accepted.")
    if kind is None:
        text_head = head[3:] if head.startswith(codecs.BOM_UTF8) else head
        if (problem := _markup_rejection(text_head)) is not None:
            raise problem  # markup is named as such whatever the extension
        if ext not in ("csv", "txt"):
            raise reject("unrecognised_content", "This kind of file is not accepted.")
        _check_text(path)
        kind = FileKind.CSV if ext == "csv" else FileKind.TXT
    if ext not in EXTENSIONS[kind]:
        raise reject("extension_mismatch", "The file extension does not match its content.")
    if kind in IMAGE_KINDS:
        _verify_image(path, kind)
    return kind
