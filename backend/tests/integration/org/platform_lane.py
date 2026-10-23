"""Shared helpers for the platform lane's integration tests (org, files, collab, search, audit, system).

- ``member``: a real user + active membership in a test company, with the role-template grants from the frozen
  permission catalogue (``employee``, ``admin``, ``finance`` ...), never hand-picked permission sets unless a
  test is about a specific key.
- ``ApiClient``: a FastAPI ``TestClient`` on the real application whose requests run as a chosen
  ``ActorContext`` (the identity lane's session resolver is replaced for the test) and send the configured
  ``Origin`` so the CSRF/Origin middleware accepts unsafe methods.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from app.core.clock import get_clock
from app.core.config import get_settings
from app.platform.authz.catalogue import template_grants
from app.platform.authz.context import ActorContext
from app.platform.authz.permissions import Scope
from app.platform.uow import UnitOfWork
from tests.support import create_user


def grants(*templates: str, extra: Mapping[str, Scope] | None = None) -> dict[str, Scope]:
    """Merged template grants from the catalogue (maximum scope per key)."""
    table = template_grants()
    merged: dict[str, Scope] = {}
    for template in templates:
        for key, scope in table[template].items():
            merged[key] = max(scope, merged.get(key, scope))
    for key, scope in (extra or {}).items():
        merged[key] = scope
    return merged


def without(perms: Mapping[str, Scope], *keys: str) -> dict[str, Scope]:
    return {k: v for k, v in perms.items() if k not in keys}


@dataclass
class Member:
    company_id: uuid.UUID
    user_id: uuid.UUID
    name: str
    permissions: dict[str, Scope] = field(default_factory=dict)

    def actor(self, *, recent_auth: bool = True, **changes: Any) -> ActorContext:
        ctx = ActorContext(
            actor_type="user",
            company_id=self.company_id,
            user_id=self.user_id,
            display_name=self.name,
            permissions=dict(self.permissions),
            channel="test",
            recent_auth_at=get_clock(self.company_id).now() if recent_auth else None,
        )
        return ctx.with_(**changes) if changes else ctx


def member(
    company_id: uuid.UUID,
    name: str,
    *templates: str,
    extra: Mapping[str, Scope] | None = None,
    job_title: str | None = None,
    department: str | None = None,
) -> Member:
    """A user with an active membership (``tests.support.create_user``) and catalogue template grants."""
    user_id = create_user(company_id, name)
    if job_title or department:
        from app.platform.identity.models import Membership

        with UnitOfWork(ActorContext.system(company_id, reason="test-setup")) as uow:
            uow.session.execute(
                update(Membership)
                .where(Membership.company_id == company_id, Membership.user_id == user_id)
                .values(job_title=job_title, department=department)
            )
    return Member(company_id, user_id, name, grants(*templates, extra=extra) if templates or extra else {})


class ApiClient:
    """``TestClient`` whose requests are authenticated as ``self.actor`` (None = signed out)."""

    def __init__(self, client: TestClient) -> None:
        self.client = client
        self.actor: ActorContext | None = None
        self.origin = get_settings().public_origin

    def as_(self, actor: ActorContext | None) -> ApiClient:
        self.actor = actor
        return self

    def request(self, method: str, url: str, **kwargs: Any) -> Any:
        headers = {"Origin": self.origin, **(kwargs.pop("headers", None) or {})}
        return self.client.request(method, url, headers=headers, **kwargs)

    def get(self, url: str, **kwargs: Any) -> Any:
        return self.request("GET", url, **kwargs)

    def put(self, url: str, **kwargs: Any) -> Any:
        return self.request("PUT", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> Any:
        return self.request("POST", url, **kwargs)

    def delete(self, url: str, **kwargs: Any) -> Any:
        return self.request("DELETE", url, **kwargs)


_APP: Any = None


def _app() -> Any:
    global _APP
    if _APP is None:
        from app.main import create_app

        _APP = create_app()
    return _APP


@contextmanager
def api_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[ApiClient]:
    from app.core.http import deps, middleware

    api = ApiClient(TestClient(_app()))
    # the identity lane owns sessions; these tests authenticate by injecting the server-built context
    monkeypatch.setattr(deps, "_resolver", lambda _request: api.actor)
    # CSRF tokens belong to sessions (identity); the Origin check stays active
    monkeypatch.setattr(middleware, "_csrf_verifier", None)
    yield api


def events(company_id: uuid.UUID, event_type: str) -> list[Any]:
    """Outbox rows of one type for a company, oldest first."""
    from sqlalchemy import select

    from app.platform.events.models import DomainEvent

    with UnitOfWork(ActorContext.system(company_id, reason="test-read")) as uow:
        return list(
            uow.session.scalars(
                select(DomainEvent)
                .where(DomainEvent.company_id == company_id, DomainEvent.event_type == event_type)
                .order_by(DomainEvent.seq)
            )
        )


def audit_rows(company_id: uuid.UUID, action: str) -> list[Any]:
    """Audit entries of one action for a company, oldest first."""
    from sqlalchemy import select

    from app.platform.audit.models import AuditLog

    with UnitOfWork(ActorContext.system(company_id, reason="test-read")) as uow:
        return list(
            uow.session.scalars(
                select(AuditLog)
                .where(AuditLog.company_id == company_id, AuditLog.action == action)
                .order_by(AuditLog.occurred_at, AuditLog.id)
            )
        )


def problem(response: Any) -> dict[str, Any]:
    assert response.headers["content-type"].startswith("application/problem+json"), response.text
    body: dict[str, Any] = response.json()
    return body
