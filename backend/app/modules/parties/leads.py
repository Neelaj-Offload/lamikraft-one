"""The lead pipeline: stage changes and the lead summary (spec 2026-11-25-leads-module-design.md).

A lead is a party with the customer role. Its stage runs new → contacted → qualified → negotiating → won / lost.
``lost`` needs a reason (also a DB check); reopening a lost lead clears it. ``won`` turns a prospect into an active
customer and is final in this module. Stage changes go only through ``change_lead_stage`` (never ``update_party``),
so ``parties.lead.stage_changed`` is the single signal the follow-up rule and the activity feed listen to.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import and_, func, select

from app.core.clock import local_date
from app.core.errors import Conflict, ValidationFailed
from app.modules.parties import events as ev
from app.modules.parties.lead_sources import labels_for
from app.modules.parties.models import Party
from app.modules.parties.schemas import (
    OPEN_STAGES,
    CountRow,
    LeadStage,
    LeadStageChange,
    LeadSummary,
    PartyDetail,
    PartyStatus,
)
from app.modules.parties.service import _detail, _owner_names
from app.platform.service import query
from app.platform.uow import UnitOfWork

READ = "parties.party.read"

STAGE_LABELS = {
    "new": "New",
    "contacted": "Contacted",
    "qualified": "Qualified",
    "negotiating": "Negotiating",
    "won": "Won",
    "lost": "Lost",
}


def _invalid(msg: str, code: str, field: str = "stage") -> ValidationFailed:
    return ValidationFailed(msg, errors=[{"loc": ["body", field], "msg": msg, "code": code}])


def change_lead_stage(uow: UnitOfWork, party_id: uuid.UUID, data: LeadStageChange) -> PartyDetail:
    party = uow.repo(Party).get(party_id, "update", for_update=True)
    uow.expect_version(party, data.expected_version)
    if party.lead_stage is None:
        raise Conflict("Only leads and customers have a pipeline stage", code="not_a_lead")
    if party.archived_at is not None:
        raise Conflict("Restore this lead before moving it", code="archived")
    if party.lead_stage == LeadStage.WON.value:
        raise Conflict("This lead is already won and is now a customer", code="lead_won")
    target = data.stage
    if target == LeadStage.LOST and not data.lost_reason:
        raise _invalid("Say why the lead was lost", "lost_reason_required", "lost_reason")
    if target != LeadStage.LOST and data.lost_reason:
        raise _invalid("A reason is only kept for lost leads", "lost_reason_not_allowed", "lost_reason")
    previous = party.lead_stage
    if target.value == previous and (target != LeadStage.LOST or data.lost_reason == party.lost_reason):
        return _detail(uow, party)
    party.lead_stage = target.value
    party.lost_reason = data.lost_reason if target == LeadStage.LOST else None
    changed = ["lead_stage"]
    if target == LeadStage.WON and party.status == PartyStatus.PROSPECT.value:
        party.status = PartyStatus.ACTIVE.value
        changed.append("status")
    if target in (LeadStage.WON, LeadStage.LOST):
        party.next_follow_up_on = None
        changed.append("next_follow_up_on")
    party.updated_at = uow.now()
    party.stage_changed_at = uow.now()
    uow.flush()
    uow.emit(
        ev.LEAD_STAGE_CHANGED,
        aggregate_id=party.id,
        aggregate_version=party.version,
        payload=ev.payload(ev.LeadStageChangedPayload(party_id=party.id, from_stage=previous, to_stage=target.value)),
    )
    if "status" in changed:
        uow.emit(
            ev.PARTY_UPDATED,
            aggregate_id=party.id,
            aggregate_version=party.version,
            payload=ev.payload(
                ev.PartyUpdatedPayload(party_id=party.id, party_number=party.party_number, changed_fields=["status"])
            ),
        )
    uow.audit(
        "parties.lead.stage_changed",
        resource_type="parties.party",
        resource_id=party.id,
        resource_label=f"{party.party_number} · {party.display_name}",
        details={"from": previous, "to": target.value, "lost_reason": party.lost_reason},
    )
    return _detail(uow, party)


def _percent(part: int, whole: int) -> str:
    if whole == 0:
        return "0.0"
    return str((Decimal(part) * 100 / Decimal(whole)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


@query(READ)
def lead_summary(uow: UnitOfWork) -> LeadSummary:
    """Pipeline numbers over the leads the caller may read (archived leads are left out)."""
    repo = uow.repo(Party)
    base = and_(
        Party.company_id == uow.actor.company_id,
        Party.lead_stage.is_not(None),
        Party.archived_at.is_(None),
        repo.clause("read"),
    )
    today: date = local_date(uow.now(), uow.actor.time_zone)
    month_start = today.replace(day=1)
    by_stage = dict(
        uow.session.execute(select(Party.lead_stage, func.count()).where(base).group_by(Party.lead_stage)).all()
    )
    open_count = sum(int(by_stage.get(s.value, 0)) for s in OPEN_STAGES)
    won = int(by_stage.get("won", 0))
    lost = int(by_stage.get("lost", 0))
    open_filter = and_(base, Party.lead_stage.in_([s.value for s in OPEN_STAGES]))
    overdue = uow.session.scalar(
        select(func.count()).where(open_filter, Party.next_follow_up_on < today)
    ) or 0
    due_today = uow.session.scalar(
        select(func.count()).where(open_filter, Party.next_follow_up_on == today)
    ) or 0
    won_this_month = uow.session.scalar(
        select(func.count()).where(
            base,
            Party.lead_stage == "won",
            func.timezone(uow.actor.time_zone, Party.stage_changed_at) >= month_start,
        )
    ) or 0
    sources = uow.session.execute(
        select(Party.lead_source_code, func.count())
        .where(open_filter)
        .group_by(Party.lead_source_code)
        .order_by(func.count().desc())
    ).all()
    source_labels = labels_for(uow, [code for code, _n in sources])
    owners = uow.session.execute(
        select(Party.owner_user_id, func.count())
        .where(open_filter)
        .group_by(Party.owner_user_id)
        .order_by(func.count().desc())
    ).all()
    owner_names = _owner_names(uow, [uid for uid, _n in owners])
    return LeadSummary(
        open=open_count,
        won=won,
        lost=lost,
        won_this_month=int(won_this_month),
        conversion_rate=_percent(won, open_count + won + lost),
        follow_ups_overdue=int(overdue),
        follow_ups_today=int(due_today),
        by_stage=[
            CountRow(key=s.value, label=STAGE_LABELS[s.value], count=int(by_stage.get(s.value, 0))) for s in LeadStage
        ],
        by_source=[
            CountRow(key=code or "none", label=source_labels.get(code, code) if code else "No source", count=int(n))
            for code, n in sources
        ],
        by_owner=[
            CountRow(key=str(uid), label=owner_names.get(uid) or "Unknown", count=int(n)) for uid, n in owners
        ],
    )


# ---- promotion: a lead becomes a customer (module 2, spec 2026-11-25-customers-samples-design.md) ------------
PROMOTION_REASONS = ("sample_sent", "quote_won", "order_confirmed")


def promote_to_customer(uow: UnitOfWork, party_id: uuid.UUID, *, reason: str) -> bool:
    """Make a lead a customer because it was sent a sample, won a quotation or confirmed an order.

    Called by outbox subscriptions in the modules that own those events (parties never imports them). Idempotent:
    an active customer, a vendor-only party and an inactive or blocked party are left alone. Returns True when
    the party was promoted."""
    from sqlalchemy import select as _select

    assert reason in PROMOTION_REASONS, reason
    party = uow.session.scalars(
        _select(Party).where(Party.id == party_id, Party.company_id == uow.actor.company_id).with_for_update()
    ).first()
    if party is None or "customer" not in party.roles or party.archived_at is not None:
        return False
    if party.status != PartyStatus.PROSPECT.value and party.lead_stage == LeadStage.WON.value:
        return False
    if party.status not in (PartyStatus.PROSPECT.value, PartyStatus.ACTIVE.value):
        return False  # inactive or blocked: a person decides
    previous = party.lead_stage
    changed: list[str] = []
    if party.status != PartyStatus.ACTIVE.value:
        party.status = PartyStatus.ACTIVE.value
        changed.append("status")
    if previous != LeadStage.WON.value:
        party.lead_stage = LeadStage.WON.value
        party.lost_reason = None
        party.next_follow_up_on = None
        party.stage_changed_at = uow.now()
        changed.append("lead_stage")
    if not changed:
        return False
    party.updated_at = uow.now()
    uow.flush()
    if "lead_stage" in changed:
        uow.emit(
            ev.LEAD_STAGE_CHANGED,
            aggregate_id=party.id,
            aggregate_version=party.version,
            payload=ev.payload(
                ev.LeadStageChangedPayload(party_id=party.id, from_stage=previous, to_stage="won", reason=reason)
            ),
        )
    if "status" in changed:
        uow.emit(
            ev.PARTY_UPDATED,
            aggregate_id=party.id,
            aggregate_version=party.version,
            payload=ev.payload(
                ev.PartyUpdatedPayload(party_id=party.id, party_number=party.party_number, changed_fields=["status"],
                                       origin=reason)
            ),
        )
    uow.audit(
        "parties.lead.promoted",
        resource_type="parties.party",
        resource_id=party.id,
        resource_label=f"{party.party_number} · {party.display_name}",
        details={"reason": reason, "from_stage": previous},
    )
    return True
