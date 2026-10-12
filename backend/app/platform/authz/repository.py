"""ScopedRepository: the only sanctioned way for domain modules to read tenant records.

``get`` returns 404 when the record is not readable and 403 when it is readable but the requested
action is not permitted. Lists, counts and searches apply the scope clause before pagination.
Search uses escaped ILIKE terms — user input never becomes a regular expression.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from sqlalchemy import ColumnElement, Select, and_, exists, func, or_, select

from app.core.errors import Forbidden, NotFound
from app.core.http.pagination import MAX_LIMIT, Page
from app.core.text import LIKE_ESCAPE, contains_pattern, tokens
from app.platform.authz.policy import ResourcePolicy, object_decisions, scope_clause

if TYPE_CHECKING:
    from app.platform.uow import UnitOfWork

M = TypeVar("M")


class ScopedRepository(Generic[M]):
    def __init__(self, uow: UnitOfWork, policy: ResourcePolicy) -> None:
        self.uow = uow
        self.policy = policy
        self.model: Any = policy.model

    # ---- predicates -------------------------------------------------------------------------
    def clause(self, action: str = "read") -> ColumnElement[bool]:
        return scope_clause(self.uow.actor, self.policy, action)

    def _not_archived(self) -> ColumnElement[bool] | None:
        col = self.policy.archived_column
        if col and hasattr(self.model, col):
            return getattr(self.model, col).is_(None)
        return None

    def select(self, action: str = "read", *, include_archived: bool = False) -> Select[Any]:
        stmt = select(self.model).where(self.clause(action))
        if not include_archived and (na := self._not_archived()) is not None:
            stmt = stmt.where(na)
        return stmt

    # ---- single record -----------------------------------------------------------------------
    def get(
        self,
        record_id: uuid.UUID,
        action: str = "read",
        *,
        for_update: bool = False,
        include_archived: bool = True,
    ) -> M:
        stmt = select(self.model).where(self.model.id == record_id, self.clause("read"))
        if not include_archived and (na := self._not_archived()) is not None:
            stmt = stmt.where(na)
        if for_update:
            stmt = stmt.with_for_update()
        obj = self.uow.session.scalars(stmt).first()
        if obj is None:
            raise NotFound(code="not_found", resource_type=self.policy.resource_type)
        if action != "read":
            self.require_action(obj, action)
        return obj

    def get_by_key(self, business_key: str, action: str = "read") -> M:
        if not self.policy.business_key_column:
            raise ValueError(f"{self.policy.resource_type} has no business key")
        col = getattr(self.model, self.policy.business_key_column)
        obj = self.uow.session.scalars(select(self.model).where(col == business_key, self.clause("read"))).first()
        if obj is None:
            raise NotFound(code="not_found", resource_type=self.policy.resource_type)
        if action != "read":
            self.require_action(obj, action)
        return obj

    def can(self, obj: Any, action: str) -> bool:
        allowed = self.uow.session.scalar(
            select(exists().where(and_(self.model.id == obj.id, self.clause(action))))
        )
        if not allowed:
            return False
        decision = object_decisions(self.uow.actor, self.policy, obj).get(action)
        return decision is None or decision.allowed

    def require_action(self, obj: Any, action: str) -> None:
        allowed = self.uow.session.scalar(
            select(exists().where(and_(self.model.id == obj.id, self.clause(action))))
        )
        if not allowed:
            raise Forbidden(code="permission_denied", permission=self.policy.permission(action))
        decision = object_decisions(self.uow.actor, self.policy, obj).get(action)
        if decision is not None and not decision.allowed:
            raise Forbidden(decision.reason_code or "action_not_allowed", code=decision.reason_code or "action_not_allowed")

    def capabilities(self, obj: Any, actions: Iterable[str]) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        rules = object_decisions(self.uow.actor, self.policy, obj)
        for action in actions:
            in_scope = bool(
                self.uow.session.scalar(select(exists().where(and_(self.model.id == obj.id, self.clause(action)))))
            )
            if not in_scope:
                out[action] = {"allowed": False, "reason_code": "permission_denied"}
                continue
            rule = rules.get(action)
            out[action] = {
                "allowed": rule is None or rule.allowed,
                "reason_code": None if rule is None or rule.allowed else rule.reason_code,
            }
        return out

    # ---- collections ---------------------------------------------------------------------------
    def list(
        self,
        *filters: ColumnElement[bool],
        order_by: Sequence[Any] = (),
        limit: int = 50,
        offset: int = 0,
        action: str = "read",
        include_archived: bool = False,
        stmt: Select[Any] | None = None,
    ) -> Page[M]:
        base = stmt if stmt is not None else self.select(action, include_archived=include_archived)
        if filters:
            base = base.where(*filters)
        total = self.uow.session.scalar(select(func.count()).select_from(base.order_by(None).subquery())) or 0
        limit = max(1, min(limit, MAX_LIMIT))
        ordered = base.order_by(*order_by) if order_by else base.order_by(self.model.id.desc())
        items = list(self.uow.session.scalars(ordered.limit(limit).offset(offset)).unique())
        return Page[M](items=items, total=int(total), limit=limit, offset=offset)  # type: ignore[valid-type]

    def count(self, *filters: ColumnElement[bool], action: str = "read") -> int:
        stmt = select(func.count()).select_from(self.model).where(self.clause(action), *filters)
        if (na := self._not_archived()) is not None:
            stmt = stmt.where(na)
        return int(self.uow.session.scalar(stmt) or 0)

    def exists(self, *filters: ColumnElement[bool], action: str = "read") -> bool:
        return bool(self.uow.session.scalar(select(exists().where(self.clause(action), *filters))))

    def visible_ids(self, action: str = "read") -> Select[Any]:
        return select(self.model.id).where(self.clause(action))

    def search_filter(self, term: str, columns: Sequence[str]) -> ColumnElement[bool] | None:
        """All tokens must match at least one column (escaped ILIKE)."""
        parts = tokens(term)
        if not parts:
            return None
        cols = [getattr(self.model, c) for c in columns]
        return and_(
            *[or_(*[col.ilike(contains_pattern(tok), escape=LIKE_ESCAPE) for col in cols]) for tok in parts]
        )
