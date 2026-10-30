"""``media`` (LM-33, FG-MED-03/04, BUG-12, SCN-G1): key (product_key, media_type, normalised location).

The location alias group (file_url | drive_link | file_path | storage_path) must name exactly one distinct location;
different values are quarantined ``ALIAS_CONFLICT``. Drive share links are canonicalised to ``gdrive:<id>``. Rows
become reference media (``external_only``: the location is recorded and shown, nothing is fetched); a re-import of
the same location creates no duplicate (partial unique index on product, type and location key). ``file_name`` and
``original_filename`` are both kept; a difference is a warning. A blank media type is inferred from the extension.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import select

from app.modules.catalogue.models import ProductMedia
from app.modules.imports.definitions.base import (
    ERROR,
    QUARANTINE,
    WARNING,
    Change,
    FieldSpec,
    ImportDefinition,
    Issue,
    Plan,
    Prepared,
    cell,
    need,
)
from app.modules.imports.definitions.sections import find_product, orphan
from app.platform.uow import UnitOfWork

LOCATIONS = ("file_url", "drive_link", "file_path", "storage_path")
MEDIA_TYPES = ("image", "document", "packaging_photo")
_IMAGE_EXT = (".jpg", ".jpeg", ".png", ".gif", ".webp")
_DRIVE = (re.compile(r"drive\.google\.com/file/d/([\w-]+)"), re.compile(r"drive\.google\.com/.*[?&]id=([\w-]+)"))


def location_key(text: str) -> str:
    for pattern in _DRIVE:
        m = pattern.search(text)
        if m:
            return f"gdrive:{m.group(1)}"
    if text.lower().startswith(("http://", "https://")):
        parts = urlsplit(text)
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, parts.query, ""))
    return text.replace("\\", "/").strip()


class MediaMaster(ImportDefinition):
    import_type = "media"
    label = "Media"
    description = "Image, document and packaging-photo locations per product (recorded as reference media)."
    fields = (
        FieldSpec("product_key", required=True),
        FieldSpec("media_type", aliases=("type",)),
        *(FieldSpec(n, aliases=("url",) if n == "file_url" else ()) for n in LOCATIONS),
        FieldSpec("file_name"),
        FieldSpec("original_filename"),
        FieldSpec("alt_text"),
        FieldSpec("source_catalog_page"),
        FieldSpec("legacy_media_id", aliases=("id", "media_id")),
    )
    depends_on = ("products_master",)
    writes = ("catalogue_product_media",)

    def normalise(self, values: Mapping[str, str | None], options: Mapping[str, Any]) -> Prepared:
        issues: list[Issue] = []
        key = need(values, "product_key", issues)
        raw = {n: cell(values, n, issues) for n in LOCATIONS}
        present = {n: v for n, v in raw.items() if v}
        keys = {location_key(v) for v in present.values()}
        loc_key: str | None = None
        if not present:
            issues.append(Issue("LOCATION_MISSING", ERROR, "No file_url, drive_link, file_path or storage_path",
                                "file_url"))
        elif len(keys) > 1:
            shown = ", ".join(f"{k}={v}" for k, v in sorted(present.items()))
            issues.append(Issue("ALIAS_CONFLICT", QUARANTINE, f"Location values disagree: {shown}", "file_url", shown))
        else:
            loc_key = next(iter(keys))
        file_name = cell(values, "file_name", issues)
        original = cell(values, "original_filename", issues)
        if file_name and original and file_name != original:
            issues.append(Issue("FILENAME_DIFFERS", WARNING, "file_name and original_filename differ; both kept",
                                "original_filename", original))
        media_type = (cell(values, "media_type", issues) or "").strip().lower().replace(" ", "_") or None
        if media_type is None:
            name = (file_name or original or (next(iter(present.values())) if present else "")).lower()
            media_type = "image" if name.endswith(_IMAGE_EXT) else "document"
            issues.append(Issue("MEDIA_TYPE_INFERRED", WARNING, f"media_type inferred as {media_type}", "media_type"))
        elif media_type not in MEDIA_TYPES:
            issues.append(Issue("MEDIA_TYPE_UNKNOWN", ERROR, f"media_type '{media_type}' is not known", "media_type",
                                media_type))
        out = {
            "product_key": key, "media_type": media_type, "location_key": loc_key,
            "location": next(iter(present.values())) if present else None,
            "file_name": file_name or original, "original_filename": original or file_name,
            "alt_text": cell(values, "alt_text", issues), "source_catalog_page": cell(values, "source_catalog_page", issues),
            "legacy_media_id": cell(values, "legacy_media_id", issues),
        }
        natural = f"{key}|{media_type}|{loc_key}" if key and loc_key else None
        return Prepared(values=out, key=natural, issues=issues)

    def plan(self, uow: UnitOfWork, prepared: Prepared, options: Mapping[str, Any]) -> Plan:
        v = prepared.values
        product = find_product(uow, v["product_key"])
        if product is None:
            return orphan(v["product_key"])
        existing = uow.session.scalars(
            select(ProductMedia).where(
                ProductMedia.product_id == product.id,
                ProductMedia.media_type == v["media_type"],
                ProductMedia.source_url_key == v["location_key"],
                ProductMedia.deleted_at.is_(None),
            )
        ).first()
        if existing is not None:
            return Plan("unchanged", existing.id, existing.version, {})
        return Plan("insert", None, None, {"location": [None, v["location"]]}, context={"product_id": str(product.id)})

    def apply(self, uow: UnitOfWork, prepared: Prepared, plan: Plan, options: Mapping[str, Any]) -> list[Change]:
        uow.actor.require("catalogue.media.manage")
        v = prepared.values
        is_url = str(v["location"]).lower().startswith(("http://", "https://")) or v["location_key"].startswith("gdrive:")
        media = ProductMedia(
            id=uuid.uuid7(),
            company_id=uow.actor.company_id,
            product_id=uuid.UUID(plan.context["product_id"]),
            media_type=v["media_type"],
            file_name=(v["file_name"] or "")[:255] or None,
            original_filename=(v["original_filename"] or "")[:255] or None,
            alt_text=v["alt_text"],
            is_primary=False,
            sort_order=0,
            source_kind="import_url" if is_url else "import_reference",
            source_url_key=v["location_key"][:1000],
            source_path=str(v["location"])[:1000],
            ingest_status="external_only",
            source_catalog_page=v["source_catalog_page"],
            legacy_media_id=v["legacy_media_id"],
            import_job_id=options.get("job_id"),
            uploaded_by=uow.actor.user_id,
            uploaded_at=uow.now(),
        )
        uow.add(media)
        uow.flush()
        return [Change("catalogue_product_media", media.id, "insert", None, {"source_url_key": media.source_url_key},
                       ["source_url_key"], media.version)]
