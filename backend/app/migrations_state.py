"""Compare the database's Alembic revision with the code's head (used by readiness)."""

from __future__ import annotations

from functools import lru_cache

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import BACKEND_DIR


@lru_cache(maxsize=1)
def code_heads() -> tuple[str, ...]:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    return tuple(ScriptDirectory.from_config(cfg).get_heads())


def head_matches(session: Session) -> tuple[bool, str | None, str | None]:
    heads = code_heads()
    try:
        current = session.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except Exception:
        session.rollback()
        current = None
    head = heads[0] if len(heads) == 1 else ",".join(heads)
    return (current is not None and len(heads) == 1 and current == heads[0]), current, head
