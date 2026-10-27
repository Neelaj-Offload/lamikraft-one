"""Fixture parties (docs/architecture/fixtures.md §4), created through the parties service.

The four Slice-1 customers are created by Priya at D-120 .. D-117 (``parties.world``, order 20; numbers P-00001 ..
P-00004 follow from the creation order through the real allocator). Maison's shipping address is changed by Priya
at D-1 10:05 IST in a separate, late SeedDef (``parties.world.changes``, order 55, after the catalogue, pricing and
sales history) so the seed clock only moves forward (fixtures.md §1 rule 2); it emits ``parties.party.updated``
with ``addresses.shipping`` (the "changes since your last visit" fact for Meera).
Re-running is idempotent: existing parties are found by legal name and only their references are recorded.
Owners are the users created by the identity seed (``ctx.refs[keys.USERS.MEERA]`` ...).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select

from app.modules.parties import service as parties
from app.modules.parties.schemas import AddressIn, ContactIn, PartyCreate, PartyUpdate
from app.platform.authz.actors import actor_for_member
from app.platform.org.models import Branch
from app.platform.uow import UnitOfWork
from app.seed.context import D0, SeedContext
from app.seed.world import keys

#: Priya (admin) creates the master data of the world
CREATOR = keys.USERS.PRIYA


def as_member(ctx: SeedContext, user_key: str) -> UnitOfWork:
    """A unit of work acting as a fixture persona at the seed clock (identity builds the effective context)."""
    actor = actor_for_member(ctx.company_id, ctx.ref(user_key), channel="cli")
    return UnitOfWork(actor, clock=ctx.clock)


def at_ist(day_offset: int, hour: int, minute: int = 0) -> datetime:
    """D0-relative local time (Asia/Kolkata), e.g. ``at_ist(-1, 10, 5)`` is D-1 10:05 IST."""
    return (D0 + timedelta(days=day_offset)).replace(hour=hour, minute=minute, second=0, microsecond=0)


@dataclass(frozen=True)
class FixtureParty:
    key: str  # attribute of keys.PARTIES (also the SeedContext.refs key)
    country: str
    currency: str
    customer_type: str
    owner: str  # keys.USERS attribute
    contact: str
    contact_email: str
    billing: AddressIn
    shipping: AddressIn
    created: datetime


def _address(kind: str, line1: str, city: str, postal: str, country: str, line2: str | None = None) -> AddressIn:
    return AddressIn(kind=kind, line1=line1, line2=line2, city=city, postal_code=postal, country_code=country)  # type: ignore[arg-type]


#: fictional addresses and contacts; tax identifiers are deliberately empty (no fabricated GSTIN/VAT numbers)
SLICE1_CUSTOMERS: tuple[FixtureParty, ...] = (
    FixtureParty(
        "NORDHAUS", "DE", "EUR", "standard", keys.USERS.MEERA, "Lena Brandt", "lena.brandt@nordhaus-interiors.test",
        _address("billing", "Lagerweg 4", "Hamburg", "20457", "DE"),
        _address("shipping", "Lagerweg 4, Tor 2", "Hamburg", "20457", "DE"),
        at_ist(-120, 10),
    ),
    FixtureParty(
        "MAISON", "FR", "EUR", "standard", keys.USERS.MEERA, "Camille Laurent", "camille.laurent@maison-atelier.test",
        _address("billing", "12 rue des Ateliers", "Lyon", "69002", "FR"),
        _address("shipping", "Entrepôt A, 8 rue du Port", "Lyon", "69007", "FR"),
        at_ist(-119, 10),
    ),
    FixtureParty(
        "BERG", "SE", "EUR", "standard", keys.USERS.MEERA, "Erik Lindqvist", "erik.lindqvist@bergco.test",
        _address("billing", "Hamngatan 5", "Göteborg", "41106", "SE"),
        _address("shipping", "Hamngatan 5, Lager 1", "Göteborg", "41106", "SE"),
        at_ist(-118, 10),
    ),
    FixtureParty(
        "THORNBURY", "GB", "GBP", "dealer", keys.USERS.NEHA, "Oliver Hart", "oliver.hart@thornbury-kitchens.test",
        _address("billing", "Unit 4, Mill Lane Trading Estate", "Bristol", "BS3 4AA", "GB"),
        _address("shipping", "Unit 4, Mill Lane Trading Estate, Gate B", "Bristol", "BS3 4AA", "GB"),
        at_ist(-117, 10),
    ),
)

#: Maison's new shipping address, recorded by Priya at D-1 10:05 IST (04:35Z)
MAISON_SHIPPING_CHANGE_AT = at_ist(-1, 10, 5)
MAISON_NEW_SHIPPING = _address("shipping", "Entrepôt B, 40 avenue des Docks", "Lyon", "69007", "FR")


def _head_office(uow: UnitOfWork) -> uuid.UUID | None:
    return uow.session.scalar(
        select(Branch.id).where(Branch.company_id == uow.actor.company_id, Branch.branch_code == keys.BRANCHES.HO)
    )


def _create(ctx: SeedContext, spec: FixtureParty) -> uuid.UUID:
    legal_name = keys.PARTY_NAMES[spec.key]
    ctx.at(spec.created)
    with as_member(ctx, CREATOR) as uow:
        existing = parties.find_party_id_by_name(uow, legal_name)
        if existing is not None:
            return existing
        detail = parties.create_party(
            uow,
            PartyCreate(
                legal_name=legal_name,
                display_name=legal_name,
                country_code=spec.country,
                default_currency=spec.currency,  # type: ignore[arg-type]
                customer_type=spec.customer_type,  # type: ignore[arg-type]
                roles=["customer"],  # type: ignore[list-item]
                owner_user_id=ctx.ref(spec.owner),
                branch_id=_head_office(uow),
                contacts=[ContactIn(name=spec.contact, email=spec.contact_email, is_primary=True)],
                addresses=[spec.billing, spec.shipping],
            ),
        )
        return detail.id


def _change_maison_shipping(ctx: SeedContext) -> None:
    ctx.at(MAISON_SHIPPING_CHANGE_AT)
    with as_member(ctx, CREATOR) as uow:
        current = parties.get_party(uow, ctx.ref("MAISON"))
        shipping = [a for a in current.addresses if a.kind == "shipping" and a.is_default]
        if shipping and shipping[0].line1 == MAISON_NEW_SHIPPING.line1:
            return  # already applied (idempotent re-run)
        addresses = [
            AddressIn(
                id=a.id, kind=a.kind, line1=a.line1, line2=a.line2, city=a.city, region=a.region,
                postal_code=a.postal_code, country_code=a.country_code, is_default=a.is_default,
            )
            if a.kind != "shipping"
            else MAISON_NEW_SHIPPING.model_copy(update={"id": a.id})
            for a in current.addresses
        ]
        parties.update_party(uow, current.id, PartyUpdate(expected_version=current.version, addresses=addresses))


def seed_parties(ctx: SeedContext) -> None:
    """``parties.world`` (order 20): the four Slice-1 customers at D-120 .. D-117."""
    for spec in SLICE1_CUSTOMERS:
        ctx.refs[spec.key] = _create(ctx, spec)


def seed_party_changes(ctx: SeedContext) -> None:
    """``parties.world.changes`` (order 55): dated master-data changes close to D0 (Maison's shipping, D-1 10:05)."""
    _change_maison_shipping(ctx)
