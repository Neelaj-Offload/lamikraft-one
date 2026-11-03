"""Helpers shared by the challan services: validation errors, the company zone and business date, user and branch
references, the ``challan_defaults`` setting and the idempotent-command wrapper."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from datetime import date, timedelta
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select

from app.core.clock import local_date
from app.core.errors import ValidationFailed
from app.modules.challans.events import ChallanDefaults
from app.modules.challans.schemas import BranchLink, UserRef
from app.platform.idempotency.service import run_idempotent
from app.platform.identity.models import AppUser
from app.platform.org.models import Branch, Company
from app.platform.uow import UnitOfWork


class Errors:
    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    def add(self, loc: Sequence[str | int], code: str, msg: str) -> None:
        self.items.append({"loc": ["body", *loc], "msg": msg, "code": code})

    def extend(self, prefix: Sequence[str | int], exc: ValidationFailed) -> None:
        """Re-home another service's field errors under ``prefix`` (e.g. ``lines.2``)."""
        for item in exc.extra.get("errors") or []:
            loc = [p for p in item.get("loc", []) if p != "body"]
            self.items.append(
                {
                    "loc": ["body", *prefix, *loc],
                    "msg": item.get("msg", ""),
                    "code": item.get("code", "invalid"),
                }
            )

    def raise_if_any(self, detail: str = "Some challan values are not valid") -> None:
        if self.items:
            raise ValidationFailed(detail, errors=self.items)


def challan_path(challan_id: uuid.UUID) -> str:
    return f"/operations/challans/{challan_id}"


def company_zone(uow: UnitOfWork) -> str:
    zone = uow.session.scalar(select(Company.default_time_zone).where(Company.id == uow.actor.company_id))
    return zone or "Asia/Kolkata"


def business_date(uow: UnitOfWork) -> date:
    return local_date(uow.now(), company_zone(uow))


def week_start(day: date) -> date:
    """Monday of the ISO week (the legacy "this week" filter)."""
    return day - timedelta(days=day.weekday())


def month_start(day: date) -> date:
    return day.replace(day=1)


def user_refs(uow: UnitOfWork, ids: Sequence[uuid.UUID | None]) -> dict[uuid.UUID, UserRef]:
    wanted = {i for i in ids if i is not None}
    if not wanted:
        return {}
    rows = uow.session.execute(select(AppUser.id, AppUser.display_name).where(AppUser.id.in_(wanted))).all()
    return {r[0]: UserRef(id=r[0], display_name=r[1]) for r in rows}


def branch_links(uow: UnitOfWork, ids: Sequence[uuid.UUID | None]) -> dict[uuid.UUID, BranchLink]:
    wanted = {i for i in ids if i is not None}
    if not wanted:
        return {}
    rows = uow.session.execute(
        select(Branch.id, Branch.branch_code, Branch.name).where(
            Branch.company_id == uow.actor.company_id, Branch.id.in_(wanted)
        )
    ).all()
    return {r[0]: BranchLink(id=r[0], branch_code=r[1], name=r[2]) for r in rows}


def defaults(uow: UnitOfWork) -> ChallanDefaults:
    from app.platform.org.service import stored_or_default

    value = stored_or_default(uow, "challan_defaults")
    assert isinstance(value, ChallanDefaults)
    return value


def idempotent[T: BaseModel](
    uow: UnitOfWork,
    operation: str,
    body: BaseModel | dict[str, Any],
    fn: Callable[[], T],
    model: type[T],
    status: int = 200,
) -> tuple[T, bool]:
    """Run ``fn`` under the actor's ``Idempotency-Key`` (when present) and replay the stored response otherwise."""
    payload = body.model_dump(mode="json") if isinstance(body, BaseModel) else body
    out, replayed = run_idempotent(
        uow,
        key=uow.actor.idempotency_key,
        operation=operation,
        body=payload,
        fn=lambda: fn().model_dump(mode="json"),
        status=status,
    )
    return model.model_validate(out), replayed
