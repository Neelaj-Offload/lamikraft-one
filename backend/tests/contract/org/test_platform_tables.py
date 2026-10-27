"""Database contract of the platform lane's tables: RLS, append-only triggers and the runtime role's grants."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.db.base import Base
from app.platform.authz.context import ActorContext
from app.platform.uow import UnitOfWork

pytestmark = pytest.mark.db

LANE_TENANT_TABLES = {
    "setting", "setting_revision", "uom", "uom_alias", "uom_conversion", "file_object", "note", "search_recent",
    "integration_status",
}
LANE_APPEND_ONLY = {"setting_revision"}


def _scalars(sql: str) -> set[str]:
    with UnitOfWork(ActorContext.system(None, reason="contract")) as uow:
        return set(uow.session.execute(text(sql)).scalars())


def _models() -> dict[str, type]:
    return {m.local_table.name: m.class_ for m in Base.registry.mappers}  # type: ignore[attr-defined]


def test_lane_tenant_tables_have_forced_rls(db: None) -> None:
    policies = _scalars("SELECT tablename FROM pg_policies WHERE policyname = 'tenant_isolation'")
    forced = _scalars("SELECT relname FROM pg_class WHERE relforcerowsecurity")
    models = _models()
    for table in LANE_TENANT_TABLES:
        assert getattr(models[table], "__tenant_rls__", True) is True
        assert table in policies and table in forced, table


def test_currency_is_global_and_read_only_for_the_app_role(db: None) -> None:
    models = _models()
    assert models["currency"].__tenant_rls__ is False  # type: ignore[attr-defined]
    assert "company_id" not in models["currency"].__table__.c  # type: ignore[attr-defined]
    with UnitOfWork(ActorContext.system(None)) as uow:
        privileges = uow.session.execute(
            text(
                "SELECT has_table_privilege('lk_app', 'currency', 'SELECT'), "
                "has_table_privilege('lk_app', 'currency', 'INSERT'), "
                "has_table_privilege('lk_app', 'currency', 'UPDATE'), "
                "has_table_privilege('lk_app', 'currency', 'DELETE')"
            )
        ).one()
    assert tuple(privileges) == (True, False, False, False)


def test_append_only_models_have_their_trigger(db: None) -> None:
    triggers = _scalars("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal")
    models = _models()
    flagged = {t for t, m in models.items() if getattr(m, "__append_only__", False)}
    assert LANE_APPEND_ONLY <= flagged
    missing = sorted(t for t in flagged if f"trg_{t}_append_only" not in triggers)
    assert missing == []
    for table in LANE_TENANT_TABLES - LANE_APPEND_ONLY:
        assert f"trg_{table}_append_only" not in triggers, table


def test_setting_revisions_cannot_be_rewritten(db: None) -> None:
    with UnitOfWork(ActorContext.system(None)) as uow:
        allowed = uow.session.execute(
            text("SELECT has_table_privilege('lk_app', 'setting_revision', 'UPDATE')")
        ).scalar()
    assert allowed is False
    with pytest.raises(DBAPIError):
        with UnitOfWork(ActorContext.system(None)) as uow:
            uow.session.execute(text("UPDATE setting_revision SET change_reason = 'rewritten'"))
