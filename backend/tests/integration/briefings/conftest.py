"""Fixtures for tasks/briefings integration tests.

``world``: the canonical world at D0 08:55 (the installed modules' real seeds plus the fake sales history; see
``world.py``). It is built once per session into its own database (cloned
from the migrated template, real commits and real job processing), then every test runs inside one
outer transaction on that database (savepoint mode) and rolls back, with fresh copies of the fake
sales records. ``fresh_world`` builds the same world inside the test's own savepoint transaction (for
tests that need to observe the history being built). ``bare_world``: company, people and calendar only.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, create_engine, make_url, text
from sqlalchemy.orm import sessionmaker

from app.core.clock import FrozenClock, get_clock, set_global_clock
from app.core.config import get_settings
from app.core.db import engine as db_engine
from tests.integration.briefings.world import BARE_MAX_ORDER, D0, FakeWorld

#: shared by the briefings and tasks test packages (each conftest gets its own session fixture instance)
_SNAPSHOT: dict[str, object] = {"users": 0, "value": None}


def _build_snapshot() -> tuple[Engine, FakeWorld, str]:
    settings = get_settings()
    name = f"{settings.db_name}_w{uuid.uuid4().hex[:8]}"
    admin = create_engine(settings.superuser_url(), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}" TEMPLATE "{settings.db_name}_tpl" OWNER lk_owner'))
    admin.dispose()
    url = make_url(settings.app_database_url).set(database=name)
    engine = db_engine.make_engine(url.render_as_string(hide_password=False), pool_size=2)
    previous_clock = get_clock()
    clock = FrozenClock(D0)
    set_global_clock(clock)
    db_engine.override_session_factory(sessionmaker(bind=engine, expire_on_commit=False, autoflush=False))
    base = FakeWorld(clock)
    try:
        base.build()
    except BaseException:
        engine.dispose()
        _drop_database(name)
        raise
    finally:
        base.uninstall()  # restores the registries even when the build fails
        db_engine.override_session_factory(None)
        set_global_clock(previous_clock if isinstance(previous_clock, FrozenClock) else None)
    return engine, base, name


def _drop_snapshot(engine: Engine, name: str) -> None:
    engine.dispose()
    _drop_database(name)


def _drop_database(name: str) -> None:
    admin = create_engine(get_settings().superuser_url(), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = :d AND pid <> pg_backend_pid()"), {"d": name})
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
    admin.dispose()


@pytest.fixture(scope="session")
def world_snapshot(migrated_db: str) -> Iterator[tuple[Engine, FakeWorld]]:
    if _SNAPSHOT["value"] is None:
        _SNAPSHOT["value"] = _build_snapshot()
    _SNAPSHOT["users"] = int(_SNAPSHOT["users"]) + 1  # type: ignore[call-overload]
    engine, base, name = _SNAPSHOT["value"]  # type: ignore[misc]
    try:
        yield engine, base
    finally:
        _SNAPSHOT["users"] = int(_SNAPSHOT["users"]) - 1  # type: ignore[call-overload]
        if _SNAPSHOT["users"] == 0:
            _SNAPSHOT["value"] = None
            _drop_snapshot(engine, name)


@pytest.fixture
def world(world_snapshot: tuple[Engine, FakeWorld], frozen_clock: FrozenClock) -> Iterator[FakeWorld]:
    engine, base = world_snapshot
    connection = engine.connect()
    outer = connection.begin()
    db_engine.override_session_factory(
        sessionmaker(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False, autoflush=False)
    )
    w = base.clone(frozen_clock)
    w.install()
    try:
        yield w
    finally:
        w.uninstall()
        db_engine.override_session_factory(None)
        outer.rollback()
        connection.close()


@pytest.fixture
def fresh_world(db: None, frozen_clock: FrozenClock) -> Iterator[FakeWorld]:
    w = FakeWorld(frozen_clock)
    try:
        yield w.build()
    finally:
        w.uninstall()


@pytest.fixture
def bare_world(db: None, frozen_clock: FrozenClock) -> Iterator[FakeWorld]:
    """Company, people and calendar only (the identity and org seeds, no history), with the fakes installed."""
    w = FakeWorld(frozen_clock)
    try:
        yield w.build(max_order=BARE_MAX_ORDER)
    finally:
        w.uninstall()
