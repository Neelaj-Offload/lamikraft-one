"""Field guards: one registry for restricted fields (costing, margins, supplier cost ...).

Mark DTO fields ``Annotated[DecimalStr | None, Restricted("pricing.cost.read")]``. Every output
path (API, exports, PDFs, notifications, idempotency replays, agent tool results) passes through
:func:`redact`. ``model_exposure="deny"`` means the value never reaches an AI model even when the
user may see it; cards render such values directly to permitted users instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel

from app.platform.authz.context import ActorContext


@dataclass(frozen=True)
class Restricted:
    guard: str
    model_exposure: Literal["deny", "allow"] = "deny"
    log: Literal["drop", "keep"] = "drop"


def _restricted_meta(model: type[BaseModel], name: str) -> Restricted | None:
    info = model.model_fields[name]
    for meta in info.metadata:
        if isinstance(meta, Restricted):
            return meta
    return None


def restricted_field_names(model: type[BaseModel]) -> dict[str, Restricted]:
    return {n: m for n in model.model_fields if (m := _restricted_meta(model, n)) is not None}


def redact(value: Any, ctx: ActorContext, *, for_model: bool = False) -> Any:
    """Return a copy of ``value`` with restricted fields nulled for ``ctx``.

    ``for_model=True`` additionally removes fields whose guard denies model exposure.
    Redacted field names are listed in ``redacted_fields`` when the DTO declares it.
    """
    if isinstance(value, BaseModel):
        updates: dict[str, Any] = {}
        redacted: list[str] = []
        for name in type(value).model_fields:
            meta = _restricted_meta(type(value), name)
            current = getattr(value, name)
            if meta is not None and (not ctx.can(meta.guard) or (for_model and meta.model_exposure == "deny")):
                if current is not None:
                    redacted.append(name)
                updates[name] = None
            else:
                nested = redact(current, ctx, for_model=for_model)
                if nested is not current:
                    updates[name] = nested
        if "redacted_fields" in type(value).model_fields:
            existing = list(value.redacted_fields or [])
            updates["redacted_fields"] = sorted(set(existing) | set(redacted))
        return value.model_copy(update=updates) if updates else value
    if isinstance(value, list):
        new = [redact(v, ctx, for_model=for_model) for v in value]
        return new if any(a is not b for a, b in zip(new, value, strict=True)) else value
    if isinstance(value, tuple):
        return tuple(redact(v, ctx, for_model=for_model) for v in value)
    if isinstance(value, dict):
        return {k: redact(v, ctx, for_model=for_model) for k, v in value.items()}
    return value
