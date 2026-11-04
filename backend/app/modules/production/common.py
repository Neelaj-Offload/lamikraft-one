"""Shared helpers: business date, read-model refs and the read-only guard used by feasibility and what-if."""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import event, select

from app.core.errors import NotFound, ValidationFailed
from app.modules.catalogue.models import Product
from app.modules.inventory.models import Warehouse
from app.modules.production.models import WorkCenter
from app.modules.production.schemas import (
    ProductionProductRef,
    ProductionUserRef,
    ProductionWarehouseRef,
    WorkCenterRef,
)
from app.platform.identity.models import AppUser
from app.platform.uow import UnitOfWork

ZERO = Decimal(0)


def business_date(uow: UnitOfWork) -> date:
    from app.core.clock import local_date
    from app.platform.org.models import Company

    zone = (
        uow.session.scalar(select(Company.default_time_zone).where(Company.id == uow.actor.company_id))
        or "Asia/Kolkata"
    )
    return local_date(uow.now(), zone)


def company_currency(uow: UnitOfWork) -> str:
    from app.platform.org.models import Company

    return uow.session.scalar(select(Company.base_currency).where(Company.id == uow.actor.company_id)) or "INR"


def problem(loc: list[str | int], msg: str, code: str, detail: str | None = None) -> ValidationFailed:
    return ValidationFailed(detail or msg, errors=[{"loc": ["body", *loc], "msg": msg, "code": code}])


def product(uow: UnitOfWork, product_id: uuid.UUID, loc: list[str | int] | None = None) -> Product:
    p = uow.session.scalars(
        select(Product).where(Product.company_id == uow.actor.company_id, Product.id == product_id)
    ).first()
    if p is None:
        raise problem(loc or ["product_id"], "unknown product", "product_not_found", "The product does not exist")
    return p


def product_refs(uow: UnitOfWork, ids: Iterable[uuid.UUID | None]) -> dict[uuid.UUID, ProductionProductRef]:
    wanted = {i for i in ids if i}
    if not wanted:
        return {}
    rows = uow.session.scalars(
        select(Product).where(Product.company_id == uow.actor.company_id, Product.id.in_(wanted))
    )
    return {
        p.id: ProductionProductRef(
            id=p.id, product_key=p.product_key, name=p.product_name, stock_uom_code=p.stock_uom_code
        )
        for p in rows
    }


def user_refs(uow: UnitOfWork, ids: Iterable[uuid.UUID | None]) -> dict[uuid.UUID, ProductionUserRef]:
    wanted = {i for i in ids if i}
    if not wanted:
        return {}
    rows = uow.session.execute(select(AppUser.id, AppUser.display_name).where(AppUser.id.in_(wanted))).all()
    return {r[0]: ProductionUserRef(id=r[0], display_name=r[1]) for r in rows}


def warehouse_refs(uow: UnitOfWork, ids: Iterable[uuid.UUID | None]) -> dict[uuid.UUID, ProductionWarehouseRef]:
    wanted = {i for i in ids if i}
    if not wanted:
        return {}
    rows = uow.session.scalars(
        select(Warehouse).where(Warehouse.company_id == uow.actor.company_id, Warehouse.id.in_(wanted))
    )
    return {w.id: ProductionWarehouseRef(id=w.id, code=w.code, name=w.name) for w in rows}


def work_center_refs(uow: UnitOfWork, ids: Iterable[uuid.UUID | None]) -> dict[uuid.UUID, WorkCenterRef]:
    wanted = {i for i in ids if i}
    if not wanted:
        return {}
    rows = uow.session.scalars(
        select(WorkCenter).where(WorkCenter.company_id == uow.actor.company_id, WorkCenter.id.in_(wanted))
    )
    return {c.id: WorkCenterRef(id=c.id, code=c.code, name=c.name) for c in rows}


def work_center(uow: UnitOfWork, work_center_id: uuid.UUID, loc: list[str | int]) -> WorkCenter:
    c = uow.session.scalars(
        select(WorkCenter).where(WorkCenter.company_id == uow.actor.company_id, WorkCenter.id == work_center_id)
    ).first()
    if c is None:
        raise problem(loc, "unknown work centre", "work_center_not_found", "The work centre does not exist")
    return c


def require_work_center(uow: UnitOfWork, work_center_id: uuid.UUID) -> WorkCenter:
    c = uow.session.scalars(
        select(WorkCenter).where(WorkCenter.company_id == uow.actor.company_id, WorkCenter.id == work_center_id)
    ).first()
    if c is None:
        raise NotFound(code="not_found", resource_type="production.work_center")
    return c


def dec(value: Any) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def fmt(value: Decimal) -> str:
    """A canonical decimal string (no exponent, trailing zeros removed) for hashes and facts."""
    q = value.normalize()
    return format(q, "f") if q != 0 else "0"


class ReadOnlyViolation(RuntimeError):
    """Raised when feasibility or what-if code tries to write (a defect, never a user error)."""


@contextmanager
def read_only(uow: UnitOfWork) -> Iterator[UnitOfWork]:
    """Run reads in ``uow`` with every write path closed: a pending flush, an event, a job, an audit row or a number
    allocation raises :class:`ReadOnlyViolation`. Feasibility and what-if run inside this guard, so "simulation never
    writes" is enforced mechanically (and proven by a test that counts rows before and after)."""
    session = uow.session

    def guard(sess: Any, _ctx: Any, _instances: Any) -> None:
        if sess.new or sess.dirty or sess.deleted:
            raise ReadOnlyViolation("a read-only production computation tried to write")

    def refuse(*_a: Any, **_k: Any) -> Any:
        raise ReadOnlyViolation("a read-only production computation tried to write")

    if session.new or session.dirty or session.deleted:
        session.flush()
    event.listen(session, "before_flush", guard)
    saved = {name: uow.__dict__.get(name) for name in ("emit", "enqueue", "audit", "allocate_number", "add", "add_all")}
    for name in saved:
        setattr(uow, name, refuse)
    try:
        yield uow
    finally:
        for name, original in saved.items():
            if original is None:
                uow.__dict__.pop(name, None)
            else:
                setattr(uow, name, original)
        event.remove(session, "before_flush", guard)
