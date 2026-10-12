"""FastAPI dependencies: the authenticated actor (resolver registered by identity), idempotency key."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Header, Request

from app.core.errors import Unauthenticated
from app.platform.authz.context import ActorContext

ActorResolver = Callable[[Request], ActorContext | None]
_resolver: ActorResolver | None = None


def register_actor_resolver(resolver: ActorResolver) -> None:
    global _resolver
    _resolver = resolver


def get_actor(request: Request) -> ActorContext:
    cached = getattr(request.state, "actor", None)
    if cached is not None:
        return cached
    actor = _resolver(request) if _resolver else None
    if actor is None:
        raise Unauthenticated()
    idem = request.headers.get("idempotency-key")
    actor = actor.with_(
        request_id=getattr(request.state, "request_id", None),
        correlation_id=getattr(request.state, "correlation_id", None),
        idempotency_key=idem,
    )
    request.state.actor = actor
    return actor


def get_optional_actor(request: Request) -> ActorContext | None:
    try:
        return get_actor(request)
    except Unauthenticated:
        return None


Actor = Annotated[ActorContext, Depends(get_actor)]
OptionalActor = Annotated[ActorContext | None, Depends(get_optional_actor)]
IdempotencyKeyHeader = Annotated[str | None, Header(alias="Idempotency-Key", max_length=128)]
