"""Test helpers: tenants, actors and inline draining. Business records are created through services."""

from __future__ import annotations

import uuid
from collections.abc import Mapping

from app.platform.authz.context import ActorContext
from app.platform.authz.permissions import Scope
from app.platform.org.models import Branch, Company
from app.platform.uow import UnitOfWork


def create_company(key: str | None = None, *, is_demo: bool = True) -> tuple[uuid.UUID, uuid.UUID]:
    """Create a company and its head-office branch. Returns (company_id, branch_id)."""
    key = key or f"t-{uuid.uuid4().hex[:10]}"
    company_id = uuid.uuid7()
    with UnitOfWork(ActorContext.system(None, reason="test-setup")) as uow:
        uow.add(Company(id=company_id, company_key=key, legal_name=f"{key} Pvt. Ltd.", display_name=key, is_demo=is_demo))
    branch_id = uuid.uuid7()
    with UnitOfWork(ActorContext.system(company_id, reason="test-setup")) as uow:
        uow.add(Branch(id=branch_id, company_id=company_id, branch_code="HO", name="Head office", is_head_office=True))
    return company_id, branch_id


def create_user(company_id: uuid.UUID, display_name: str = "Test User", *, email: str | None = None) -> uuid.UUID:
    """Create an active user with an active membership (no credentials; tests build contexts directly)."""
    from app.platform.identity.models import AppUser, Membership

    user_id = uuid.uuid7()
    email = email or f"{uuid.uuid4().hex[:12]}@example.test"
    with UnitOfWork(ActorContext.system(None, reason="test-setup")) as uow:
        uow.add(AppUser(id=user_id, email=email, email_normalized=email.lower(), display_name=display_name, status="active"))
    with UnitOfWork(ActorContext.system(company_id, reason="test-setup")) as uow:
        uow.add(Membership(id=uuid.uuid7(), company_id=company_id, user_id=user_id, status="active"))
    return user_id


def actor(
    company_id: uuid.UUID,
    *,
    user_id: uuid.UUID | None = None,
    permissions: Mapping[str, Scope | str] | None = None,
    branch_ids: frozenset[uuid.UUID] = frozenset(),
    team: frozenset[uuid.UUID] = frozenset(),
) -> ActorContext:
    perms = {k: Scope.parse(v) for k, v in (permissions or {}).items()}
    return ActorContext(
        actor_type="user",
        company_id=company_id,
        user_id=user_id or uuid.uuid7(),
        permissions=perms,
        branch_ids=branch_ids,
        team_peer_user_ids=team,
        channel="test",
    )


def drain() -> int:
    from app.platform.jobs.worker import drain as _drain

    return _drain()
