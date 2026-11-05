"""Route authorization matrix (api-conventions §2): every mounted /api route declares exactly one kind, declared
permission keys exist in the frozen catalogue, and the platform lane's routes declare what this file pins.

FastAPI 0.143 mounts included routers lazily (``app.routes`` holds ``_IncludedRouter`` wrappers), so the routes
are enumerated through ``fastapi.routing.iter_route_contexts``, which yields every effective route with its full
path — the same view the request router uses.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.routing import APIRoute, iter_route_contexts

from app.core.http.authz_decl import KINDS
from app.platform.authz.catalogue_data import PERMISSIONS as CATALOGUE
from app.registry import get_registry

API = "/api/v1"
VERBS = {"list", "get", "create", "update", "delete", "archive", "transition", "export", "run", "issue", "post",
         "decide", "resolve", "upload", "download", "poll"}
#: api-conventions §1 documented path exceptions (owner module differs from the first path segment)
PATH_EXCEPTIONS = {"health": "system", "session": "ui", "webhooks": "channels", "_test": "test",
                   # Slice 3 agents runtime: draft receipts (Undo) and the trace view live at the top level
                   "receipts": "agents", "traces": "agents",
                   # Slice 3 WhatsApp: the review-link resolver
                   "review-links": "channels"}

#: the platform lane's routes: (method, path) -> (kind, permission keys)
PLATFORM_MATRIX: dict[tuple[str, str], tuple[str, tuple[str, ...]]] = {
    ("GET", f"{API}/org/settings"): ("permission", ("org.settings.read",)),
    ("GET", f"{API}/org/settings/{{key}}"): ("permission", ("org.settings.read",)),
    ("PUT", f"{API}/org/settings/{{key}}"): (
        "permission",
        ("agents.ai_routing.manage", "finance.configuration.manage", "identity.mfa.manage", "org.bank_account.update",
         "org.company.update", "org.settings.manage", "sales.quote_settings.manage"),
    ),
    ("GET", f"{API}/org/settings/{{key}}/revisions"): ("permission", ("org.settings.read",)),
    ("GET", f"{API}/org/currencies"): ("authenticated", ()),
    ("GET", f"{API}/org/uoms"): ("authenticated", ()),
    ("GET", f"{API}/org/calendar/me"): ("permission", ("org.calendar.read",)),
    ("POST", f"{API}/files"): ("permission", ("files.file.create",)),
    ("GET", f"{API}/files/{{file_id}}/content"): ("authenticated", ()),
    ("GET", f"{API}/collab/notes"): ("authenticated", ()),
    ("PUT", f"{API}/collab/notes"): ("authenticated", ()),
    ("GET", f"{API}/search"): ("permission", ("search.global.use",)),
    ("GET", f"{API}/search/recent"): ("permission", ("search.global.use",)),
    ("POST", f"{API}/search/recent"): ("permission", ("search.global.use",)),
    ("DELETE", f"{API}/search/recent"): ("permission", ("search.global.use",)),
    ("GET", f"{API}/audit"): ("permission", ("audit.log.read",)),
    ("GET", f"{API}/system/integrations"): ("permission", ("system.integration.read",)),
    # platform-2 (Slice 2)
    ("GET", f"{API}/collab/attachments"): ("authenticated", ()),
    ("POST", f"{API}/collab/attachments"): ("authenticated", ()),
    ("PATCH", f"{API}/collab/attachments/{{attachment_id}}"): ("authenticated", ()),
    ("DELETE", f"{API}/collab/attachments/{{attachment_id}}"): ("authenticated", ()),
    ("GET", f"{API}/collab/activity"): ("permission", ("collab.activity.read",)),
    ("GET", f"{API}/identity/users"): ("permission", ("identity.user.manage", "identity.user.read")),
    ("GET", f"{API}/identity/users/{{user_id}}"): ("permission", ("identity.user.manage", "identity.user.read")),
    ("PATCH", f"{API}/identity/users/{{user_id}}"): ("permission", ("identity.user.manage",)),
    ("PUT", f"{API}/identity/users/{{user_id}}/roles"): ("permission", ("identity.role.manage",)),
    ("POST", f"{API}/identity/users/{{user_id}}/deactivation"): ("permission", ("identity.user.manage",)),
    ("POST", f"{API}/identity/users/{{user_id}}/reactivation"): ("permission", ("identity.user.manage",)),
    ("POST", f"{API}/identity/users/{{user_id}}/password-reset"): ("permission", ("identity.user.manage",)),
    ("DELETE", f"{API}/identity/users/{{user_id}}/mfa"): ("permission", ("identity.mfa.manage",)),
    ("GET", f"{API}/identity/roles"): ("permission", ("identity.role.manage", "identity.role.read")),
    ("POST", f"{API}/identity/roles"): ("permission", ("identity.role.manage",)),
    ("PATCH", f"{API}/identity/roles/{{role_id}}"): ("permission", ("identity.role.manage",)),
    ("POST", f"{API}/identity/roles/{{role_id}}/archive"): ("permission", ("identity.role.manage",)),
    ("GET", f"{API}/identity/access/effective"): ("permission", ("identity.role.manage", "identity.role.read", "identity.user.read")),
    ("POST", f"{API}/identity/invitations"): ("permission", ("identity.user.manage",)),
    ("POST", f"{API}/identity/invitations/preview"): ("public", ()),
    ("POST", f"{API}/identity/invitations/acceptance"): ("public", ()),
    ("POST", f"{API}/identity/password-resets"): ("public", ()),
    ("POST", f"{API}/identity/password-resets/completion"): ("public", ()),
    ("POST", f"{API}/identity/session/verification"): ("public", ()),
    ("POST", f"{API}/identity/session/reauthentication"): ("authenticated", ()),
    ("POST", f"{API}/identity/me/mfa/totp"): ("authenticated", ()),
    ("POST", f"{API}/identity/delegations"): ("authenticated", ()),
    ("POST", f"{API}/identity/absences"): ("authenticated", ()),
    ("POST", f"{API}/identity/access-requests/{{request_id}}/decision"): ("permission", ("identity.access_request.approve",)),
    ("GET", f"{API}/health/live"): ("public", ()),
    ("GET", f"{API}/health/ready"): ("public", ()),
}


@pytest.fixture(scope="module")
def routes() -> list[tuple[str, str, APIRoute, Any]]:
    from app.main import create_app

    out: list[tuple[str, str, APIRoute, Any]] = []
    for ctx in iter_route_contexts(create_app().routes):
        route = ctx.original_route
        if not isinstance(route, APIRoute) or not str(ctx.path).startswith("/api/"):
            continue
        for method in sorted(ctx.methods or ()):
            out.append((method, str(ctx.path), route, ctx))
    return out


def _decl(route: APIRoute) -> dict[str, Any] | None:
    decl = (route.openapi_extra or {}).get("x-authz")
    return decl if isinstance(decl, dict) else None


def _iter_permission_routes(routes: list[tuple[str, str, APIRoute, Any]]) -> Iterator[tuple[str, list[str]]]:
    for method, path, route, _ctx in routes:
        decl = _decl(route)
        if decl and decl.get("kind") == "permission":
            yield f"{method} {path}", list(decl.get("permissions", []))


def test_routes_are_discovered(routes) -> None:  # type: ignore[no-untyped-def]
    paths = {(m, p) for m, p, _r, _c in routes}
    assert set(PLATFORM_MATRIX) <= paths


def test_every_api_route_declares_exactly_one_known_kind(routes) -> None:  # type: ignore[no-untyped-def]
    missing = [f"{m} {p}" for m, p, route, _ in routes if (_decl(route) or {}).get("kind") not in KINDS]
    assert missing == []


def test_permission_routes_name_catalogue_keys(routes) -> None:  # type: ignore[no-untyped-def]
    catalogue = {row["key"] for row in CATALOGUE}
    registry = set(get_registry().permissions)
    problems = []
    for where, keys in _iter_permission_routes(routes):
        if not keys:
            problems.append(f"{where}: permission kind without keys")
        problems += [f"{where}: {k} not in the catalogue" for k in keys if k not in catalogue or k not in registry]
    assert problems == []


def test_public_routes_give_a_reason(routes) -> None:  # type: ignore[no-untyped-def]
    for method, path, route, _ in routes:
        decl = _decl(route) or {}
        if decl.get("kind") == "public":
            assert decl.get("reason"), f"{method} {path}"


def test_platform_lane_matrix(routes) -> None:  # type: ignore[no-untyped-def]
    actual = {(m, p): _decl(r) for m, p, r, _ in routes if (m, p) in PLATFORM_MATRIX}
    for key, (kind, perms) in PLATFORM_MATRIX.items():
        decl = actual[key]
        assert decl is not None and decl["kind"] == kind, key
        assert tuple(sorted(decl.get("permissions", []))) == tuple(sorted(perms)), key


def test_setting_routes_cover_every_registered_definition(routes) -> None:  # type: ignore[no-untyped-def]
    from app.platform.org.service import setting_defs

    put = next(r for m, p, r, _ in routes if (m, p) == ("PUT", f"{API}/org/settings/{{key}}"))
    get = next(r for m, p, r, _ in routes if (m, p) == ("GET", f"{API}/org/settings/{{key}}"))
    defs = setting_defs().values()
    assert {d.manage_permission for d in defs} <= set(_decl(put)["permissions"])  # type: ignore[index]
    assert {d.read_permission for d in defs} <= set(_decl(get)["permissions"])  # type: ignore[index]


def test_operation_ids_follow_module_verb_noun() -> None:
    """Effective operationIds (explicit or generated from tag + function name) in the OpenAPI document:
    ``<module>_<verb>_<noun>`` whose module is the path's owning module and the operation's tag."""
    from app.main import create_app

    pattern = re.compile(r"^(?P<module>[a-z]+)_(?P<verb>[a-z]+)_(?P<noun>[a-z][a-z_]*)$")
    problems = []
    for path, item in create_app().openapi()["paths"].items():
        if not path.startswith(f"{API}/") or path.startswith(f"{API}/_test"):
            continue
        segment = path.removeprefix(f"{API}/").split("/", 1)[0]
        owner = PATH_EXCEPTIONS.get(segment, segment)
        for method, op in item.items():
            op_id = op.get("operationId", "")
            match = pattern.match(op_id)
            if match is None:
                problems.append(f"{method} {path}: operationId {op_id!r}")
                continue
            # the closed verb list is enforced here for the platform lane's routes; other lanes' deviations are
            # reported in docs/lanes/platform.md (e.g. approvals_withdraw_proposal)
            if (method.upper(), path) in PLATFORM_MATRIX and match["verb"] not in VERBS:
                problems.append(f"{method} {path}: verb {match['verb']!r}")
            if match["module"] != owner or op.get("tags", [owner])[0] != owner:
                problems.append(f"{method} {path}: module {match['module']!r} / tags {op.get('tags')} != {owner!r}")
    assert problems == []
