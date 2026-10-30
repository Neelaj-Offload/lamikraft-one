"""FX snapshots: dated, sourced rates proposed by one person and approved by another (approvals engine).

A rate is ``1 base_currency = rate quote_currency`` on ``rate_date``. Only an **approved** rate converts a price,
only for the exact pair (rates are never inverted, chained or invented), only when the company FX policy enables
conversion, and only while the rate is at most ``max_rate_age_days`` old on the business date. Converted unit prices
are rounded to the target currency's minor unit (ROUND_HALF_UP) and carry the rate as provenance.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select

from app.core.db.base import new_id
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.core.http.capabilities import Capability
from app.core.http.pagination import MAX_LIMIT, Page
from app.core.money import quantize_money
from app.modules.approvals import service as approvals
from app.modules.approvals.service import ApprovalHandler, TargetRef
from app.modules.pricing import events as ev
from app.modules.pricing.models import FxPolicyRow, FxRate
from app.modules.pricing.schemas import (
    FX_APPROVAL_KIND,
    FxConversion,
    FxDecision,
    FxPolicy,
    FxPolicyRead,
    FxPolicyUpdate,
    FxRateCreate,
    FxRateRead,
    FxRateStatus,
)
from app.platform.service import query
from app.platform.uow import UnitOfWork

FX_READ = "pricing.fx_rate.read"
FX_CREATE = "pricing.fx_rate.create"
FX_APPROVE = "pricing.fx_rate.approve"
POLICY_MANAGE = "pricing.fx_policy.manage"


def _policy_row(uow: UnitOfWork, *, for_update: bool = False) -> FxPolicyRow | None:
    stmt = select(FxPolicyRow).where(FxPolicyRow.company_id == uow.actor.company_id)
    return uow.session.scalars(stmt.with_for_update() if for_update else stmt).first()


def fx_policy(uow: UnitOfWork) -> FxPolicy:
    """The company FX policy (defaults when never configured); not restricted, read by price resolution."""
    row = _policy_row(uow)
    if row is None:
        return FxPolicy()
    return FxPolicy(conversion_enabled=row.conversion_enabled, conversion_source_currency=row.conversion_source_currency,  # type: ignore[arg-type]
                    max_rate_age_days=row.max_rate_age_days)


def _policy_read(uow: UnitOfWork) -> FxPolicyRead:
    row = _policy_row(uow)
    can = uow.actor.can(POLICY_MANAGE)
    return FxPolicyRead(**fx_policy(uow).model_dump(), version=row.version if row is not None else 0,
                        capabilities={"manage": Capability(allowed=can, reason_code=None if can else "permission_denied")})


@query(FX_READ)
def get_fx_policy(uow: UnitOfWork) -> FxPolicyRead:
    return _policy_read(uow)


def update_fx_policy(uow: UnitOfWork, data: FxPolicyUpdate) -> FxPolicyRead:
    """Change the policy (``pricing.fx_policy.manage``); ``expected_version`` 0 creates the row; stale is 409."""
    from app.platform.org.stepup import require_recent_auth

    uow.actor.require(POLICY_MANAGE)
    require_recent_auth(uow, POLICY_MANAGE)
    current = fx_policy(uow)
    row = _policy_row(uow, for_update=True)
    if row is None:
        if data.expected_version != 0:
            raise Conflict("The FX policy changed since you opened it", code="version_conflict", current_version=0)
        row = FxPolicyRow(id=new_id(), company_id=uow.actor.company_id, conversion_enabled=current.conversion_enabled,
                          conversion_source_currency=current.conversion_source_currency,
                          max_rate_age_days=current.max_rate_age_days)
        uow.add(row)
    else:
        uow.expect_version(row, data.expected_version)
    changed = []
    for name in ("conversion_enabled", "conversion_source_currency", "max_rate_age_days"):
        value = getattr(data, name)
        if value is not None and getattr(row, name) != value:
            setattr(row, name, value)
            changed.append(name)
    row.updated_at = uow.now()
    uow.flush()
    uow.audit("pricing.fx_policy.updated", resource_type="pricing.fx_policy", resource_id=row.id, details={"changed_fields": changed})
    return _policy_read(uow)


def _business_date(uow: UnitOfWork) -> date:
    from app.modules.pricing.service import business_date

    return business_date(uow)


def _content(row: FxRate) -> dict[str, Any]:
    return {
        "fx_rate_id": str(row.id),
        "base_currency": row.base_currency,
        "quote_currency": row.quote_currency,
        "rate": format(Decimal(row.rate).normalize(), "f"),
        "rate_date": row.rate_date.isoformat(),
        "source_kind": row.source_kind,
        "source_reference": row.source_reference,
    }


def _payload(row: FxRate, origin: str | None = None) -> dict[str, object]:
    return ev.payload(
        ev.FxRatePayload(
            fx_rate_id=row.id, base_currency=row.base_currency, quote_currency=row.quote_currency,
            rate_date=row.rate_date.isoformat(), origin=origin,
        )
    )


def _approved_on(uow: UnitOfWork, base: str, quote: str, rate_date: date, *, exclude: uuid.UUID | None = None) -> FxRate | None:
    stmt = select(FxRate).where(
        FxRate.company_id == uow.actor.company_id, FxRate.base_currency == base, FxRate.quote_currency == quote,
        FxRate.rate_date == rate_date, FxRate.status == FxRateStatus.APPROVED.value,
    )
    if exclude is not None:
        stmt = stmt.where(FxRate.id != exclude)
    return uow.session.scalars(stmt).first()


def propose_fx_rate(uow: UnitOfWork, data: FxRateCreate, *, origin: str | None = None, is_demo: bool = False) -> FxRate:
    """Record a proposed rate and submit it for approval (the proposer can never approve it)."""
    uow.actor.require(FX_CREATE)
    errors: list[dict[str, Any]] = []
    if data.base_currency == data.quote_currency:
        errors.append({"loc": ["body", "quote_currency"], "msg": "the two currencies must differ", "code": "same_currency"})
    if data.rate_date > _business_date(uow):
        errors.append({"loc": ["body", "rate_date"], "msg": "a rate cannot be dated in the future", "code": "future_rate_date"})
    if errors:
        raise ValidationFailed("Some FX values are not valid", errors=errors)
    if _approved_on(uow, data.base_currency, data.quote_currency, data.rate_date) is not None:
        raise Conflict(
            f"An approved {data.base_currency}->{data.quote_currency} rate for {data.rate_date.isoformat()} already exists",
            code="fx_rate_exists",
        )
    row = FxRate(
        id=new_id(),
        company_id=uow.actor.company_id,
        base_currency=data.base_currency,
        quote_currency=data.quote_currency,
        rate=data.rate,
        rate_date=data.rate_date,
        source_kind=data.source_kind.value,
        source_reference=data.source_reference,
        status=FxRateStatus.PROPOSED.value,
        proposed_by=uow.actor.user_id,
        proposed_at=uow.now(),
        notes=data.notes,
        is_demo=is_demo,
    )
    # the proposal binds to version 1 of the row inserted below (one INSERT, so the version stays 1)
    proposal = approvals.submit(
        uow,
        kind=FX_APPROVAL_KIND,
        targets=[TargetRef("pricing.fx_rate", row.id, 1)],
        content=_content(row),
        title=f"FX {row.base_currency}→{row.quote_currency} {format(Decimal(row.rate).normalize(), 'f')} on {row.rate_date.isoformat()}",
        summary=f"Source: {row.source_reference}",
        facts={"base_currency": row.base_currency, "quote_currency": row.quote_currency, "rate_date": row.rate_date.isoformat()},
        expires_in=timedelta(days=7),
    )
    row.proposal_id = proposal.id
    uow.add(row)
    uow.flush()
    uow.emit(ev.FX_RATE_PROPOSED, aggregate_id=row.id, aggregate_version=row.version, payload=_payload(row, origin))
    uow.audit("pricing.fx_rate.proposed", resource_type="pricing.fx_rate", resource_id=row.id,
              resource_label=f"{row.base_currency}/{row.quote_currency} {row.rate_date.isoformat()}")
    return row


def _row(uow: UnitOfWork, fx_rate_id: uuid.UUID, *, for_update: bool = False) -> FxRate:
    stmt = select(FxRate).where(FxRate.id == fx_rate_id, FxRate.company_id == uow.actor.company_id)
    row = uow.session.scalars(stmt.with_for_update() if for_update else stmt).first()
    if row is None:
        raise NotFound(code="not_found", resource_type="pricing.fx_rate")
    return row


def withdraw_fx_rate(uow: UnitOfWork, fx_rate_id: uuid.UUID) -> FxRate:
    """The proposer withdraws a still-pending rate."""
    uow.actor.require(FX_READ)
    row = _row(uow, fx_rate_id, for_update=True)
    if row.status != FxRateStatus.PROPOSED.value:
        raise Conflict(f"The rate is {row.status}", code="fx_rate_not_pending")
    if row.proposed_by != uow.actor.user_id:
        raise Forbidden("Only the proposer can withdraw a rate", code="only_requester_can_withdraw")
    if row.proposal_id is not None:
        proposal = approvals.get(uow, row.proposal_id)
        if proposal.status == "pending":
            approvals.withdraw(uow, row.proposal_id)
    row.status = FxRateStatus.WITHDRAWN.value
    row.updated_at = uow.now()
    uow.flush()
    uow.audit("pricing.fx_rate.withdrawn", resource_type="pricing.fx_rate", resource_id=row.id)
    return row


def decide_fx_rate(uow: UnitOfWork, fx_rate_id: uuid.UUID, data: FxDecision) -> FxRate:
    """Approve or reject through the approvals engine (separation of duties, version and content checks)."""
    uow.actor.require(FX_APPROVE)
    row = _row(uow, fx_rate_id)
    if row.proposed_by == uow.actor.user_id:
        raise Forbidden("You cannot decide your own request", code="separation_of_duties")
    if row.status != FxRateStatus.PROPOSED.value or row.proposal_id is None:
        raise Conflict(f"The rate is {row.status}", code="fx_rate_not_pending")
    proposal = approvals.get(uow, row.proposal_id)
    decided = approvals.decide(
        uow, proposal.id, decision=data.decision, content_hash_seen=proposal.content_hash,
        expected_version=proposal.version, reason=data.reason,
    )
    approvals.raise_if_not_decided(decided)
    return _row(uow, fx_rate_id)


# ---- approvals handler -------------------------------------------------------------------------------
def _target_row(uow: UnitOfWork, target: TargetRef) -> FxRate | None:
    if target.target_type != "pricing.fx_rate":
        return None
    return uow.session.scalars(
        select(FxRate).where(FxRate.id == target.target_id, FxRate.company_id == uow.actor.company_id).with_for_update()
    ).first()


def _current_version(uow: UnitOfWork, target: TargetRef) -> int | None:
    row = _target_row(uow, target)
    if row is None or row.status != FxRateStatus.PROPOSED.value:
        return None
    return row.version


def _on_approved(uow: UnitOfWork, proposal: Any) -> None:
    for target in approvals.targets_of(uow, proposal):
        row = _target_row(uow, target)
        if row is None:
            continue
        if _approved_on(uow, row.base_currency, row.quote_currency, row.rate_date, exclude=row.id) is not None:
            raise Conflict("Another rate for this pair and date was approved meanwhile", code="fx_rate_exists")
        row.status = FxRateStatus.APPROVED.value
        row.decided_by = uow.actor.user_id
        row.decided_at = uow.now()
        row.decision_reason = proposal.decision_reason
        row.updated_at = uow.now()
        uow.flush()
        uow.emit(ev.FX_RATE_APPROVED, aggregate_id=row.id, aggregate_version=row.version, payload=_payload(row))
        uow.audit("pricing.fx_rate.approved", resource_type="pricing.fx_rate", resource_id=row.id)


def _on_rejected(uow: UnitOfWork, proposal: Any) -> None:
    for target in approvals.targets_of(uow, proposal):
        row = _target_row(uow, target)
        if row is None:
            continue
        row.status = FxRateStatus.REJECTED.value
        row.decided_by = uow.actor.user_id
        row.decided_at = uow.now()
        row.decision_reason = proposal.decision_reason
        row.updated_at = uow.now()
        uow.flush()
        uow.emit(ev.FX_RATE_REJECTED, aggregate_id=row.id, aggregate_version=row.version, payload=_payload(row))
        uow.audit("pricing.fx_rate.rejected", resource_type="pricing.fx_rate", resource_id=row.id,
                  reason=proposal.decision_reason)


FX_RATE_HANDLER = ApprovalHandler(
    kind=FX_APPROVAL_KIND,
    approve_permission=FX_APPROVE,
    current_version=_current_version,
    on_approved=_on_approved,
    on_rejected=_on_rejected,
)


# ---- reads -----------------------------------------------------------------------------------------
def _names(uow: UnitOfWork, ids: set[uuid.UUID | None]) -> dict[uuid.UUID, str | None]:
    from app.platform.identity.models import AppUser

    wanted = {i for i in ids if i is not None}
    if not wanted:
        return {}
    return dict(uow.session.execute(select(AppUser.id, AppUser.display_name).where(AppUser.id.in_(wanted))).all())


def _read(uow: UnitOfWork, row: FxRate, names: dict[uuid.UUID, str | None]) -> FxRateRead:
    pending = row.status == FxRateStatus.PROPOSED.value
    own = row.proposed_by == uow.actor.user_id
    can_decide = pending and not own and uow.actor.can(FX_APPROVE)
    return FxRateRead(
        id=row.id,
        base_currency=row.base_currency,
        quote_currency=row.quote_currency,
        rate=format(Decimal(row.rate).normalize(), "f"),
        rate_date=row.rate_date,
        source_kind=row.source_kind,  # type: ignore[arg-type]
        source_reference=row.source_reference,
        status=FxRateStatus(row.status),
        proposal_id=row.proposal_id,
        proposed_by_name=names.get(row.proposed_by) if row.proposed_by else None,
        proposed_at=row.proposed_at,
        decided_by_name=names.get(row.decided_by) if row.decided_by else None,
        decided_at=row.decided_at,
        decision_reason=row.decision_reason,
        notes=row.notes,
        is_demo=row.is_demo,
        version=row.version,
        capabilities={
            "decide": Capability(
                allowed=can_decide,
                reason_code=None if can_decide else ("fx_rate_not_pending" if not pending else ("separation_of_duties" if own else "permission_denied")),
            ),
            "withdraw": Capability(
                allowed=pending and own, reason_code=None if pending and own else ("fx_rate_not_pending" if not pending else "not_requester")
            ),
        },
    )


@query(FX_READ)
def list_fx_rates(
    uow: UnitOfWork,
    *,
    base_currency: str | None = None,
    quote_currency: str | None = None,
    status: list[FxRateStatus] | None = None,
    limit: int = 50,
    offset: int = 0,
) -> Page[FxRateRead]:
    conds = [FxRate.company_id == uow.actor.company_id]
    if base_currency:
        conds.append(FxRate.base_currency == base_currency.upper())
    if quote_currency:
        conds.append(FxRate.quote_currency == quote_currency.upper())
    if status:
        conds.append(FxRate.status.in_([s.value for s in status]))
    total = uow.session.scalar(select(func.count(FxRate.id)).where(*conds)) or 0
    limit = max(1, min(limit, MAX_LIMIT))
    rows = list(
        uow.session.scalars(
            select(FxRate).where(*conds).order_by(FxRate.rate_date.desc(), FxRate.proposed_at.desc(), FxRate.id)
            .limit(limit).offset(max(0, offset))
        )
    )
    names = _names(uow, {r.proposed_by for r in rows} | {r.decided_by for r in rows})
    return Page[FxRateRead](items=[_read(uow, r, names) for r in rows], total=int(total), limit=limit, offset=max(0, offset))


@query(FX_READ)
def get_fx_rate(uow: UnitOfWork, fx_rate_id: uuid.UUID) -> FxRateRead:
    row = _row(uow, fx_rate_id)
    return _read(uow, row, _names(uow, {row.proposed_by, row.decided_by}))


# ---- conversion ------------------------------------------------------------------------------------
def find_approved_rate(uow: UnitOfWork, base: str, quote: str, on_date: date | None = None) -> FxRate | None:
    """The latest approved rate for exactly ``base -> quote`` dated on or before ``on_date`` and within the policy's
    maximum age; None when conversion is disabled or no such rate exists (never inverted or chained)."""
    policy = fx_policy(uow)
    if not policy.conversion_enabled or base == quote:
        return None
    day = on_date or _business_date(uow)
    return uow.session.scalars(
        select(FxRate)
        .where(
            FxRate.company_id == uow.actor.company_id,
            FxRate.base_currency == base.upper(),
            FxRate.quote_currency == quote.upper(),
            FxRate.status == FxRateStatus.APPROVED.value,
            FxRate.rate_date <= day,
            FxRate.rate_date >= day - timedelta(days=policy.max_rate_age_days),
        )
        .order_by(FxRate.rate_date.desc(), FxRate.decided_at.desc())
    ).first()


def convert_amount(uow: UnitOfWork, amount: Decimal, base: str, quote: str, on_date: date | None = None) -> tuple[Decimal, FxConversion] | None:
    """``amount`` in ``base`` converted to ``quote`` at the approved rate (minor units, ROUND_HALF_UP), or None."""
    rate = find_approved_rate(uow, base, quote, on_date)
    if rate is None:
        return None
    converted = quantize_money(Decimal(amount) * Decimal(rate.rate), quote)
    return converted, FxConversion(
        fx_rate_id=rate.id, base_currency=rate.base_currency, quote_currency=rate.quote_currency, rate=rate.rate,
        rate_date=rate.rate_date, source_reference=rate.source_reference,
    )


__all__ = [
    "FX_RATE_HANDLER",
    "convert_amount",
    "decide_fx_rate",
    "find_approved_rate",
    "fx_policy",
    "get_fx_policy",
    "get_fx_rate",
    "list_fx_rates",
    "update_fx_policy",
    "propose_fx_rate",
    "withdraw_fx_rate",
]
