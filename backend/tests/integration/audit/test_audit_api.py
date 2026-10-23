"""Audit read API: audit.log.read only, filters before the page limit, stable keyset pagination."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import pytest

from app.platform.audit import query as audit_query
from app.platform.authz.context import ActorContext
from app.platform.uow import UnitOfWork
from app.seed.world import keys
from tests.integration.org.platform_lane import ApiClient, audit_rows, member, problem
from tests.support import create_company

pytestmark = pytest.mark.db
URL = "/api/v1/audit"


def _record(actor: ActorContext, action: str, **fields: Any) -> None:
    with UnitOfWork(actor) as uow:
        uow.audit(action, **fields)


@pytest.fixture
def log(company, frozen_clock):  # type: ignore[no-untyped-def]
    company_id, _ = company
    priya = member(company_id, keys.PEOPLE["PRIYA"].name, "admin")
    meera = member(company_id, keys.PEOPLE["MEERA"].name, "sales")
    quote_id = uuid.uuid7()
    _record(meera.actor(), "sales.quote.created", resource_type="sales.quote", resource_id=quote_id)
    frozen_clock.advance(minutes=1)
    _record(meera.actor(), "sales.quote.status_changed", resource_type="sales.quote", resource_id=quote_id,
            reason="sent to customer")
    _record(priya.actor(), "org.setting.updated", resource_type="org.setting", resource_label="document_terms")
    frozen_clock.advance(minutes=1)
    _record(priya.actor(), "identity.login.failed", outcome="failed")
    _record(priya.actor(), "files.100%_export", resource_type="files.file")
    return {"company_id": company_id, "priya": priya, "meera": meera, "quote_id": quote_id}


def _actions(body: dict[str, Any]) -> list[str]:
    return [e["action"] for e in body["items"]]


def test_entries_are_newest_first_with_actor_names(api: ApiClient, log) -> None:  # type: ignore[no-untyped-def]
    r = api.as_(log["priya"].actor()).get(URL)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["next_cursor"] is None and body["limit"] == 50
    assert _actions(body)[-1] == "sales.quote.created"
    newest_first = [e["occurred_at"] for e in body["items"]]
    assert newest_first == sorted(newest_first, reverse=True)
    created = body["items"][-1]
    assert created["actor_name"] == keys.PEOPLE["MEERA"].name
    assert created["resource_id"] == str(log["quote_id"]) and created["outcome"] == "success"


def test_keyset_pages_never_skip_or_repeat(api: ApiClient, log, frozen_clock) -> None:  # type: ignore[no-untyped-def]
    api.as_(log["priya"].actor())
    everything = [e["id"] for e in api.get(URL).json()["items"]]
    seen: list[dict[str, Any]] = []
    cursor = None
    while True:
        params = {"limit": 2} | ({"cursor": cursor} if cursor else {})
        page = api.get(URL, params=params).json()
        seen += page["items"]
        # new activity while paging (including the audited reads themselves) never shifts later pages
        frozen_clock.advance(seconds=1)
        _record(log["meera"].actor(), "sales.quote.viewed")
        cursor = page["next_cursor"]
        if cursor is None:
            break
    # the first page starts with the audit entry of the read that produced ``everything``
    assert seen[0]["action"] == "audit.log.read"
    assert [e["id"] for e in seen[1:]] == everything
    assert len({e["id"] for e in seen}) == len(seen)


def test_filters_apply_before_the_limit(api: ApiClient, log, frozen_clock) -> None:  # type: ignore[no-untyped-def]
    api.as_(log["priya"].actor())
    assert _actions(api.get(URL, params={"action": "org.setting.updated"}).json()) == ["org.setting.updated"]
    assert _actions(api.get(URL, params={"action_prefix": "sales.quote.", "limit": 1}).json()) == [
        "sales.quote.status_changed"
    ]
    assert _actions(api.get(URL, params={"action_prefix": "files.100%"}).json()) == ["files.100%_export"]
    assert api.get(URL, params={"action_prefix": "files.1000"}).json()["items"] == []  # % is literal
    mine = api.get(URL, params={"actor_user_id": str(log["meera"].user_id)}).json()
    assert set(_actions(mine)) == {"sales.quote.created", "sales.quote.status_changed"}
    by_record = api.get(URL, params={"resource_type": "sales.quote", "resource_id": str(log["quote_id"])}).json()
    assert len(by_record["items"]) == 2
    assert _actions(api.get(URL, params={"outcome": "failed"}).json()) == ["identity.login.failed"]
    start = (keys.CLOCK_D0 + timedelta(minutes=1)).isoformat()
    end = (keys.CLOCK_D0 + timedelta(minutes=2)).isoformat()
    window = api.get(URL, params={"occurred_from": start, "occurred_to": end}).json()
    assert set(_actions(window)) == {"sales.quote.status_changed", "org.setting.updated"}


def test_invalid_inputs_are_422(api: ApiClient, log) -> None:  # type: ignore[no-untyped-def]
    api.as_(log["priya"].actor())
    r = api.get(URL, params={"cursor": "not-a-cursor"})
    assert r.status_code == 422 and problem(r)["errors"][0]["code"] == "invalid_cursor"
    r = api.get(URL, params={"occurred_from": keys.CLOCK_D0.replace(tzinfo=None).isoformat()})
    assert r.status_code == 422 and problem(r)["errors"][0]["code"] == "naive_datetime"
    assert api.get(URL, params={"outcome": "maybe"}).status_code == 422
    assert api.get(URL, params={"limit": 201}).status_code == 422


def test_cursor_round_trip() -> None:
    at, row_id = keys.CLOCK_D0, uuid.uuid7()
    assert audit_query.decode_cursor(audit_query.encode_cursor(at, row_id)) == (at, row_id)


def test_reading_needs_audit_log_read_and_is_itself_audited(api: ApiClient, log) -> None:  # type: ignore[no-untyped-def]
    r = api.as_(log["meera"].actor()).get(URL)
    assert r.status_code == 403 and problem(r)["code"] == "permission_denied"
    api.as_(log["priya"].actor()).get(URL, params={"action": "org.setting.updated"})
    reads = audit_rows(log["company_id"], "audit.log.read")
    assert len(reads) == 1 and reads[0].actor_user_id == log["priya"].user_id
    assert reads[0].details == {"filters": {"action": "org.setting.updated"}, "rows": 1}


def test_other_tenants_entries_are_invisible(api: ApiClient, log) -> None:  # type: ignore[no-untyped-def]
    other, _ = create_company()
    admin = member(other, "Other Admin", "admin")
    _record(admin.actor(), "org.setting.updated")
    body = api.as_(log["priya"].actor()).get(URL, params={"action": "org.setting.updated"}).json()
    assert len(body["items"]) == 1
    assert body["items"][0]["actor_user_id"] == str(log["priya"].user_id)
