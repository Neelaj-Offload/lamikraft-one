"""Dry-run analysers for the catalogue collections, on the import workbench's value rules.

``category_taxonomy``, ``products_master``, ``pricing``, ``packaging``, ``specifications``, ``media`` and
``lookup_reference`` are normalised by the matching ``ImportDefinition.normalise`` (header aliases, identifier and
decimal rules, packaging alias reconciliation ``ALIAS_CONFLICT``, ``PRICE_AMBIGUOUS``, blank currency/price type
quarantined unless a default is confirmed). On top of the row rules the dry run checks the export as a whole:

- duplicate identities (same natural key, different content) -> every row quarantined (``DUPLICATE_IDENTITY``;
  pricing: ``PRICE_AMBIGUOUS``); exact repeats are reported once (``DUPLICATE_IDENTICAL``);
- product keys that differ only by case or spacing -> quarantined (``KEY_CASE_COLLISION``);
- display SKUs are not identities: shared ones are preserved and reported (``DISPLAY_SKU_SHARED``, info);
- rows for a product that is neither in the export nor in the catalogue -> ``ORPHAN_PRODUCT`` (quarantine);
- products whose category is neither in the taxonomy export nor in the catalogue -> ``TAXONOMY_UNKNOWN`` (warning);
- media: a location inside the export is hashed (sha256, size); a missing file is ``MEDIA_INACCESSIBLE``, a remote
  link that was not fetched ``MEDIA_NOT_FETCHED`` (both warnings: the row can still become reference media), a path
  leaving the export ``MEDIA_PATH_OUTSIDE_EXPORT`` (quarantine).
"""

from __future__ import annotations

import hashlib
import mimetypes
from collections import Counter, defaultdict
from collections.abc import Callable
from typing import Any

from sqlalchemy import select

from app.modules.imports.definitions import definition
from app.modules.imports.definitions.base import Issue, Prepared
from app.modules.imports.headers import analyse_headers, suggest_mapping
from app.modules.migration.analysis import (
    INFO,
    QUARANTINE,
    WARNING,
    Analysis,
    fold_key,
    group_duplicates,
)
from app.modules.migration.sources import SourceRow, as_text, media_path

MAX_REMOTE_MEDIA = 25 * 1024 * 1024

#: legacy collection -> import type
IMPORT_TYPES = {
    "category_taxonomy": "category_taxonomy",
    "products_master": "products_master",
    "pricing": "pricing",
    "packaging": "packaging",
    "specifications": "specifications",
    "media": "media",
    "lookup_reference": "lookup_reference",
}


def _mapping(an: Analysis, entity: str, rows: list[SourceRow], import_type: str) -> dict[str, str | None]:
    headers: list[str] = []
    for row in rows:
        for k in row.values:
            if k not in headers and k != "_id":
                headers.append(k)
    infos, collisions = analyse_headers(headers)
    mapping = suggest_mapping(infos, definition(import_type).field_spellings(), collisions)
    for norm, originals in collisions.items():
        an.add(
            None,
            entity,
            "HEADER_COLLISION",
            WARNING,
            f"Columns {', '.join(originals)} collide as {norm}; ignored",
            field_name=norm,
        )
    unmapped = sorted(h for h, f in mapping.items() if f is None)
    if unmapped:
        an.report.setdefault("unmapped_columns", {})[entity] = unmapped
    return mapping


def _values(row: SourceRow, mapping: dict[str, str | None]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    extra: dict[str, str] = {}
    for header, raw in row.values.items():
        if header == "_id":
            continue
        text = as_text(raw)
        target = mapping.get(header)
        if target:
            values[target] = text
        elif text and text.strip():
            extra[header] = text
    values["__extra__"] = extra
    values["__cleared__"] = []
    return values


def _existing_product_keys(an: Analysis) -> set[str]:
    from app.modules.catalogue.models import Product

    return set(an.uow.session.scalars(select(Product.product_key)))


def _existing_categories(an: Analysis) -> set[str]:
    from app.modules.catalogue.models import Category

    return set(an.uow.session.scalars(select(Category.name_key)))


def analyse_entity(
    an: Analysis,
    entity: str,
    *,
    duplicate_code: str = "DUPLICATE_IDENTITY",
    row_checks: Callable[[Analysis, SourceRow, Prepared], list[Issue]] | None = None,
) -> None:
    rows = an.source.rows(entity)
    if not rows:
        return
    import_type = IMPORT_TYPES[entity]
    defn = definition(import_type)
    mapping = _mapping(an, entity, rows, import_type)
    options = an.options.for_definitions()
    prepared: dict[int, Prepared] = {}
    for row in rows:
        prepared[row.row_number] = defn.normalise(_values(row, mapping), options)
    unique, conflicts, repeats = group_duplicates(rows, lambda r: prepared[r.row_number].key)
    if entity == "products_master":
        folded: dict[str, set[str]] = defaultdict(set)
        for _row, key in unique:
            if key:
                folded[fold_key(key)].add(key)
        clashing = {k for keys in folded.values() if len(keys) > 1 for k in keys}
    else:
        clashing = set()
    for key, group in conflicts.items():
        for row in group:
            p = prepared[row.row_number]
            issue = Issue(
                duplicate_code,
                QUARANTINE,
                f"{len(group)} rows share the key {key} with different values; "
                "none is migrated until one is chosen",
                None,
                key,
            )
            extra = row_checks(an, row, p) if row_checks else []
            an.settle(row, entity, key, [*p.issues, *extra, issue], values=p.values)
    for row, key in repeats:
        an.duplicate(row, entity, key)
    for row, key in unique:
        p = prepared[row.row_number]
        issues = list(p.issues)
        if key in clashing:
            issues.append(
                Issue(
                    "KEY_CASE_COLLISION",
                    QUARANTINE,
                    f"product_key {key} differs from another key only by case or spacing",
                    "product_key",
                    key,
                )
            )
        if row_checks:
            issues.extend(row_checks(an, row, p))
        an.settle(row, entity, key, issues, business_key=_business_key(entity, p), values=p.values)


def _business_key(entity: str, p: Prepared) -> str | None:
    v = p.values
    if entity == "products_master":
        return v.get("display_sku") or v.get("product_key")
    return p.key


# ---- per-entity checks ---------------------------------------------------------------------------------------------
def _known_products(an: Analysis) -> set[str]:
    cached = an.cache.get("known_products")
    if cached is None:
        cached = an.seen["products_master"] | _existing_product_keys(an)
        an.cache["known_products"] = cached
    return cached  # type: ignore[no-any-return]


def _orphan_check(an: Analysis, row: SourceRow, p: Prepared) -> list[Issue]:
    key = p.values.get("product_key")
    if key and key not in _known_products(an):
        return [
            Issue(
                "ORPHAN_PRODUCT",
                QUARANTINE,
                f"product {key} is neither in the export nor in the catalogue",
                "product_key",
                key,
            )
        ]
    return []


def _taxonomy_check(an: Analysis, row: SourceRow, p: Prepared) -> list[Issue]:
    from app.modules.catalogue.service import name_key

    known = an.cache.get("known_categories")
    if known is None:
        known = {k.split("|", 1)[0] for k in an.seen["category_taxonomy"]} | _existing_categories(an)
        an.cache["known_categories"] = known
    category = p.values.get("category")
    if category and name_key(category) not in known:
        return [
            Issue(
                "TAXONOMY_UNKNOWN",
                WARNING,
                f"category '{category}' is not in the taxonomy export or the "
                "catalogue (it would be created by the products import)",
                "category",
                category,
            )
        ]
    return []


def _fetch(url: str) -> tuple[str, int] | str:
    import httpx

    try:
        h = hashlib.sha256()
        size = 0
        with httpx.stream("GET", url, timeout=20.0, follow_redirects=True) as response:
            if response.status_code != 200:
                return f"http_{response.status_code}"
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > MAX_REMOTE_MEDIA:
                    return "too_large"
                h.update(chunk)
        return h.hexdigest(), size
    except httpx.HTTPError as exc:
        return type(exc).__name__


def _media_check(an: Analysis, row: SourceRow, p: Prepared) -> list[Issue]:
    issues = _orphan_check(an, row, p)
    v = p.values
    location = v.get("location")
    media = an.report.setdefault(
        "media", {"accessible": 0, "inaccessible": [], "not_fetched": 0, "files": []}
    )
    if not location or v.get("location_key") is None:
        return issues
    lower = str(location).lower()
    if lower.startswith(("http://", "https://")) or str(v.get("location_key", "")).startswith("gdrive:"):
        if an.options.fetch_media and lower.startswith(("http://", "https://")):
            got = _fetch(str(location))
            if isinstance(got, tuple):
                v["file"] = {"sha256": got[0], "size": got[1], "remote": True}
                media["accessible"] += 1
                media["files"].append({"source_key": p.key, "sha256": got[0], "bytes": got[1]})
                return issues
            media["inaccessible"].append(
                {"source_key": p.key, "location": str(location)[:300], "reason": got}
            )
            issues.append(
                Issue(
                    "MEDIA_INACCESSIBLE",
                    WARNING,
                    f"The link could not be downloaded ({got})",
                    "file_url",
                    str(location)[:500],
                )
            )
            return issues
        media["not_fetched"] += 1
        issues.append(
            Issue(
                "MEDIA_NOT_FETCHED",
                WARNING,
                "A remote link: not downloaded in this run (run with "
                "--fetch-media for authorised links; Drive links need an authorised export)",
                "file_url",
                str(location)[:500],
            )
        )
        return issues
    path = media_path(an.source.root, str(location))
    if path is None:
        issues.append(
            Issue(
                "MEDIA_PATH_OUTSIDE_EXPORT",
                QUARANTINE,
                "The media path leaves the export directory",
                "file_path",
                str(location)[:500],
            )
        )
        return issues
    if not path.is_file():
        media["inaccessible"].append(
            {"source_key": p.key, "location": str(location)[:300], "reason": "missing"}
        )
        issues.append(
            Issue(
                "MEDIA_INACCESSIBLE",
                WARNING,
                "The media file is not in the export",
                "file_path",
                str(location)[:500],
            )
        )
        return issues
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    relative = path.relative_to(an.source.root.resolve()).as_posix()
    v["file"] = {
        "path": relative,
        "sha256": digest,
        "size": len(data),
        "content_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
    }
    media["accessible"] += 1
    media["files"].append({"source_key": p.key, "path": relative, "sha256": digest, "bytes": len(data)})
    return issues


def analyse_catalogue(an: Analysis) -> None:
    analyse_entity(an, "category_taxonomy")
    analyse_entity(an, "products_master", row_checks=_taxonomy_check)
    _shared_display_skus(an)
    analyse_entity(an, "pricing", duplicate_code="PRICE_AMBIGUOUS", row_checks=_orphan_check)
    analyse_entity(an, "packaging", row_checks=_orphan_check)
    analyse_entity(an, "specifications", row_checks=_orphan_check)
    analyse_entity(an, "media", row_checks=_media_check)
    analyse_entity(an, "lookup_reference")
    _pricing_totals(an)


def _shared_display_skus(an: Analysis) -> None:
    skus: dict[str, list[str]] = defaultdict(list)
    for key, acc in an.accepted["products_master"].items():
        sku = acc.values.get("display_sku")
        if sku:
            skus[sku].append(key)
    shared = {sku: keys for sku, keys in skus.items() if len(keys) > 1}
    for sku, keys in sorted(shared.items()):
        an.add(
            None,
            "products_master",
            "DISPLAY_SKU_SHARED",
            INFO,
            f"display_sku {sku} is shared by {len(keys)} products ({', '.join(sorted(keys))}); preserved as is",
            key=sku,
            field_name="display_sku",
            raw_value=sku,
        )
    an.report["display_skus_shared"] = len(shared)


def _pricing_totals(an: Analysis) -> None:
    source: Counter[str] = Counter()
    accepted: Counter[str] = Counter()
    for row in an.source.rows("pricing"):
        cur = (as_text(row.values.get("currency")) or "").strip().upper() or "(blank)"
        source[cur] += 1
    for acc in an.accepted["pricing"].values():
        accepted[str(acc.values.get("currency") or "(blank)")] += 1
    an.report["pricing_rows_by_currency"] = {
        cur: {"source_rows": source[cur], "accepted": accepted.get(cur, 0)}
        for cur in sorted(source | accepted)
    }


__all__ = ["IMPORT_TYPES", "analyse_catalogue", "analyse_entity"]
