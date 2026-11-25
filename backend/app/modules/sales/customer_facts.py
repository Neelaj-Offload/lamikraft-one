"""Customer facts for the customer record (module 2, spec 2026-11-25-customers-samples-design.md).

Customer since, last contact (latest logged activity) and won business per currency. Counts of quotations, samples and
orders are already on the record's tabs. Quotations are counted through the caller's own quote scope, so a sales user
sees only the value of the quotations they may read.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel
from sqlalchemy import func, select

from app.core.money import DecimalStr
from app.modules.parties.models import Party, PartyActivity
from app.modules.sales.models import Quote
from app.platform.service import query
from app.platform.uow import UnitOfWork


class WonValue(BaseModel):
    currency: str
    amount: DecimalStr
    quotations: int


class CustomerFacts(BaseModel):
    party_id: uuid.UUID
    #: when the lead became a customer (stage won); else the first contact for an older customer
    customer_since: date | None
    last_activity_at: datetime | None
    #: won quotations the caller may read, summed per currency (grand totals; decimal strings)
    won: list[WonValue]


@query("parties.party.read")
def customer_facts(uow: UnitOfWork, party_id: uuid.UUID) -> CustomerFacts:
    party = uow.repo(Party).get(party_id)  # 404 outside the caller's scope
    since: date | None = None
    if party.lead_stage == "won" and party.stage_changed_at is not None:
        since = party.stage_changed_at.date()
    elif party.status == "active":
        since = party.first_contact_on
    last = uow.session.scalar(
        select(func.max(PartyActivity.occurred_at)).where(
            PartyActivity.company_id == uow.actor.company_id, PartyActivity.party_id == party.id
        )
    )
    won: list[WonValue] = []
    if uow.actor.can("sales.quote.read"):
        repo = uow.repo(Quote)
        rows = uow.session.execute(
            select(Quote.currency, func.coalesce(func.sum(Quote.grand_total_amount), 0), func.count())
            .where(Quote.party_id == party.id, Quote.status == "won", repo.clause("read"))
            .group_by(Quote.currency)
            .order_by(Quote.currency)
        ).all()
        won = [WonValue(currency=c, amount=str(a), quotations=int(n)) for c, a, n in rows]
    return CustomerFacts(party_id=party.id, customer_since=since, last_activity_at=last, won=won)
