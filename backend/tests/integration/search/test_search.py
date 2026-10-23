"""Global search: provider dispatch by permission, grouping and caps, literal matching, recent searches."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import update

from app.platform.authz.context import ActorContext
from app.platform.authz.permissions import Scope
from app.platform.identity.models import Membership
from app.platform.search import service as search
from app.platform.search.defs import SearchHit, SearchProvider
from app.platform.uow import UnitOfWork
from app.registry import get_registry
from app.seed.world import keys
from tests.integration.org.platform_lane import ApiClient, member, problem
from tests.support import create_company

pytestmark = pytest.mark.db


@pytest.fixture
def directory(company):  # type: ignore[no-untyped-def]
    company_id, _ = company
    people = {
        key: member(company_id, keys.PEOPLE[key].name, "sales", job_title=title, department=dept)
        for key, title, dept in (
            ("MEERA", "Export sales executive", "Export Sales"),
            ("NEHA", "Export sales executive", "Export Sales"),
            ("SAHIL", "Head of export sales", "Export Sales"),
            ("RAVI", "Operations lead", "Operations"),
        )
    }
    return company_id, people


def _groups(body: dict[str, Any]) -> dict[str, list[str]]:
    return {g["group"]: [h["title"] for h in g["hits"]] for g in body["groups"]}


def test_people_are_found_by_name_and_title(api: ApiClient, directory) -> None:  # type: ignore[no-untyped-def]
    company_id, people = directory
    api.as_(people["MEERA"].actor())
    r = api.get("/api/v1/search", params={"q": "meera"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["terms"] == ["meera"]
    group = body["groups"][0]
    assert group["resource_type"] == "org.person" and group["group"] == "People"
    assert group["hits"] == [
        {
            "resource_type": "org.person",
            "resource_id": str(people["MEERA"].user_id),
            "title": keys.PEOPLE["MEERA"].name,
            "subtitle": "Export sales executive · Export Sales",
            "path": f"/people/{people['MEERA'].user_id}",
        }
    ]
    by_title = _groups(api.get("/api/v1/search", params={"q": "operations lead"}).json())
    assert by_title == {"People": [keys.PEOPLE["RAVI"].name]}
    every = _groups(api.get("/api/v1/search", params={"q": "export sales"}).json())["People"]
    assert sorted(every) == sorted(keys.PEOPLE[k].name for k in ("MEERA", "NEHA", "SAHIL"))


def test_contact_details_are_never_searchable(api: ApiClient, directory) -> None:  # type: ignore[no-untyped-def]
    _company, people = directory
    r = api.as_(people["MEERA"].actor()).get("/api/v1/search", params={"q": "example.test"})
    assert r.json()["groups"] == []  # emails live on app_user but are not directory facts


def test_inactive_members_and_other_tenants_are_not_found(api: ApiClient, directory) -> None:  # type: ignore[no-untyped-def]
    company_id, people = directory
    with UnitOfWork(ActorContext.system(company_id)) as uow:
        uow.session.execute(
            update(Membership).where(Membership.user_id == people["NEHA"].user_id).values(status="suspended")
        )
    other, _ = create_company()
    member(other, "Neha Outsider", "employee")
    titles = _groups(api.as_(people["MEERA"].actor()).get("/api/v1/search", params={"q": "neha"}).json())
    assert titles == {}


@pytest.mark.parametrize(
    ("query", "match", "decoy"),
    [
        ("100%", "Ravi 100% Kumar", "Ravi 1000 Kumar"),
        ("a_b", "Kabir a_b Shah", "Kabir axb Shah"),
        ("k\\s", "Back\\slash Rao", "Backxslash Rao"),
        (".*", "Arjun .* Das", "Arjun xy Das"),
        ("[a-z]+", "Priya [a-z]+ Nair", "Priya abc Nair"),
        ("((", "Vikram (( Singh", "Vikram Singh"),
        ("^$|", "Ananya ^$| Rao", "Ananya Rao"),
        ("%_\\", "Odd %_\\ Name", "Odd x Name"),
    ],
)
def test_wildcards_and_regex_metacharacters_are_literal(api: ApiClient, company, query, match, decoy) -> None:  # type: ignore[no-untyped-def]
    company_id, _ = company
    searcher = member(company_id, "Searcher", "employee")
    member(company_id, match, "employee")
    member(company_id, decoy, "employee")
    r = api.as_(searcher.actor()).get("/api/v1/search", params={"q": query, "limit": 20})
    assert r.status_code == 200, r.text
    assert _groups(r.json()).get("People") == [match]


def test_diacritics_match_both_spellings(api: ApiClient, company) -> None:  # type: ignore[no-untyped-def]
    company_id, _ = company
    searcher = member(company_id, "Searcher", "employee")
    member(company_id, "Zoë Fernandes", "employee")
    api.as_(searcher.actor())
    assert _groups(api.get("/api/v1/search", params={"q": "zoë"}).json()) == {"People": ["Zoë Fernandes"]}


def test_short_queries_return_no_groups(api: ApiClient, directory) -> None:  # type: ignore[no-untyped-def]
    _company, people = directory
    body = api.as_(people["MEERA"].actor()).get("/api/v1/search", params={"q": " m "}).json()
    assert body["groups"] == [] and body["terms"] == ["m"]


def test_groups_are_capped_with_has_more(api: ApiClient, company) -> None:  # type: ignore[no-untyped-def]
    company_id, _ = company
    searcher = member(company_id, "Searcher", "employee")
    for i in range(7):
        member(company_id, f"Panel Member {i}", "employee")
    body = api.as_(searcher.actor()).get("/api/v1/search", params={"q": "panel member", "limit": 5}).json()
    group = body["groups"][0]
    assert len(group["hits"]) == 5 and group["has_more"] is True
    assert [h["title"] for h in group["hits"]] == [f"Panel Member {i}" for i in range(5)]
    assert api.get("/api/v1/search", params={"q": "panel", "limit": 21}).status_code == 422


def test_providers_run_only_with_their_read_permission(api: ApiClient, directory) -> None:  # type: ignore[no-untyped-def]
    company_id, _people = directory
    no_directory = member(company_id, "Guest", extra={"search.global.use": Scope.COMPANY})
    body = api.as_(no_directory.actor()).get("/api/v1/search", params={"q": "meera"}).json()
    assert body["groups"] == []
    no_search = member(company_id, "No Search", extra={"org.directory.read": Scope.COMPANY})
    r = api.as_(no_search.actor()).get("/api/v1/search", params={"q": "meera"})
    assert r.status_code == 403 and problem(r)["code"] == "permission_denied"


def test_types_filter_selects_providers(api: ApiClient, directory) -> None:  # type: ignore[no-untyped-def]
    _company, people = directory
    api.as_(people["MEERA"].actor())
    assert api.get("/api/v1/search", params={"q": "meera", "types": "catalogue.product"}).json()["groups"] == []
    assert len(api.get("/api/v1/search", params={"q": "meera", "types": "org.person"}).json()["groups"]) == 1


def test_a_failing_provider_is_reported_unavailable(api: ApiClient, directory, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _company, people = directory

    def broken(_uow: UnitOfWork, _q: str, _limit: int) -> list[SearchHit]:
        raise RuntimeError("index offline")

    def wrong_type(_uow: UnitOfWork, _q: str, _limit: int) -> list[SearchHit]:
        return [SearchHit("sales.quote", uuid.uuid7(), "leak", None, "/x")]

    registry = get_registry()
    extra = [
        SearchProvider("test.broken", "Broken", "org.directory.read", broken),
        SearchProvider("test.mislabelled", "Mislabelled", "org.directory.read", wrong_type),
    ]
    monkeypatch.setattr(registry, "search_providers", [*registry.search_providers, *extra])
    body = api.as_(people["MEERA"].actor()).get("/api/v1/search", params={"q": "meera"}).json()
    assert body["unavailable_groups"] == ["Broken", "Mislabelled"]
    assert _groups(body) == {"People": [keys.PEOPLE["MEERA"].name]}


@settings(
    max_examples=25, deadline=None, derandomize=True,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
@given(fragment=st.text(alphabet=st.characters(min_codepoint=33, max_codepoint=126), min_size=2, max_size=8))
def test_every_hit_contains_the_literal_query(company, fragment: str) -> None:  # type: ignore[no-untyped-def]
    company_id, _ = company
    searcher = ActorContext(
        actor_type="user", company_id=company_id, user_id=uuid.uuid7(),
        permissions={"search.global.use": Scope.COMPANY, "org.directory.read": Scope.COMPANY},
    )
    name = f"Hx{fragment}Hy"
    created = member(company_id, name, "employee")
    results = search.search(searcher, f"x{fragment}h", limit=20)
    hits = [h for g in results.groups for h in g.hits]
    assert created.user_id in {h.resource_id for h in hits}
    needle = f"x{fragment}h".casefold()
    assert all(needle in h.title.casefold() for h in hits)


# ---- recent searches ---------------------------------------------------------------------------------------------
def test_recent_searches_are_kept_per_user_newest_first(api: ApiClient, directory, frozen_clock) -> None:  # type: ignore[no-untyped-def]
    _company, people = directory
    api.as_(people["MEERA"].actor())
    assert api.get("/api/v1/search/recent").json() == []
    first = api.post("/api/v1/search/recent", json={"query": "  Oak   tray "})
    assert first.status_code == 201 and first.json()["query"] == "Oak tray"
    frozen_clock.advance(seconds=5)
    api.post("/api/v1/search/recent", json={"query": "Nordhaus"})
    frozen_clock.advance(seconds=5)
    again = api.post("/api/v1/search/recent", json={"query": "oak TRAY"})  # a repeat moves to the top
    assert again.json()["id"] == first.json()["id"]
    recent = api.get("/api/v1/search/recent").json()
    assert [r["query"] for r in recent] == ["oak TRAY", "Nordhaus"]
    assert recent[0]["searched_at"] == (keys.CLOCK_D0 + timedelta(seconds=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    # another user's history is separate
    api.as_(people["NEHA"].actor())
    assert api.get("/api/v1/search/recent").json() == []
    api.post("/api/v1/search/recent", json={"query": "Thornbury"})
    api.as_(people["MEERA"].actor())
    assert [r["query"] for r in api.get("/api/v1/search/recent").json()] == ["oak TRAY", "Nordhaus"]


def test_only_the_newest_ten_are_kept(api: ApiClient, directory, frozen_clock) -> None:  # type: ignore[no-untyped-def]
    _company, people = directory
    api.as_(people["MEERA"].actor())
    for i in range(12):
        frozen_clock.advance(seconds=1)
        assert api.post("/api/v1/search/recent", json={"query": f"query {i}"}).status_code == 201
    recent = [r["query"] for r in api.get("/api/v1/search/recent").json()]
    assert recent == [f"query {i}" for i in range(11, 1, -1)]


def test_clearing_recent_searches_only_touches_my_own(api: ApiClient, directory) -> None:  # type: ignore[no-untyped-def]
    company_id, people = directory
    api.as_(people["NEHA"].actor()).post("/api/v1/search/recent", json={"query": "Thornbury"})
    api.as_(people["MEERA"].actor()).post("/api/v1/search/recent", json={"query": "Berg"})
    with UnitOfWork(people["MEERA"].actor()) as uow:
        assert search.has_recent_search(uow, people["MEERA"].user_id) is True
    r = api.delete("/api/v1/search/recent")
    assert r.status_code == 204
    assert api.get("/api/v1/search/recent").json() == []
    assert len(api.as_(people["NEHA"].actor()).get("/api/v1/search/recent").json()) == 1


def test_recent_search_validation(api: ApiClient, directory) -> None:  # type: ignore[no-untyped-def]
    _company, people = directory
    api.as_(people["MEERA"].actor())
    assert api.post("/api/v1/search/recent", json={"query": "   "}).status_code == 422
    assert api.post("/api/v1/search/recent", json={"query": "x" * 201}).status_code == 422
    assert api.post("/api/v1/search/recent", json={}).status_code == 422
