"""Storage backends. ``local_fs`` (``LK_STORAGE_DIR``) is the default; ``s3`` (``LK_STORAGE_BACKEND=s3``, boto3,
any S3-compatible endpoint via ``LK_S3_ENDPOINT_URL``) implements the same ``StorageBackend`` protocol and shares its
contract tests (moto). Credentials come from the standard AWS environment / profile chain, never from settings.
Downloads always stream through the backend: no presigned URLs.

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


class S3Storage:
    """Objects in one bucket under the same random keys; reads stream from the response body."""

    name = "s3"

    def __init__(self, bucket: str, *, endpoint_url: str | None = None, region: str | None = None, client: object | None = None) -> None:
        if not bucket:
            raise NotConfigured("Set LK_S3_BUCKET to use the S3 storage backend.", code="not_configured")
        self.bucket = bucket
        if client is None:
            import boto3

            client = boto3.client("s3", endpoint_url=endpoint_url or None, region_name=region or None)
        self._s3 = client

    @staticmethod
    def _key(key: str) -> str:
        if not _KEY.match(key):
            raise ValueError("invalid storage key")
        return key

    def put_file(self, key: str, source: Path) -> None:
        with Path(source).open("rb") as fh:
            self._s3.put_object(Bucket=self.bucket, Key=self._key(key), Body=fh)  # type: ignore[attr-defined]
        Path(source).unlink(missing_ok=True)

    def open(self, key: str) -> BinaryIO:
        try:
            body = self._s3.get_object(Bucket=self.bucket, Key=self._key(key))["Body"]  # type: ignore[attr-defined]
        except Exception as exc:  # botocore ClientError NoSuchKey -> the same error as a missing local file
            if _missing(exc):
                raise FileNotFoundError(key) from None
            raise
        return body  # type: ignore[no-any-return]  # StreamingBody: read(n), close(), context manager

    def exists(self, key: str) -> bool:
        try:
            self._s3.head_object(Bucket=self.bucket, Key=self._key(key))  # type: ignore[attr-defined]
        except Exception as exc:
            if _missing(exc):
                return False
            raise
        return True

    def delete(self, key: str) -> None:
        self._s3.delete_object(Bucket=self.bucket, Key=self._key(key))  # type: ignore[attr-defined]


def _missing(exc: Exception) -> bool:
    code = str(getattr(exc, "response", {}).get("Error", {}).get("Code", ""))
    return code in {"404", "NoSuchKey", "NotFound"}


_lock = threading.Lock()
_backend: StorageBackend | None = None


def get_storage() -> StorageBackend:
    global _backend
    with _lock:
        if _backend is None:
            settings = get_settings()
            if settings.storage_backend == "s3":
                _backend = S3Storage(settings.s3_bucket or "", endpoint_url=settings.s3_endpoint_url, region=settings.s3_region)
            else:
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
