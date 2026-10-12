"""Event definitions and subscriptions (declared per module in ``events.py``; collected by the registry)."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

if TYPE_CHECKING:
    from app.platform.events.models import DomainEvent
    from app.platform.uow import UnitOfWork

_NAME = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")


@dataclass(frozen=True)
class EventDef:
    name: str
    aggregate_type: str
    description: str
    payload: type[BaseModel] | None = None
    version: int = 1
    #: allowed payload field names (catalogue); ``origin`` is always allowed
    fields: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        if not _NAME.match(self.name):
            raise ValueError(f"event name {self.name!r} must be <module>.<entity>.<past_tense_verb>")

    @property
    def module(self) -> str:
        return self.name.split(".", 1)[0]

    def validate_payload(self, payload: BaseModel | dict[str, Any] | None) -> dict[str, Any]:
        if payload is None:
            data: dict[str, Any] = {}
        elif isinstance(payload, BaseModel):
            data = payload.model_dump(mode="json")
        else:
            data = dict(payload)
        if self.payload is not None:
            data = self.payload.model_validate(data).model_dump(mode="json")
        if self.fields is not None:
            unknown = sorted(set(data) - set(self.fields) - {"origin"})
            if unknown:
                raise ValueError(f"event {self.name} payload has undeclared fields {unknown}")
        return data


Handler = Callable[["UnitOfWork", "DomainEvent"], None]


@dataclass(frozen=True)
class Subscription:
    event: str
    handler_key: str
    handler: Handler
    queue: str = "events"
    max_attempts: int = 8
