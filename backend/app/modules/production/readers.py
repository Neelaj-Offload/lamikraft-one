"""Source readers for tasks, briefings and the agent: ``production.work_order`` and ``production.capacity_overload``.
Facts are ids, numbers, statuses and dates only: never quantities of cost, rates or rollup figures (the cost guard
denies model exposure, so production readers carry none)."""

from __future__ import annotations

import uuid

from app.core.errors import NotFound
from app.modules.production.models import CapacityOverload, WorkCenter, WorkOrder
from app.platform.sources import SourceFacts
from app.platform.uow import UnitOfWork

CLOSED = frozenset({"completed", "closed", "cancelled"})


def read_work_order_facts(uow: UnitOfWork, work_order_id: uuid.UUID) -> SourceFacts | None:
    from app.modules.catalogue.models import Product

    try:
        w = uow.repo(WorkOrder).get(work_order_id)
    except NotFound:
        return None
    p = uow.session.get(Product, w.product_id)
    return SourceFacts(
        source_type="production.work_order",
        source_id=w.id,
        version=w.version,
        label=f"{w.wo_number} · {p.product_key if p else ''}".rstrip(" ·"),
        status=w.status,
        owner_user_id=w.owner_user_id,
        branch_id=w.branch_id,
        required_permission="production.work_order.read",
        canonical_path=f"/operations/production/work-orders/{w.id}",
        is_closed=w.status in CLOSED or not w.is_blocked,
        updated_at=w.updated_at,
        facts={
            "wo_number": w.wo_number,
            "product_key": p.product_key if p else None,
            "status": w.status,
            "is_blocked": w.is_blocked,
            "caused_by": list(w.blocked_causes or []),
            "planned_start_date": w.planned_start_date.isoformat() if w.planned_start_date else None,
            "due_date": w.due_date.isoformat() if w.due_date else None,
        },
    )


def read_overload_facts(uow: UnitOfWork, overload_id: uuid.UUID) -> SourceFacts | None:
    row = uow.session.get(CapacityOverload, overload_id)
    if row is None or row.company_id != uow.actor.company_id or not uow.actor.can("production.capacity.read"):
        return None
    wc = uow.session.get(WorkCenter, row.work_center_id)
    return SourceFacts(
        source_type="production.capacity_overload",
        source_id=row.id,
        version=row.version,
        label=f"{wc.code if wc else 'Work centre'} overloaded on {row.load_date.isoformat()}",
        status=row.status,
        owner_user_id=None,
        branch_id=None,
        required_permission="production.capacity.read",
        canonical_path=f"/operations/production/capacity?from={row.load_date.isoformat()}",
        is_closed=row.status != "open",
        updated_at=row.updated_at,
        facts={"work_center_code": wc.code if wc else None, "date": row.load_date.isoformat()},
    )


READERS = {"production.work_order": read_work_order_facts, "production.capacity_overload": read_overload_facts}
