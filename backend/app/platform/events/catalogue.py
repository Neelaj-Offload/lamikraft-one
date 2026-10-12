"""The event vocabulary as code (generated data from docs/architecture/events.md).

Payloads carry ids, business keys, versions, enum codes and changed-field names only. Each event's
allowed payload fields come from the catalogue; ``origin`` is always allowed.
"""

from __future__ import annotations

from app.platform.events.catalogue_data import EVENTS as _ROWS
from app.platform.events.defs import EventDef


def event_defs() -> list[EventDef]:
    out = []
    for row in _ROWS:
        module, entity, _verb = row["name"].split(".")
        out.append(
            EventDef(
                name=row["name"],
                aggregate_type=f"{module}.{entity}",
                description=row["name"],
                version=row["version"],
                fields=tuple(row["fields"]),
            )
        )
    return out
