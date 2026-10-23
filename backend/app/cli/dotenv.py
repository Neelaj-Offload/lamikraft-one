"""A small dotenv reader/writer whose output parses identically in python-dotenv, Docker Compose and
``scripts/lib/env.mjs``.

Values are written unquoted when they only contain safe characters, otherwise single-quoted
(literal in all three parsers). Paths are written with forward slashes so no backslash escapes
are ever involved.
"""

from __future__ import annotations

import os
import re
import secrets
from collections.abc import Iterable
from pathlib import Path

_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_SAFE_UNQUOTED = re.compile(r"[A-Za-z0-9_\-.:/+=@,%]*")
_DOUBLE_QUOTED_ESCAPES = {"n": "\n", "r": "\r", "t": "\t", '"': '"', "\\": "\\", "'": "'"}


def parse(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        key, sep, rest = line.partition("=")
        key = key.strip()
        if not sep or not _KEY.fullmatch(key):
            continue
        values[key] = _parse_value(rest.strip())
    return values


def _parse_value(value: str) -> str:
    if value.startswith("'"):
        end = value.find("'", 1)
        return value[1:end] if end != -1 else value[1:]
    if value.startswith('"'):
        chars: list[str] = []
        i = 1
        while i < len(value):
            ch = value[i]
            if ch == "\\" and i + 1 < len(value):
                nxt = value[i + 1]
                chars.append(_DOUBLE_QUOTED_ESCAPES.get(nxt, "\\" + nxt))
                i += 2
                continue
            if ch == '"':
                break
            chars.append(ch)
            i += 1
        return "".join(chars)
    comment = re.search(r"\s#", value)
    return (value[: comment.start()] if comment else value).rstrip()


def format_value(value: str) -> str:
    if "\n" in value or "\r" in value:
        raise ValueError("multi-line values are not supported in .env files")
    if _SAFE_UNQUOTED.fullmatch(value):
        return value
    if "'" not in value:
        return f"'{value}'"
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def read(path: Path) -> dict[str, str]:
    return parse(path.read_text(encoding="utf-8")) if path.is_file() else {}


Section = tuple[str | None, Iterable[tuple[str, str]]]


def render(header: Iterable[str], sections: Iterable[Section]) -> str:
    lines = [f"# {h}".rstrip() for h in header]
    for title, entries in sections:
        lines.append("")
        if title:
            lines.append(f"# --- {title} ---")
        for key, value in entries:
            if not _KEY.fullmatch(key):
                raise ValueError(f"invalid environment variable name: {key!r}")
            lines.append(f"{key}={format_value(value)}")
    return "\n".join(lines) + "\n"


def write_private(path: Path, content: str, *, exclusive: bool) -> bool:
    """Write a secrets file readable only by the current user (POSIX mode 0600; on Windows the
    user-profile ACL applies). With ``exclusive`` the file must not exist yet: returns False if
    another process created it first. Otherwise the file is replaced atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(6)}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        if not exclusive:
            os.replace(tmp, path)
            return True
        try:
            os.link(tmp, path)  # atomic create-if-absent on NTFS and POSIX filesystems
        except FileExistsError:
            return False
        except OSError:
            try:
                fd2 = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
            except FileExistsError:
                return False
            with os.fdopen(fd2, "wb") as handle:
                handle.write(content.encode("utf-8"))
        return True
    finally:
        tmp.unlink(missing_ok=True)
