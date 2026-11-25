"""Warehouses and locations: the company's virtual locations, the per-warehouse STOCK/QC/REJ set, bins, the
per-party external holding and the per-branch office location (all created on demand, idempotently)."""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.errors import NotFound, ValidationFailed
from app.modules.inventory.enums import (
    CATEGORY_LOCATIONS,
    COMPANY_LOCATIONS,
    COUNTS_AVAILABLE,
    STOCK_BEARING,
    WAREHOUSE_LOCATIONS,
    LocationType,
)
from app.modules.inventory.models import Location, Warehouse
from app.modules.parties.models import Party
from app.platform.org.models import Branch
from app.platform.uow import UnitOfWork

LOCATION_NAMES = {
    LocationType.SUPPLIER: "Suppliers",
    LocationType.CUSTOMER: "Customers",
    LocationType.PRODUCTION: "Production",
    LocationType.SCRAP: "Scrap",
    LocationType.ADJUSTMENT: "Inventory adjustments",
    LocationType.OPENING: "Opening stock",
    LocationType.SAMPLE_CONSUMPTION: "Samples given away",
    LocationType.IN_TRANSIT: "In transit",
}


def _flags(location_type: LocationType) -> tuple[bool, bool]:
    return location_type in STOCK_BEARING, location_type in COUNTS_AVAILABLE


def _insert_location(uow: UnitOfWork, **values: object) -> None:
    """INSERT ... ON CONFLICT DO NOTHING (concurrent first use of a holding or virtual location converges)."""
    location_type = LocationType(str(values["location_type"]))
    bearing, available = _flags(location_type)
    now = uow.now()
    uow.session.execute(
        pg_insert(Location)
        .values(
            id=uuid.uuid7(),
            company_id=uow.actor.company_id,
            is_stock_bearing=bearing,
            counts_available=available,
            is_default=False,
            is_active=True,
            created_at=now,
            updated_at=now,
            created_by=uow.actor.user_id,
            updated_by=uow.actor.user_id,
            **values,
        )
        .on_conflict_do_nothing()
    )


def ensure_company_locations(uow: UnitOfWork) -> dict[LocationType, Location]:
    existing = {
        LocationType(loc.location_type): loc
        for loc in uow.session.scalars(
            select(Location).where(
                Location.company_id == uow.actor.company_id,
                Location.warehouse_id.is_(None),
                Location.location_type.in_([t.value for t in COMPANY_LOCATIONS]),
            )
        )
    }
    missing = [t for t in COMPANY_LOCATIONS if t not in existing]
    for t in missing:
        _insert_location(uow, code=t.value.upper(), name=LOCATION_NAMES[t], location_type=t.value)
    if missing:
        return ensure_company_locations(uow)
    return existing


def company_location(uow: UnitOfWork, location_type: LocationType) -> Location:
    return ensure_company_locations(uow)[location_type]


def holding_location(uow: UnitOfWork, party_id: uuid.UUID) -> Location:
    """The external holding of ``party_id`` (goods out on job work, returnable samples); company-owned stock."""
    found = uow.session.scalars(
        select(Location).where(
            Location.company_id == uow.actor.company_id,
            Location.party_id == party_id,
            Location.location_type == LocationType.EXTERNAL_HOLDING.value,
        )
    ).first()
    if found is not None:
        return found
    party = uow.session.scalars(
        select(Party).where(Party.company_id == uow.actor.company_id, Party.id == party_id)
    ).first()
    if party is None:
        raise NotFound("party not found", code="party_not_found")
    _insert_location(
        uow,
        code=f"EXT-{party.party_number}",
        name=f"Held by {party.display_name}"[:200],
        location_type=LocationType.EXTERNAL_HOLDING.value,
        party_id=party_id,
    )
    return holding_location(uow, party_id)


def office_location(uow: UnitOfWork, branch_id: uuid.UUID) -> Location:
    found = uow.session.scalars(
        select(Location).where(
            Location.company_id == uow.actor.company_id,
            Location.office_branch_id == branch_id,
            Location.location_type == LocationType.OFFICE.value,
        )
    ).first()
    if found is not None:
        return found
    branch = uow.session.scalars(
        select(Branch).where(Branch.company_id == uow.actor.company_id, Branch.id == branch_id)
    ).first()
    if branch is None:
        raise NotFound("branch not found", code="branch_not_found")
    _insert_location(
        uow,
        code=f"OFFICE-{branch.branch_code}",
        name=f"{branch.name} office"[:200],
        location_type=LocationType.OFFICE.value,
        office_branch_id=branch_id,
    )
    return office_location(uow, branch_id)


def create_warehouse_rows(
    uow: UnitOfWork,
    *,
    code: str,
    name: str,
    branch_id: uuid.UUID | None,
    address: str | None,
    origin_ref: str | None,
    market: str | None = None,
    country_code: str | None = None,
) -> Warehouse:
    wh = Warehouse(
        id=uuid.uuid7(),
        company_id=uow.actor.company_id,
        code=code,
        name=name,
        branch_id=branch_id,
        address=address,
        origin_ref=origin_ref,
        is_active=True,
        market=market,
        country_code=country_code,
    )
    uow.add(wh)
    uow.flush()
    for loc_code, loc_type, loc_name in WAREHOUSE_LOCATIONS:
        bearing, available = _flags(loc_type)
        uow.add(
            Location(
                id=uuid.uuid7(),
                company_id=uow.actor.company_id,
                warehouse_id=wh.id,
                code=loc_code,
                name=loc_name,
                location_type=loc_type.value,
                is_stock_bearing=bearing,
                counts_available=available,
                is_default=loc_code == "STOCK",
                stock_category="inventory" if loc_type == LocationType.INTERNAL else None,
            )
        )
    for loc_code, loc_name, category in CATEGORY_LOCATIONS:
        uow.add(
            Location(
                id=uuid.uuid7(),
                company_id=uow.actor.company_id,
                warehouse_id=wh.id,
                code=loc_code,
                name=loc_name,
                location_type=LocationType.INTERNAL.value,
                is_stock_bearing=True,
                counts_available=False,
                is_default=False,
                stock_category=category,
            )
        )
    uow.flush()
    ensure_company_locations(uow)
    return wh


def add_bin(uow: UnitOfWork, warehouse: Warehouse, *, code: str, name: str | None) -> Location:
    parent = default_location(uow, warehouse.id)
    dup = uow.session.scalar(
        select(Location.id).where(
            Location.company_id == uow.actor.company_id,
            Location.warehouse_id == warehouse.id,
            Location.code == code,
        )
    )
    if dup is not None:
        raise ValidationFailed(
            "A location with this code exists in the warehouse",
            errors=[
                {
                    "loc": ["body", "code"],
                    "msg": "code already used in this warehouse",
                    "code": "duplicate_code",
                }
            ],
        )
    loc = Location(
        id=uuid.uuid7(),
        company_id=uow.actor.company_id,
        warehouse_id=warehouse.id,
        code=code,
        name=name or f"Bin {code}",
        location_type=LocationType.INTERNAL.value,
        parent_id=parent.id,
        is_stock_bearing=True,
        counts_available=True,
        is_default=False,
        stock_category="inventory",
    )
    uow.add(loc)
    uow.flush()
    return loc


def default_location(uow: UnitOfWork, warehouse_id: uuid.UUID) -> Location:
    loc = uow.session.scalars(
        select(Location).where(
            Location.company_id == uow.actor.company_id,
            Location.warehouse_id == warehouse_id,
            Location.is_default.is_(True),
        )
    ).first()
    if loc is None:
        raise NotFound("warehouse has no stock location", code="warehouse_not_found")
    return loc


def warehouse_location(uow: UnitOfWork, warehouse_id: uuid.UUID, location_type: LocationType) -> Location:
    if location_type == LocationType.INTERNAL:
        return default_location(uow, warehouse_id)
    loc = uow.session.scalars(
        select(Location)
        .where(
            Location.company_id == uow.actor.company_id,
            Location.warehouse_id == warehouse_id,
            Location.location_type == location_type.value,
        )
        .order_by(Location.code)
    ).first()
    if loc is None:
        raise NotFound(f"warehouse has no {location_type.value} location", code="location_not_found")
    return loc


def locations_by_id(uow: UnitOfWork, ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, Location]:
    wanted = {i for i in ids if i is not None}
    if not wanted:
        return {}
    rows = uow.session.scalars(
        select(Location).where(Location.company_id == uow.actor.company_id, Location.id.in_(wanted))
    )
    return {loc.id: loc for loc in rows}


def get_location(uow: UnitOfWork, location_id: uuid.UUID) -> Location:
    loc = locations_by_id(uow, [location_id]).get(location_id)
    if loc is None:
        raise NotFound("location not found", code="location_not_found")
    return loc


def active_warehouses(uow: UnitOfWork) -> list[Warehouse]:
    return list(
        uow.session.scalars(
            select(Warehouse)
            .where(Warehouse.company_id == uow.actor.company_id, Warehouse.is_active.is_(True))
            .order_by(Warehouse.code)
        )
    )


def wip_location(uow: UnitOfWork, warehouse_id: uuid.UUID) -> Location:
    """The work-in-progress location of a warehouse (``WIP``, stock-bearing, not available), created on first use.

    Production issues material internal -> WIP and consumes it WIP -> production (operations.md §6)."""
    found = uow.session.scalars(
        select(Location).where(
            Location.company_id == uow.actor.company_id,
            Location.warehouse_id == warehouse_id,
            Location.location_type == LocationType.WIP.value,
        ).order_by(Location.code)
    ).first()
    if found is not None:
        return found
    _insert_location(uow, code="WIP", name="Work in progress", location_type=LocationType.WIP.value,
                     warehouse_id=warehouse_id)
    return wip_location(uow, warehouse_id)
