"""The contract every import type implements, plus the shared value rules (design §4.4, §9.1).

A type declares its fields (canonical name, accepted header spellings, required flag), its natural key and its
dependencies, and implements three steps:

- ``normalise(values, options)``: text cells -> typed, normalised values plus row issues (no database access);
- ``plan(uow, row)``: resolve dependencies against committed data (quarantine orphans) and diff against the current
  entity (insert / update / unchanged, the target id and version seen);
- ``apply(uow, row, plan)``: write through the owning module's services and return the change records rollback uses.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, ClassVar

from app.core.csv_safe import strip_guard
from app.platform.uow import UnitOfWork

ERROR, QUARANTINE, WARNING, INFO = "error", "quarantine", "warning", "info"


@dataclass(frozen=True)
class FieldSpec:
    name: str
    #: other accepted header spellings (normalised form); the canonical name is always accepted
    aliases: tuple[str, ...] = ()
    required: bool = False
    #: documented legacy alias (``True``) or a spelling the header normaliser produces (``False``)
    label: str = ""

    @property
    def spellings(self) -> tuple[str, ...]:
        return (self.name, *self.aliases)


@dataclass
class Issue:
    code: str
    severity: str
    message: str
    field: str | None = None
    raw_value: str | None = None


@dataclass
class Prepared:
    values: dict[str, Any]
    key: str | None
    issues: list[Issue] = field(default_factory=list)


@dataclass
class Plan:
    action: str  # insert | update | unchanged
    target_id: uuid.UUID | None = None
    target_version: int | None = None
    #: field -> [before, after] for display and for the row's diff
    diff: dict[str, list[Any]] = field(default_factory=dict)
    issues: list[Issue] = field(default_factory=list)
    #: free data the apply step reuses (resolved ids)
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class Change:
    entity_table: str
    entity_id: uuid.UUID
    op: str  # insert | update
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    changed_fields: list[str]
    version_after: int | None


class ImportDefinition:
    import_type: ClassVar[str]
    label: ClassVar[str]
    description: ClassVar[str] = ""
    fields: ClassVar[tuple[FieldSpec, ...]]
    depends_on: ClassVar[tuple[str, ...]] = ()
    #: entity tables this type writes (rollback handlers are looked up by table)
    writes: ClassVar[tuple[str, ...]] = ()

    def field_spellings(self) -> dict[str, tuple[str, ...]]:
        return {f.name: f.spellings for f in self.fields}

    def normalise(self, values: Mapping[str, str | None], options: Mapping[str, Any]) -> Prepared:
        raise NotImplementedError

    def plan(self, uow: UnitOfWork, prepared: Prepared, options: Mapping[str, Any]) -> Plan:
        raise NotImplementedError

    def apply(self, uow: UnitOfWork, prepared: Prepared, plan: Plan, options: Mapping[str, Any]) -> list[Change]:
        raise NotImplementedError

    def order_key(self, prepared: Prepared) -> tuple[Any, ...]:
        """Commit order within a batch run (taxonomy: categories before subcategories)."""
        return ()

    def dependency_status(self, uow: UnitOfWork) -> dict[str, Any]:
        return {}


# ---- shared value rules ------------------------------------------------------------------------------------------
def cell(values: Mapping[str, str | None], name: str, issues: list[Issue]) -> str | None:
    """The trimmed cell text or None when blank. Our own CSV formula guard (``'=...``) is removed with an info."""
    raw = values.get(name)
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    unguarded = strip_guard(text)
    if unguarded != text:
        issues.append(Issue("FORMULA_GUARD_STRIPPED", INFO, "The export's formula guard was removed", name, text[:500]))
    return unguarded


def need(values: Mapping[str, str | None], name: str, issues: list[Issue]) -> str | None:
    value = cell(values, name, issues)
    if value is None:
        issues.append(Issue("REQUIRED", ERROR, f"{name} is required", name))
    return value


_BOOL = {
    "true": True, "false": False, "yes": True, "no": False, "y": True, "n": False, "1": True, "0": False,
    "active": True, "inactive": False,
}


def as_bool(text: str | None, name: str, issues: list[Issue]) -> bool | None:
    if text is None:
        return None
    value = _BOOL.get(text.strip().casefold())
    if value is None:
        issues.append(Issue("NOT_A_BOOLEAN", ERROR, f"{name} must be yes/no, true/false or 1/0", name, text))
    return value


def as_int(text: str | None, name: str, issues: list[Issue], *, minimum: int | None = 0) -> int | None:
    if text is None:
        return None
    try:
        d = Decimal(text.replace(",", ""))
    except InvalidOperation:
        issues.append(Issue("NOT_A_NUMBER", ERROR, f"{name} must be a whole number", name, text))
        return None
    if d != d.to_integral_value():
        issues.append(Issue("NOT_INTEGER", ERROR, f"{name} must be a whole number", name, text))
        return None
    if minimum is not None and d < minimum:
        issues.append(Issue("OUT_OF_RANGE", ERROR, f"{name} must be at least {minimum}", name, text))
        return None
    return int(d)


_CURRENCY_SYMBOLS = {"€": "EUR", "₹": "INR", "$": "USD", "£": "GBP"}


def as_decimal(text: str | None, name: str, issues: list[Issue], *, positive: bool = False) -> Decimal | None:
    if text is None:
        return None
    clean = text.strip()
    for symbol in _CURRENCY_SYMBOLS:
        clean = clean.replace(symbol, "")
    clean = clean.replace(",", "").strip()
    try:
        d = Decimal(clean)
    except InvalidOperation:
        issues.append(Issue("NOT_A_NUMBER", ERROR, f"{name} must be a number", name, text))
        return None
    if not d.is_finite() or (positive and d <= 0) or d < 0:
        issues.append(Issue("OUT_OF_RANGE", ERROR, f"{name} must be {'positive' if positive else 'zero or more'}", name, text))
        return None
    return d


def currency_code(text: str | None, name: str, issues: list[Issue]) -> str | None:
    if text is None:
        return None
    value = text.strip()
    if value in _CURRENCY_SYMBOLS:
        issues.append(Issue("CURRENCY_SYMBOL_MAPPED", WARNING, f"{value} read as {_CURRENCY_SYMBOLS[value]}", name, value))
        return _CURRENCY_SYMBOLS[value]
    return value.upper()


_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SLASH = re.compile(r"^(\d{1,2})[/.](\d{1,2})[/.](\d{4})$")


def as_date(text: str | None, name: str, issues: list[Issue], *, order: str = "DMY") -> date | None:
    if text is None:
        return None
    value = text.strip()[:10] if _ISO.match(text.strip()[:10]) else text.strip()
    try:
        if _ISO.match(value):
            return date.fromisoformat(value)
        m = _SLASH.match(value)
        if m:
            a, b, y = int(m[1]), int(m[2]), int(m[3])
            day, month = (a, b) if order == "DMY" else (b, a)
            return date(y, month, day)
    except ValueError:
        pass
    issues.append(Issue("NOT_A_DATE", ERROR, f"{name} must be a date (YYYY-MM-DD or {order} with slashes)", name, text))
    return None


_STATUS = {
    "active": "active", "inactive": "inactive", "under_development": "under_development",
    "under development": "under_development", "in dev": "under_development", "in development": "under_development",
    "dev": "under_development", "discontinued": "inactive",
}


def product_status(text: str | None, issues: list[Issue]) -> str | None:
    if text is None:
        return None
    key = " ".join(text.replace("_", " ").replace("-", " ").split()).casefold()
    value = _STATUS.get(key) or _STATUS.get(key.replace(" ", "_"))
    if value is None:
        issues.append(Issue("STATUS_UNKNOWN", ERROR, "status must be active, inactive or under development", "status", text))
    return value


def compact(values: Mapping[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in values.items() if v is not None}


def jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    return value


def diff(before: Mapping[str, Any], after: Mapping[str, Any], names: Sequence[str]) -> dict[str, list[Any]]:
    """Field -> [before, after] for every named field whose JSON value differs."""
    out: dict[str, list[Any]] = {}
    for name in names:
        b, a = jsonable(before.get(name)), jsonable(after.get(name))
        if a is not None and b != a:
            out[name] = [b, a]
    return out
