"""Helpers shared by the sales services: validation errors, member checks, party/contact references, user names,
company zone and the idempotent-command wrapper."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from datetime import date
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select

from app.core.clock import local_date
from app.core.errors import ValidationFailed
from app.modules.parties import service as parties
from app.modules.parties.schemas import ContactRead
from app.modules.sales.schemas import PartyRef, UserRef
from app.platform.idempotency.service import run_idempotent
from app.platform.identity.models import AppUser, Membership
from app.platform.org.models import Company
from app.platform.uow import UnitOfWork


class Errors:
    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    def add(self, loc: Sequence[str | int], code: str, msg: str) -> None:
        self.items.append({"loc": ["body", *loc], "msg": msg, "code": code})

    def raise_if_any(self) -> None:
        if self.items:
            raise ValidationFailed("Some sales values are not valid", errors=self.items)


def quote_path(quote_id: uuid.UUID) -> str:
    return f"/sales/quotes/{quote_id}"


def enquiry_path(enquiry_id: uuid.UUID) -> str:
    return f"/sales/enquiries/{enquiry_id}"


def message_path(message_id: uuid.UUID) -> str:
    return f"/sales/messages/{message_id}"


def company_zone(uow: UnitOfWork) -> str:
    """The company's time zone (business dates, validity, document dates)."""
    zone = uow.session.scalar(select(Company.default_time_zone).where(Company.id == uow.actor.company_id))
    return zone or "Asia/Kolkata"


def company_names(uow: UnitOfWork) -> tuple[str, str]:
    row = uow.session.execute(
        select(Company.legal_name, Company.display_name).where(Company.id == uow.actor.company_id)
    ).first()
    return (row[0], row[1]) if row else ("Company", "Company")


def business_date(uow: UnitOfWork) -> date:
    return local_date(uow.now(), company_zone(uow))


def check_member(uow: UnitOfWork, user_id: uuid.UUID, errors: Errors, field: str) -> None:
    active = uow.session.scalar(
        select(Membership.id).where(
            Membership.company_id == uow.actor.company_id, Membership.user_id == user_id, Membership.status == "active"
        )
    )
    if active is None:
        errors.add([field], "not_a_member", "The user must be an active member of the company")


def user_refs(uow: UnitOfWork, ids: Sequence[uuid.UUID | None]) -> dict[uuid.UUID, UserRef]:
    wanted = {i for i in ids if i is not None}
    if not wanted:
        return {}
    rows = uow.session.execute(select(AppUser.id, AppUser.display_name).where(AppUser.id.in_(wanted))).all()
    return {r[0]: UserRef(id=r[0], display_name=r[1]) for r in rows}


def user_ref(uow: UnitOfWork, user_id: uuid.UUID | None) -> UserRef | None:
    if user_id is None:
        return None
    return user_refs(uow, [user_id]).get(user_id) or UserRef(id=user_id, display_name=None)


def party_ref(uow: UnitOfWork, party_id: uuid.UUID) -> parties.PartyRef:
    """A party visible to the actor (404 outside scope, no existence leak)."""
    return parties.get_party_ref(uow, party_id)


def party_refs(uow: UnitOfWork, ids: Sequence[uuid.UUID], fallback: dict[uuid.UUID, tuple[str, str, str]]) -> dict[uuid.UUID, PartyRef]:
    """PartyRef per id from the party master when visible, else from the sales-side flattened columns
    (``fallback``: id -> (number, name, country)) so a quote never hides its customer name from its owner."""
    labels = parties.party_labels(uow, list(ids))
    out: dict[uuid.UUID, PartyRef] = {}
    for pid in {i for i in ids if i is not None}:
        number, name, country = fallback.get(pid, ("", "", ""))
        if pid in labels:
            number, name = labels[pid]
        out[pid] = PartyRef(id=pid, party_number=number, display_name=name, country_code=country)
    return out


def contact_of(uow: UnitOfWork, party_id: uuid.UUID, contact_id: uuid.UUID | None) -> ContactRead | None:
    """The named contact of a party (or its primary contact when ``contact_id`` is None); 422 when it does not
    belong to the party."""
    detail = parties.get_party(uow, party_id)
    if contact_id is None:
        primary = [c for c in detail.contacts if c.is_primary] or detail.contacts
        return primary[0] if primary else None
    for contact in detail.contacts:
        if contact.id == contact_id:
            return contact
    errors = Errors()
    errors.add(["contact_id"], "contact_not_of_party", "The contact does not belong to the party")
    errors.raise_if_any()
    return None


def idempotent[T: BaseModel](
    uow: UnitOfWork, operation: str, body: BaseModel | dict[str, Any], fn: Callable[[], T], model: type[T], status: int = 200
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
