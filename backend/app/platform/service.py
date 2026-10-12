"""Service decorators: the one way UI endpoints, agent tools and jobs call business logic.

``@command("sales.quote.create")`` / ``@query("sales.quote.read")`` wrap a function whose first
parameter is a :class:`UnitOfWork`. Callers pass an :class:`ActorContext` (a new unit of work is
opened and committed) or an existing ``UnitOfWork`` (composition inside one transaction). The
decorator checks the coarse permission, runs idempotently when asked, and redacts restricted
fields from the result for the calling actor. Record-level rules stay in ScopedRepository.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any, ParamSpec, TypeVar

from pydantic import BaseModel

from app.platform.authz.context import ActorContext
from app.platform.authz.permissions import Scope
from app.platform.authz.redaction import redact
from app.platform.uow import UnitOfWork

P = ParamSpec("P")
R = TypeVar("R")

_SERVICES: dict[str, dict[str, Any]] = {}


def _body_of(args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
    def dump(v: Any) -> Any:
        return v.model_dump(mode="json") if isinstance(v, BaseModel) else v

    return {"args": [dump(a) for a in args], "kwargs": {k: dump(v) for k, v in sorted(kwargs.items())}}


def _wrap(kind: str, permission: str | None, at_least: Scope, idempotent: bool) -> Callable[[Callable[..., R]], Callable[..., R]]:
    def decorator(fn: Callable[..., R]) -> Callable[..., R]:
        name = f"{fn.__module__}.{fn.__qualname__}"
        _SERVICES[name] = {"kind": kind, "permission": permission, "idempotent": idempotent}

        def run(uow: UnitOfWork, args: tuple[Any, ...], kwargs: dict[str, Any]) -> R:
            if permission is not None:
                uow.actor.require(permission, at_least)
            if idempotent and uow.actor.idempotency_key:
                from app.platform.idempotency.service import run_idempotent

                def call() -> dict[str, Any]:
                    out = fn(uow, *args, **kwargs)
                    return {"__value__": out.model_dump(mode="json") if isinstance(out, BaseModel) else out}

                body, _replayed = run_idempotent(
                    uow, key=uow.actor.idempotency_key, operation=name, body=_body_of(args, kwargs), fn=call
                )
                value = body.get("__value__")
                hints = fn.__annotations__.get("return")
                ret_type = hints if isinstance(hints, type) else None
                if ret_type is not None and issubclass(ret_type, BaseModel) and isinstance(value, dict):
                    return redact(ret_type.model_validate(value), uow.actor)  # type: ignore[return-value]
                return value  # type: ignore[return-value]
            result = fn(uow, *args, **kwargs)
            return redact(result, uow.actor)  # type: ignore[no-any-return]

        @functools.wraps(fn)
        def wrapper(ctx: ActorContext | UnitOfWork, *args: Any, **kwargs: Any) -> R:
            if isinstance(ctx, UnitOfWork):
                return run(ctx, args, kwargs)
            if not isinstance(ctx, ActorContext):
                raise TypeError(f"{name} must be called with an ActorContext or UnitOfWork")
            with UnitOfWork(ctx) as uow:
                return run(uow, args, kwargs)

        wrapper.__lk_service__ = {"kind": kind, "permission": permission}  # type: ignore[attr-defined]
        return wrapper

    return decorator


def command(permission: str | None = None, *, at_least: Scope = Scope.OWN, idempotent: bool = False) -> Callable[[Callable[..., R]], Callable[..., R]]:
    return _wrap("command", permission, at_least, idempotent)


def query(permission: str | None = None, *, at_least: Scope = Scope.OWN) -> Callable[[Callable[..., R]], Callable[..., R]]:
    return _wrap("query", permission, at_least, False)


def registered_services() -> dict[str, dict[str, Any]]:
    return dict(_SERVICES)
