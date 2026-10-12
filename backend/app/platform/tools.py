"""Typed agent tools. A tool is a thin descriptor over an application service — the same service the
UI endpoint calls — so agents can never do more than the authenticated user could do in the app.

Rules (docs/architecture/ai-routing.md): inputs never carry identity (user/company/role/permission
fields are rejected by a contract test); prices are never model inputs except an explicit,
permission-gated override; outputs pass through field-guard redaction for the model
(``model_exposure="deny"`` fields are removed even for permitted users).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel

if TYPE_CHECKING:
    from app.platform.uow import UnitOfWork

Effect = Literal["read", "draft", "propose", "execute"]
FORBIDDEN_INPUT_FIELDS = frozenset(
    {"user_id", "company_id", "actor", "actor_id", "role", "roles", "permission", "permissions", "scope", "membership_id", "tenant_id"}
)


@dataclass(frozen=True)
class ToolDef:
    name: str
    group: str  # Sales | Catalogue | Procurement | Production | Warehouse | Finance | Management | Briefing
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    handler: Callable[[UnitOfWork, BaseModel], BaseModel]
    effect: Effect
    permission: str | None = None
    #: drafts and proposals created by tools must be idempotent per agent step
    requires_idempotency: bool = False

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_]{2,63}", self.name):
            raise ValueError(f"tool name {self.name!r} must be snake_case")
        bad = FORBIDDEN_INPUT_FIELDS & set(self.input_model.model_fields)
        if bad:
            raise ValueError(f"tool {self.name} input carries identity fields {sorted(bad)}")
        if self.effect == "execute":
            raise ValueError("execute tools are only advertised by the approvals runtime once policy and idempotency exist")

    def json_schema(self) -> dict:
        return self.input_model.model_json_schema()
