"""Grain locks (LM-74, FG-GRN-01..03, API-53..56, UI-74) and company settings / machine profiles (LM-72): writes
need the manage keys, keys are canonical decors, every change is audited, and plans and the packer honour them."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.platform.audit.models import AuditLog
from app.platform.authz.context import ActorContext
from app.platform.uow import UnitOfWork
from app.seed.world import keys
from tests.integration.cutting.helpers import API, as_, calculate, create_plan, item, problem
from tests.integration.sales.world import SalesWorld

ADMIN = keys.USERS.PRIYA


def _audit(world: SalesWorld, prefix: str) -> list[AuditLog]:
    with UnitOfWork(ActorContext.system(world.company_id)) as uow:
        return list(
            uow.session.scalars(
                select(AuditLog).where(AuditLog.company_id == world.company_id, AuditLog.action.startswith(prefix))
                .order_by(AuditLog.occurred_at, AuditLog.id)
            )
        )


def test_grain_lock_writes_require_manage_and_canonical_key(client: TestClient, world: SalesWorld) -> None:
    # reading is open to every cutting user; writing needs cutting.grain_lock.manage (legacy: admin only)
    assert client.get(f"{API}/grain-locks", headers=as_(keys.USERS.MEERA)).json() == {"items": [], "can_manage": False, "warnings": []}
    problem(client.post(f"{API}/grain-locks", json={"decor": "120"}, headers=as_(keys.USERS.RAVI)), 403, "permission_denied")
    problem(client.get(f"{API}/grain-locks", headers=as_(keys.USERS.KABIR)), 403, "permission_denied")

    added = client.post(f"{API}/grain-locks", json={"decor": " 120.0 ", "label": "Rift oak"}, headers=as_(ADMIN))
    assert added.status_code == 201, added.text
    body = added.json()
    assert [(i["decor_key"], i["decor_source"], i["label"]) for i in body["items"]] == [("120", "120.0", "Rift oak")]
    assert body["warnings"] == ["120.0 was stored as 120"] and body["can_manage"] is True
    assert body["items"][0]["updated_by"]["id"] == str(world.user_id(ADMIN))
    problem(client.post(f"{API}/grain-locks", json={"decor": "120"}, headers=as_(ADMIN)), 409, "grain_lock_exists")
    # '0120' keeps its leading zero: a different decor
    assert client.post(f"{API}/grain-locks", json={"decor": "0120"}, headers=as_(ADMIN)).status_code == 201
    audit = _audit(world, "cutting.grain_lock")
    assert [a.action for a in audit] == ["cutting.grain_lock.added", "cutting.grain_lock.added"]
    assert audit[0].changes == {"decor": {"before": None, "after": "120"}, "label": {"before": None, "after": "Rift oak"}}
    assert audit[0].actor_user_id == world.user_id(ADMIN)

    # the lock on 120 blocks rotation of pieces entered as 120.0; 0120 is locked too, other decors still rotate
    plan = calculate(client, create_plan(client, items=[item("TURN", "1200", "2400", 1, decor="120.0"),
                                                         item("FREE", "1200", "2400", 1, decor="W-7")]))
    results = {i["sku"]: i for g in plan["latest_calculation"]["groups"] for i in g["items"]}
    assert results["TURN"]["unfit_reason"] == "grain_lock_prevents_rotation" and results["TURN"]["rotation_allowed"] is False
    assert results["FREE"]["placed_required"] == 1 and results["FREE"]["rotation_allowed"] is True
    assert plan["latest_calculation"]["grain_locked_decors"] == ["120"]
    assert any("decor 120.0 is 120" in w for w in plan["warnings"])


def test_bulk_replace_and_add_remove(client: TestClient, world: SalesWorld) -> None:
    for decor in ("A1", "B2"):
        client.post(f"{API}/grain-locks", json={"decor": decor}, headers=as_(ADMIN))
    replaced = client.put(f"{API}/grain-locks", json={"locks": [{"decor": "B2", "label": "Teak"}, {"decor": "C3"}]},
                          headers=as_(ADMIN))
    assert replaced.status_code == 200, replaced.text
    assert [(i["decor_key"], i["label"]) for i in replaced.json()["items"]] == [("B2", "Teak"), ("C3", None)]
    last = _audit(world, "cutting.grain_lock.replaced")[-1]
    assert last.changes == {"added": ["C3"], "removed": ["A1"], "relabelled": ["B2"]}
    dup = problem(client.put(f"{API}/grain-locks", json={"locks": [{"decor": "7"}, {"decor": "7.0"}]}, headers=as_(ADMIN)),
                  422, "validation_failed")
    assert dup["errors"][0]["code"] == "duplicate_decor"
    removed = client.delete(f"{API}/grain-locks/C3", headers=as_(ADMIN))
    assert [i["decor_key"] for i in removed.json()["items"]] == ["B2"]
    problem(client.delete(f"{API}/grain-locks/C3", headers=as_(ADMIN)), 404, "not_found")
    problem(client.put(f"{API}/grain-locks", json={"locks": []}, headers=as_(keys.USERS.SAHIL)), 403, "permission_denied")
    assert client.put(f"{API}/grain-locks", json={"locks": []}, headers=as_(ADMIN)).json()["items"] == []


def test_settings_defaults_overrides_and_machine_profiles(client: TestClient, world: SalesWorld) -> None:
    defaults = client.get(f"{API}/settings").json()
    assert (defaults["board_length_mm"], defaults["board_width_mm"], defaults["margin_mm"], defaults["gap_mm"],
            defaults["oversize_mm"], defaults["customised"]) == ("2440", "1220", "5", "6", "10", False)
    problem(client.patch(f"{API}/settings", json={"gap_mm": "4"}), 403, "permission_denied")
    updated = client.patch(f"{API}/settings", json={"gap_mm": "4", "board_length_mm": "2800"}, headers=as_(ADMIN)).json()
    assert (updated["gap_mm"], updated["board_length_mm"], updated["customised"], updated["version"]) == ("4", "2800", True, 1)
    problem(client.patch(f"{API}/settings", json={"expected_version": 0, "gap_mm": "5"}, headers=as_(ADMIN)), 409, "version_conflict")
    problem(client.patch(f"{API}/settings", json={"margin_mm": "700"}, headers=as_(ADMIN)), 422, "validation_failed")
    bad = problem(client.patch(f"{API}/settings", json={"gap_mm": "4.25"}, headers=as_(ADMIN)), 422, "validation_failed")
    assert bad["errors"]

    saw = client.post(f"{API}/machine-profiles", json={"code": "SAW-1", "name": "Panel saw", "mode": "guillotine", "gap_mm": "3.2"},
                      headers=as_(ADMIN))
    assert saw.status_code == 201, saw.text
    problem(client.post(f"{API}/machine-profiles", json={"code": "SAW-1", "name": "Again", "mode": "nested"}, headers=as_(ADMIN)),
            409, "machine_profile_exists")
    # a new plan snapshots the company settings; a machine profile brings its mode and kerf
    plan = create_plan(client, settings={"machine_profile_id": saw.json()["id"]})
    assert (plan["settings"]["board_length_mm"], plan["settings"]["gap_mm"], plan["settings"]["mode"]) == ("2800", "3.2", "guillotine")
    calculated = calculate(client, plan)
    assert all(c["kerf_mm"] == "3.2" for g in calculated["latest_calculation"]["groups"] for b in g["boards"] for c in b["cuts"])
    archived = client.patch(f"{API}/machine-profiles/{saw.json()['id']}", json={"archived": True}, headers=as_(ADMIN)).json()
    assert archived["archived"] is True
    assert client.get(f"{API}/machine-profiles").json() == []
    assert [a.action for a in _audit(world, "cutting.settings")] == ["cutting.settings.updated"]
