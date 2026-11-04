"""Shared procurement helpers: business date, numbering, reference reads, the vendor and product checks used by
every command (a guessed vendor id is a 404 through the parties scope; a non-vendor party is a 422)."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.core.errors import Forbidden, ValidationFailed
from app.core.http.capabilities import Capability
from app.modules.catalogue.models import Product
from app.modules.parties.models import Party
from app.modules.procurement.schemas import PartyBrief, ProductBrief, UserBrief, WarehouseBrief
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


def number(uow: UnitOfWork, key: str, resource_id: uuid.UUID, branch_id: uuid.UUID | None) -> str:
    return uow.allocate_number(
        key, document_date=business_date(uow), resource_type=key, resource_id=resource_id, branch_id=branch_id
    )


def cap(ok: bool, reason: str) -> Capability:
    return Capability(allowed=ok, reason_code=None if ok else reason)


def invalid(msg: str, loc: list[str | int], code: str) -> ValidationFailed:
    return ValidationFailed(msg, errors=[{"loc": ["body", *loc], "msg": msg, "code": code}])


def require_vendor(uow: UnitOfWork, party_id: uuid.UUID, loc: list[str | int] | None = None) -> Party:
    """The party when the actor may read it (404 otherwise) and it holds the vendor role (422 otherwise)."""
    party = uow.repo(Party).get(party_id)
    if "vendor" not in (party.roles or []):
        raise invalid("The party is not a vendor", loc or ["vendor_party_id"], "party_not_vendor")
    return party


def stock_product(uow: UnitOfWork, product_id: uuid.UUID, loc: list[str | int]) -> Product:
    p = uow.session.scalars(
        select(Product).where(Product.company_id == uow.actor.company_id, Product.id == product_id)
    ).first()
    if p is None or not p.is_stock_tracked or not p.stock_uom_code:
        raise invalid("The product is not stock-tracked", [*loc, "product_id"], "product_not_stock_tracked")
    return p


def product_briefs(uow: UnitOfWork, ids: Iterable[uuid.UUID | None]) -> dict[uuid.UUID, ProductBrief]:
    wanted = {i for i in ids if i}
    if not wanted:
        return {}
    rows = uow.session.scalars(
        select(Product).where(Product.company_id == uow.actor.company_id, Product.id.in_(wanted))
    )
    return {
        p.id: ProductBrief(
            id=p.id,
            product_key=p.product_key,
            name=p.product_name,
            stock_unit=p.stock_uom_code,
            qc_required=bool(p.qc_required),
            track_lots=bool(p.track_lots),
        )
        for p in rows
    }


def party_briefs(uow: UnitOfWork, ids: Iterable[uuid.UUID | None]) -> dict[uuid.UUID, PartyBrief]:
    """Names of parties referenced by documents the actor can already read (not a party-scope bypass for lists)."""
    wanted = {i for i in ids if i}
    if not wanted:
        return {}
    rows = uow.session.execute(
        select(Party.id, Party.party_number, Party.display_name).where(
            Party.company_id == uow.actor.company_id, Party.id.in_(wanted)
        )
    ).all()
    return {r[0]: PartyBrief(id=r[0], party_number=r[1], display_name=r[2]) for r in rows}


def warehouse_briefs(uow: UnitOfWork, ids: Iterable[uuid.UUID | None]) -> dict[uuid.UUID, WarehouseBrief]:
    from app.modules.inventory.reads import warehouse_refs

    return {k: WarehouseBrief(id=v.id, code=v.code, name=v.name) for k, v in warehouse_refs(uow, ids).items()}


def user_briefs(uow: UnitOfWork, ids: Iterable[uuid.UUID | None]) -> dict[uuid.UUID, UserBrief]:
    wanted = {i for i in ids if i}
    if not wanted:
        return {}
    rows = uow.session.execute(select(AppUser.id, AppUser.display_name).where(AppUser.id.in_(wanted))).all()
    return {r[0]: UserBrief(id=r[0], display_name=r[1]) for r in rows}


def plain(value: Decimal | int | None) -> Decimal:
    """A Decimal without trailing zeros (``240.0000`` -> ``240``) for read models."""
    if value is None:
        return ZERO
    d = Decimal(value)
    return d.quantize(Decimal(1)) if d == d.to_integral() else d.normalize()


def require_scope(uow: UnitOfWork, model: type, record_id: uuid.UUID, action: str) -> None:
    """The actor holds ``<prefix>.<action>`` in scope over the record (state rules are checked by the caller)."""
    repo = uow.repo(model)
    if uow.session.scalar(select(model.id).where(model.id == record_id, repo.clause(action))) is None:
        raise Forbidden(code="permission_denied", permission=repo.policy.permission(action))


def money4(value: Decimal | int | None) -> Decimal:
    """Money as stored (NUMERIC(18,4)): four places in read models whatever the in-memory scale."""
    from app.core.money import quantize_unit_price

    return quantize_unit_price(Decimal(value or 0))
