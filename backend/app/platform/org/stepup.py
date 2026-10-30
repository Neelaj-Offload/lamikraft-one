"""Step-up for org settings: delegates to :mod:`app.platform.authz.stepup` (MFA and recent-auth flags)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.platform.authz.stepup import RECENT_AUTH_WINDOW, MfaRequired, ReauthRequired, require_step_up

if TYPE_CHECKING:
    from app.platform.uow import UnitOfWork

__all__ = ["RECENT_AUTH_WINDOW", "MfaRequired", "ReauthRequired", "require_recent_auth"]


def require_recent_auth(uow: UnitOfWork, permission_key: str) -> None:
    """MFA (``MFA`` flag) and recent authentication (``RA`` flag) for writing a setting."""
    require_step_up(uow, permission_key)
