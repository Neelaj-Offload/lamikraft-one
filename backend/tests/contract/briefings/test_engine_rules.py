"""Architecture rules for the work lane: business time only from the Clock, the engine stays pure, and
routers never import models."""

from __future__ import annotations

import ast
from pathlib import Path

from app.core.config import BACKEND_DIR

MODULES = [BACKEND_DIR / "app" / "modules" / "tasks", BACKEND_DIR / "app" / "modules" / "briefings"]
BANNED_CALLS = {("datetime", "now"), ("datetime", "utcnow"), ("date", "today"), ("time", "time")}


def _files() -> list[Path]:
    return [p for root in MODULES for p in root.rglob("*.py")]


def test_no_wall_clock_for_business_time() -> None:
    offenders = []
    for path in _files():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                if (node.func.value.id, node.func.attr) in BANNED_CALLS:
                    offenders.append(f"{path.relative_to(BACKEND_DIR)}:{node.lineno}")
    assert offenders == []


def test_pure_engine_parts_do_not_touch_the_database() -> None:
    engine = BACKEND_DIR / "app" / "modules" / "briefings" / "engine"
    for name in ("priority.py", "sections.py", "overview.py", "labels.py", "recommend.py", "model.py", "fingerprint.py"):
        source = (engine / name).read_text(encoding="utf-8")
        assert "sqlalchemy" not in source and "UnitOfWork" not in source, name


def test_routers_do_not_import_models() -> None:
    for root in MODULES:
        tree = ast.parse((root / "router.py").read_text(encoding="utf-8"))
        imported = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module]
        assert not [m for m in imported if m.endswith(".models")], root.name
