"""Inventory record scope (permissions.md §7.7).

Stock is scoped by **warehouse**: a warehouse belongs to a branch, so ``inventory.stock.read`` at branch scope sees
the warehouses of the actor's branches (operations, warehouse, production) and company scope sees all (management,
sales, finance, procurement). Every inventory document (pick list, count, adjustment, opening batch, transfer),
summary, balance, reservation, shortage and movement is visible through its warehouse; a document of an invisible
warehouse is a 404, a visible one without the action key in scope is a 403.

Write keys are checked against the warehouse with :func:`require_warehouse` (an ad-hoc policy per key over the same
branch column), so ``inventory.adjustment.approve`` at branch scope approves only in the actor's branches.
"""

from __future__ import annotations

import uuid
from functools import lru_cache

from sqlalchemy import ColumnElement, select

from app.core.errors import Forbidden, NotFound
from app.modules.inventory.models import Warehouse
from app.platform.authz.policy import ResourcePolicy, scope_clause
from app.platform.uow import UnitOfWork

READ = "inventory.stock.read"

WAREHOUSE_POLICY = ResourcePolicy(
    resource_type="inventory.warehouse",
    model=Warehouse,
    permission_prefix="inventory.stock",
    branch_column="branch_id",
    business_key_column="code",
    label=lambda w: f"{w.code} · {w.name}",
    canonical_path=lambda w: f"/operations/inventory?warehouse={w.id}",
    archived_column=None,
)

POLICIES = [WAREHOUSE_POLICY]


@lru_cache(maxsize=64)
def _policy_for(prefix: str) -> ResourcePolicy:
    return ResourcePolicy(
        resource_type=f"inventory.warehouse[{prefix}]",
        model=Warehouse,
        permission_prefix=prefix,
        branch_column="branch_id",
        archived_column=None,
    )


def warehouse_clause(uow: UnitOfWork, key: str = READ) -> ColumnElement[bool]:
    prefix, action = key.rsplit(".", 1)
    return scope_clause(uow.actor, _policy_for(prefix), action)


def visible_warehouse_ids(uow: UnitOfWork, key: str = READ) -> list[uuid.UUID]:
    return list(uow.session.scalars(select(Warehouse.id).where(warehouse_clause(uow, key))))


def can_on_warehouse(uow: UnitOfWork, warehouse_id: uuid.UUID, key: str) -> bool:
    return (
        uow.session.scalar(
            select(Warehouse.id).where(Warehouse.id == warehouse_id, warehouse_clause(uow, key))
        )
        is not None
    )


def require_warehouse(uow: UnitOfWork, warehouse_id: uuid.UUID, key: str = READ) -> Warehouse:
    """The warehouse when the actor may read it (else 404) and holds ``key`` in scope over it (else 403)."""
    wh = uow.session.scalars(
        select(Warehouse).where(Warehouse.id == warehouse_id, warehouse_clause(uow, READ))
    ).first()
    if wh is None:
        raise NotFound(code="not_found", resource_type="inventory.warehouse")
    if key != READ and not can_on_warehouse(uow, warehouse_id, key):
        raise Forbidden(code="permission_denied", permission=key)
    return wh
