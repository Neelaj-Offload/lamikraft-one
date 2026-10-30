"""Saved plans (LM-71, LM-78, LP-09.6, SCN-H3, UI-76): save, reopen without recomputing, stale inputs, optimistic
versions, duplicate (inputs only), exports (CSV formula-escaped, PDF, SVG at true scale), archive, the oversize
verification flow and the job path for large inputs."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.modules.cutting.models import Calculation
from app.platform.authz.context import ActorContext
from app.platform.events.models import DomainEvent
from app.platform.uow import UnitOfWork
from app.seed.world import keys
from tests.integration.cutting.helpers import API, CUT_LIST, calculate, create_plan, item, problem
from tests.integration.sales.world import SalesWorld
from tests.support import drain


def _events(world: SalesWorld, name: str) -> list[dict[str, Any]]:
    with UnitOfWork(ActorContext.system(world.company_id)) as uow:
        return [
            e.payload
            for e in uow.session.scalars(
                select(DomainEvent).where(DomainEvent.company_id == world.company_id, DomainEvent.event_type == name)
            )
        ]


def test_save_reopen_preserves_inputs_and_results(client: TestClient, world: SalesWorld) -> None:
    plan = create_plan(client)
    assert plan["plan_number"] == "CUT-2026-0001" and plan["status"] == "draft"
    assert plan["settings"]["board_length_mm"] == "2440" and plan["settings"]["gap_mm"] == "6"
    assert [i["sku"] for i in plan["items"]] == [i["sku"] for i in CUT_LIST]
    assert plan["latest_calculation"] is None and plan["capabilities"]["export"]["allowed"] is False
    calculated = calculate(client, plan)
    calc = calculated["latest_calculation"]
    assert calculated["status"] == "calculated" and not calculated["stale"]
    assert calc["calc_no"] == 1 and calc["origin"] == "sync" and calc["note"] == "Heuristic layout, not guaranteed optimal"
    totals = calc["totals"]
    assert totals["required"] == 13 and totals["placed_required"] == 13 and totals["unfit"] == 0
    assert totals["boards"] >= 2  # two decors are two groups

    reopened = client.get(f"{API}/plans/{plan['id']}").json()
    assert reopened["latest_calculation"] == calc  # stored result, not recomputed
    assert reopened["items"] == calculated["items"] and reopened["settings"] == calculated["settings"]
    with UnitOfWork(ActorContext.system(world.company_id)) as uow:
        assert uow.session.scalar(select(func.count(Calculation.id)).where(Calculation.plan_id == plan["id"])) == 1
    assert _events(world, "cutting.plan.calculated")[0]["calc_no"] == 1
    assert {e["plan_number"] for e in _events(world, "cutting.plan.saved")} == {"CUT-2026-0001"}

    by_number = client.get(f"{API}/plans/{plan['id']}/calculations/1").json()
    assert by_number["result_hash"] == calc["result_hash"]


def test_edit_marks_stale_and_stale_version_is_409(client: TestClient) -> None:
    plan = calculate(client, create_plan(client))
    edited = client.patch(
        f"{API}/plans/{plan['id']}",
        json={"expected_version": plan["version"], "items": [*CUT_LIST, item("PANEL-C", "300", "300", 2)]},
    )
    assert edited.status_code == 200, edited.text
    body = edited.json()
    assert body["stale"] is True and body["version"] > plan["version"]
    assert body["latest_calculation"]["calc_no"] == 1  # the old result stays visible until recalculated
    problem(client.patch(f"{API}/plans/{plan['id']}", json={"expected_version": plan["version"], "name": "x"}), 409, "version_conflict")
    again = calculate(client, body)
    assert again["stale"] is False and again["latest_calculation"]["calc_no"] == 2
    assert [c["calc_no"] for c in again["calculations"]] == [2, 1]


def test_duplicate_copies_inputs_and_exports_escape_formulas(client: TestClient) -> None:
    plan = calculate(client, create_plan(client, settings={"gap_mm": "4", "mode": "guillotine"}))
    dup = client.post(f"{API}/plans/{plan['id']}/duplicate", headers={"Idempotency-Key": "dup-1"})
    assert dup.status_code == 201, dup.text
    copy = dup.json()
    assert copy["plan_number"] == "CUT-2026-0002" and copy["status"] == "draft"
    assert copy["duplicated_from"] == plan["plan_number"] and copy["latest_calculation"] is None
    strip = ("id",)
    assert [{k: v for k, v in i.items() if k not in strip} for i in copy["items"]] == [
        {k: v for k, v in i.items() if k not in strip} for i in plan["items"]
    ]
    assert copy["settings"] == plan["settings"] and copy["settings"]["mode"] == "guillotine"
    replay = client.post(f"{API}/plans/{plan['id']}/duplicate", headers={"Idempotency-Key": "dup-1"})
    assert replay.json()["id"] == copy["id"] and replay.headers.get("Idempotent-Replayed") == "true"

    csv = client.get(f"{API}/plans/{plan['id']}/export.csv")
    assert csv.status_code == 200 and csv.headers["content-type"].startswith("text/csv")
    text = csv.content.decode("utf-8-sig")
    assert '"\'=HYPERLINK(""x"")"' in text and "=HYPERLINK" not in text.replace("'=HYPERLINK", "")
    lines = text.strip().split("\r\n")
    assert len(lines) == 1 + plan["latest_calculation"]["totals"]["produced"]
    summary = client.get(f"{API}/plans/{plan['id']}/export.csv", params={"kind": "summary"}).content.decode("utf-8-sig")
    assert len(summary.strip().split("\r\n")) == 1 + len(CUT_LIST)
    pdf = client.get(f"{API}/plans/{plan['id']}/export.pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    board = plan["latest_calculation"]["groups"][0]["boards"][0]
    svg = client.get(board["svg_path"])
    assert svg.status_code == 200 and svg.headers["content-type"].startswith("image/svg+xml")
    assert f'viewBox="0 0 {board["raw_length_mm"]} {board["raw_width_mm"]}"' in svg.text
    assert svg.text.count("<rect") >= 2 + len(board["placements"])
    problem(client.get(f"{API}/plans/{copy['id']}/export.csv"), 403, "plan_not_calculated")
    problem(client.get(f"{API}/plans/{plan['id']}/calculations/1/boards/999.svg"), 404, "not_found")


def test_oversize_and_overproduction_have_effects(client: TestClient, world: SalesWorld) -> None:
    piece = [item("WIDE", "2435", "1215", 1)]
    plain = calculate(client, create_plan(client, items=piece))
    assert plain["latest_calculation"]["totals"]["unfit"] == 1
    assert plain["latest_calculation"]["groups"][0]["items"][0]["unfit_reason"] == "exceeds_usable_board"
    over = calculate(client, create_plan(client, items=piece, settings={"oversize_enabled": True}))
    assert over["latest_calculation"]["totals"]["placed_required"] == 1
    assert over["verification"] == {**over["verification"], "required": True, "verified": False,
                                     "assumed_length_mm": "2460", "assumed_width_mm": "1240"}
    assert over["capabilities"]["verify"]["allowed"] is True
    assert [t["action"] for t in over["allowed_transitions"]] == ["verify_boards", "archive"]
    assert _events(world, "cutting.plan.verification_required") == [{"plan_id": over["id"], "origin": "user"}]

    small = client.post(f"{API}/plans/{over['id']}/verify-boards",
                        json={"expected_version": over["version"], "measured_length_mm": "2455", "measured_width_mm": "1240"})
    assert small.status_code == 200, small.text
    assert small.json()["verification"]["verified"] is False and small.json()["stale"] is True
    ok = client.post(f"{API}/plans/{over['id']}/verify-boards",
                     json={"expected_version": small.json()["version"], "measured_length_mm": "2461", "measured_width_mm": "1240.5"})
    assert ok.json()["verification"]["verified"] is True and ok.json()["verification"]["verified_by"]["id"]
    assert len(_events(world, "cutting.plan.verified")) == 1
    problem(client.post(f"{API}/plans/{over['id']}/verify-boards",
                        json={"expected_version": ok.json()["version"], "measured_length_mm": "2461", "measured_width_mm": "1241"}),
            409, "verification_not_required")

    extra_off = calculate(client, create_plan(client, items=[item("TILE", "600", "400", 10)]))
    extra_on = calculate(client, create_plan(client, items=[item("TILE", "600", "400", 10)],
                                             settings={"overproduction_enabled": True, "max_extra_qty": 3, "max_extra_pct": "20"}))
    off_item = extra_off["latest_calculation"]["groups"][0]["items"][0]
    on_item = extra_on["latest_calculation"]["groups"][0]["items"][0]
    assert off_item["extra"] == 0 and 0 < on_item["extra"] <= 2  # min(3, floor(10 x 20 %))
    assert on_item["produced"] == on_item["placed_required"] + on_item["extra"]
    assert extra_on["latest_calculation"]["totals"]["boards"] == extra_off["latest_calculation"]["totals"]["boards"]


def test_archive_makes_the_plan_read_only(client: TestClient) -> None:
    plan = calculate(client, create_plan(client))
    archived = client.post(f"{API}/plans/{plan['id']}/transitions", json={"action": "archive", "expected_version": plan["version"]})
    assert archived.status_code == 200 and archived.json()["status"] == "archived"
    body = archived.json()
    assert body["capabilities"]["update"] == {"allowed": False, "reason_code": "plan_archived"}
    assert body["allowed_transitions"] == []
    problem(client.patch(f"{API}/plans/{plan['id']}", json={"expected_version": body["version"], "name": "x"}), 403, "plan_archived")
    listed = client.get(f"{API}/plans").json()
    assert plan["id"] not in [p["id"] for p in listed["items"]]
    assert plan["id"] in [p["id"] for p in client.get(f"{API}/plans", params={"include_archived": True}).json()["items"]]
    assert client.get(f"{API}/plans/{plan['id']}/export.csv").status_code == 200  # archived plans stay exportable


def test_large_plan_calculates_as_a_job(client: TestClient, world: SalesWorld) -> None:
    big = [item(f"P-{n}", str(200 + 10 * n), str(150 + 5 * n), 40) for n in range(1, 10)]  # 360 pieces > 300
    plan = create_plan(client, items=big)
    queued = calculate(client, plan)
    assert queued["calculation"]["status"] == "queued" and queued["latest_calculation"] is None
    assert queued["calculation"]["pieces"] == 360 and queued["calculation"]["sync_piece_limit"] == 300
    again = calculate(client, queued)  # a second request while queued changes nothing
    assert again["calculation"]["status"] == "queued"
    assert drain() >= 1
    done = client.get(f"{API}/plans/{plan['id']}").json()
    assert done["calculation"]["status"] == "idle" and done["latest_calculation"]["origin"] == "job"
    assert done["latest_calculation"]["totals"]["placed_required"] == 360


def test_too_large_and_empty_inputs_are_clear_errors(client: TestClient) -> None:
    body = problem(
        client.post(f"{API}/plans", json={"name": "Huge", "items": [item("X", "100", "100", 5000), item("Y", "100", "100", 1)]}),
        422, "validation_failed",
    )
    assert body["errors"][0]["code"] == "cutting_input_too_large"
    empty = create_plan(client, items=[])
    problem(client.post(f"{API}/plans/{empty['id']}/calculate", json={"expected_version": empty["version"]}), 422, "plan_has_no_items")
    bad = problem(client.post(f"{API}/plans", json={"name": "x", "items": [item("Z", "12.25", "100", 1)]}), 422, "validation_failed")
    assert "decimal place" in str(bad)
    zero = problem(client.post(f"{API}/plans", json={"name": "x", "items": [item("Z", "0", "100", 1)]}), 422, "validation_failed")
    assert zero["errors"]


def test_budget_exceeded_is_a_clear_error(client: TestClient, monkeypatch: Any) -> None:
    from app.modules.cutting import plans

    real = plans._pack_settings

    def tiny_budget(*args: Any, **kwargs: Any) -> Any:
        s = real(*args, **kwargs)
        return s.__class__(**{**s.__dict__, "work_budget": 10})

    monkeypatch.setattr(plans, "_pack_settings", tiny_budget)
    plan = create_plan(client)
    body = problem(client.post(f"{API}/plans/{plan['id']}/calculate", json={"expected_version": plan["version"]}), 422,
                   "cutting_budget_exceeded")
    assert body["budget"] == 10
    assert client.get(f"{API}/plans/{plan['id']}").json()["latest_calculation"] is None


def test_plan_list_filters_before_paging(client: TestClient) -> None:
    create_plan(client, name="Walnut doors")
    create_plan(client, name="Oak shelves")
    create_plan(client, persona=keys.USERS.MEERA, name="Meera samples")
    page = client.get(f"{API}/plans", params={"q": "walnut", "limit": 1}).json()
    assert page["total"] == 1 and page["items"][0]["name"] == "Walnut doors"
    assert page["items"][0]["piece_count"] == 13 and page["items"][0]["item_count"] == 3
    mine = client.get(f"{API}/plans", params={"scope": "mine"}).json()
    assert {p["name"] for p in mine["items"]} == {"Walnut doors", "Oak shelves"}
    drafts = client.get(f"{API}/plans", params={"status": "calculated"}).json()
    assert drafts["total"] == 0
