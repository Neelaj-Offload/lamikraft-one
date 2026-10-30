"""Record scope for cut plans (PERM-23, SEC-03): the optimiser is no longer open to any login. Sales see their own
plans, operations their branch, management everything read-only; an invisible plan is a 404 on every child path
(calculations, exports, SVG); visible-but-forbidden is a 403."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.seed.world import keys
from tests.integration.cutting.helpers import API, as_, calculate, create_plan, problem
from tests.integration.sales.world import SalesWorld


def test_sales_own_scope_and_child_paths_hide_other_plans(client: TestClient, world: SalesWorld) -> None:
    meera = calculate(client, create_plan(client, persona=keys.USERS.MEERA), persona=keys.USERS.MEERA)
    ravi = calculate(client, create_plan(client))
    neha = as_(keys.USERS.NEHA)
    assert client.get(f"{API}/plans", headers=neha).json()["total"] == 0
    for path in (
        f"/plans/{meera['id']}",
        f"/plans/{meera['id']}/calculations/1",
        f"/plans/{meera['id']}/export.csv",
        f"/plans/{meera['id']}/export.pdf",
        f"/plans/{meera['id']}/calculations/1/boards/1.svg",
    ):
        problem(client.get(f"{API}{path}", headers=neha), 404, "not_found")
    problem(client.patch(f"{API}/plans/{meera['id']}", json={"expected_version": meera["version"], "name": "x"}, headers=neha),
            404, "not_found")
    problem(client.post(f"{API}/plans/{meera['id']}/duplicate", headers=neha), 404, "not_found")
    # Meera sees only her own plan; Ravi (operations, branch) sees both; Sahil (management) reads but cannot edit
    assert [p["id"] for p in client.get(f"{API}/plans", headers=as_(keys.USERS.MEERA)).json()["items"]] == [meera["id"]]
    assert {p["id"] for p in client.get(f"{API}/plans").json()["items"]} == {meera["id"], ravi["id"]}
    sahil = as_(keys.USERS.SAHIL)
    detail = client.get(f"{API}/plans/{ravi['id']}", headers=sahil).json()
    assert detail["capabilities"]["update"]["allowed"] is False and detail["capabilities"]["export"]["allowed"] is True
    problem(client.patch(f"{API}/plans/{ravi['id']}", json={"expected_version": ravi["version"], "name": "x"}, headers=sahil),
            403, "permission_denied")
    assert client.get(f"{API}/plans/{ravi['id']}/export.csv", headers=sahil).status_code == 200
    # sales may not archive (no cutting.plan.transition)
    problem(client.post(f"{API}/plans/{meera['id']}/transitions", json={"action": "archive", "expected_version": meera["version"]},
                        headers=as_(keys.USERS.MEERA)), 403, "permission_denied")


def test_restricted_persona_has_no_optimiser(client: TestClient) -> None:
    kabir = as_(keys.USERS.KABIR)
    problem(client.get(f"{API}/plans", headers=kabir), 403, "permission_denied")
    problem(client.post(f"{API}/plans", json={"name": "x", "items": []}, headers=kabir), 403, "permission_denied")
    problem(client.get(f"{API}/settings", headers=kabir), 403, "permission_denied")
    problem(client.get(f"{API}/machine-profiles", headers=kabir), 403, "permission_denied")
