"""Header normalisation (LM-39, design §9.2): strip the BOM, NFKC, casefold, collapse every run of non-alphanumeric
characters to ``_`` and trim ``_``. ``"Unit Weight (g)"`` -> ``unit_weight_g``; ``"Plate 1 Size (mm)"`` ->
``plate_1_size_mm`` (an alias of ``plate1_size_mm``). Headers that collide after normalisation need explicit mapping.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

_NON_ALNUM = re.compile(r"[^0-9a-z]+")


def normalise_header(text: str) -> str:
    value = unicodedata.normalize("NFKC", (text or "").replace("﻿", "")).casefold()
    return _NON_ALNUM.sub("_", value).strip("_")


@dataclass(frozen=True)
class HeaderInfo:
    index: int
    original: str
    normalised: str


def analyse_headers(headers: Sequence[str]) -> tuple[list[HeaderInfo], dict[str, list[str]]]:
    """(header infos, collisions: normalised -> the original headers sharing it)."""
    infos = [HeaderInfo(i, h, normalise_header(h)) for i, h in enumerate(headers)]
    groups: dict[str, list[str]] = {}
    for info in infos:
        if info.normalised:
            groups.setdefault(info.normalised, []).append(info.original)
    return infos, {k: v for k, v in groups.items() if len(v) > 1}


def suggest_mapping(
    infos: Sequence[HeaderInfo], fields: Mapping[str, Sequence[str]], collisions: Mapping[str, Sequence[str]]
) -> dict[str, str | None]:
    """original header -> field name (by normalised name or documented alias), or None (ignored / unknown).

    ``fields`` maps a field name to its accepted normalised spellings (the name itself first). Colliding headers are
    left unmapped (``HEADER_COLLISION``) so the admin decides explicitly.
    """
    by_alias: dict[str, str] = {}
    for name, spellings in fields.items():
        for spelling in spellings:
            by_alias.setdefault(normalise_header(spelling), name)
    out: dict[str, str | None] = {}
    taken: set[str] = set()
    for info in infos:
        field = by_alias.get(info.normalised)
        if info.normalised in collisions or field is None or field in taken:
            out[info.original] = None
            continue
        out[info.original] = field
        taken.add(field)
    return out
