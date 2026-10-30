"""Lookup reference (FG-LKP, LM-34): the legacy ``lookup_reference`` rows, kept as read-only reference data.

The legacy system imported these rows and never read them, so their meaning is unconfirmed: they are browsable,
exportable (safe CSV) and importable, and no business rule consumes them (docs: reference-only data).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy import and_, func, select

from app.core.csv_safe import write_csv
from app.core.http.pagination import MAX_LIMIT, Page
from app.core.text import LIKE_ESCAPE, contains_pattern, tokens
from app.modules.catalogue.models import LookupReference
from app.platform.service import query
from app.platform.uow import UnitOfWork

READ = "catalogue.lookup.read"
L = LookupReference
EXPORT_COLUMNS = ("lookup_type", "key_1", "key_2", "value_1", "value_2", "notes")


class LookupRead(BaseModel):
    id: uuid.UUID
    lookup_type: str
    key_1: str
    key_2: str
    value_1: str | None
    value_2: str | None
    notes: str | None
    source_extra: dict[str, Any] | None
    updated_at: datetime


class LookupType(BaseModel):
    lookup_type: str
    count: int


def _where(uow: UnitOfWork, lookup_type: str | None, q: str | None) -> list[Any]:
    conds: list[Any] = [L.company_id == uow.actor.company_id]
    if lookup_type:
        conds.append(L.lookup_type == lookup_type)
    for tok in tokens(q or ""):
        pattern = contains_pattern(tok)
        conds.append(
            L.key_1.ilike(pattern, escape=LIKE_ESCAPE)
            | L.key_2.ilike(pattern, escape=LIKE_ESCAPE)
            | L.value_1.ilike(pattern, escape=LIKE_ESCAPE)
            | L.value_2.ilike(pattern, escape=LIKE_ESCAPE)
        )
    return conds


@query(READ)
def list_lookups(
    uow: UnitOfWork,
    *,
    lookup_type: str | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> Page[LookupRead]:
    """Filters (type, tokens over keys and values) apply before paging; ordered by type, key_1, key_2."""
    where = _where(uow, lookup_type, q)
    total = uow.session.scalar(select(func.count(L.id)).where(*where)) or 0
    limit = max(1, min(limit, MAX_LIMIT))
    rows = uow.session.scalars(
        select(L).where(*where).order_by(L.lookup_type, L.key_1, L.key_2, L.id).limit(limit).offset(max(0, offset))
    )
    return Page[LookupRead](
        items=[
            LookupRead(
                id=r.id, lookup_type=r.lookup_type, key_1=r.key_1, key_2=r.key_2, value_1=r.value_1, value_2=r.value_2,
                notes=r.notes, source_extra=r.source_extra, updated_at=r.updated_at,
            )
            for r in rows
        ],
        total=int(total),
        limit=limit,
        offset=max(0, offset),
    )


@query(READ)
def lookup_types(uow: UnitOfWork) -> list[LookupType]:
    rows = uow.session.execute(
        select(L.lookup_type, func.count(L.id)).where(L.company_id == uow.actor.company_id)
        .group_by(L.lookup_type).order_by(L.lookup_type)
    ).all()
    return [LookupType(lookup_type=t, count=int(n)) for t, n in rows]


@query(READ)
def export_lookups_csv(uow: UnitOfWork, *, lookup_type: str | None = None, q: str | None = None) -> bytes:
    """Import-compatible CSV (``lookup_reference`` columns) through ``core.csv_safe``."""
    rows = uow.session.scalars(
        select(L).where(*_where(uow, lookup_type, q)).order_by(L.lookup_type, L.key_1, L.key_2, L.id)
    )
    data = write_csv(EXPORT_COLUMNS, ([getattr(r, c) for c in EXPORT_COLUMNS] for r in rows))
    uow.audit("catalogue.lookup.exported", resource_type="catalogue.lookup", details={"lookup_type": lookup_type})
    return data


def find_lookup(uow: UnitOfWork, lookup_type: str, key_1: str, key_2: str) -> LookupReference | None:
    return uow.session.scalars(
        select(L).where(
            and_(L.company_id == uow.actor.company_id, L.lookup_type == lookup_type, L.key_1 == key_1, L.key_2 == key_2)
        )
    ).first()


def upsert_lookup(uow: UnitOfWork, values: dict[str, Any]) -> tuple[uuid.UUID, bool]:
    """Insert or update one row by (type, key_1, key_2); returns (id, inserted). Used by the import workbench."""
    row = find_lookup(uow, values["lookup_type"], values["key_1"], values["key_2"])
    if row is None:
        row = LookupReference(id=uuid.uuid7(), company_id=uow.actor.company_id, **values)
        uow.add(row)
        uow.flush()
        return row.id, True
    for name in ("value_1", "value_2", "notes", "source_extra"):
        if name in values:
            setattr(row, name, values[name])
    row.updated_at = uow.now()
    uow.flush()
    return row.id, False
