"""Helpers for the migration tests: the synthetic export's path and the migration operator."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from app.platform.authz.context import ActorContext
from app.seed.world import keys
from tests.integration.catalogue.world import World

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "legacy_export"


def operator(world: World) -> ActorContext:
    """Priya (admin) with an MFA-verified, recent sign-in: migration reads are MFA-flagged (permissions.md §7.8)."""
    from app.core.clock import get_clock

    return world.actor(keys.USERS.PRIYA).with_(auth_strength="mfa",
                                               recent_auth_at=get_clock().now() - timedelta(minutes=1))
