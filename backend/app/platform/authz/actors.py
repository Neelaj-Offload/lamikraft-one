"""Building a member's ActorContext outside an HTTP request (jobs, briefings, channels, agents).

``identity`` registers the builder in its manifest ``on_load``; consumers (tasks, briefings, agents,
channels) call ``actor_for_member`` and never assemble permissions themselves. Tests may register a
fake builder. The builder returns None for a missing, inactive or suspended membership.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

from app.core.errors import NotFound
from app.platform.authz.context import ActorContext, Channel

MemberActorBuilder = Callable[[uuid.UUID, uuid.UUID, Channel], ActorContext | None]
_builder: MemberActorBuilder | None = None


def register_member_actor_builder(builder: MemberActorBuilder | None) -> None:
    global _builder
    _builder = builder


def actor_for_member(company_id: uuid.UUID, user_id: uuid.UUID, *, channel: Channel = "job") -> ActorContext:
    """The effective, server-built context for an active member (roles, overrides, scopes, delegations)."""
    if _builder is None:
        raise RuntimeError("no member actor builder registered (identity module not installed)")
    actor = _builder(company_id, user_id, channel)
    if actor is None:
        raise NotFound(code="membership_inactive", resource_type="identity.membership")
    return actor
