"""Customer types (SC-13): a per-company reference table that parties (and later price lists) point at.

The three built-in types (standard, dealer, distributor) exist in every company: the migration backfills them and
``ensure_customer_type`` provisions them on first use for companies created afterwards. Built-in types can be
relabelled, reordered and deactivated but never removed; an inactive type cannot be newly assigned.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.errors import Conflict, NotFound
from app.core.http.capabilities import Capability
from app.modules.parties.models import SYSTEM_CUSTOMER_TYPES, CustomerTypeRecord, Party
from app.modules.parties.schemas import CustomerTypeCreate, CustomerTypeRead, CustomerTypeUpdate
from app.platform.service import query
from app.platform.uow import UnitOfWork

MANAGE = "parties.customer_type.manage"
READ = "parties.party.read"
T = CustomerTypeRecord


def _provision_system_types(uow: UnitOfWork) -> None:
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
                for code, label, order in SYSTEM_CUSTOMER_TYPES
            ]
        )
        .on_conflict_do_nothing(index_elements=["company_id", "code"])
    )


def _find(uow: UnitOfWork, code: str) -> CustomerTypeRecord | None:
    return uow.session.scalars(select(T).where(T.company_id == uow.actor.company_id, T.code == code)).first()


def ensure_customer_type(uow: UnitOfWork, code: str | None, *, current: str | None = None) -> str | None:
    """The validated code for a party write: 422 ``customer_type_unknown`` / ``customer_type_inactive`` (an
    inactive type a party already has may stay)."""
    from app.core.errors import ValidationFailed

    if code is None:
        return None
    row = _find(uow, code)
    if row is None and code in {c for c, _l, _o in SYSTEM_CUSTOMER_TYPES}:
        _provision_system_types(uow)
        row = _find(uow, code)
    if row is None:
        raise ValidationFailed(
            "The customer type does not exist",
            errors=[{"loc": ["body", "customer_type"], "msg": "unknown customer type", "code": "customer_type_unknown"}],
        )
    if not row.is_active and code != current:
        raise ValidationFailed(
            "The customer type is inactive",
            errors=[{"loc": ["body", "customer_type"], "msg": "inactive customer type", "code": "customer_type_inactive"}],
        )
    return row.code


def _read(uow: UnitOfWork, row: CustomerTypeRecord, counts: dict[str, int]) -> CustomerTypeRead:
    can = uow.actor.can(MANAGE)
    reason = None if can else "permission_denied"
    return CustomerTypeRead(
        id=row.id,
        code=row.code,
        label=row.label,
        description=row.description,
        display_order=row.display_order,
        is_active=row.is_active,
        is_system=row.is_system,
        party_count=counts.get(row.code, 0),
        version=row.version,
        capabilities={"update": Capability(allowed=can, reason_code=reason)},
    )


def _counts(uow: UnitOfWork, codes: Sequence[str]) -> dict[str, int]:
    if not codes:
        return {}
    rows = uow.session.execute(
        select(Party.customer_type, func.count())
        .where(Party.company_id == uow.actor.company_id, Party.customer_type.in_(list(codes)), Party.archived_at.is_(None))
        .group_by(Party.customer_type)
    ).all()
    return {code: int(n) for code, n in rows}


@query(READ)
def list_customer_types(uow: UnitOfWork, *, include_inactive: bool = True) -> list[CustomerTypeRead]:
    """Customer types ordered by display order then label (party counts are company-wide live parties)."""
    if uow.session.scalar(select(func.count()).select_from(T).where(T.company_id == uow.actor.company_id)) == 0:
        _provision_system_types(uow)
    stmt = select(T).where(T.company_id == uow.actor.company_id)
    if not include_inactive:
        stmt = stmt.where(T.is_active.is_(True))
    rows = list(uow.session.scalars(stmt.order_by(T.display_order, T.label, T.id)))
    counts = _counts(uow, [r.code for r in rows])
    return [_read(uow, r, counts) for r in rows]


def create_customer_type(uow: UnitOfWork, data: CustomerTypeCreate) -> CustomerTypeRead:
    uow.actor.require(MANAGE)
    _provision_system_types(uow)
    if _find(uow, data.code) is not None:
        raise Conflict("A customer type with this code already exists", code="customer_type_exists")
    row = CustomerTypeRecord(
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
    uow.audit("parties.customer_type.created", resource_type="parties.customer_type", resource_id=row.id,
              resource_label=row.code)
    return _read(uow, row, {})


def update_customer_type(uow: UnitOfWork, type_id: uuid.UUID, data: CustomerTypeUpdate) -> CustomerTypeRead:
    uow.actor.require(MANAGE)
    row = uow.session.scalars(
        select(T).where(T.id == type_id, T.company_id == uow.actor.company_id).with_for_update()
    ).first()
    if row is None:
        raise NotFound(code="not_found", resource_type="parties.customer_type")
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
        uow.audit("parties.customer_type.updated", resource_type="parties.customer_type", resource_id=row.id,
                  resource_label=row.code, details={"changed_fields": sorted(changed)})
    return _read(uow, row, _counts(uow, [row.code]))
