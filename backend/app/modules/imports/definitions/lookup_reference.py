"""``lookup_reference`` (LM-34, FG-LKP-01/02): key (lookup_type, key_1, key_2); upserted, never read by rules."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.modules.catalogue import lookups
from app.modules.imports.definitions.base import (
    Change,
    FieldSpec,
    ImportDefinition,
    Issue,
    Plan,
    Prepared,
    cell,
    diff,
    need,
)
from app.platform.uow import UnitOfWork

VALUES = ("value_1", "value_2", "notes")


class LookupReferenceImport(ImportDefinition):
    import_type = "lookup_reference"
    label = "Lookup reference"
    description = "Legacy reference rows kept for browsing and export (no business rule reads them)."
    fields = (
        FieldSpec("lookup_type", aliases=("type",), required=True),
        FieldSpec("key_1", aliases=("key1",), required=True),
        FieldSpec("key_2", aliases=("key2",)),
        FieldSpec("value_1", aliases=("value1",)),
        FieldSpec("value_2", aliases=("value2",)),
        FieldSpec("notes"),
    )
    writes = ("catalogue_lookup_reference",)

    def normalise(self, values: Mapping[str, str | None], options: Mapping[str, Any]) -> Prepared:
        issues: list[Issue] = []
        out: dict[str, Any] = {
            "lookup_type": need(values, "lookup_type", issues),
            "key_1": need(values, "key_1", issues),
            "key_2": cell(values, "key_2", issues) or "",
        }
        for name in VALUES:
            out[name] = cell(values, name, issues)
        extra = values.get("__extra__")
        out["source_extra"] = dict(extra) if isinstance(extra, Mapping) and extra else None
        key = f"{out['lookup_type']}|{out['key_1']}|{out['key_2']}" if out["lookup_type"] and out["key_1"] else None
        return Prepared(values=out, key=key, issues=issues)

    def plan(self, uow: UnitOfWork, prepared: Prepared, options: Mapping[str, Any]) -> Plan:
        v = prepared.values
        row = lookups.find_lookup(uow, v["lookup_type"], v["key_1"], v["key_2"])
        if row is None:
            return Plan("insert", diff=diff({}, v, VALUES))
        current = {n: getattr(row, n) for n in VALUES}
        changes = diff(current, v, VALUES)
        return Plan("update" if changes else "unchanged", row.id, None, changes)

    def apply(self, uow: UnitOfWork, prepared: Prepared, plan: Plan, options: Mapping[str, Any]) -> list[Change]:
        uow.actor.require("catalogue.lookup.read")
        v = prepared.values
        row = lookups.find_lookup(uow, v["lookup_type"], v["key_1"], v["key_2"])
        before = {n: getattr(row, n) for n in VALUES} if row is not None else None
        values = {k: v[k] for k in ("lookup_type", "key_1", "key_2", "source_extra")}
        values.update({n: (v[n] if v[n] is not None else (before or {}).get(n)) for n in VALUES})
        row_id, inserted = lookups.upsert_lookup(uow, values)
        after = {n: values[n] for n in VALUES}
        return [Change("catalogue_lookup_reference", row_id, "insert" if inserted else "update", before, after,
                       sorted(plan.diff) or list(VALUES), None)]
