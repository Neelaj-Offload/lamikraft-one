"""The migration and backup API over HTTP: route declarations, the run / quarantine / candidate / backup reads, the
candidate decision, MFA step-up, and the IDOR matrix (another company's runs, candidates and parties are invisible;
members without the permission get 403)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.http.deps import get_actor
from app.modules.migration.dry_run import run_dry_run
from app.platform.authz.context import ActorContext
from app.seed.world import keys
from tests.integration.catalogue.world import World, build_personas
from tests.integration.migration.helpers import operator

pytestmark = pytest.mark.db

API = "/api/v1/migration"
ROUTES = {
    ("get", f"{API}/runs"): "migration.run.read",
    ("get", f"{API}/runs/{{run_id}}"): "migration.run.read",
    ("get", f"{API}/runs/{{run_id}}/issues"): "migration.run.read",
    ("get", f"{API}/runs/{{run_id}}/issue-facets"): "migration.run.read",
    ("get", f"{API}/runs/{{run_id}}/issues.csv"): "migration.run.read",
    ("get", f"{API}/party-candidates"): "migration.run.read",
    ("post", f"{API}/party-candidates/{{candidate_id}}/decision"): "migration.party_candidate.update",
    ("get", f"{API}/opening-balance-batches"): "migration.run.read",
    ("get", "/api/v1/system/backups"): "system.backup.read",
}


@pytest.fixture(scope="module")
def app() -> FastAPI:
    from app.main import create_app

    return create_app()


@pytest.fixture
def other(world: World) -> World:
    """A second company with its own admin and customers."""
    from app.seed.world.parties import seed_parties

    second = build_personas()
    seed_parties(second.ctx)
    return second


@pytest.fixture
def client(app: FastAPI, world: World, other: World) -> Iterator[TestClient]:
    def resolve(request: Request) -> ActorContext:
        who = request.headers.get("x-test-as", "admin")
        if who == "other-admin":
            return operator(other)
        if who == "password-only":
            return world.actor(keys.USERS.PRIYA)
        if who == "sales":
            return world.actor(keys.USERS.MEERA).with_(auth_strength="mfa")
        return operator(world)

    app.dependency_overrides[get_actor] = resolve
    try:
        with TestClient(app, headers={"Origin": get_settings().public_origin}) as c:
            yield c
    finally:
        app.dependency_overrides.clear()


def test_routes_declare_their_permission(app: FastAPI) -> None:
    paths = app.openapi()["paths"]
    for (method, path), key in ROUTES.items():
        op = paths[path][method]
        assert op["x-authz"]["permissions"] == [key], (method, path)
        assert op["operationId"].startswith(("migration_", "system_")), op["operationId"]


def test_runs_quarantine_and_candidates_over_http(client: TestClient, world: World, export_dir: Path) -> None:
    run = run_dry_run(operator(world), export_dir)
    page = client.get(f"{API}/runs").json()
    assert page["total"] == 1 and page["items"][0]["id"] == str(run.run_id)
    assert page["items"][0]["path"] == f"/settings/migration/runs/{run.run_id}"
    detail = client.get(f"{API}/runs/{run.run_id}").json()
    assert detail["report"]["reconciled"] is True and detail["report"]["challans"]["stock_movements"] == 0
    quarantine = client.get(f"{API}/runs/{run.run_id}/issues", params={"severity": "quarantine", "entity": "packaging"})
    items = quarantine.json()["items"]
    assert quarantine.status_code == 200 and {i["code"] for i in items} == {"ALIAS_CONFLICT"}
    assert all(i["source_file"] == "packaging.xlsx" and i["row_number"] and i["raw"] for i in items)
    facets = client.get(f"{API}/runs/{run.run_id}/issue-facets").json()
    assert {f["value"] for f in facets["severity"]} == {"error", "quarantine", "warning", "info"}
    csv = client.get(f"{API}/runs/{run.run_id}/issues.csv")
    assert csv.status_code == 200 and csv.headers["content-type"].startswith("text/csv")
    assert "ALIAS_CONFLICT" in csv.content.decode("utf-8")
    candidates = client.get(f"{API}/party-candidates", params={"q": "nordhaus"}).json()["items"]
    nordhaus = next(c for c in candidates if c["country_key"] == "DE")
    assert nordhaus["suggested_party"]["id"] == str(world.ref("NORDHAUS"))
    assert nordhaus["capabilities"]["decide"]["allowed"] is True
    linked = client.post(f"{API}/party-candidates/{nordhaus['id']}/decision",
                         json={"expected_version": nordhaus["version"], "decision": "link",
                               "party_id": nordhaus["suggested_party"]["id"], "note": "same customer"})
    assert linked.status_code == 200, linked.text
    body = linked.json()
    assert body["status"] == "linked" and body["linked_party"]["party_number"] == "P-00001"
    assert body["capabilities"]["decide"] == {"allowed": False, "reason_code": "already_decided"}
    stale = client.post(f"{API}/party-candidates/{nordhaus['id']}/decision",
                        json={"expected_version": nordhaus["version"], "decision": "reject"})
    assert stale.status_code == 409 and stale.json()["code"] == "version_conflict"
    # a rerun keeps the decision
    run_dry_run(operator(world), export_dir)
    again = next(c for c in client.get(f"{API}/party-candidates", params={"status": "linked"}).json()["items"])
    assert again["id"] == nordhaus["id"] and again["linked_party"]["id"] == nordhaus["suggested_party"]["id"]
    assert client.get(f"{API}/opening-balance-batches").json()["total"] == 0
    backups = client.get("/api/v1/system/backups").json()
    assert backups["last_backup"] is None and backups["max_age_hours_for_apply"] == 24


def test_idor_matrix(client: TestClient, world: World, other: World, export_dir: Path) -> None:
    run = run_dry_run(operator(world), export_dir)
    candidate = client.get(f"{API}/party-candidates").json()["items"][0]
    # another company's admin: nothing of this company is visible or decidable
    as_other = {"x-test-as": "other-admin"}
    assert client.get(f"{API}/runs", headers=as_other).json()["total"] == 0
    for path in (f"/runs/{run.run_id}", f"/runs/{run.run_id}/issues", f"/runs/{run.run_id}/issue-facets",
                 f"/runs/{run.run_id}/issues.csv"):
        assert client.get(f"{API}{path}", headers=as_other).status_code == 404, path
    assert client.get(f"{API}/party-candidates", headers=as_other).json()["total"] == 0
    decided = client.post(f"{API}/party-candidates/{candidate['id']}/decision", headers=as_other,
                          json={"expected_version": candidate["version"], "decision": "reject"})
    assert decided.status_code == 404
    # this company's admin cannot link a candidate to another company's party
    foreign_party = other.ref("NORDHAUS")
    refused = client.post(f"{API}/party-candidates/{candidate['id']}/decision",
                          json={"expected_version": candidate["version"], "decision": "link",
                                "party_id": str(foreign_party)})
    assert refused.status_code == 422 and refused.json()["errors"][0]["code"] == "party_not_found"
    missing = client.post(f"{API}/party-candidates/{uuid.uuid4()}/decision",
                          json={"expected_version": 1, "decision": "reject"})
    assert missing.status_code == 404
    # members without the permission: 403 everywhere; an admin without an MFA-verified session: 401 mfa_required
    for method, path in [("get", "/runs"), ("get", f"/runs/{run.run_id}"), ("get", "/party-candidates"),
                         ("get", "/opening-balance-batches")]:
        assert client.request(method, f"{API}{path}", headers={"x-test-as": "sales"}).status_code == 403, path
    assert client.get("/api/v1/system/backups", headers={"x-test-as": "sales"}).status_code == 403
    assert client.post(f"{API}/party-candidates/{candidate['id']}/decision", headers={"x-test-as": "sales"},
                       json={"expected_version": candidate["version"], "decision": "reject"}).status_code == 403
    step_up = client.get(f"{API}/runs", headers={"x-test-as": "password-only"})
    assert step_up.status_code == 401 and step_up.json()["code"] == "mfa_required"
    assert client.get("/api/v1/system/backups", headers={"x-test-as": "password-only"}).json()["code"] == "mfa_required"
