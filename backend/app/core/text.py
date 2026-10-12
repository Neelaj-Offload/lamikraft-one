"""Text helpers. User input never becomes a regex; LIKE patterns are always escaped."""

from __future__ import annotations

import re
import unicodedata

LIKE_ESCAPE = "\\"


def escape_like(term: str) -> str:
    """Escape ``%``, ``_`` and the escape char so a user term matches literally in ILIKE."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def contains_pattern(term: str) -> str:
    return f"%{escape_like(term)}%"


def normalize_email(email: str) -> str:
    return unicodedata.normalize("NFKC", email).strip().lower()


def normalize_search_text(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text)
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", folded).strip().lower()


def tokens(text: str, max_tokens: int = 8) -> list[str]:
    return [t for t in normalize_search_text(text).split(" ") if t][:max_tokens]
