"""Identity's SourceReaders (``app.platform.sources``), registered in the identity manifest ``on_load``.

- ``identity.membership`` (source id = membership id): directory facts of a member of the actor's company. Any
  member with ``org.directory.read`` sees the name and status; the member's role templates (what onboarding is
  derived from) are added only for the system, the member themself or a holder of ``identity.user.read``.
- ``identity.user_preference`` (source id = user id): whether the user has saved their briefing and locale
  preferences (onboarding step "Choose your language and briefing detail"). Personal: only the system and the
  user themself get facts.

Readers run in the caller's unit of work (RLS keeps them inside the actor's company) and answer None for
records the actor may not see, never a partial leak.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING
from urllib.parse import urlencode

from sqlalchemy import select

from app.platform.identity.models import AppUser, Membership, MembershipRole, Role, UserPreference
from app.platform.sources import SourceFacts

if TYPE_CHECKING:
    from app.platform.uow import UnitOfWork

DIRECTORY_READ = "org.directory.read"
USER_READ = "identity.user.read"
_CLOSED_STATUSES = frozenset({"deactivated", "historical", "disabled"})


def _role_templates(uow: UnitOfWork, membership_id: uuid.UUID) -> list[str]:
    rows = uow.session.execute(
        select(Role.template_key, Role.role_key)
        .join(MembershipRole, MembershipRole.role_id == Role.id)
        .where(MembershipRole.membership_id == membership_id)
        .order_by(Role.role_key)
    ).all()
    templates = [template or key for template, key in rows]
    return [t for t in dict.fromkeys(templates) if t != "employee"]


def read_membership_facts(uow: UnitOfWork, membership_id: uuid.UUID) -> SourceFacts | None:
    actor = uow.actor
    row = uow.session.execute(
        select(Membership, AppUser.display_name)
        .join(AppUser, AppUser.id == Membership.user_id)
        .where(Membership.id == membership_id, Membership.company_id == actor.company_id)
    ).first()
    if row is None:
        return None
    membership, display_name = row
    own = actor.user_id is not None and actor.user_id == membership.user_id
    if not (actor.is_system or own or actor.can(DIRECTORY_READ)):
        return None
    facts: dict[str, object] = {"user_id": str(membership.user_id), "display_name": display_name}
    if actor.is_system or own or actor.can(USER_READ):
        facts["role_templates"] = _role_templates(uow, membership.id)
        facts["manager_membership_id"] = str(membership.manager_membership_id) if membership.manager_membership_id else None
    return SourceFacts(
        source_type="identity.membership",
        source_id=membership.id,
        version=membership.version,
        label=display_name,
        status=membership.status,
        owner_user_id=membership.user_id,
        branch_id=membership.default_branch_id,
        required_permission=DIRECTORY_READ,
        # no person page in Slice 1: people open in global search (frontend_verification §6)
        canonical_path=f"/search?{urlencode({'q': display_name, 'types': 'org.person'})}",
        is_closed=membership.status in _CLOSED_STATUSES,
        updated_at=membership.updated_at,
        facts=facts,
    )


def read_user_preference_facts(uow: UnitOfWork, user_id: uuid.UUID) -> SourceFacts | None:
    actor = uow.actor
    if not (actor.is_system or actor.user_id == user_id):
        return None
    member = uow.session.scalar(
        select(Membership.id).where(Membership.user_id == user_id, Membership.company_id == actor.company_id)
    )
    if member is None:  # not a member of this company: nothing to say
        return None
    row = uow.session.get(UserPreference, user_id)
    return SourceFacts(
        source_type="identity.user_preference",
        source_id=user_id,
        version=row.version if row is not None else 0,
        label="Personal preferences",
        status="saved" if row is not None else "default",
        owner_user_id=user_id,
        branch_id=None,
        required_permission=DIRECTORY_READ,
        canonical_path="/settings",
        updated_at=row.updated_at if row is not None else None,
        facts={
            "briefing_saved": bool(row is not None and row.briefing),
            "locale_saved": bool(row is not None and row.locale),
        },
    )


def register_readers() -> None:
    from app.platform.sources import register_reader

    register_reader("identity.membership", read_membership_facts)
    register_reader("identity.user_preference", read_user_preference_facts)
    from app.platform.identity.availability import read_absence_facts

    register_reader("identity.absence", read_absence_facts)
