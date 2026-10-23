"""Storage backends. ``local_fs`` (``LK_STORAGE_DIR``) is the Slice-1 default; the Slice-2 ``s3`` adapter
implements the same ``StorageBackend`` protocol and shares its contract tests.

Storage keys are random (``<company_id>/<shard>/<token>``) and never derived from a filename; the backend
validates every key so a key can never escape the storage root.
"""

from __future__ import annotations

import os
import re
import secrets
import shutil
import threading
import uuid
from pathlib import Path
from typing import BinaryIO, Protocol

from app.core.config import get_settings
from app.core.errors import NotConfigured

_KEY = re.compile(r"^[0-9a-f-]{36}/[0-9a-f]{2}/[0-9a-f]{32}$")


class StorageBackend(Protocol):
    name: str

    def put_file(self, key: str, source: Path) -> None:
        """Move or copy a fully written staging file into storage under ``key``."""

    def open(self, key: str) -> BinaryIO: ...

    def exists(self, key: str) -> bool: ...

    def delete(self, key: str) -> None: ...


def new_storage_key(company_id: uuid.UUID) -> str:
    token = secrets.token_hex(16)
    return f"{company_id}/{token[:2]}/{token}"


class LocalFsStorage:
    name = "local_fs"

    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()

    def _path(self, key: str) -> Path:
        if not _KEY.match(key):
            raise ValueError("invalid storage key")
        path = (self.root / key).resolve()
        if self.root not in path.parents:
            raise ValueError("storage key escapes the storage root")
        return path

    def put_file(self, key: str, source: Path) -> None:
        dest = self._path(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        partial = dest.with_name(dest.name + ".partial")
        try:
            os.replace(source, partial)  # same volume: atomic rename of the staging file
        except OSError:
            shutil.copyfile(source, partial)
        with partial.open("r+b") as fh:
            os.fsync(fh.fileno())
        os.replace(partial, dest)

    def open(self, key: str) -> BinaryIO:
        return self._path(key).open("rb")

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)


_lock = threading.Lock()
_backend: StorageBackend | None = None


def get_storage() -> StorageBackend:
    global _backend
    with _lock:
        if _backend is None:
            settings = get_settings()
            if settings.storage_backend != "local_fs":
                raise NotConfigured(
                    "The S3 storage adapter arrives in Slice 2; set LK_STORAGE_BACKEND=local_fs.",
                    code="not_configured",
                )
            _backend = LocalFsStorage(settings.storage_dir)
        return _backend


def set_storage(backend: StorageBackend | None) -> None:
    """Tests and the CLI: replace the process-wide backend (None resets to configuration)."""
    global _backend
    with _lock:
        _backend = backend


def staging_dir() -> Path:
    """Where uploads are spooled while streaming (inside the storage root, so ``put_file`` can rename)."""
    root = getattr(get_storage(), "root", None)
    base = Path(root) if root is not None else get_settings().storage_dir
    path = base / "_staging"
    path.mkdir(parents=True, exist_ok=True)
    return path
