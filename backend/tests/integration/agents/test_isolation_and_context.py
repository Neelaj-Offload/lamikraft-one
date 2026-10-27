"""Own-scope isolation (Neha cannot read Meera's conversation or run: 404), the screen context as a hint
(records re-read, unauthorised refs dropped without a leak, size and item limits -> 422), ordinals, and the
grammar commands."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import select

from app.modules.agents.models import ObjectContext, Run
from app.modules.agents.schemas import MAX_CONTEXT_BYTES
from app.platform.uow import UnitOfWork
from app.seed.world import keys
from tests.integration.agents.conftest import API, Assistant, cards_of, tool_calls
from tests.integration.catalogue.world import World

pytestmark = pytest.mark.db


def _item(ordinal: int, resource_type: str, resource_id: Any, list_key: str = "parties", version: int | None = None) -> dict[str, Any]:
    """A visible item; ``version`` stays unknown unless a test asserts staleness (seeded parties have moved on)."""
    return {"ref": f"i{ordinal}", "list_key": list_key, "ordinal": ordinal, "type": resource_type, "id": str(resource_id), "version": version}


# ---- own scope -----------------------------------------------------------------------------------------------
def test_own_scope_isolation_between_sales_users(client: Any, meera: Assistant) -> None:
    response = meera.post_turn("go to quotes")
    run_id = response.json()["run_id"]
    neha = {"x-test-persona": keys.USERS.NEHA}
    assert client.get(f"{API}/agents/conversations/{meera.conversation_id}", headers=neha).status_code == 404
    assert client.get(f"{API}/agents/runs/{run_id}", headers=neha).status_code == 404
    assert client.post(f"{API}/agents/runs/{run_id}/cancel", headers=neha).status_code == 404
    assert client.post(f"{API}/agents/conversations/{meera.conversation_id}/turns", json={"text": "hi"}, headers=neha).status_code == 404
    sahil = {"x-test-persona": keys.USERS.SAHIL}  # management: company scope elsewhere, still not another user's chat
    assert client.get(f"{API}/agents/conversations/{meera.conversation_id}", headers=sahil).status_code == 404
    assert client.get(f"{API}/agents/conversations/{meera.conversation_id}", headers=meera.headers).status_code == 200


def test_unknown_conversation_and_run_are_404(client: Any, meera: Assistant) -> None:
    assert client.get(f"{API}/agents/conversations/{uuid.uuid7()}", headers=meera.headers).status_code == 404
    assert client.get(f"{API}/agents/runs/{uuid.uuid7()}", headers=meera.headers).status_code == 404
    assert client.post(f"{API}/agents/conversations/{uuid.uuid7()}/turns", json={"text": "hi"}, headers=meera.headers).status_code == 404


# ---- screen context -------------------------------------------------------------------------------------------
def test_context_is_hint_and_records_are_reread(meera: Assistant, world: World) -> None:
    nordhaus, maison = world.ref("NORDHAUS"), world.ref("MAISON")
    context = {
        "schema_version": 1,
        "route": {"path": "/sales/parties", "area": "sales"},
        "records": [{"type": "parties.party", "id": str(nordhaus), "version": 99, "role": "primary"}],
        "visible_items": [_item(1, "parties.party", nordhaus), _item(2, "parties.party", maison),
                          _item(3, "orders.sales_order", uuid.uuid7(), "orders")],
        "draft": {"form_key": "party_header", "dirty_fields": ["remarks"], "values": {"remarks": "secret draft text"}},
    }
    detail = meera.say("open the second item", context=context)
    assert detail["run"]["status"] == "succeeded"
    card = cards_of(detail, "record_link")[0]
    assert card["resource_id"] == str(maison) and card["path"] == f"/sales/parties/{maison}" and card["ordinal"] == 2
    assert keys.PARTY_NAMES["MAISON"] in card["label"]
    with UnitOfWork(world.actor(keys.USERS.MEERA)) as uow:
        run = uow.session.get(Run, uuid.UUID(detail["run"]["id"]))
        rows = list(uow.session.scalars(select(ObjectContext).where(ObjectContext.run_id == run.id)))
        assert {r.resource_type for r in rows} == {"parties.party"}, "unknown types are dropped"
        assert {(str(r.resource_id), r.origin) for r in rows} == {(str(nordhaus), "screen"), (str(maison), "screen")}
        assert all(r.version is not None and r.version >= 1 for r in rows), "versions come from the re-read record, not the client"
    conversation = meera.conversation()
    stored = conversation["turns"][0]
    assert "secret draft text" not in str(stored), "draft values are never persisted from context"


def test_unauthorised_refs_dropped_without_leak(client: Any, sales_tools: Any, world: World) -> None:
    neha = Assistant(client, keys.USERS.NEHA)
    nordhaus, thornbury = world.ref("NORDHAUS"), world.ref("THORNBURY")  # Nordhaus is Meera's, Thornbury is Neha's
    context = {"schema_version": 1, "visible_items": [_item(1, "parties.party", nordhaus), _item(2, "parties.party", thornbury)]}
    detail = neha.say("open the first item", context=context)
    assert detail["run"]["status"] == "failed" and detail["run"]["error_code"] == "no_list_in_context", detail
    error = cards_of(detail, "error")[0]
    assert str(nordhaus) not in str(detail) and keys.PARTY_NAMES["NORDHAUS"] not in str(detail)
    assert error["code"] == "no_list_in_context"
    with UnitOfWork(world.actor(keys.USERS.NEHA)) as uow:
        run = uow.session.get(Run, uuid.UUID(detail["run"]["id"]))
        rows = list(uow.session.scalars(select(ObjectContext).where(ObjectContext.run_id == run.id)))
        assert [str(r.resource_id) for r in rows] == [str(thornbury)]
    second = neha.say("open the second item", context=context)
    assert cards_of(second, "record_link")[0]["resource_id"] == str(thornbury)


def test_changed_list_asks_instead_of_guessing(meera: Assistant, world: World) -> None:
    nordhaus, maison = world.ref("NORDHAUS"), world.ref("MAISON")
    stale = {"schema_version": 1, "visible_items": [_item(1, "parties.party", nordhaus), _item(2, "parties.party", maison, version=7)]}
    detail = meera.say("open the second item", context=stale)
    card = cards_of(detail, "clarification")[0]
    assert card["slot"] == "item" and [o["action"]["value"] for o in card["options"]] == [str(nordhaus), str(maison)]


def test_context_limits_are_422(meera: Assistant, world: World) -> None:
    nordhaus = world.ref("NORDHAUS")
    too_many = {"schema_version": 1, "visible_items": [_item(i, "parties.party", nordhaus) for i in range(1, 52)]}
    response = meera.post_turn("open the first item", context=too_many)
    assert response.status_code == 422 and response.json()["code"] == "validation_failed"
    too_big = {"schema_version": 1, "filters": {"note": "x" * (MAX_CONTEXT_BYTES + 1)}}
    response = meera.post_turn("open the first item", context=too_big)
    assert response.status_code == 422
    assert meera.post_turn("x" * 4001).status_code == 422
    assert meera.post_turn("").status_code == 422


def test_ordinal_falls_back_to_the_last_presented_list(client: Any, meera: Assistant, world: World) -> None:
    from app.modules.parties import service as parties
    from app.modules.parties.schemas import PartyCreate

    with UnitOfWork(world.actor(keys.USERS.MEERA)) as uow:
        other = parties.create_party(uow, PartyCreate(
            legal_name="Nordhaus Logistik AG", display_name="Nordhaus Logistik AG", country_code="CH", default_currency="EUR",
            customer_type="standard", roles=["customer"], owner_user_id=world.user_id(keys.USERS.MEERA),  # type: ignore[arg-type]
        )).id
    first = meera.say("Prepare Nordhaus's usual oak tray quote")
    assert cards_of(first, "clarification")
    second = meera.say("open the second item")
    card = cards_of(second, "record_link")[0]
    assert card["resource_id"] == str(other) and card["ordinal"] == 2


# ---- grammar commands ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("text", "kind", "card_kind", "path"),
    [
        ("go to quotes", "navigate", "record_link", "/sales/quotes"),
        ("inbox par jao", "navigate", "record_link", "/inbox"),
        ("what should I handle today?", "today_overview", "record_link", "/today"),
        ("aaj kya karna hai", "today_overview", "record_link", "/today"),
        ("stop", "stop", None, None),
        ("ruko", "stop", None, None),
        ("help", "help", None, None),
    ],
)
def test_deterministic_commands_need_no_model(meera: Assistant, world: World, text: str, kind: str, card_kind: str | None, path: str | None) -> None:
    detail = meera.say(text)
    assert detail["run"]["status"] == "succeeded" and detail["steps"][0]["output"]["kind"] == kind
    assert detail["run"]["model_route"] == "grammar" and tool_calls(detail) == []
    if card_kind:
        assert cards_of(detail, card_kind)[0]["path"] == path
    else:
        assert detail["cards"] == []
    with UnitOfWork(world.actor(keys.USERS.MEERA)) as uow:
        from app.modules.agents.models import AiCallLog

        assert uow.session.scalar(select(AiCallLog).where(AiCallLog.run_id == uuid.UUID(detail["run"]["id"]))) is None


def test_snooze_without_briefings_is_a_named_missing_capability(meera: Assistant) -> None:
    detail = meera.say("snooze this until tomorrow")
    assert detail["run"]["status"] == "failed" and cards_of(detail, "error")[0]["code"] == "capability_not_installed"
