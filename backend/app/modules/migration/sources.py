"""Reading an authorised legacy export directory (the legacy system is MongoDB; the spec is not a dump).

Layout (docs/runbooks/migration.md): one file per legacy collection, named after it (``products_master.csv``,
``quotes.jsonl``, ...), in any of the formats the legacy system or an operator produces:

- CSV / XLSX: through the import workbench readers (``app.modules.imports.readers``): every cell stays text exactly as
  the sheet shows it, no type inference;
- JSON: an array of documents, or an object holding the array under ``items`` / ``rows`` / the collection name;
- JSON Lines (``.jsonl`` / ``.ndjson``; ``mongoexport``'s default): one document per line.

MongoDB Extended JSON wrappers are unwrapped to text (``{"$oid": ...}``, ``{"$date": ...}``, ``{"$numberDecimal":
...}``, ``$numberLong``, ``$numberInt``, ``$numberDouble``). Nested objects (quote revision snapshots, permission
overrides) are kept as objects. Optional ``export_manifest.json`` records who authorised the export; media binaries
live under ``media/``. Two files for the same collection, a file outside the directory (symlink) or an unreadable file
stop the run before anything is analysed.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.modules.imports.headers import normalise_header

#: legacy collection -> accepted file stems (the collection name first)
ENTITY_FILES: dict[str, tuple[str, ...]] = {
    "category_taxonomy": ("category_taxonomy", "taxonomy"),
    "products_master": ("products_master", "products"),
    "pricing": ("pricing",),
    "packaging": ("packaging",),
    "specifications": ("specifications",),
    "media": ("media",),
    "lookup_reference": ("lookup_reference",),
    "users": ("users",),
    "quote_settings": ("quote_settings",),
    "custom_products": ("custom_products",),
    "quotes": ("quotes",),
    "quote_lines": ("quote_lines",),
    "quote_revisions": ("quote_revisions",),
    "grain_locked_decors": ("grain_locked_decors", "grain_locks"),
    "delivery_challans": ("delivery_challans", "challans"),
    "delivery_challan_lines": ("delivery_challan_lines", "challan_lines"),
    "opening_balances": ("opening_balances",),
}
FORMATS = {".csv": "csv", ".xlsx": "xlsx", ".json": "json", ".jsonl": "jsonl", ".ndjson": "jsonl"}
MANIFEST_NAME = "export_manifest.json"
MEDIA_DIR = "media"
MAX_FILE_BYTES = 200 * 1024 * 1024
MAX_JSON_ROWS = 200_000
#: keys never copied out of a source row (legacy credentials and secrets)
SECRET_KEYS = frozenset(
    {"password", "password_hash", "hashed_password", "token", "secret", "api_key", "otp_secret"}
)


class SourceError(Exception):
    """The export cannot be read as a whole (the run stops before analysis)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class SourceRow:
    entity: str
    file: str
    #: CSV/XLSX: the physical sheet row (header = 1); JSON: the 1-based document index
    row_number: int
    #: normalised key -> value (text for CSV/XLSX; text, bool, None, dict or list for JSON)
    values: dict[str, Any]


@dataclass
class SourceFile:
    entity: str
    name: str
    format: str
    sha256: str
    size: int
    rows: list[SourceRow] = field(default_factory=list)
    notes: list[tuple[int | None, str | None, str, str]] = field(default_factory=list)

    def describe(self) -> dict[str, Any]:
        return {
            "file": self.name,
            "entity": self.entity,
            "format": self.format,
            "sha256": self.sha256,
            "bytes": self.size,
            "rows": len(self.rows),
        }


@dataclass
class ExportSource:
    root: Path
    files: dict[str, SourceFile]
    manifest: dict[str, Any]
    manifest_sha256: str | None
    ignored: list[str]

    @property
    def label(self) -> str:
        return self.root.name[:200] or "export"

    @property
    def digest(self) -> str:
        parts = sorted(f"{f.name}:{f.sha256}" for f in self.files.values())
        if self.manifest_sha256:
            parts.append(f"{MANIFEST_NAME}:{self.manifest_sha256}")
        return hashlib.sha256("\n".join(parts).encode()).hexdigest()

    def rows(self, entity: str) -> list[SourceRow]:
        f = self.files.get(entity)
        return list(f.rows) if f else []

    def file_name(self, entity: str) -> str | None:
        f = self.files.get(entity)
        return f.name if f else None

    @property
    def authorised(self) -> bool:
        return bool(str(self.manifest.get("authorised_by") or "").strip()) and bool(
            self.manifest.get("exported_at")
        )


# ---- value helpers -----------------------------------------------------------------------------------------------
_EXT_SCALARS = ("$oid", "$numberDecimal", "$numberLong", "$numberInt", "$numberDouble", "$uuid")


def unwrap(value: Any) -> Any:
    """MongoDB Extended JSON -> plain values (wrappers become text; objects and arrays are walked)."""
    if isinstance(value, dict):
        if len(value) == 1:
            ((k, v),) = value.items()
            if k in _EXT_SCALARS:
                return str(v)
            if k == "$date":
                if isinstance(v, dict) and "$numberLong" in v:
                    from datetime import UTC, datetime

                    return datetime.fromtimestamp(int(v["$numberLong"]) / 1000, tz=UTC).isoformat()
                return str(v)
        return {str(k): unwrap(v) for k, v in value.items()}
    if isinstance(value, list):
        return [unwrap(v) for v in value]
    if isinstance(value, float):
        d = Decimal(repr(value))
        return str(int(d)) + ".0" if d == d.to_integral_value() else format(d, "f")
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return value


def as_text(value: Any) -> str | None:
    """A source value as cell text (what the import definitions expect); objects become compact JSON."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return str(value)


def scrub(values: dict[str, Any]) -> dict[str, Any]:
    """The row without credential fields (kept out of issues, reports and the legacy archive)."""
    return {k: v for k, v in values.items() if k not in SECRET_KEYS}


def row_hash(values: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(scrub(values), sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


# ---- reading -------------------------------------------------------------------------------------------------------
def _sha256(path: Path) -> tuple[str, int]:
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
            size += len(chunk)
    return h.hexdigest(), size


def _documents(data: bytes, fmt: str, entity: str, name: str) -> list[Any]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SourceError("not_utf8", f"{name} is not UTF-8 JSON") from exc
    if fmt == "jsonl":
        docs = []
        for i, line in enumerate(text.splitlines(), start=1):
            if line.strip():
                try:
                    docs.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise SourceError("bad_json", f"{name} line {i} is not valid JSON") from exc
        return docs
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SourceError("bad_json", f"{name} is not valid JSON ({exc.msg} at line {exc.lineno})") from exc
    if isinstance(doc, dict):
        for key in ("items", "rows", entity):
            if isinstance(doc.get(key), list):
                return list(doc[key])
        return [doc]  # a singleton collection (quote_settings)
    if isinstance(doc, list):
        return doc
    raise SourceError("bad_json", f"{name} must hold a JSON array of documents")


def _read_file(path: Path, entity: str) -> SourceFile:
    fmt = FORMATS[path.suffix.lower()]
    sha, size = _sha256(path)
    if size > MAX_FILE_BYTES:
        raise SourceError(
            "file_too_large", f"{path.name} is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB"
        )
    data = path.read_bytes()
    out = SourceFile(entity=entity, name=path.name, format=fmt, sha256=sha, size=size)
    if fmt in ("csv", "xlsx"):
        from app.core.errors import ValidationFailed
        from app.modules.imports.readers import read_file

        try:
            sheet = read_file(data, path.name)
        except ValidationFailed as exc:
            raise SourceError("unreadable_sheet", f"{path.name}: {exc.detail}") from exc
        out.notes = list(sheet.notes)
        for row_no, raw in sheet.rows:
            values: dict[str, Any] = {}
            for header, text in raw.items():
                key = normalise_header(header) or header
                values.setdefault(key, text)
            out.rows.append(SourceRow(entity, path.name, row_no, values))
        return out
    docs = _documents(data, fmt, entity, path.name)
    if len(docs) > MAX_JSON_ROWS:
        raise SourceError("too_many_rows", f"{path.name} has more than {MAX_JSON_ROWS} documents")
    for i, doc in enumerate(docs, start=1):
        if not isinstance(doc, dict):
            out.notes.append((i, None, "NOT_A_DOCUMENT", "The entry is not a JSON object and was skipped"))
            continue
        plain = unwrap(doc)
        values = {}
        for k, v in plain.items():
            if k == "_id":
                values.setdefault("_id", v)
                continue
            values.setdefault(normalise_header(k) or k, v)
        out.rows.append(SourceRow(entity, path.name, i, values))
    return out


def _entity_for(stem: str) -> str | None:
    norm = normalise_header(stem)
    for entity, stems in ENTITY_FILES.items():
        if norm in stems:
            return entity
    return None


def read_export(root: Path) -> ExportSource:
    root = Path(root)
    if not root.is_dir():
        raise SourceError("not_a_directory", f"{root} is not a directory")
    real_root = root.resolve()
    files: dict[str, SourceFile] = {}
    ignored: list[str] = []
    manifest: dict[str, Any] = {}
    manifest_sha: str | None = None
    for path in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if path.is_dir():
            if path.name != MEDIA_DIR:
                ignored.append(path.name + "/")
            continue
        if not path.resolve().is_relative_to(real_root):
            raise SourceError("outside_export", f"{path.name} points outside the export directory")
        if path.name == MANIFEST_NAME:
            manifest_sha, _ = _sha256(path)
            try:
                loaded = json.loads(path.read_text(encoding="utf-8-sig"))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise SourceError("bad_manifest", f"{MANIFEST_NAME} is not valid JSON") from exc
            manifest = loaded if isinstance(loaded, dict) else {}
            continue
        fmt = FORMATS.get(path.suffix.lower())
        entity = _entity_for(path.stem) if fmt else None
        if entity is None:
            ignored.append(path.name)
            continue
        if entity in files:
            raise SourceError(
                "duplicate_source_file", f"both {files[entity].name} and {path.name} hold {entity}; keep one"
            )
        files[entity] = _read_file(path, entity)
    if not files:
        raise SourceError("empty_export", f"{root.name} holds no legacy collection files")
    return ExportSource(
        root=root, files=files, manifest=manifest, manifest_sha256=manifest_sha, ignored=ignored
    )


def media_path(root: Path, location: str) -> Path | None:
    """A media location inside the export (``media/<file>`` or a path relative to the export), or None when it would
    leave the directory (absolute paths, ``..``, drive letters)."""
    text = location.replace("\\", "/").strip()
    if not text or text.startswith("/") or ":" in text.split("/")[0] or ".." in text.split("/"):
        return None
    base = root.resolve()
    for candidate in (base / text, base / MEDIA_DIR / text):
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved.is_relative_to(base) and resolved.is_file():
            return resolved
    resolved = (base / MEDIA_DIR / text).resolve()
    return resolved if resolved.is_relative_to(base) else None


def iter_entities(source: ExportSource) -> Iterator[str]:
    for entity in ENTITY_FILES:
        if entity in source.files:
            yield entity


__all__ = [
    "ENTITY_FILES",
    "MANIFEST_NAME",
    "MEDIA_DIR",
    "ExportSource",
    "SourceError",
    "SourceFile",
    "SourceRow",
    "as_text",
    "iter_entities",
    "media_path",
    "read_export",
    "row_hash",
    "scrub",
    "unwrap",
]
