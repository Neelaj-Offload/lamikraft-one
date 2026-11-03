"""Image variants: ``thumb`` (fits 256 px) and ``medium`` (fits 1024 px), re-encoded with Pillow.

Re-encoding drops EXIF and every other metadata block (GPS, camera serials). PNG, GIF and WebP sources become PNG
(transparency kept), JPEG stays JPEG. A variant is never larger than its source: when the source already fits, the
variant is a clean re-encode at the source size. Variants are created when an image is attached (idempotent per
file and variant) and served by ``GET /api/v1/files/{id}/content?variant=thumb|medium`` under the source file's
authorisation. Decompression bombs are refused by the same pixel guard as uploads.
"""

from __future__ import annotations

import hashlib
import io
import os
import tempfile
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image, ImageOps
from sqlalchemy import select

from app.platform.files.models import FileObject, FileVariant
from app.platform.files.sniff import MAX_IMAGE_PIXELS
from app.platform.files.storage import get_storage, new_storage_key, staging_dir

if TYPE_CHECKING:
    from app.platform.uow import UnitOfWork

VARIANTS: dict[str, int] = {"thumb": 256, "medium": 1024}
IMAGE_KINDS = frozenset({"png", "jpeg", "gif", "webp"})


def render(data: bytes, max_side: int) -> tuple[bytes, str, int, int]:
    """(bytes, content type, width, height) of a metadata-free rendition fitting ``max_side``."""
    with Image.open(io.BytesIO(data)) as src:
        if src.width * src.height > MAX_IMAGE_PIXELS:
            raise ValueError("image too large to render")
        src.seek(0)
        img = ImageOps.exif_transpose(src)  # keep the visible orientation, then drop the EXIF block
        fmt = "JPEG" if src.format == "JPEG" else "PNG"
        if fmt == "JPEG":
            img = img.convert("RGB")
        elif img.mode not in ("RGB", "RGBA", "L", "LA"):
            img = img.convert("RGBA")
        img.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        if fmt == "JPEG":
            img.save(out, format="JPEG", quality=85, optimize=True)
        else:
            img.save(out, format="PNG", optimize=True)
        return out.getvalue(), "image/jpeg" if fmt == "JPEG" else "image/png", img.width, img.height


def ensure_variants(uow: UnitOfWork, file: FileObject) -> list[FileVariant]:
    """Create the missing variants of an image file inside the caller's unit of work."""
    from app.platform.files.service import _delete_unless_committed

    if file.kind not in IMAGE_KINDS:
        return []
    have = {v.variant: v for v in uow.session.scalars(select(FileVariant).where(FileVariant.file_id == file.id))}
    missing = [name for name in VARIANTS if name not in have]
    if not missing:
        return list(have.values())
    storage = get_storage()
    with storage.open(file.storage_key) as fh:
        data = fh.read()
    for name in missing:
        try:
            blob, content_type, width, height = render(data, VARIANTS[name])
        except (OSError, ValueError):
            return list(have.values())  # an unreadable image keeps its original only
        fd, tmp = tempfile.mkstemp(prefix="variant-", suffix=".part", dir=staging_dir())
        try:
            with os.fdopen(fd, "wb") as out:
                out.write(blob)
            key = new_storage_key(file.company_id)
            storage.put_file(key, Path(tmp))
        finally:
            Path(tmp).unlink(missing_ok=True)
        _delete_unless_committed(uow, storage, key)
        row = FileVariant(
            id=uuid.uuid7(),
            company_id=file.company_id,
            file_id=file.id,
            variant=name,
            storage_backend=storage.name,
            storage_key=key,
            content_type=content_type,
            sha256=hashlib.sha256(blob).hexdigest(),
            size_bytes=len(blob),
            width=width,
            height=height,
            created_at=uow.now(),
        )
        uow.add(row)
        have[name] = row
    uow.flush()
    return list(have.values())


def variant_of(uow: UnitOfWork, file_id: uuid.UUID, name: str) -> FileVariant | None:
    return uow.session.scalars(select(FileVariant).where(FileVariant.file_id == file_id, FileVariant.variant == name)).first()
