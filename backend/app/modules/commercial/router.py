"""Commercial rule-set read API (``/api/v1/commercial``)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from app.core.http.authz_decl import requires
from app.core.http.deps import Actor
from app.core.http.pagination import MAX_LIMIT, Page
from app.modules.commercial import service
from app.modules.commercial.schemas import RuleSetDetail, RuleSetRead

router = APIRouter(prefix="/commercial", tags=["commercial"])
READ = requires("commercial.rule_set.read")


@router.get("/rule-sets", openapi_extra=READ)
def list_rule_sets(
    actor: Actor,
    code: Annotated[str | None, Query(max_length=60)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[RuleSetRead]:
    return service.list_rule_sets(actor, code=code, limit=limit, offset=offset)


@router.get("/rule-sets/{rule_set_id}", openapi_extra=READ)
def get_rule_set(actor: Actor, rule_set_id: uuid.UUID) -> RuleSetDetail:
    return service.get_rule_set(actor, rule_set_id)
