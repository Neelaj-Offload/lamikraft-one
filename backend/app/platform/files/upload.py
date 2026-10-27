"""Streaming multipart receive for ``POST /api/v1/files``.

The endpoint is a sync ``def`` (conventions §10); the request body is pulled chunk by chunk from the event
loop with ``anyio.from_thread.run`` and fed to python-multipart, so the file part is hashed (SHA-256) and
spooled to a temp file while it arrives and the request is cut off with 413 as soon as the per-purpose
limit is exceeded — before anything is parsed into memory. Exactly one file part named ``file`` is
accepted; no transaction is open while the body streams.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import anyio.from_thread
from python_multipart.multipart import MultipartParser, parse_options_header
from starlette.requests import Request

from app.core.errors import ValidationFailed
from app.platform.files.errors import PayloadTooLarge, UnsupportedMediaType
from app.platform.files.sniff import HEAD_BYTES

#: multipart framing, part headers and small fields on top of the file bytes
MULTIPART_OVERHEAD = 64 * 1024


@dataclass
class ReceivedUpload:
    path: Path
    size: int
    sha256: str
    filename: str
    declared_content_type: str | None
    head: bytes

    def discard(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass


@dataclass
class _Part:
    headers: dict[bytes, bytes] = field(default_factory=dict)
    name: str | None = None
    filename: str | None = None
    is_file: bool = False


def _too_large(limit: int) -> PayloadTooLarge:
    return PayloadTooLarge(f"The file is larger than the {limit // (1024 * 1024)} MB allowed here.", limit_bytes=limit)


def receive_upload(request: Request, *, max_bytes: int, staging: Path) -> ReceivedUpload:
    content_type = request.headers.get("content-type", "")
    ctype, params = parse_options_header(content_type)
    if ctype.strip().lower() != b"multipart/form-data" or b"boundary" not in params:
        raise UnsupportedMediaType("Upload the file as multipart/form-data.", reason="multipart_required")
    declared_length = request.headers.get("content-length")
    if declared_length is not None:
        try:
            if int(declared_length) > max_bytes + MULTIPART_OVERHEAD:
                raise _too_large(max_bytes)
        except ValueError:
            raise ValidationFailed("Invalid Content-Length header.") from None

    fd, tmp_name = tempfile.mkstemp(prefix="upload-", suffix=".part", dir=staging)
    sink = os.fdopen(fd, "wb")
    state: dict[str, Any] = {"part": None, "files": 0, "size": 0, "head": bytearray(), "field": b"", "hfield": b""}
    digest = hashlib.sha256()
    result: dict[str, Any] = {}

    def on_part_begin() -> None:
        state["part"] = _Part()

    def on_header_field(data: bytes, start: int, end: int) -> None:
        state["hfield"] += data[start:end]

    def on_header_value(data: bytes, start: int, end: int) -> None:
        part: _Part = state["part"]
        name = state["hfield"].lower()
        part.headers[name] = part.headers.get(name, b"") + data[start:end]

    def on_header_end() -> None:
        state["hfield"] = b""

    def on_headers_finished() -> None:
        part: _Part = state["part"]
        _disp, options = parse_options_header(part.headers.get(b"content-disposition", b""))
        part.name = options.get(b"name", b"").decode("utf-8", errors="replace")
        raw_filename = options.get(b"filename")
        if raw_filename is not None:
            part.is_file = True
            part.filename = raw_filename.decode("utf-8", errors="replace")
            state["files"] += 1
            if part.name != "file" or state["files"] > 1:
                raise ValidationFailed(
                    "Send exactly one file in a part named 'file'.",
                    errors=[{"loc": ["body", "file"], "msg": "exactly one file part", "code": "one_file_required"}],
                )
            ctype_header = part.headers.get(b"content-type")
            result["declared_content_type"] = (
                ctype_header.decode("latin-1")[:120] if ctype_header else None
            )
            result["filename"] = part.filename

    def on_part_data(data: bytes, start: int, end: int) -> None:
        part: _Part = state["part"]
        chunk = data[start:end]
        if part.is_file:
            state["size"] += len(chunk)
            if state["size"] > max_bytes:
                raise _too_large(max_bytes)
            digest.update(chunk)
            head: bytearray = state["head"]
            if len(head) < HEAD_BYTES:
                head.extend(chunk[: HEAD_BYTES - len(head)])
            sink.write(chunk)
        else:
            state["field"] += chunk
            if len(state["field"]) > 4096:
                raise ValidationFailed("Unexpected form field.")

    def on_part_end() -> None:
        state["field"] = b""

    callbacks: Any = {
        "on_part_begin": on_part_begin,
        "on_part_data": on_part_data,
        "on_part_end": on_part_end,
        "on_header_field": on_header_field,
        "on_header_value": on_header_value,
        "on_header_end": on_header_end,
        "on_headers_finished": on_headers_finished,
    }
    stream = request.stream()

    async def _next_chunk() -> bytes | None:
        try:
            return await stream.__anext__()
        except StopAsyncIteration:
            return None

    received_total = 0
    try:
        parser = MultipartParser(params[b"boundary"], callbacks)
        while True:
            chunk = anyio.from_thread.run(_next_chunk)
            if chunk is None:
                break
            if not chunk:
                continue
            received_total += len(chunk)
            if received_total > max_bytes + MULTIPART_OVERHEAD:
                raise _too_large(max_bytes)
            parser.write(chunk)
        parser.finalize()
        sink.close()
    except BaseException:
        sink.close()
        Path(tmp_name).unlink(missing_ok=True)
        raise
    if "filename" not in result:
        Path(tmp_name).unlink(missing_ok=True)
        raise ValidationFailed(
            "No file was sent.",
            errors=[{"loc": ["body", "file"], "msg": "a file part named 'file' is required", "code": "missing"}],
        )
    return ReceivedUpload(
        path=Path(tmp_name),
        size=state["size"],
        sha256=digest.hexdigest(),
        filename=result["filename"],
        declared_content_type=result.get("declared_content_type"),
        head=bytes(state["head"]),
    )
