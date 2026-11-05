"""Finance configuration: tax profiles (business-entered, verified by a second person; never invented rates) and the
read of the issue-gate configuration state (company identity, e-invoice provider, accounting adapter)."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.core.errors import Conflict, Forbidden
from app.core.http.capabilities import Capability
from app.modules.finance import common as c
from app.modules.finance import events as ev
from app.modules.finance.enums import TaxProfileStatus
from app.modules.finance.models import TaxProfile
from app.modules.finance.schemas import TaxProfileCreate, TaxProfileRead, Versioned
from app.platform.authz.stepup import require_step_up
from app.platform.uow import UnitOfWork


def tax_profile_read(uow: UnitOfWork, p: TaxProfile) -> TaxProfileRead:
    people = c.users(uow, [p.author_user_id, p.verified_by])
    can_verify = (
        p.status == TaxProfileStatus.DRAFT.value
        and uow.actor.can(c.TAX_PROFILE_APPROVE)
        and uow.actor.user_id != p.author_user_id
    )
    return TaxProfileRead(
        id=p.id, code=p.code, name=p.name, scenario=p.scenario, rate_percent=p.rate_percent,
        requires_e_invoice=p.requires_e_invoice, source_reference=p.source_reference,
        status=TaxProfileStatus(p.status), author=people.get(p.author_user_id),
        verified_by=people.get(p.verified_by) if p.verified_by else None, verified_at=p.verified_at, version=p.version,
        capabilities={
            "verify": Capability(
                allowed=can_verify,
                reason_code=None
                if can_verify
                else ("author_cannot_verify" if uow.actor.user_id == p.author_user_id else "permission_denied"),
            )
        },
    )


def list_tax_profiles(uow: UnitOfWork) -> list[TaxProfileRead]:
    uow.actor.require(c.INVOICE_READ)
    rows = uow.session.scalars(
        select(TaxProfile).where(uow.repo(TaxProfile).clause("read")).order_by(TaxProfile.code)
    )
    return [tax_profile_read(uow, p) for p in rows]


def create_tax_profile(uow: UnitOfWork, data: TaxProfileCreate) -> TaxProfile:
    uow.actor.require(c.CONFIG_MANAGE)
    require_step_up(uow, c.CONFIG_MANAGE)
    if uow.actor.user_id is None:
        raise Forbidden(code="permission_denied")
    exists = uow.session.scalar(
        select(TaxProfile.id).where(TaxProfile.company_id == uow.actor.company_id, TaxProfile.code == data.code)
    )
    if exists:
        raise Conflict("A tax profile with this code exists", code="duplicate_code")
    p = TaxProfile(
        company_id=uow.actor.company_id, code=data.code, name=data.name, scenario=data.scenario,
        rate_percent=data.rate_percent, requires_e_invoice=data.requires_e_invoice,
        source_reference=data.source_reference, status=TaxProfileStatus.DRAFT.value,
        author_user_id=uow.actor.user_id,
    )
    uow.add(p)
    uow.flush()
    uow.audit("finance.tax_profile.created", resource_type="finance.tax_profile", resource_id=p.id, resource_label=p.code)
    return p


def verify_tax_profile(uow: UnitOfWork, profile_id: uuid.UUID, data: Versioned) -> TaxProfile:
    """A second person confirms the rate and source (MFA; never the author — also a CHECK constraint)."""
    uow.actor.require(c.TAX_PROFILE_APPROVE)
    require_step_up(uow, c.TAX_PROFILE_APPROVE)
    p = uow.repo(TaxProfile).get(profile_id, for_update=True)
    uow.expect_version(p, data.expected_version)
    if p.status != TaxProfileStatus.DRAFT.value:
        raise Conflict("This tax profile is already verified", code="already_verified")
    if p.author_user_id == uow.actor.user_id:
        raise Forbidden("The author of a tax profile cannot verify it", code="author_cannot_verify")
    p.status, p.verified_by, p.verified_at = TaxProfileStatus.VERIFIED.value, uow.actor.user_id, uow.now()
    uow.flush()
    uow.emit(ev.TAX_PROFILE_VERIFIED, aggregate_id=p.id, aggregate_version=p.version,
             payload={"tax_profile_id": str(p.id), "version": p.version})
    uow.audit("finance.tax_profile.verified", resource_type="finance.tax_profile", resource_id=p.id, resource_label=p.code)
    return p
