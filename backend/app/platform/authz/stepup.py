"""Step-up checks for flagged permissions (permissions.md §6), applied by the services that use those keys.

- ``MFA``: the actor's session passed a TOTP or recovery-code check (``auth_strength == "mfa"``). Members who
  hold privileged keys are already made to verify at sign-in; this check also covers demo-link sessions,
  channel-linked contexts and every other MFA-flagged key. 401 ``mfa_required``: confirm with the authenticator
  (``POST /api/v1/identity/session/reauth`` with a code), enrolling first if needed.
- ``RA``: an authentication (password or code) within the last 10 minutes. 401 ``reauth_required``.

System, CLI and seed actors are exempt. Agents and channel-linked contexts never satisfy either flag.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from app.core.errors import AppError

if TYPE_CHECKING:
    from app.platform.uow import UnitOfWork

RECENT_AUTH_WINDOW = timedelta(minutes=10)


class MfaRequired(AppError):
    status, code, title = 401, "mfa_required", "Confirm with your authenticator to continue"


class ReauthRequired(AppError):
    status, code, title = 401, "reauth_required", "Confirm it is you to continue"


def require_step_up(uow: UnitOfWork, permission_key: str) -> None:
    from app.registry import get_registry

    definition = get_registry().permissions.get(permission_key)
    if definition is None or not (definition.requires_mfa or definition.requires_recent_auth):
        return
    actor = uow.actor
    if actor.is_system or actor.actor_type == "cli":
        return
    if definition.requires_mfa and (actor.auth_strength != "mfa" or actor.actor_type != "user"):
        raise MfaRequired(
            "This change needs your authenticator. Confirm with a code and try again.", permission=permission_key
        )
    if definition.requires_recent_auth:
        at = actor.recent_auth_at
        if actor.actor_type != "user" or at is None or uow.now() - at > RECENT_AUTH_WINDOW:
            raise ReauthRequired(
                "This change needs a recent sign-in. Confirm your password and try again.", permission=permission_key
            )
