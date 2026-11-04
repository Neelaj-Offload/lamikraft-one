"""Fixture inventory (docs/architecture/fixtures.md §8, Slice 4), created through the inventory services:

- the four catalogue products become stock-tracked (fixtures.md §5: ``is_stock_tracked`` true from Slice 4);
- Main Warehouse ``WH-MAIN`` (branch HO) with its STOCK/QC/REJ locations and bin ``A-12`` (Priya, D-10 09:00);
- opening batch ``OB-2026-0001`` created by Ravi (D-10 10:00) and approved by Sahil (D-10 11:30): 600 x LK-OT-0450,
  300 x LK-MT-0300, 200 x LK-AB-0400 in STOCK and 40 sheets of LK-WB-1800 lot WB-2610-A in A-12;
- inventory go-live: ``inventory_policy`` with challan postings on and WH-MAIN as the default warehouse. The earlier
  fixture challans (issued before go-live) stay documents only.

Re-running is idempotent (``origin_ref`` on the warehouse and the batch). The seeded personas' step-up (recent sign-in,
MFA for Sahil's approval) is represented on their seed contexts.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

from app.modules.catalogue import service as catalogue
from app.modules.catalogue.models import Product
from app.modules.catalogue.schemas import ProductUpdate
from app.modules.inventory import documents
from app.modules.inventory.models import Location, OpeningBatch, Warehouse
from app.modules.inventory.schemas import (
    BinCreate,
    Decision,
    OpeningBatchCreate,
    OpeningLineIn,
    Versioned,
    WarehouseCreate,
)
from app.platform.authz.actors import actor_for_member
from app.platform.org.models import Branch
from app.platform.uow import UnitOfWork
from app.seed.context import SeedContext
from app.seed.world import keys
from app.seed.world.parties import at_ist

WH_REF = "seed:WH-MAIN"
OB_REF = "seed:OB-MAIN"


def _uow(ctx: SeedContext, person: str, *, step_up: bool = False) -> UnitOfWork:
    actor = actor_for_member(ctx.company_id, ctx.ref(person), channel="cli")
    if step_up:
        actor = actor.with_(auth_strength="mfa", recent_auth_at=ctx.clock.now())
    return UnitOfWork(actor, clock=ctx.clock)


def make_stock_tracked(uow: UnitOfWork, product_ids: list) -> None:  # type: ignore[type-arg]
    for pid in product_ids:
        product = uow.session.get(Product, pid)
        if product is None or product.is_stock_tracked:
            continue
        catalogue.update_product(
            uow, pid, ProductUpdate(expected_version=product.version, is_stock_tracked=True)
        )


def seed_inventory(ctx: SeedContext) -> None:
    products = {k: ctx.ref(k) for k in ("OAK_TRAY", "MAPLE_TRIVET", "ASH_BOARD", "WALNUT_BOARD")}
    ctx.at(at_ist(-10, 9, 0))
    with _uow(ctx, keys.USERS.PRIYA, step_up=True) as uow:
        make_stock_tracked(uow, list(products.values()))
        wh = uow.session.scalars(
            select(Warehouse).where(Warehouse.company_id == ctx.company_id, Warehouse.origin_ref == WH_REF)
        ).first()
        if wh is None:
            ho = uow.session.scalar(
                select(Branch.id).where(
                    Branch.company_id == ctx.company_id, Branch.branch_code == keys.BRANCHES.HO
                )
            )
            wh = documents.create_warehouse(
                uow,
                WarehouseCreate(code=keys.WAREHOUSES.MAIN, name="Main Warehouse", branch_id=ho),
                origin_ref=WH_REF,
            )
            documents.create_bin(uow, wh.id, BinCreate(code=keys.BINS.A12, name="Bin A-12"))
        ctx.refs[keys.WAREHOUSE_REFS.MAIN] = wh.id
        ctx.refs[keys.WAREHOUSE_REFS.BIN_A12] = uow.session.scalar(
            select(Location.id).where(Location.warehouse_id == wh.id, Location.code == keys.BINS.A12)
        )
    batch_id = None
    with _uow(ctx, keys.USERS.RAVI) as uow:
        existing = uow.session.scalars(
            select(OpeningBatch).where(
                OpeningBatch.company_id == ctx.company_id, OpeningBatch.origin_ref == OB_REF
            )
        ).first()
        if existing is not None:
            ctx.refs[keys.OPENING_BATCH_REFS.MAIN] = existing.id
            return
    ctx.at(at_ist(-10, 10, 0))
    with _uow(ctx, keys.USERS.RAVI, step_up=True) as uow:
        lines = [
            OpeningLineIn(
                product_id=products[pk],
                quantity=Decimal(qty),
                location_id=None if loc == "STOCK" else ctx.ref(keys.WAREHOUSE_REFS.BIN_A12),
                lot_code=lot,
                source_row_ref=f"opening:{i}",
            )
            for i, (pk, qty, loc, lot) in enumerate(keys.OPENING_LINES, start=1)
        ]
        batch = documents.create_opening_batch(
            uow,
            OpeningBatchCreate(
                warehouse_id=ctx.ref(keys.WAREHOUSE_REFS.MAIN), notes="Opening stock at go-live", lines=lines
            ),
            origin_ref=OB_REF,
        )
        documents.submit_opening_batch(uow, batch.id, Versioned(expected_version=batch.version))
        batch_id = batch.id
    ctx.refs[keys.OPENING_BATCH_REFS.MAIN] = batch_id
    ctx.at(at_ist(-10, 11, 30))
    with _uow(ctx, keys.USERS.SAHIL, step_up=True) as uow:
        b = uow.session.get(OpeningBatch, batch_id)
        assert b is not None
        documents.decide_opening_batch(
            uow, batch_id, Decision(expected_version=b.version, note="Counted at go-live"), approve=True
        )
    with _uow(ctx, keys.USERS.PRIYA, step_up=True) as uow:
        from app.platform.org.service import get_setting, update_setting

        current = get_setting(uow, "inventory_policy")
        update_setting(
            uow,
            "inventory_policy",
            value={"challan_postings_enabled": True, "default_warehouse_code": keys.WAREHOUSES.MAIN},
            expected_version=current.version,
            change_reason="Inventory go-live",
            origin="seed",
        )
