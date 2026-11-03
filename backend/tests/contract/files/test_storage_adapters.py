"""Storage adapter contract (PARITY DEBT-06): local_fs and s3 (boto3 against moto) behave identically."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.core.config import get_settings, reset_settings_cache
from app.core.errors import NotConfigured
from app.platform.files import storage as storage_mod
from app.platform.files.storage import LocalFsStorage, S3Storage, new_storage_key


@pytest.fixture(params=["local_fs", "s3"])
def backend(request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[object]:
    if request.param == "local_fs":
        yield LocalFsStorage(tmp_path / "root")
        return
    from moto import mock_aws

    for name, value in (("AWS_ACCESS_KEY_ID", "testing"), ("AWS_SECRET_ACCESS_KEY", "testing"), ("AWS_DEFAULT_REGION", "ap-south-1")):
        monkeypatch.setenv(name, value)
    with mock_aws():
        import boto3

        boto3.client("s3", region_name="ap-south-1").create_bucket(
            Bucket="lk-test", CreateBucketConfiguration={"LocationConstraint": "ap-south-1"}
        )
        yield S3Storage("lk-test", region="ap-south-1")


def _staged(tmp_path: Path, data: bytes) -> Path:
    path = tmp_path / f"stage-{uuid.uuid4().hex}"
    path.write_bytes(data)
    return path


def test_local_fs_and_s3_moto_same_contract(backend, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    key = new_storage_key(uuid.uuid7())
    assert backend.exists(key) is False
    data = b"%PDF-1.7 " + bytes(range(256)) * 300  # binary and larger than one read chunk
    staged = _staged(tmp_path, data)
    backend.put_file(key, staged)
    assert not staged.exists()  # the staging file is consumed (moved or uploaded)
    assert backend.exists(key) is True
    with backend.open(key) as fh:
        chunks = []
        while chunk := fh.read(64 * 1024):
            chunks.append(chunk)
    assert b"".join(chunks) == data
    # overwrite under the same key, then delete (idempotent)
    backend.put_file(key, _staged(tmp_path, b"second"))
    with backend.open(key) as fh:
        assert fh.read() == b"second"
    backend.delete(key)
    backend.delete(key)
    assert backend.exists(key) is False
    with pytest.raises(FileNotFoundError):
        backend.open(key)


def test_keys_are_validated_by_every_backend(backend) -> None:  # type: ignore[no-untyped-def]
    for bad in ("../etc/passwd", "a/b/c", f"{uuid.uuid7()}/00/../../x"):
        with pytest.raises(ValueError):
            backend.exists(bad)


def test_s3_backend_is_selected_by_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LK_STORAGE_BACKEND", "s3")
    monkeypatch.setenv("LK_S3_BUCKET", "")
    reset_settings_cache()
    storage_mod.set_storage(None)
    try:
        with pytest.raises(NotConfigured):
            storage_mod.get_storage()
        monkeypatch.setenv("LK_S3_BUCKET", "lk-bucket")
        monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-south-1")
        reset_settings_cache()
        chosen = storage_mod.get_storage()
        assert isinstance(chosen, S3Storage) and chosen.bucket == "lk-bucket"
        assert get_settings().storage_backend == "s3"
    finally:
        monkeypatch.delenv("LK_STORAGE_BACKEND")
        monkeypatch.delenv("LK_S3_BUCKET")
        reset_settings_cache()
        storage_mod.set_storage(None)
