"""SourceReaders behind the onboarding completion checks (tasks ``completion.CHECK_SOURCES``):
``identity.membership``, ``identity.user_preference``, ``ui.recent_record`` and ``search.recent``, plus
``POST /api/v1/ui/recent-records`` that feeds ``ui.recent_record``. Each reader returns facts for the seeded
world and answers None to an actor who may not see them."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.modules.ui import recents
from app.modules.ui.schemas import RecentRecordCreate
from app.platform import sources
from app.platform.authz.context import ActorContext
from app.platform.identity import service as identity
from app.platform.identity.actors import actor_for
from app.platform.identity.models import Membership
from app.platform.identity.preferences import PreferencesPatch
from app.platform.search import service as search
from app.platform.uow import UnitOfWork
from app.seed.context import SeedContext
from app.seed.world import keys
from tests.integration.identity.fixtures import csrf_headers, test_sign_in

pytestmark = pytest.mark.db

RECENT = "/api/v1/ui/recent-records"


def _actor(world: SeedContext, person: str) -> ActorContext:
    actor = actor_for(world.company_id, world.refs[person], "test")
    assert actor is not None
    return actor


def _read(actor: ActorContext, source_type: str, source_id: uuid.UUID) -> sources.SourceFacts | None:
    with UnitOfWork(actor) as uow:
        return sources.read(uow, source_type, source_id)


def _membership_id(world: SeedContext, person: str) -> uuid.UUID:
    with UnitOfWork(ActorContext.system(world.company_id)) as uow:
        found = uow.session.scalar(select(Membership.id).where(Membership.user_id == world.refs[person]))
    assert found is not None
    return found


def test_every_onboarding_source_has_a_registered_reader(world: SeedContext) -> None:
    from app.modules.tasks.completion import CHECK_SOURCES, verifiable

    for check in ("pref_briefing_saved", "recent_record_exists", "recent_search_exists"):
        assert sources.has_reader(CHECK_SOURCES[check]) and verifiable(check)
    assert sources.has_reader("identity.membership")


def test_membership_reader_gives_role_templates_to_the_system_and_self_only(world: SeedContext) -> None:
    arjun_membership = _membership_id(world, keys.USERS.ARJUN)
    system = _read(ActorContext.system(world.company_id), "identity.membership", arjun_membership)
    assert system is not None
    assert system.facts["role_templates"] == [keys.PEOPLE[keys.USERS.ARJUN].role_template]
    assert system.label == keys.PEOPLE[keys.USERS.ARJUN].name and system.owner_user_id == world.refs[keys.USERS.ARJUN]
    own = _read(_actor(world, keys.USERS.ARJUN), "identity.membership", arjun_membership)
    assert own is not None and own.facts["role_templates"] == ["sales"]
    # a colleague sees the directory facts (org.directory.read) but not the member's access
    colleague = _read(_actor(world, keys.USERS.KABIR), "identity.membership", arjun_membership)
    assert colleague is not None and colleague.label == keys.PEOPLE[keys.USERS.ARJUN].name
    assert "role_templates" not in colleague.facts
    assert _read(_actor(world, keys.USERS.KABIR), "identity.membership", uuid.uuid7()) is None


def test_preference_reader_reports_saved_briefing_preferences_to_the_user_only(world: SeedContext) -> None:
    meera = _actor(world, keys.USERS.MEERA)
    meera_id = world.refs[keys.USERS.MEERA]
    before = _read(meera, "identity.user_preference", meera_id)
    assert before is not None and before.facts["briefing_saved"] is False
    identity.update_preferences(meera, PreferencesPatch(expected_version=0, briefing={"detail_level": "brief"}))
    after = _read(meera, "identity.user_preference", meera_id)
    assert after is not None and after.facts["briefing_saved"] is True and after.version == 1
    system = _read(ActorContext.system(world.company_id), "identity.user_preference", meera_id)
    assert system is not None and system.facts["briefing_saved"] is True
    assert _read(_actor(world, keys.USERS.SAHIL), "identity.user_preference", meera_id) is None  # her manager too


def test_recent_search_reader_counts_the_users_searches(world: SeedContext) -> None:
    neha = _actor(world, keys.USERS.NEHA)
    neha_id = world.refs[keys.USERS.NEHA]
    first = _read(neha, "search.recent", neha_id)
    assert first is not None and first.facts["count"] == 0
    search.record_recent(neha, "oak tray")
    second = _read(neha, "search.recent", neha_id)
    assert second is not None and second.facts["count"] == 1
    assert _read(_actor(world, keys.USERS.MEERA), "search.recent", neha_id) is None


def test_recent_records_over_http_feed_the_reader(client: TestClient, world: SeedContext) -> None:
    test_sign_in(client, keys.USERS.ARJUN)
    arjun_id = world.refs[keys.USERS.ARJUN]
    product_id = world.refs["OAK_TRAY"]
    assert _read(_actor(world, keys.USERS.ARJUN), "ui.recent_record", arjun_id).facts["count"] == 0  # type: ignore[union-attr]
    body = {"resource_type": "catalogue.product", "resource_id": str(product_id)}
    r = client.post(RECENT, json=body, headers=csrf_headers(client))
    assert r.status_code == 201, r.text
    assert r.json()["resource_id"] == str(product_id)
    again = client.post(RECENT, json=body, headers=csrf_headers(client))  # a repeat moves it to the top
    assert again.status_code == 201
    facts = _read(_actor(world, keys.USERS.ARJUN), "ui.recent_record", arjun_id)
    assert facts is not None and facts.facts == {"count": 1, "by_type": {"catalogue.product": 1}}
    assert _read(_actor(world, keys.USERS.MEERA), "ui.recent_record", arjun_id) is None
    system = _read(ActorContext.system(world.company_id), "ui.recent_record", arjun_id)
    assert system is not None and system.facts["count"] == 1


def test_recent_records_never_confirm_invisible_or_unknown_records(client: TestClient, world: SeedContext) -> None:
    test_sign_in(client, keys.USERS.MEERA)
    unknown = client.post(
        RECENT, json={"resource_type": "catalogue.product", "resource_id": str(uuid.uuid7())}, headers=csrf_headers(client)
    )
    assert unknown.status_code == 404
    # Neha's customer Thornbury is outside Meera's own scope: same answer as a record that does not exist
    hidden = client.post(
        RECENT,
        json={"resource_type": "parties.party", "resource_id": str(world.refs["THORNBURY"])},
        headers=csrf_headers(client),
    )
    assert hidden.status_code == 404
    unsupported = client.post(
        RECENT, json={"resource_type": "nothing.here", "resource_id": str(uuid.uuid7())}, headers=csrf_headers(client)
    )
    assert unsupported.status_code == 422
    assert client.post(RECENT, json={"resource_type": "catalogue.product", "resource_id": str(uuid.uuid7())}).status_code == 403


def test_recent_records_keep_only_the_newest(world: SeedContext, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(recents, "RECENT_KEEP", 2)
    meera = _actor(world, keys.USERS.MEERA)
    for product in ("OAK_TRAY", "MAPLE_TRIVET", "ASH_BOARD"):
        recents.record_recent_record(meera, RecentRecordCreate(resource_type="catalogue.product", resource_id=world.refs[product]))
    facts = _read(meera, "ui.recent_record", world.refs[keys.USERS.MEERA])
    assert facts is not None and facts.facts["count"] == 2
