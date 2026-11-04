"""Test support (mounted only when ``LK_ENV=test``): ``POST /api/v1/_test/inventory/go-live`` runs the Slice-4
inventory fixture seed (WH-MAIN, bin A-12, the approved opening batch, go-live) on the demo company of the e2e world,
which is seeded at Slice 2. Idempotent; the e2e scenario I spec calls it once before it starts."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from sqlalchemy import select

from app.core.clock import FrozenClock
from app.core.config import get_settings
from app.core.errors import NotFound
from app.core.http.authz_decl import test_support
from app.platform.authz.context import ActorContext
from app.platform.uow import UnitOfWork

router = APIRouter(prefix="/_test/inventory", tags=["inventory"])


@router.post("/go-live", openapi_extra=test_support(), operation_id="inventory_create_test_go_live")
def go_live() -> dict[str, Any]:
    if not get_settings().is_test:
        raise NotFound(code="not_found")
    from app.modules.catalogue.models import Product
    from app.platform.identity.models import AppUser, Membership
    from app.platform.org.models import Company
    from app.seed.context import D0, SeedContext
    from app.seed.world import keys
    from app.seed.world.inventory import seed_inventory

    with UnitOfWork(ActorContext.system(None, reason="test-support")) as uow:
        company_id = uow.session.scalar(select(Company.id).where(Company.company_key == keys.COMPANY_KEY))
    if company_id is None:
        raise NotFound("No demo company seeded", code="not_found")
    refs = {}
    with UnitOfWork(ActorContext.system(company_id, reason="test-support")) as uow:
        emails = {p.email: k for k, p in keys.PEOPLE.items()}
        for user_id, email in uow.session.execute(
            select(AppUser.id, AppUser.email)
            .join(Membership, Membership.user_id == AppUser.id)
            .where(Membership.company_id == company_id)
        ).all():
            if email in emails:
                refs[emails[email]] = user_id
        for attr in ("OAK_TRAY", "MAPLE_TRIVET", "ASH_BOARD", "WALNUT_BOARD"):
            pid = uow.session.scalar(
                select(Product.id).where(
                    Product.company_id == company_id, Product.product_key == getattr(keys.PRODUCTS, attr)
                )
            )
            if pid is None:
                raise NotFound(f"fixture product {attr} missing", code="not_found")
            refs[attr] = pid
    ctx = SeedContext(company_id=company_id, clock=FrozenClock(D0), refs=refs, slice_max=4)
    seed_inventory(ctx)
    return {
        "warehouse_id": str(ctx.refs[keys.WAREHOUSE_REFS.MAIN]),
        "opening_batch_id": str(ctx.refs[keys.OPENING_BATCH_REFS.MAIN]),
    }
