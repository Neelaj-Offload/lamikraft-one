"""The dry-run analysis: findings, planned ID-map rows and counts per legacy entity (no domain data is written).

Every analyser turns source rows into one outcome per row:

- ``accepted`` (valid or with warnings): would be migrated;
- ``quarantined``: kept out until a person resolves it (alias conflicts, ambiguous prices, duplicate identities,
  orphans, unknown statuses) - the original values stay in the issue;
- ``rejected``: not readable as the entity (missing key, non-numbers);
- ``duplicate_identical``: an exact repeat of an accepted row (reported, not migrated twice).

Catalogue entities reuse the import workbench's value rules (``app.modules.imports.definitions``: the same header
aliases, packaging alias reconciliation, price ambiguity and identifier rules), so a dry run and a later workbench
import judge a row the same way.
"""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.modules.imports.definitions.base import Issue
from app.modules.migration.sources import ExportSource, SourceRow, as_text, row_hash, scrub
from app.platform.uow import UnitOfWork

ERROR, QUARANTINE, WARNING, INFO = "error", "quarantine", "warning", "info"
ACCEPTED, QUARANTINED, REJECTED, DUPLICATE = "accepted", "quarantined", "rejected", "duplicate_identical"


@dataclass
class Finding:
    entity: str
    code: str
    severity: str
    message: str
    file: str | None = None
    row_number: int | None = None
    source_key: str | None = None
    field: str | None = None
    raw_value: str | None = None
    raw: dict[str, Any] | None = None


@dataclass
class Planned:
    entity: str
    source_key: str
    business_key: str | None
    status: str  # planned | quarantined | rejected
    source_hash: str


@dataclass
class Accepted:
    row: SourceRow
    key: str
    values: dict[str, Any]


@dataclass
class Options:
    fetch_media: bool = False
    default_price_type: str | None = None
    default_currency: str | None = None
    date_order: str = "DMY"

    def for_definitions(self) -> dict[str, Any]:
        return {
            "blank_cells": "ignore",
            "decor_float_artefact_rule": True,
            "default_price_type": self.default_price_type,
            "default_currency": self.default_currency,
            "date_order": self.date_order,
        }


@dataclass
class Analysis:
    source: ExportSource
    uow: UnitOfWork
    options: Options = field(default_factory=Options)
    findings: list[Finding] = field(default_factory=list)
    planned: dict[tuple[str, str], Planned] = field(default_factory=dict)
    counts: dict[str, Counter[str]] = field(default_factory=lambda: defaultdict(Counter))
    accepted: dict[str, dict[str, Accepted]] = field(default_factory=lambda: defaultdict(dict))
    #: every key seen per entity (accepted or not): links resolve against the source, not only accepted rows
    seen: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    report: dict[str, Any] = field(default_factory=dict)
    #: per-run lookups (known product keys, categories); never persisted
    cache: dict[str, Any] = field(default_factory=dict)

    # ---- findings -------------------------------------------------------------------------------------------
    def add(
        self,
        row: SourceRow | None,
        entity: str,
        code: str,
        severity: str,
        message: str,
        *,
        key: str | None = None,
        field_name: str | None = None,
        raw_value: Any = None,
        with_raw: bool = True,
    ) -> None:
        self.findings.append(
            Finding(
                entity=entity,
                code=code,
                severity=severity,
                message=message[:1000],
                file=row.file if row else self.source.file_name(entity),
                row_number=row.row_number if row else None,
                source_key=key[:400] if key else None,
                field=field_name,
                raw_value=None if raw_value is None else str(raw_value)[:500],
                raw=scrub(row.values)
                if (row is not None and with_raw and severity in (ERROR, QUARANTINE))
                else None,
            )
        )

    def add_issues(self, row: SourceRow, entity: str, key: str | None, issues: Iterable[Issue]) -> None:
        for i in issues:
            self.add(
                row, entity, i.code, i.severity, i.message, key=key, field_name=i.field, raw_value=i.raw_value
            )

    # ---- outcomes -------------------------------------------------------------------------------------------
    def settle(
        self,
        row: SourceRow,
        entity: str,
        key: str | None,
        issues: Sequence[Issue],
        *,
        business_key: str | None = None,
        values: dict[str, Any] | None = None,
    ) -> str:
        """Record the row's issues and outcome; returns accepted | quarantined | rejected."""
        self.add_issues(row, entity, key, issues)
        severities = {i.severity for i in issues}
        outcome = (
            REJECTED
            if ERROR in severities or not key
            else QUARANTINED
            if QUARANTINE in severities
            else ACCEPTED
        )
        self.counts[entity]["source_rows"] += 1
        self.counts[entity][outcome] += 1
        if WARNING in severities and outcome == ACCEPTED:
            self.counts[entity]["with_warnings"] += 1
        if key:
            self.seen[entity].add(key)
            status = {ACCEPTED: "planned", QUARANTINED: "quarantined", REJECTED: "rejected"}[outcome]
            previous = self.planned.get((entity, key))
            # a key that is both accepted and quarantined in one export stays quarantined
            if previous is None or previous.status == "planned":
                self.planned[(entity, key)] = Planned(entity, key, business_key, status, row_hash(row.values))
            if outcome == ACCEPTED:
                self.accepted[entity][key] = Accepted(row, key, values if values is not None else row.values)
            else:
                self.accepted[entity].pop(key, None)
        return outcome

    def duplicate(self, row: SourceRow, entity: str, key: str) -> None:
        self.counts[entity]["source_rows"] += 1
        self.counts[entity][DUPLICATE] += 1
        self.add(
            row,
            entity,
            "DUPLICATE_IDENTICAL",
            INFO,
            "An exact repeat of an earlier row; migrated once",
            key=key,
            with_raw=False,
        )


# ---- shared rules -------------------------------------------------------------------------------------------------
def field_text(values: Mapping[str, Any], *names: str) -> str | None:
    """The first non-blank value among ``names`` as trimmed text."""
    for name in names:
        value = as_text(values.get(name))
        if value is not None and value.strip():
            return value.strip()
    return None


def group_duplicates(
    rows: Sequence[SourceRow], key_of: Any
) -> tuple[list[tuple[SourceRow, str | None]], dict[str, list[SourceRow]], list[tuple[SourceRow, str]]]:
    """Split rows by key: (unique rows with their key or None, conflicting groups, exact repeats).

    A key whose rows are all byte-identical (after scrubbing) keeps its first row and reports the others as exact
    repeats; a key whose rows differ is a duplicate identity and every one of its rows is quarantined."""
    by_key: dict[str, list[SourceRow]] = defaultdict(list)
    keyless: list[tuple[SourceRow, str | None]] = []
    for row in rows:
        key = key_of(row)
        if key:
            by_key[key].append(row)
        else:
            keyless.append((row, None))
    unique: list[tuple[SourceRow, str | None]] = list(keyless)
    conflicts: dict[str, list[SourceRow]] = {}
    repeats: list[tuple[SourceRow, str]] = []
    for key, group in by_key.items():
        if len(group) == 1:
            unique.append((group[0], key))
            continue
        hashes = {row_hash(r.values) for r in group}
        if len(hashes) == 1:
            unique.append((group[0], key))
            repeats.extend((r, key) for r in group[1:])
        else:
            conflicts[key] = group
    unique.sort(key=lambda pair: pair[0].row_number)
    return unique, conflicts, repeats


def fold_key(value: str) -> str:
    """Case- and space-insensitive comparison key for identities that must not differ only by case."""
    return " ".join(value.split()).casefold()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


__all__ = [
    "ACCEPTED",
    "DUPLICATE",
    "ERROR",
    "INFO",
    "QUARANTINE",
    "QUARANTINED",
    "REJECTED",
    "WARNING",
    "Accepted",
    "Analysis",
    "Finding",
    "Options",
    "Planned",
    "fold_key",
    "group_duplicates",
    "sha256_hex",
    "field_text",
]
