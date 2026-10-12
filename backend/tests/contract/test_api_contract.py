"""API and architecture contracts that hold for every module."""

from __future__ import annotations

import ast
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import BACKEND_DIR

APP_DIR = BACKEND_DIR / "app"
MONEY_HINTS = ("amount", "price", "total", "subtotal", "surcharge", "quantity", "qty", "rate", "cost")


def _client() -> TestClient:
    from app.main import create_app

    return TestClient(create_app())


def test_health_live_is_public() -> None:
    r = _client().get("/api/v1/health/live")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_unknown_route_returns_problem_json() -> None:
    r = _client().get("/api/v1/does-not-exist")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["code"] == "not_found"


def test_unsafe_request_from_foreign_origin_is_blocked() -> None:
    r = _client().post("/api/v1/health/live", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403 and r.json()["code"] in {"origin_mismatch", "cross_site_request"}


def test_money_and_quantity_fields_are_strings_in_openapi() -> None:
    from app.main import create_app

    spec = create_app().openapi()
    offenders = []
    for name, schema in spec.get("components", {}).get("schemas", {}).items():
        for prop, prop_schema in (schema.get("properties") or {}).items():
            lowered = prop.lower()
            if any(h in lowered for h in MONEY_HINTS):
                types = {prop_schema.get("type")} | {s.get("type") for s in prop_schema.get("anyOf", [])}
                if "number" in types:
                    offenders.append(f"{name}.{prop}")
    assert offenders == [], f"money/quantity fields typed as number: {offenders}"


def test_operation_ids_are_unique() -> None:
    from app.main import create_app

    ids = [op.get("operationId") for path in create_app().openapi()["paths"].values() for op in path.values()]
    assert len(ids) == len(set(ids))


def _py_files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*.py") if ".venv" not in p.parts]


def test_only_csv_safe_writes_csv() -> None:
    offenders = []
    for path in _py_files(APP_DIR):
        if path.name == "csv_safe.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in {"writer", "DictWriter"}:
                if isinstance(node.value, ast.Name) and node.value.id == "csv":
                    offenders.append(str(path.relative_to(BACKEND_DIR)))
    assert offenders == []


def test_no_query_parameters_named_token_or_auth() -> None:
    from app.main import create_app

    bad = []
    for path, item in create_app().openapi()["paths"].items():
        for op in item.values():
            for param in op.get("parameters", []):
                if param.get("in") == "query" and param.get("name", "").lower() in {"token", "auth", "access_token", "session"}:
                    bad.append(f"{path}?{param['name']}")
    assert bad == []


def test_modules_do_not_use_raw_sql_text_outside_allowlist() -> None:
    offenders = []
    modules_dir = APP_DIR / "modules"
    for path in _py_files(modules_dir):
        if path.name == "sql.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "text":
                offenders.append(str(path.relative_to(BACKEND_DIR)))
    assert offenders == [], "raw SQL text() belongs in a module's sql.py"


def test_no_async_psycopg() -> None:
    offenders = [
        str(p.relative_to(BACKEND_DIR))
        for p in _py_files(APP_DIR)
        if "AsyncConnection" in p.read_text(encoding="utf-8") or "create_async_engine" in p.read_text(encoding="utf-8")
    ]
    assert offenders == []
