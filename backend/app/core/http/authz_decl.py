"""Route authorization declarations. Every /api route must declare one, or startup fails.

Usage: ``@router.get("/quotes/{id}", openapi_extra=requires("sales.quote.read"))``.
The declaration documents intent in OpenAPI (``x-authz``) and lets the startup check prove that no
route was added without thinking about access. Enforcement itself happens in services
(``ActorContext.require`` and ScopedRepository), so the declaration can never be the only guard.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.routing import APIRoute

KINDS = {"public", "authenticated", "permission", "webhook", "test_support"}


def public(reason: str) -> dict[str, Any]:
    return {"x-authz": {"kind": "public", "reason": reason}}


def authenticated() -> dict[str, Any]:
    """Any signed-in actor; the service applies record-level rules (e.g. own briefing)."""
    return {"x-authz": {"kind": "authenticated"}}


def requires(*permissions: str) -> dict[str, Any]:
    return {"x-authz": {"kind": "permission", "permissions": list(permissions)}}


def webhook(provider: str) -> dict[str, Any]:
    """Signature-verified provider callback: CSRF/Origin-exempt, raw body preserved."""
    return {"x-authz": {"kind": "webhook", "provider": provider}}


def test_support() -> dict[str, Any]:
    return {"x-authz": {"kind": "test_support"}}


def route_kind(route: APIRoute) -> str | None:
    extra = route.openapi_extra or {}
    decl = extra.get("x-authz")
    return decl.get("kind") if isinstance(decl, dict) else None


def validate_routes(app: FastAPI, known_permissions: set[str]) -> None:
    problems: list[str] = []
    for route in app.routes:
        if not isinstance(route, APIRoute) or not route.path.startswith("/api/"):
            continue
        extra = route.openapi_extra or {}
        decl = extra.get("x-authz")
        if not isinstance(decl, dict) or decl.get("kind") not in KINDS:
            problems.append(f"{sorted(route.methods)} {route.path}: missing x-authz declaration")
            continue
        if decl["kind"] == "permission":
            for key in decl.get("permissions", []):
                if key not in known_permissions:
                    problems.append(f"{route.path}: unknown permission {key}")
    if problems:
        raise RuntimeError("route authorization declarations invalid:\n  - " + "\n  - ".join(problems))


def webhook_paths(app: FastAPI) -> set[str]:
    return {r.path for r in app.routes if isinstance(r, APIRoute) and route_kind(r) == "webhook"}
