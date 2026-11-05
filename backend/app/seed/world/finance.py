"""Fixture finance (docs/architecture/fixtures.md §8, Slice 5), created through the finance services:

- receipt ``RCPT-2026-27-0001``: Maison Atelier SARL, EUR 2,400.0000 by bank transfer, received D-4, recorded by Ananya
  (D-4 11:00) and left unallocated (no invoice can be issued under the Demo defaults, BUILD_STATE §5 #4 and #9);
- the accounting integration stays "Not connected (demo)" and no tax profile is seeded (rates are never invented);
- invoice suggestions for any issued Outward challan to a customer the earlier seeds produced (none in the base
  world; the consumer creates them as challans are issued).

Re-running is idempotent (``origin_ref`` on the receipt). Ananya's briefing then holds the unallocated receipt once the
``finance.unallocated_sweep`` has run (it is run here so the seeded world matches the fixture).
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

from app.modules.finance import jobs, receipts
from app.modules.finance.enums import ReceiptMethod
from app.modules.finance.models import Receipt
from app.modules.finance.schemas import ReceiptCreate
from app.platform.authz.actors import actor_for_member
from app.platform.authz.context import ActorContext
from app.platform.uow import UnitOfWork
from app.seed.context import SeedContext
from app.seed.world import keys
from app.seed.world.parties import at_ist

RECEIPT_REF = "seed:RCPT-MAISON"
#: SeedContext.refs key of the Maison receipt
RECEIPT_MAISON = keys.FINANCE_REFS.RECEIPT_MAISON


def _uow(ctx: SeedContext, person: str) -> UnitOfWork:
    return UnitOfWork(actor_for_member(ctx.company_id, ctx.ref(person), channel="cli"), clock=ctx.clock)


def seed_finance(ctx: SeedContext) -> None:
    with _uow(ctx, keys.USERS.ANANYA) as uow:
        existing = uow.session.scalars(
            select(Receipt).where(Receipt.company_id == ctx.company_id, Receipt.origin_ref == RECEIPT_REF)
        ).first()
        if existing is not None:
            ctx.refs[RECEIPT_MAISON] = existing.id
            return
    ctx.at(at_ist(-4, 11, 0))
    with _uow(ctx, keys.USERS.ANANYA) as uow:
        r = receipts.record_receipt(
            uow,
            ReceiptCreate(
                party_id=ctx.ref("MAISON"), amount=Decimal("2400.0000"), currency="EUR",
                received_on=at_ist(-4, 11, 0).date(), method=ReceiptMethod.BANK_TRANSFER,
                reference="SEPA 2026-10-08 MAISON", bank_account_label="EUR account",
            ),
            origin="seed",
            origin_ref=RECEIPT_REF,
        )
        ctx.refs[RECEIPT_MAISON] = r.id
    ctx.at(at_ist(0, 6, 0))
    with UnitOfWork(ActorContext.system(ctx.company_id, reason=jobs.UNALLOCATED_JOB), clock=ctx.clock) as uow:
        jobs.sweep_unallocated(uow)
