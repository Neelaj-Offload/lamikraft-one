"""Test harness.

Modes
- default (savepoint): each test runs inside one outer transaction on the ``<db>_test`` database as
  ``lk_app``; every unit of work becomes a SAVEPOINT; everything rolls back at the end.
- ``@pytest.mark.committed``: the test gets a fresh database cloned from a migrated template, so RLS,
  concurrency, worker and backup behaviour is exercised with real commits and real connections.

The clock is frozen at the canonical D0 (Mon 2026-10-12 08:55 IST) unless a test changes it.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

os.environ["LK_ENV"] = "test"

from app.core import config as _config  # noqa: E402

_config.reset_settings_cache()
_base_settings = _config.get_settings()
if not _base_settings.db_name.endswith("_test"):
    os.environ["LK_DB_NAME"] = f"{_base_settings.db_name}_test"
    _config.reset_settings_cache()

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.core.clock import FrozenClock, set_global_clock  # noqa: E402
from app.core.config import BACKEND_DIR, get_settings, reset_settings_cache  # noqa: E402
from app.core.db import engine as db_engine  # noqa: E402

D0 = datetime(2026, 10, 12, 8, 55, tzinfo=ZoneInfo("Asia/Kolkata"))
TEMPLATE_SUFFIX = "_tpl"


def _db_configured() -> bool:
    s = get_settings()
    return bool(s.db_app_password.get_secret_value() and s.db_owner_password.get_secret_value())


def _run_migrations(database_url: str) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.attributes["database_url"] = database_url
    command.upgrade(cfg, "heads")


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "committed: runs against a cloned committed database")
    config.addinivalue_line("markers", "db: needs PostgreSQL")


@pytest.fixture(scope="session")
def migrated_db() -> Iterator[str]:
    if not _db_configured():
        pytest.skip("database not configured (run: npm run setup)")
    settings = get_settings()
    _run_migrations(settings.owner_database_url)
    # refresh the clone template for committed tests
    admin = create_engine(settings.superuser_url(), isolation_level="AUTOCOMMIT")
    tpl = f"{settings.db_name}{TEMPLATE_SUFFIX}"
    with admin.connect() as conn:
        conn.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = :d AND pid <> pg_backend_pid()"), {"d": settings.db_name})
        conn.execute(text(f'DROP DATABASE IF EXISTS "{tpl}"'))
        conn.execute(text(f'CREATE DATABASE "{tpl}" TEMPLATE "{settings.db_name}" OWNER lk_owner'))
    admin.dispose()
    db_engine.dispose_engine()
    yield settings.db_name


@pytest.fixture(autouse=True)
def frozen_clock() -> Iterator[FrozenClock]:
    clock = FrozenClock(D0)
    set_global_clock(clock)
    yield clock
    set_global_clock(None)


@pytest.fixture(autouse=True)
def _registry_loaded() -> None:
    from app.registry import get_registry

    get_registry()


@pytest.fixture
def db(request: pytest.FixtureRequest, migrated_db: str) -> Iterator[None]:
    """Savepoint mode: all units of work share one outer transaction that is rolled back."""
    if request.node.get_closest_marker("committed"):
        yield
        return
    engine = db_engine.get_engine()
    connection = engine.connect()
    outer = connection.begin()
    factory = sessionmaker(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False, autoflush=False)
    db_engine.override_session_factory(factory)
    try:
        yield
    finally:
        db_engine.override_session_factory(None)
        outer.rollback()
        connection.close()


@pytest.fixture
def committed_db(migrated_db: str) -> Iterator[str]:
    """A fresh database cloned from the migrated template; real commits, real connections."""
    settings = get_settings()
    name = f"{settings.db_name}_c{uuid.uuid4().hex[:8]}"
    admin = create_engine(settings.superuser_url(), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}" TEMPLATE "{settings.db_name}{TEMPLATE_SUFFIX}" OWNER lk_owner'))
    previous = os.environ.get("LK_DB_NAME")
    os.environ["LK_DB_NAME"] = name
    reset_settings_cache()
    db_engine.dispose_engine()
    try:
        yield name
    finally:
        db_engine.dispose_engine()
        if previous is None:
            os.environ.pop("LK_DB_NAME", None)
        else:
            os.environ["LK_DB_NAME"] = previous
        reset_settings_cache()
        with admin.connect() as conn:
            conn.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = :d AND pid <> pg_backend_pid()"), {"d": name})
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
        admin.dispose()
