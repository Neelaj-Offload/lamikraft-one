"""Engine and session factory.

The application connects as ``lk_app`` (no superuser, no BYPASSRLS). Tests can override the
session factory so every unit of work joins an outer transaction (savepoint mode).
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

_lock = threading.RLock()
_engine: Engine | None = None
_factory: Callable[[], Session] | None = None
_override: Callable[[], Session] | None = None


def make_engine(url: str, *, pool_size: int = 10) -> Engine:
    engine = create_engine(
        url,
        pool_size=pool_size,
        max_overflow=pool_size,
        pool_pre_ping=True,
        pool_recycle=1800,
        hide_parameters=True,
        connect_args={"options": "-c timezone=UTC", "application_name": "lamikraft-one"},
    )

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_connection, _record):  # type: ignore[no-untyped-def]
        with dbapi_connection.cursor() as cur:
            cur.execute("SET TIME ZONE 'UTC'")

    return engine


def get_engine() -> Engine:
    global _engine
    with _lock:
        if _engine is None:
            settings = get_settings()
            _engine = make_engine(settings.app_database_url, pool_size=settings.db_pool_size)
        return _engine


def session_factory() -> Callable[[], Session]:
    global _factory
    if _override is not None:
        return _override
    with _lock:
        if _factory is None:
            _factory = sessionmaker(bind=get_engine(), expire_on_commit=False, autoflush=False)
        return _factory


def override_session_factory(factory: Callable[[], Session] | None) -> None:
    """Tests only: route every unit of work through ``factory``."""
    global _override
    _override = factory


def dispose_engine() -> None:
    global _engine, _factory
    with _lock:
        if _engine is not None:
            _engine.dispose()
        _engine = None
        _factory = None
