"""Shared builders for the cutting integration tests (personas from ``keys.USERS``; no literal names)."""

from __future__ import annotations

from typing import Any

from app.seed.world import keys

API = "/api/v1/cutting"


def as_(persona: str, **extra: str) -> dict[str, str]:
    return {"x-test-persona": persona, **extra}


def item(sku: str, length: str, width: str, qty: int, *, decor: str | None = "W-7", thickness: str = "18", **extra: Any) -> dict[str, Any]:
    return {"sku": sku, "decor": decor, "thickness_mm": thickness, "length_mm": length, "width_mm": width, "quantity": qty, **extra}


CUT_LIST = [
    item("PANEL-A", "720", "560", 6),
    item("PANEL-B", "1200", "600", 3, decor="0120"),
    item("=HYPERLINK(\"x\")", "400", "300", 4),
]


def problem(response: Any, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    body: dict[str, Any] = response.json()
    assert body["code"] == code, body
    return body


def create_plan(client: Any, persona: str = keys.USERS.RAVI, items: list[dict[str, Any]] | None = None,
                settings: dict[str, Any] | None = None, name: str = "Test plan") -> dict[str, Any]:
    body: dict[str, Any] = {"name": name, "items": CUT_LIST if items is None else items}
    if settings is not None:
        body["settings"] = settings
    r = client.post(f"{API}/plans", json=body, headers=as_(persona))
    assert r.status_code == 201, r.text
    return r.json()


def calculate(client: Any, plan: dict[str, Any], persona: str = keys.USERS.RAVI) -> dict[str, Any]:
    r = client.post(f"{API}/plans/{plan['id']}/calculate", json={"expected_version": plan["version"]}, headers=as_(persona))
    assert r.status_code == 200, r.text
    return r.json()
