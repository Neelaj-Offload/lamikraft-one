"""Lead sources: where a lead came from (website, a trade show, a visiting card), a per-company managed list.

A copy of the customer-type pattern (``customer_types.py``): five built-in sources exist in every company (the
migration backfills them, ``_provision_system_sources`` creates them on first use for later companies). Built-in
sources can be relabelled, reordered and deactivated but never removed; an inactive source cannot be newly assigned,
and a lead that already has it keeps it. Trade shows are added each year, so ``slug_code`` turns a label into a code.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.http.capabilities import Capability
from app.modules.parties.models import SYSTEM_LEAD_SOURCES, LeadSourceRecord, Party
from app.modules.parties.schemas import LeadSourceCreate, LeadSourceRead, LeadSourceUpdate
from app.platform.service import query
from app.platform.uow import UnitOfWork

MANAGE = "parties.lead_source.manage"
READ = "parties.party.read"
T = LeadSourceRecord


def slug_code(label: str) -> str:
    """A valid source code from a label: "NRA Chicago 2026" → ``nra_chicago_2026`` (max 20 characters)."""
    ascii_label = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode()
    code = re.sub(r"[^a-z0-9]+", "_", ascii_label.lower()).strip("_")
    if not code or not code[0].isalpha():
        code = "s_" + code
    code = code[:20].rstrip("_")
    return code if len(code) >= 2 else (code + "_x")[:20]


def _provision_system_sources(uow: UnitOfWork) -> None:
    now = uow.now()
    uow.session.execute(
        pg_insert(T)
        .values(
            [
                {
                    "id": uuid.uuid7(),
                    "company_id": uow.actor.company_id,
                    "code": code,
                    "label": label,
                    "display_order": order,
                    "is_active": True,
                    "is_system": True,
                    "version": 1,
                    "created_at": now,
                    "updated_at": now,
                }
                for code, label, order in SYSTEM_LEAD_SOURCES
            ]
        )
        .on_conflict_do_nothing(index_elements=["company_id", "code"])
    )


def ensure_system_sources(uow: UnitOfWork) -> None:
    """Create the built-in sources for this company if they are missing (idempotent, same transaction)."""
    _provision_system_sources(uow)


def _find(uow: UnitOfWork, code: str) -> LeadSourceRecord | None:
    return uow.session.scalars(select(T).where(T.company_id == uow.actor.company_id, T.code == code)).first()


def labels_for(uow: UnitOfWork, codes: Sequence[str | None]) -> dict[str, str]:
    wanted = sorted({c for c in codes if c})
    if not wanted:
        return {}
    rows = uow.session.execute(select(T.code, T.label).where(T.company_id == uow.actor.company_id, T.code.in_(wanted)))
    return {code: label for code, label in rows}


def ensure_lead_source(uow: UnitOfWork, code: str | None, *, current: str | None = None) -> str | None:
    """The validated code for a party write: 422 ``lead_source_unknown`` / ``lead_source_inactive`` (an inactive
    source a lead already has may stay)."""
    if code is None:
        return None
    row = _find(uow, code)
    if row is None and code in {c for c, _l, _o in SYSTEM_LEAD_SOURCES}:
        _provision_system_sources(uow)
        row = _find(uow, code)
    if row is None:
        raise ValidationFailed(
            "The lead source does not exist",
            errors=[{"loc": ["body", "lead_source"], "msg": "unknown lead source", "code": "lead_source_unknown"}],
        )
    if not row.is_active and code != current:
        raise ValidationFailed(
            "The lead source is switched off",
            errors=[{"loc": ["body", "lead_source"], "msg": "inactive lead source", "code": "lead_source_inactive"}],
        )
    return row.code


def _read(uow: UnitOfWork, row: LeadSourceRecord, counts: dict[str, int]) -> LeadSourceRead:
    can = uow.actor.can(MANAGE)
    reason = None if can else "permission_denied"
    return LeadSourceRead(
        id=row.id,
        code=row.code,
        label=row.label,
        description=row.description,
        display_order=row.display_order,
        is_active=row.is_active,
        is_system=row.is_system,
        lead_count=counts.get(row.code, 0),
        version=row.version,
        capabilities={"update": Capability(allowed=can, reason_code=reason)},
    )


def _counts(uow: UnitOfWork, codes: Sequence[str]) -> dict[str, int]:
    if not codes:
        return {}
    rows = uow.session.execute(
        select(Party.lead_source_code, func.count())
        .where(
            Party.company_id == uow.actor.company_id,
            Party.lead_source_code.in_(list(codes)),
            Party.archived_at.is_(None),
        )
        .group_by(Party.lead_source_code)
    ).all()
    return {code: int(n) for code, n in rows}


@query(READ)
def list_lead_sources(uow: UnitOfWork, *, include_inactive: bool = True) -> list[LeadSourceRead]:
    """Lead sources ordered by display order then label (lead counts are company-wide live parties)."""
    if uow.session.scalar(select(func.count()).select_from(T).where(T.company_id == uow.actor.company_id)) == 0:
        _provision_system_sources(uow)
    stmt = select(T).where(T.company_id == uow.actor.company_id)
    if not include_inactive:
        stmt = stmt.where(T.is_active.is_(True))
    rows = list(uow.session.scalars(stmt.order_by(T.display_order, T.label, T.id)))
    counts = _counts(uow, [r.code for r in rows])
    return [_read(uow, r, counts) for r in rows]


def insert_lead_source(uow: UnitOfWork, data: LeadSourceCreate) -> LeadSourceRecord:
    """Insert without the permission check (the import adds the sheet's own sources as the operator)."""
    _provision_system_sources(uow)
    if _find(uow, data.code) is not None:
        raise Conflict("A lead source with this code already exists", code="lead_source_exists")
    row = LeadSourceRecord(
        id=uuid.uuid7(),
        company_id=uow.actor.company_id,
        code=data.code,
        label=data.label,
        description=data.description,
        display_order=data.display_order,
        is_active=data.is_active,
        is_system=False,
    )
    uow.add(row)
    uow.flush()
    uow.audit("parties.lead_source.created", resource_type="parties.lead_source", resource_id=row.id,
              resource_label=row.code)
    return row


def create_lead_source(uow: UnitOfWork, data: LeadSourceCreate) -> LeadSourceRead:
    uow.actor.require(MANAGE)
    return _read(uow, insert_lead_source(uow, data), {})


def update_lead_source(uow: UnitOfWork, source_id: uuid.UUID, data: LeadSourceUpdate) -> LeadSourceRead:
    uow.actor.require(MANAGE)
    row = uow.session.scalars(
        select(T).where(T.id == source_id, T.company_id == uow.actor.company_id).with_for_update()
    ).first()
    if row is None:
        raise NotFound(code="not_found", resource_type="parties.lead_source")
    uow.expect_version(row, data.expected_version)
    fields: dict[str, Any] = data.model_dump(exclude_unset=True, exclude={"expected_version"})
    changed = []
    for name, value in fields.items():
        if name in ("label", "is_active", "display_order") and value is None:
            continue
        if getattr(row, name) != value:
            setattr(row, name, value)
            changed.append(name)
    if changed:
        row.updated_at = uow.now()
        uow.flush()
        uow.audit("parties.lead_source.updated", resource_type="parties.lead_source", resource_id=row.id,
                  resource_label=row.code, details={"changed_fields": sorted(changed)})
    return _read(uow, row, _counts(uow, [row.code]))
