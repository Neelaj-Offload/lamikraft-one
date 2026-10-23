"""Recent-authentication (step-up) check for permissions flagged ``requires_recent_auth`` (RA).

permissions.md §6: an RA permission needs an authentication within the last 10 minutes. The session layer
(identity) records ``ActorContext.recent_auth_at``; system, CLI and seed actors are exempt. MFA-flagged keys
are enforced from Slice 2 (permissions.md §9: "MFA required from Slice 2").
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from app.core.errors import AppError

if TYPE_CHECKING:
    from app.platform.uow import UnitOfWork

RECENT_AUTH_WINDOW = timedelta(minutes=10)


class ReauthRequired(AppError):
    status, code, title = 401, "reauth_required", "Confirm it is you to continue"


def require_recent_auth(uow: UnitOfWork, permission_key: str) -> None:
    from app.registry import get_registry

    definition = get_registry().permissions.get(permission_key)
    if definition is None or not definition.requires_recent_auth:
        return
    actor = uow.actor
    if actor.is_system or actor.actor_type == "cli":
        return
    at = actor.recent_auth_at
    if at is None or uow.now() - at > RECENT_AUTH_WINDOW:
        raise ReauthRequired(
            "This change needs a recent sign-in. Confirm your password and try again.", permission=permission_key
        )
