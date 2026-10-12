"""Unit of work: one transaction per command, run as a server-built ActorContext.

On entry it opens a session, begins a transaction and sets the RLS GUCs (``app.company_id``,
``app.user_id``) transaction-locally; on success it commits *before* the HTTP response is sent, so
a 2xx always means committed. It exposes the sanctioned primitives: scoped repositories, ordered
row locks, advisory locks, deferred constraints, event emission, job enqueueing, document number
allocation and audit recording. Business timestamps come from the injected Clock.
"""

from __future__ import annotations

import uuid
import zlib
from collections.abc import Callable, Iterable, Sequence
from datetime import date, datetime
from types import TracebackType
from typing import Any, TypeVar

from pydantic import BaseModel
from sqlalchemy import event as sa_event
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.core.clock import Clock, get_clock
from app.core.db.engine import session_factory
from app.core.errors import VersionConflict
from app.platform.authz.context import ActorContext
from app.platform.authz.policy import policy_for_model
from app.platform.authz.repository import ScopedRepository

M = TypeVar("M")


class UnitOfWork:
    def __init__(self, actor: ActorContext, *, clock: Clock | None = None) -> None:
        self.actor = actor
        self.clock: Clock = clock or get_clock(actor.company_id)
        self.session: Session
        self._after_commit: list[Callable[[], None]] = []
        self._committed = False

    # ---- lifecycle -----------------------------------------------------------------------------
    def __enter__(self) -> UnitOfWork:
        self.session = session_factory()()
        self.session.info["uow"] = self
        self._tx = self.session.begin()
        self._set_tenant_gucs(self.actor.company_id, self.actor.user_id)
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        try:
            if exc_type is None:
                try:
                    self.session.flush()
                    self._set_tenant_gucs(None, None)
                    self._tx.commit()
                    self._committed = True
                except StaleDataError as stale:
                    self._tx.rollback()
                    raise VersionConflict() from stale
            else:
                self._tx.rollback()
        finally:
            self.session.info.pop("uow", None)
            self.session.close()
        if self._committed:
            for callback in self._after_commit:
                callback()

    def _set_tenant_gucs(self, company_id: uuid.UUID | None, user_id: uuid.UUID | None) -> None:
        self.session.execute(
            text("SELECT set_config('app.company_id', :c, true), set_config('app.user_id', :u, true)"),
            {"c": str(company_id) if company_id else "", "u": str(user_id) if user_id else ""},
        )

    def after_commit(self, callback: Callable[[], None]) -> None:
        self._after_commit.append(callback)

    # ---- time ----------------------------------------------------------------------------------
    def now(self) -> datetime:
        return self.clock.now()

    # ---- persistence ---------------------------------------------------------------------------
    def add(self, obj: M) -> M:
        self.session.add(obj)
        return obj

    def add_all(self, objs: Iterable[Any]) -> None:
        self.session.add_all(list(objs))

    def flush(self) -> None:
        try:
            self.session.flush()
        except StaleDataError as stale:
            raise VersionConflict() from stale

    def repo(self, model: type[M]) -> ScopedRepository[M]:
        return ScopedRepository(self, policy_for_model(model))

    def lock(self, model: type[M], ids: Sequence[uuid.UUID]) -> list[M]:
        """Ordered SELECT ... FOR UPDATE (deterministic order prevents deadlocks)."""
        if not ids:
            return []
        stmt = select(model).where(model.id.in_(sorted(set(ids)))).order_by(model.id).with_for_update()  # type: ignore[attr-defined]
        return list(self.session.scalars(stmt))

    def advisory_xact_lock(self, namespace: str, key: str) -> None:
        a = zlib.crc32(namespace.encode()) & 0x7FFFFFFF
        b = zlib.crc32(key.encode()) & 0x7FFFFFFF
        self.session.execute(text("SELECT pg_advisory_xact_lock(:a, :b)"), {"a": a, "b": b})

    def defer_constraints(self, *names: str) -> None:
        for name in names:
            if not name.replace("_", "").isalnum():
                raise ValueError("invalid constraint name")
            self.session.execute(text(f'SET CONSTRAINTS "{name}" DEFERRED'))

    def expect_version(self, obj: Any, expected: int | None) -> None:
        """Optimistic concurrency for client-supplied versions."""
        if expected is not None and getattr(obj, "version", None) != expected:
            raise VersionConflict(current_version=getattr(obj, "version", None))

    # ---- platform services ---------------------------------------------------------------------
    def emit(
        self,
        event_name: str,
        *,
        aggregate_id: uuid.UUID | None,
        payload: BaseModel | dict[str, Any] | None = None,
        aggregate_version: int | None = None,
        causation_id: uuid.UUID | None = None,
    ) -> uuid.UUID:
        from app.platform.events.service import emit

        return emit(
            self,
            event_name,
            aggregate_id=aggregate_id,
            payload=payload,
            aggregate_version=aggregate_version,
            causation_id=causation_id,
        )

    def enqueue(self, kind: str, payload: dict[str, Any] | None = None, **options: Any) -> uuid.UUID | None:
        from app.platform.jobs.queue import enqueue

        return enqueue(self, kind, payload or {}, **options)

    def allocate_number(
        self,
        sequence_key: str,
        *,
        document_date: date,
        resource_type: str,
        resource_id: uuid.UUID,
        branch_id: uuid.UUID | None = None,
        tokens: dict[str, str] | None = None,
    ) -> str:
        from app.platform.numbering.service import allocate

        return allocate(
            self,
            sequence_key,
            document_date=document_date,
            resource_type=resource_type,
            resource_id=resource_id,
            branch_id=branch_id,
            tokens=tokens or {},
        )

    def audit(self, action: str, **fields: Any) -> None:
        from app.platform.audit.service import record

        record(self, action, **fields)


def current_uow(session: Session) -> UnitOfWork | None:
    return session.info.get("uow")


@sa_event.listens_for(Session, "before_flush")
def _stamp(session: Session, _ctx: Any, _instances: Any) -> None:
    """Stamp tenant, actor and clock-derived timestamps on new and dirty rows."""
    uow = current_uow(session)
    if uow is None:
        return
    now = uow.now()
    actor = uow.actor
    for obj in session.new:
        if hasattr(obj, "company_id"):
            supplied = getattr(obj, "company_id", None)
            if supplied is None:
                obj.company_id = actor.company_id
            elif actor.company_id is not None and supplied != actor.company_id:
                raise PermissionError("cross-tenant write blocked: company_id does not match the actor")
        if hasattr(obj, "created_at") and getattr(obj, "created_at", None) is None:
            obj.created_at = now
        if hasattr(obj, "updated_at") and getattr(obj, "updated_at", None) is None:
            obj.updated_at = now
        if hasattr(obj, "created_by") and getattr(obj, "created_by", None) is None:
            obj.created_by = actor.user_id
        if hasattr(obj, "updated_by") and getattr(obj, "updated_by", None) is None:
            obj.updated_by = actor.user_id
    for obj in session.dirty:
        if not session.is_modified(obj, include_collections=False):
            continue
        if hasattr(obj, "company_id") and actor.company_id is not None and obj.company_id != actor.company_id:
            raise PermissionError("cross-tenant write blocked")
        if hasattr(obj, "updated_at"):
            obj.updated_at = now
        if hasattr(obj, "updated_by"):
            obj.updated_by = actor.user_id
