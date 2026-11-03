"""The imports API over HTTP: route declarations, upload -> job -> validate -> commit through the real endpoints,
problem codes and the CSV report (UI-86, API-30..33)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.http.deps import get_actor
from app.platform.authz.context import ActorContext
from app.seed.world import keys
from tests.integration.catalogue.world import World
from tests.integration.imports.helpers import admin, csv_bytes
from tests.support import drain

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("media_storage")]

API = "/api/v1/imports"
ROUTES = {
    ("get", "/types"): "imports.job.read",
    ("get", "/types/{import_type}/template.csv"): "imports.job.read",
    ("post", "/jobs"): "imports.job.run",
    ("get", "/jobs"): "imports.job.read",
    ("get", "/jobs/{job_id}"): "imports.job.read",
    ("get", "/jobs/{job_id}/preview"): "imports.job.read",
    ("put", "/jobs/{job_id}/mapping"): "imports.job.run",
    ("post", "/jobs/{job_id}/validate"): "imports.job.run",
    ("get", "/jobs/{job_id}/rows"): "imports.job.read",
    ("get", "/jobs/{job_id}/issues"): "imports.job.read",
    ("get", "/jobs/{job_id}/issues/report.csv"): "imports.job.read",
    ("get", "/jobs/{job_id}/changes"): "imports.job.read",
    ("post", "/jobs/{job_id}/commit"): "imports.job.run",
    ("post", "/jobs/{job_id}/cancel"): "imports.job.run",
    ("post", "/jobs/{job_id}/quarantine/recheck"): "imports.job.run",
    ("get", "/jobs/{job_id}/rollback-plan"): "imports.rollback.execute",
    ("post", "/jobs/{job_id}/rollback"): "imports.rollback.execute",
    ("get", "/demo-reset/preview"): "system.demo_data.delete",
    ("post", "/demo-reset"): "system.demo_data.delete",
}


@pytest.fixture(scope="module")
def app() -> FastAPI:
    from app.main import create_app

    return create_app()


@pytest.fixture
def client(app: FastAPI, world: World) -> Iterator[TestClient]:
    def resolve(request: Request) -> ActorContext:
        persona = request.headers.get("x-test-persona")
        return world.actor(persona) if persona else admin(world)

    app.dependency_overrides[get_actor] = resolve
    try:
        with TestClient(app, headers={"Origin": get_settings().public_origin}) as c:
            yield c
    finally:
        app.dependency_overrides.clear()


def test_routes_declare_their_permission(app: FastAPI) -> None:
    paths = app.openapi()["paths"]
    for (method, path), key in ROUTES.items():
        op = paths[f"{API}{path}"][method]
        assert op["x-authz"]["permissions"] == [key] and op["operationId"].startswith("imports_"), (method, path)


def test_workbench_flow_over_http(client: TestClient, world: World) -> None:
    data = csv_bytes(["lookup_type", "key_1", "value_1"], [["finish", "MT", "Matte"], ["finish", "", "broken"]])
    up = client.post("/api/v1/files", params={"purpose": "import"}, files={"file": ("lookups.csv", data, "text/csv")})
    assert up.status_code == 201, up.text
    created = client.post(f"{API}/jobs", json={"import_type": "lookup_reference", "file_id": up.json()["id"]})
    assert created.status_code == 201, created.text
    job = created.json()
    assert job["status"] == "parsed" and job["row_count"] == 2
    assert client.get(f"{API}/jobs/{job['id']}/preview").json()["total_rows"] == 2
    queued = client.post(f"{API}/jobs/{job['id']}/validate", json={"expected_version": job["version"]})
    assert queued.status_code == 202 and queued.json()["progress"]["state"] == "validating"
    drain()
    job = client.get(f"{API}/jobs/{job['id']}").json()
    assert job["status"] == "validated" and job["counts"]["rejected"] == 1
    refused = client.post(f"{API}/jobs/{job['id']}/commit", json={"expected_version": job["version"]})
    assert refused.status_code == 409 and refused.json()["code"] == "excluded_rows_not_acknowledged"
    stale = client.post(f"{API}/jobs/{job['id']}/commit", json={"expected_version": 1, "acknowledge_excluded": True})
    assert stale.status_code == 409 and stale.json()["code"] == "version_conflict"
    ok = client.post(f"{API}/jobs/{job['id']}/commit",
                     json={"expected_version": job["version"], "acknowledge_excluded": True})
    assert ok.status_code == 202, ok.text
    drain()
    assert client.get(f"{API}/jobs/{job['id']}").json()["status"] == "committed"
    report = client.get(f"{API}/jobs/{job['id']}/issues/report.csv")
    assert report.status_code == 200 and report.headers["content-type"].startswith("text/csv")
    assert '"3","key_1","key_1","REQUIRED"' in report.content.decode("utf-8")
    template = client.get(f"{API}/types/products_master/template.csv").content.decode("utf-8")
    assert template.lstrip("﻿").startswith('"product_key"')
    denied = client.get(f"{API}/jobs/{job['id']}", headers={"x-test-persona": keys.USERS.MEERA})
    assert denied.status_code == 403
    missing = client.get(f"{API}/jobs/00000000-0000-7000-8000-000000000000")
    assert missing.status_code == 404
