"""Fixture logistics (Slice 4): the container profiles a load suggestion can use, entered by Ravi (D-10 14:00).
Values are entered, never assumed: 20 ft GP 33.2 m3 / 28,200 kg, 40 ft HC 76.4 m3 / 28,600 kg, fill factor 0.85.
Re-running updates the same codes."""

from __future__ import annotations

from decimal import Decimal

from app.modules.logistics import shipments
from app.modules.logistics.schemas import ContainerProfileIn
from app.platform.authz.actors import actor_for_member
from app.platform.uow import UnitOfWork
from app.seed.context import SeedContext
from app.seed.world import keys
from app.seed.world.parties import at_ist

PROFILES = (
    ("20GP", "20 ft general purpose", "33.2", "28200", "0.85"),
    ("40HC", "40 ft high cube", "76.4", "28600", "0.85"),
)


def seed_logistics(ctx: SeedContext) -> None:
    ctx.at(at_ist(-10, 14, 0))
    with UnitOfWork(
        actor_for_member(ctx.company_id, ctx.ref(keys.USERS.RAVI), channel="cli"), clock=ctx.clock
    ) as uow:
        for code, name, vol, kg, fill in PROFILES:
            p = shipments.save_profile(
                uow,
                ContainerProfileIn(
                    code=code,
                    name=name,
                    internal_volume_m3=Decimal(vol),
                    max_payload_kg=Decimal(kg),
                    fill_factor=Decimal(fill),
                ),
            )
            ctx.refs[f"CONTAINER_{code}"] = p.id
