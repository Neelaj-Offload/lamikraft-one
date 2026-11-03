"""Fixture delivery challans (docs/architecture/fixtures.md §8, Slice 2), created through the challan services as
Ravi (operations) with the clock at each fact's time.

- ``DC-2026-0001``: Job Work, returnable, 12 × LK-WB-1800 to Precision Edge Fabricators; issued D-7 10:30, expected
  return D0+1 (so the returnables sweep raises ``became_due`` the day after D0).
- ``DC-2026-0002``: Sample, returnable, 2 × LK-AB-0400 to Maison Atelier; issued D-3 15:00 (the sample ``SMP-2026-0001``
  itself belongs to the sales module's Slice-2 work and is not created here).
- ``DC-2026-0003``: Outward, non-returnable, 40 × LK-OT-0450 to Nordhaus; a draft at D0 08:30 for the operations UI.

The fabricator party (``P-00006`` Precision Edge Fabricators, slice 2) is created here when the parties seed has not
yet produced it. Re-running is idempotent: every challan carries ``origin_ref = seed:<KEY>``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.modules.challans import service as challans
from app.modules.challans.models import Challan
from app.modules.challans.schemas import (
    ChallanCreate,
    ChallanLineCreate,
    ChallanTransition,
    ChallanType,
    DestinationType,
    LineType,
    ReturnType,
)
from app.modules.challans.transitions import transition_challan_command
from app.modules.parties import service as parties
from app.modules.parties.schemas import AddressIn, ContactIn, PartyCreate
from app.platform.authz.actors import actor_for_member
from app.platform.org.models import Branch
from app.platform.uow import UnitOfWork
from app.seed.context import SeedContext
from app.seed.world import keys
from app.seed.world.parties import as_member, at_ist

SEED = "seed"
FABRICATOR_CREATED_AT = at_ist(-30, 10, 0)


def _ref(key: str) -> str:
    return f"{SEED}:{key}"


@dataclass(frozen=True)
class FixtureChallan:
    key: str  # keys.CHALLANS attribute
    challan_type: ChallanType
    return_type: ReturnType
    destination_type: DestinationType
    party: str  # keys.PARTIES attribute / refs key
    created: datetime
    reference_no: str
    remarks: str
    issued: datetime | None = None
    expected_return_days: int | None = None  # from the challan date


FIXTURES: tuple[FixtureChallan, ...] = (
    FixtureChallan(
        "JOB_WORK",
        ChallanType.JOB_WORK,
        ReturnType.RETURNABLE,
        DestinationType.FABRICATOR,
        "PRECISION_EDGE",
        at_ist(-7, 10, 15),
        "JW-0918",
        "Edge banding of walnut panels; return trimmed boards.",
        issued=at_ist(-7, 10, 30),
        expected_return_days=8,
    ),
    FixtureChallan(
        "SAMPLE_MAISON",
        ChallanType.SAMPLE,
        ReturnType.RETURNABLE,
        DestinationType.CUSTOMER,
        "MAISON",
        at_ist(-3, 14, 45),
        "SMP-2026-0001",
        "Launch range samples for approval.",
        issued=at_ist(-3, 15, 0),
        expected_return_days=30,
    ),
    FixtureChallan(
        "OUTWARD_DRAFT",
        ChallanType.OUTWARD,
        ReturnType.NON_RETURNABLE,
        DestinationType.CUSTOMER,
        "NORDHAUS",
        at_ist(0, 8, 30),
        "PO-NH-2211",
        "Repeat order trays; palletised.",
    ),
)


def _head_office(uow: UnitOfWork) -> uuid.UUID | None:
    return uow.session.scalar(
        select(Branch.id).where(
            Branch.company_id == uow.actor.company_id, Branch.branch_code == keys.BRANCHES.HO
        )
    )


def _ensure_vendor(ctx: SeedContext) -> None:
    """Kaveri Timber Supplies (fixtures.md: P-00005, vendor, slice 2), created first so Precision Edge is P-00006 as
    ``keys.PARTIES`` says (Slice-2 merge: no other slice-2 seed creates it yet)."""
    if "KAVERI" in ctx.refs:
        return
    legal_name = keys.PARTY_NAMES["KAVERI"]
    ctx.at(FABRICATOR_CREATED_AT)
    with as_member(ctx, keys.USERS.PRIYA) as uow:
        existing = parties.find_party_id_by_name(uow, legal_name)
        if existing is not None:
            ctx.refs["KAVERI"] = existing
            return
        detail = parties.create_party(
            uow,
            PartyCreate(
                legal_name=legal_name,
                display_name=legal_name,
                country_code="IN",
                default_currency="INR",  # type: ignore[arg-type]
                roles=["vendor"],  # type: ignore[list-item]
                owner_user_id=ctx.ref(keys.USERS.RAVI),
                branch_id=_head_office(uow),
                contacts=[ContactIn(name="Anil Rao", email="anil.rao@kaveri-timber.test", is_primary=True)],
            ),
        )
        ctx.refs["KAVERI"] = detail.id


def _ensure_fabricator(ctx: SeedContext) -> None:
    """Precision Edge Fabricators (slice 2 party) unless the parties seed already created it."""
    if "PRECISION_EDGE" in ctx.refs:
        return
    _ensure_vendor(ctx)
    legal_name = keys.PARTY_NAMES["PRECISION_EDGE"]
    ctx.at(FABRICATOR_CREATED_AT)
    with as_member(ctx, keys.USERS.PRIYA) as uow:
        existing = parties.find_party_id_by_name(uow, legal_name)
        if existing is not None:
            ctx.refs["PRECISION_EDGE"] = existing
            return
        detail = parties.create_party(
            uow,
            PartyCreate(
                legal_name=legal_name,
                display_name=legal_name,
                country_code="IN",
                default_currency="INR",  # type: ignore[arg-type]
                roles=["fabricator"],  # type: ignore[list-item]
                owner_user_id=ctx.ref(keys.USERS.RAVI),
                branch_id=_head_office(uow),
                contacts=[
                    ContactIn(name="Suresh Patil", email="suresh.patil@precision-edge.test", is_primary=True)
                ],
                addresses=[
                    AddressIn(
                        kind="shipping",
                        line1="Plot 14, MIDC Phase II",
                        city="Pune",
                        postal_code="411026",
                        country_code="IN",
                    )
                ],  # type: ignore[arg-type]
            ),
        )
        ctx.refs["PRECISION_EDGE"] = detail.id


def _find(uow: UnitOfWork, key: str) -> uuid.UUID | None:
    return uow.session.scalar(
        select(Challan.id).where(Challan.company_id == uow.actor.company_id, Challan.origin_ref == _ref(key))
    )


def _create(ctx: SeedContext, spec: FixtureChallan) -> uuid.UUID:
    ctx.at(spec.created)
    product_key, quantity = keys.CHALLAN_LINES[spec.key]
    with as_member(ctx, keys.USERS.RAVI) as uow:
        existing = _find(uow, spec.key)
        if existing is not None:
            return existing
        challan_date = spec.created.date()
        challan = challans.create_challan(
            uow,
            ChallanCreate(
                challan_date=challan_date,
                challan_type=spec.challan_type,
                return_type=spec.return_type,
                destination_type=spec.destination_type,
                party_id=ctx.ref(spec.party),
                reference_no=spec.reference_no,
                remarks=spec.remarks,
                expected_return_date=(challan_date + timedelta(days=spec.expected_return_days))
                if spec.expected_return_days
                else None,
                lines=[
                    ChallanLineCreate(
                        line_type=LineType.CATALOG,
                        product_id=ctx.ref(product_key),
                        quantity=Decimal(quantity),
                    )
                ],
            ),
            origin=SEED,
            origin_ref=_ref(spec.key),
        )
        return challan.id


def _issue(ctx: SeedContext, challan_id: uuid.UUID, at: datetime) -> None:
    ctx.at(at)
    actor = actor_for_member(ctx.company_id, ctx.ref(keys.USERS.RAVI), channel="cli").with_(
        idempotency_key=f"seed:{challan_id}:issue"
    )
    with UnitOfWork(actor, clock=ctx.clock) as uow:
        current = challans.get_challan(uow, challan_id)
        if current.status != "draft":
            return
        transition_challan_command(
            uow, challan_id, ChallanTransition(action="issue", expected_version=current.version)
        )


def _settle(ctx: SeedContext) -> None:
    from app.platform.jobs.worker import drain
    from app.seed.world.tasks import seed_clock

    with seed_clock(ctx):
        drain()


def seed_challans(ctx: SeedContext) -> None:
    """``challans.world`` (order 52): the fixture challans of fixtures.md §8 in creation order."""
    _ensure_fabricator(ctx)
    for spec in FIXTURES:
        challan_id = _create(ctx, spec)
        ctx.refs[keys.CHALLAN_REFS.__dict__[spec.key]] = challan_id
        if spec.issued is not None:
            _issue(ctx, challan_id, spec.issued)
        _settle(ctx)
