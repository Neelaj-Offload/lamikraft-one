"""Demo-only catalogue reset (LM-37, API-33, UI-88, LP-04.9): the legacy "Clear sample data" wiped the catalogue of
any installation. Here it is refused unless the company is a demo company (``company.is_demo``, set at seed and not
changeable through any API), needs ``system.demo_data.delete`` with a recent sign-in, a preview whose token expires in
five minutes and binds the counts, and the typed phrase ``RESET <company name>``. It is also refused while anything
outside the catalogue (price lists, quotes, challans...) references the demo products, so it never breaks other
records; every delete runs inside the same unit of work that re-checks ``is_demo``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select

from app.core.config import get_settings
from app.core.db.base import Base
from app.core.errors import Conflict, Forbidden, ValidationFailed
from app.modules.catalogue.models import (
    Category,
    LookupReference,
    Product,
    ProductMedia,
    Subcategory,
    TaxonomyAlias,
)
from app.modules.imports.models import ImportJob
from app.modules.imports.schemas import DemoResetPreview, DemoResetRequest, DemoResetResult
from app.platform.uow import UnitOfWork

PERMISSION = "system.demo_data.delete"
TOKEN_TTL = timedelta(minutes=5)
#: tables cleared, in delete order (children cascade from products: specification, packaging, dimensions, media)
_TABLES: tuple[tuple[str, Any], ...] = (
    ("imports_job", ImportJob),
    ("catalogue_product_media", ProductMedia),
    ("catalogue_product", Product),
    ("catalogue_taxonomy_alias", TaxonomyAlias),
    ("catalogue_subcategory", Subcategory),
    ("catalogue_category", Category),
    ("catalogue_lookup_reference", LookupReference),
)
_OWN_TABLES = {name for name, _m in _TABLES} | {
    "catalogue_product_specification", "catalogue_product_packaging", "catalogue_product_dimension",
    "imports_staged_row", "imports_row_issue", "imports_change",
}


def _require(uow: UnitOfWork) -> Any:
    from app.platform.identity.errors import ReauthRequired
    from app.platform.org.models import Company

    uow.actor.require(PERMISSION)
    if not uow.actor.is_system and (
        uow.actor.recent_auth_at is None or uow.now() - uow.actor.recent_auth_at > timedelta(minutes=10)
    ):
        raise ReauthRequired()
    company = uow.session.get(Company, uow.actor.company_id)
    assert company is not None
    return company


def _counts(uow: UnitOfWork) -> dict[str, int]:
    return {
        name: int(uow.session.scalar(select(func.count()).select_from(model).where(model.company_id == uow.actor.company_id)) or 0)
        for name, model in _TABLES
    }


def _blocking(uow: UnitOfWork) -> dict[str, int]:
    """Rows outside the catalogue that reference catalogue products, taxonomy or media (non-cascading FKs)."""
    targets = {"catalogue_product", "catalogue_category", "catalogue_subcategory", "catalogue_product_media"}
    out: dict[str, int] = {}
    for table in Base.metadata.sorted_tables:
        if table.name in _OWN_TABLES:
            continue
        for fk in table.foreign_keys:
            if fk.column.table.name in targets and (fk.ondelete or "").upper() != "CASCADE":
                n = uow.session.scalar(select(func.count()).select_from(table).where(fk.parent.is_not(None))) or 0
                if n:
                    out[table.name] = out.get(table.name, 0) + int(n)
    return out


def _phrase(company: Any) -> str:
    return f"RESET {company.display_name}"


def _sign(uow: UnitOfWork, expires: datetime, counts: dict[str, int]) -> str:
    key = get_settings().secret_key.get_secret_value().encode() or b"lk-dev"
    message = json.dumps([str(uow.actor.company_id), str(uow.actor.user_id), expires.isoformat(), counts], sort_keys=True)
    return hmac.new(key, message.encode(), hashlib.sha256).hexdigest()


def preview(uow: UnitOfWork) -> DemoResetPreview:
    company = _require(uow)
    counts = _counts(uow)
    blocking = _blocking(uow)
    reason = None if company.is_demo else "not_a_demo_company"
    if reason is None and blocking:
        reason = "demo_data_referenced"
    expires = uow.now() + TOKEN_TTL
    token = f"{int(expires.timestamp())}.{_sign(uow, expires, counts)}" if reason is None else None
    return DemoResetPreview(
        company_name=company.display_name, is_demo=bool(company.is_demo), counts=counts, blocking_references=blocking,
        allowed=reason is None, reason_code=reason, phrase=_phrase(company), token=token,
        expires_at=expires if token else None,
    )


def execute(uow: UnitOfWork, data: DemoResetRequest) -> DemoResetResult:
    company = _require(uow)
    if not company.is_demo:
        raise Forbidden("The catalogue reset is available only in a demo company", code="not_a_demo_company")
    if data.phrase.strip() != _phrase(company):
        raise ValidationFailed("Type the confirmation phrase exactly",
                               errors=[{"loc": ["body", "phrase"], "msg": "phrase mismatch", "code": "phrase_mismatch"}])
    counts = _counts(uow)
    try:
        stamp, signature = data.token.split(".", 1)
        expires = datetime.fromtimestamp(int(stamp), tz=uow.now().tzinfo)
    except ValueError as exc:
        raise Conflict("The preview token is not valid; preview again", code="preview_token_invalid") from exc
    if expires < uow.now() or not hmac.compare_digest(signature, _sign(uow, expires, counts)):
        raise Conflict("The preview expired or the data changed since; preview again", code="preview_token_invalid")
    blocking = _blocking(uow)
    if blocking:
        raise Conflict("Other records reference the demo catalogue", code="demo_data_referenced", references=blocking)
    uow.session.execute(  # recheck children before their parents (self-referencing RESTRICT FK)
        delete(ImportJob).where(ImportJob.company_id == uow.actor.company_id, ImportJob.parent_job_id.is_not(None))
    )
    for _name, model in _TABLES:
        uow.session.execute(delete(model).where(model.company_id == uow.actor.company_id))
    uow.flush()
    uow.emit("system.demo_data.deleted", aggregate_id=uow.actor.company_id, payload={"modules": ["catalogue", "imports"]})
    uow.audit("system.demo_data.deleted", resource_type="org.company", resource_id=uow.actor.company_id,
              resource_label=company.display_name, details={"deleted": counts})
    return DemoResetResult(deleted=counts)
