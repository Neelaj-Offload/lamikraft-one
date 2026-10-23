"""Route authorization declarations. Every /api route must declare one, or startup fails.

Usage: ``@router.get("/quotes/{id}", openapi_extra=requires("sales.quote.read"))``.
The declaration documents intent in OpenAPI (``x-authz``) and lets the startup check prove that no
route was added without thinking about access. Enforcement itself happens in services
(``ActorContext.require`` and ScopedRepository), so the declaration can never be the only guard.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from fastapi import FastAPI
from fastapi.routing import APIRoute, iter_route_contexts

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


def api_routes(app: FastAPI) -> Iterator[tuple[str, APIRoute]]:
    """(effective path, route) for every mounted APIRoute.

    FastAPI 0.143 wraps included routers in ``_IncludedRouter``; ``app.routes`` alone hides them, so the
    effective paths come from ``iter_route_contexts``.
    """
    for ctx in iter_route_contexts(app.routes):
        route = ctx.original_route
        if isinstance(route, APIRoute) and ctx.path:
            yield ctx.path, route


def validate_routes(app: FastAPI, known_permissions: set[str]) -> None:
    problems: list[str] = []
    for path, route in api_routes(app):
        if not path.startswith("/api/"):
            continue
        extra = route.openapi_extra or {}
        decl = extra.get("x-authz")
        if not isinstance(decl, dict) or decl.get("kind") not in KINDS:
            problems.append(f"{sorted(route.methods)} {path}: missing x-authz declaration")
            continue
        if decl["kind"] == "permission":
            for key in decl.get("permissions", []):
                if key not in known_permissions:
                    problems.append(f"{path}: unknown permission {key}")
    if problems:
        raise RuntimeError("route authorization declarations invalid:\n  - " + "\n  - ".join(problems))


def webhook_paths(app: FastAPI) -> set[str]:
    return {path for path, route in api_routes(app) if route_kind(route) == "webhook"}
