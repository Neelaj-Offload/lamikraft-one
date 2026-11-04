"""Typed settings: defaults, versioned writes, revisions, events, audit, permissions and restricted fields."""

from __future__ import annotations

import json
import uuid
from datetime import timedelta

import pytest

from app.core.errors import Forbidden, NotFound, ValidationFailed, VersionConflict
from app.platform.authz.permissions import Scope
from app.platform.org import service
from app.platform.org.settings import DEFAULT_BRANDS, QuoteDefaults
from app.platform.org.stepup import ReauthRequired
from app.platform.uow import UnitOfWork
from app.seed.world import keys
from tests.integration.org.platform_lane import (
    ApiClient,
    audit_rows,
    events,
    grants,
    member,
    problem,
    without,
)

pytestmark = pytest.mark.db

ACCOUNT_NUMBER = "50200012345678"
BANK_VALUE = {
    "accounts": [
        {
            "label": "Export collections",
            "bank_name": "Demo Bank",
            "account_number": ACCOUNT_NUMBER,
            "ifsc": "DEMO0001234",
            "currency": "EUR",
            "is_default": True,
        }
    ]
}


@pytest.fixture
def people(company):  # type: ignore[no-untyped-def]
    company_id, _branch = company
    return {
        "priya": member(company_id, keys.PEOPLE["PRIYA"].name, "admin"),
        "meera": member(company_id, keys.PEOPLE["MEERA"].name, "sales"),
        "ananya": member(company_id, keys.PEOPLE["ANANYA"].name, "finance"),
    }


def _put(api: ApiClient, key: str, value: dict, version: int, **extra):  # type: ignore[no-untyped-def]
    return api.put(f"/api/v1/org/settings/{key}", json={"value": value, "expected_version": version, **extra})


# ---- defaults ------------------------------------------------------------------------------------------
def test_every_member_sees_defaults_with_not_configured_fields(api: ApiClient, people, company) -> None:  # type: ignore[no-untyped-def]
    r = api.as_(people["meera"].actor()).get("/api/v1/org/settings")
    assert r.status_code == 200, r.text
    by_key = {s["key"]: s for s in r.json()}
    assert set(by_key) >= {"company_identity", "bank_details", "document_terms", "quote_defaults", "brands"}
    identity = by_key["company_identity"]
    assert identity["version"] == 0 and identity["configured"] is False
    assert identity["value"]["legal_name"].endswith("Pvt. Ltd.")  # from the company row, never invented
    assert {"gstin", "pan", "iec", "address_lines", "logo_file_id", "contacts.email"} <= set(
        identity["not_configured_fields"]
    )
    assert identity["capabilities"]["update"] == {"allowed": False, "reason_code": "permission_denied"}
    assert by_key["bank_details"]["value"] == {"accounts": []}
    assert "accounts" in by_key["bank_details"]["not_configured_fields"]


def test_quote_defaults_and_brands_match_the_fixture_world(api: ApiClient, people) -> None:  # type: ignore[no-untyped-def]
    api.as_(people["meera"].actor())
    defaults = api.get("/api/v1/org/settings/quote_defaults").json()["value"]
    # the unconfigured value is the definition's default (fixtures.md §6); keys.py has no QUOTE_DEFAULTS, so
    # only the keyed parts of the defaults are pinned to keys.py
    assert defaults == QuoteDefaults().model_dump(mode="json")
    assert defaults["brand"] == keys.BRANDS.LK and defaults["currency"] in keys.CURRENCIES
    brands = api.get("/api/v1/org/settings/brands").json()["value"]["brands"]
    assert [b["token"] for b in brands] == [keys.BRANDS.LK, keys.BRANDS.CR]
    assert [(b["token"], b["name"]) for b in brands] == list(DEFAULT_BRANDS) == list(keys.BRAND_NAMES.items())


def test_effective_value_is_typed_for_other_modules(people) -> None:  # type: ignore[no-untyped-def]
    value = service.effective_value(people["meera"].actor(), "quote_defaults")
    assert isinstance(value, QuoteDefaults) and value.validity_days == 30


# ---- versioned writes --------------------------------------------------------------------------------------
def test_update_creates_revision_event_and_audit(api: ApiClient, people, company) -> None:  # type: ignore[no-untyped-def]
    company_id, _ = company
    api.as_(people["priya"].actor())
    r = _put(api, "document_terms", {"quote": "Prices ex-works.", "footer": "Demo"}, 0, change_reason="first terms")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["version"] == 1 and body["configured"] is True
    assert body["value"] == {"quote": "Prices ex-works.", "challan": None, "invoice": None, "footer": "Demo"}
    assert body["not_configured_fields"] == ["challan", "invoice"]
    assert body["capabilities"]["update"]["allowed"] is True

    r2 = _put(api, "document_terms", {"quote": "Prices FOB.", "footer": "Demo"}, 1)
    assert r2.status_code == 200 and r2.json()["version"] == 2

    revisions = api.get("/api/v1/org/settings/document_terms/revisions").json()
    assert [rev["version"] for rev in revisions] == [2, 1]
    assert revisions[1]["change_reason"] == "first terms"
    assert revisions[0]["changed_by"] == str(people["priya"].user_id)

    emitted = events(company_id, "org.setting.updated")
    assert [e.payload for e in emitted] == [
        {"setting_key": "document_terms", "branch_id": None, "version": 1, "origin": "user"},
        {"setting_key": "document_terms", "branch_id": None, "version": 2, "origin": "user"},
    ]
    audited = audit_rows(company_id, "org.setting.updated")
    assert len(audited) == 2
    assert audited[0].changes == {"changed_fields": ["footer", "quote"]}
    assert audited[1].changes == {"changed_fields": ["quote"]}


def test_stale_version_returns_409_with_the_current_setting(api: ApiClient, people) -> None:  # type: ignore[no-untyped-def]
    api.as_(people["priya"].actor())
    assert _put(api, "document_terms", {"quote": "A"}, 0).status_code == 200
    r = _put(api, "document_terms", {"quote": "B"}, 0)
    assert r.status_code == 409
    body = problem(r)
    assert body["code"] == "version_conflict"
    assert body["current_version"] == 1
    assert body["current"]["value"]["quote"] == "A"
    assert body["changed_by"] == str(people["priya"].user_id)


def test_unchanged_value_writes_no_new_version(people, company) -> None:  # type: ignore[no-untyped-def]
    company_id, _ = company
    actor = people["priya"].actor()
    first = service.update_setting(actor, "document_terms", value={"quote": "Same"}, expected_version=0)
    again = service.update_setting(actor, "document_terms", value={"quote": " Same "}, expected_version=1)
    assert first.version == again.version == 1
    assert len(events(company_id, "org.setting.updated")) == 1


def test_validation_errors_are_422_without_echoing_values(api: ApiClient, people) -> None:  # type: ignore[no-untyped-def]
    api.as_(people["priya"].actor())
    r = _put(api, "company_identity", {"gstin": "NOT-A-GSTIN", "pan": "ABCDE1234F"}, 0)
    assert r.status_code == 422
    body = problem(r)
    assert body["code"] == "validation_failed"
    assert any(e["loc"][-1] == "gstin" for e in body["errors"])
    assert "NOT-A-GSTIN" not in r.text
    r = _put(api, "company_identity", {"unknown_field": "x"}, 0)
    assert r.status_code == 422


def test_company_identity_round_trip(api: ApiClient, people) -> None:  # type: ignore[no-untyped-def]
    api.as_(people["priya"].actor())
    value = {
        "legal_name": keys.COMPANY_LEGAL_NAME,
        "display_name": keys.COMPANY_DISPLAY_NAME,
        "address_lines": ["Plot 12, Demo Industrial Estate", "  ", "Pune 411001"],
        "gstin": "27aapcc1234d1zv",
        "contacts": {"email": "office@demo.lamikraft.test"},
    }
    r = _put(api, "company_identity", value, 0)
    assert r.status_code == 200, r.text
    stored = r.json()["value"]
    assert stored["address_lines"] == ["Plot 12, Demo Industrial Estate", "Pune 411001"]
    assert stored["gstin"] == "27AAPCC1234D1ZV"
    assert "pan" in r.json()["not_configured_fields"] and "gstin" not in r.json()["not_configured_fields"]


def test_logo_must_be_a_readable_company_file(api: ApiClient, people) -> None:  # type: ignore[no-untyped-def]
    api.as_(people["priya"].actor())
    r = _put(api, "company_identity", {"logo_file_id": str(uuid.uuid7())}, 0)
    assert r.status_code == 422
    assert problem(r)["errors"][0]["code"] == "file_not_found"


def test_company_scoped_setting_rejects_a_branch(api: ApiClient, people, company) -> None:  # type: ignore[no-untyped-def]
    _, branch_id = company
    api.as_(people["priya"].actor())
    r = _put(api, "document_terms", {"quote": "x"}, 0, branch_id=str(branch_id))
    assert r.status_code == 422
    assert problem(r)["errors"][0]["code"] == "branch_not_allowed"


# ---- permissions ---------------------------------------------------------------------------------------------
def test_member_without_manage_right_gets_403(api: ApiClient, people) -> None:  # type: ignore[no-untyped-def]
    r = _put(api.as_(people["meera"].actor()), "document_terms", {"quote": "x"}, 0)
    assert r.status_code == 403
    assert problem(r)["code"] == "permission_denied"


def test_unknown_setting_is_404(api: ApiClient, people) -> None:  # type: ignore[no-untyped-def]
    api.as_(people["priya"].actor())
    assert api.get("/api/v1/org/settings/not_a_setting").status_code == 404
    assert _put(api, "not_a_setting", {}, 0).status_code == 404


def test_reading_settings_needs_the_read_permission(api: ApiClient, company) -> None:  # type: ignore[no-untyped-def]
    company_id, _ = company
    outsider = member(company_id, "No Settings", extra={"search.global.use": Scope.COMPANY})
    assert api.as_(outsider.actor()).get("/api/v1/org/settings").status_code == 403


def test_signed_out_requests_are_401(api: ApiClient) -> None:
    r = api.as_(None).get("/api/v1/org/settings")
    assert r.status_code == 401 and problem(r)["code"] == "unauthenticated"


def test_recent_authentication_is_required_for_ra_permissions(api: ApiClient, people, frozen_clock) -> None:  # type: ignore[no-untyped-def]
    stale = people["priya"].actor(recent_auth_at=frozen_clock.now() - timedelta(minutes=11))
    r = _put(api.as_(stale), "document_terms", {"quote": "x"}, 0)
    assert r.status_code == 401 and problem(r)["code"] == "reauth_required"
    with pytest.raises(ReauthRequired):
        service.update_setting(people["priya"].actor(recent_auth=False), "brands", value={}, expected_version=0)
    fresh = people["priya"].actor(recent_auth_at=frozen_clock.now() - timedelta(minutes=9))
    assert _put(api.as_(fresh), "document_terms", {"quote": "x"}, 0).status_code == 200


# ---- cross-setting validation ----------------------------------------------------------------------------------
def test_default_brand_must_be_a_configured_brand(api: ApiClient, people) -> None:  # type: ignore[no-untyped-def]
    api.as_(people["priya"].actor())
    defaults = {"currency": "EUR", "incoterm": "FOB", "validity_days": 30, "brand": "XX", "price_type": "export"}
    r = _put(api, "quote_defaults", defaults, 0)
    assert r.status_code == 422 and problem(r)["errors"][0]["code"] == "unknown_brand"
    r = _put(api, "brands", {"brands": [{"token": keys.BRANDS.CR, "name": "Crown"}]}, 0)
    assert r.status_code == 422 and problem(r)["errors"][0]["code"] == "brand_in_use"
    r = _put(api, "brands", {"brands": [{"token": "LK", "name": "Lamikraft"}, {"token": "LK", "name": "Dup"}]}, 0)
    assert r.status_code == 422
    defaults["brand"] = keys.BRANDS.CR
    defaults["validity_days"] = 45
    assert _put(api, "quote_defaults", defaults, 0).status_code == 200
    assert _put(api, "brands", {"brands": [{"token": keys.BRANDS.CR, "name": "Crown"}]}, 0).status_code == 200


def test_validity_days_must_be_positive(people) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValidationFailed):
        service.update_setting(
            people["priya"].actor(), "quote_defaults", value={"validity_days": 0}, expected_version=0
        )


# ---- restricted sub-fields (bank account numbers) -------------------------------------------------------------
def test_bank_account_numbers_are_redacted_without_the_guard(api: ApiClient, people, company) -> None:  # type: ignore[no-untyped-def]
    company_id, _ = company
    r = _put(api.as_(people["priya"].actor()), "bank_details", BANK_VALUE, 0)
    assert r.status_code == 200, r.text
    assert r.json()["value"]["accounts"][0]["account_number"] == ACCOUNT_NUMBER

    seen_by_sales = api.as_(people["meera"].actor()).get("/api/v1/org/settings/bank_details")
    body = seen_by_sales.json()
    account = body["value"]["accounts"][0]
    assert account["account_number"] is None
    assert account["account_number_last4"] == ACCOUNT_NUMBER[-4:]
    assert body["redacted_fields"] == ["accounts[0].account_number"]
    assert ACCOUNT_NUMBER not in seen_by_sales.text
    revisions = api.get("/api/v1/org/settings/bank_details/revisions")
    assert ACCOUNT_NUMBER not in revisions.text
    listed = api.get("/api/v1/org/settings")
    assert ACCOUNT_NUMBER not in listed.text

    seen_by_finance = api.as_(people["ananya"].actor()).get("/api/v1/org/settings/bank_details")
    assert seen_by_finance.json()["value"]["accounts"][0]["account_number"] == ACCOUNT_NUMBER
    assert seen_by_finance.json()["redacted_fields"] == []
    # sensitive guard (S flag): an unmasked read is audited; the audit stores names, never the number
    reads = audit_rows(company_id, "org.setting.restricted_read")
    assert reads and reads[-1].actor_user_id == people["ananya"].user_id
    assert reads[-1].restricted_fields == ["accounts[].account_number"]

    # the write left no number in the outbox or the audit log
    assert ACCOUNT_NUMBER not in json.dumps([e.payload for e in events(company_id, "org.setting.updated")])
    written = audit_rows(company_id, "org.setting.updated")[-1]
    assert written.restricted_fields == ["accounts[].account_number"]
    assert ACCOUNT_NUMBER not in json.dumps([written.changes, written.details])


def test_writing_restricted_values_needs_their_guard(people, company) -> None:  # type: ignore[no-untyped-def]
    company_id, _ = company
    updater_only = member(
        company_id, "Updater", "employee", extra={"org.bank_account.update": Scope.COMPANY}
    ).actor()
    with pytest.raises(Forbidden) as exc:
        service.update_setting(updater_only, "bank_details", value=BANK_VALUE, expected_version=0)
    assert exc.value.extra["permission"] == "org.bank_account.read"
    caps = service.get_setting(updater_only, "bank_details").capabilities["update"]
    assert caps.allowed is False and caps.reason_code == "restricted_fields_not_readable"


def test_last4_is_derived_and_never_trusted_from_input(people) -> None:  # type: ignore[no-untyped-def]
    value = {"accounts": [{**BANK_VALUE["accounts"][0], "account_number_last4": "0000"}]}
    out = service.update_setting(people["priya"].actor(), "bank_details", value=value, expected_version=0)
    assert out.value["accounts"][0]["account_number_last4"] == ACCOUNT_NUMBER[-4:]


# ---- idempotency ---------------------------------------------------------------------------------------------------
def test_idempotency_key_replays_and_rechecks_rights(api: ApiClient, people, company) -> None:  # type: ignore[no-untyped-def]
    company_id, _ = company
    key = str(uuid.uuid7())
    api.as_(people["priya"].actor())
    first = api.put(
        "/api/v1/org/settings/document_terms",
        json={"value": {"quote": "Once"}, "expected_version": 0},
        headers={"Idempotency-Key": key},
    )
    assert first.status_code == 200, first.text
    replay = api.put(
        "/api/v1/org/settings/document_terms",
        json={"value": {"quote": "Once"}, "expected_version": 0},
        headers={"Idempotency-Key": key},
    )
    assert replay.status_code == 200 and replay.json()["version"] == 1
    assert len(events(company_id, "org.setting.updated")) == 1
    reused = api.put(
        "/api/v1/org/settings/document_terms",
        json={"value": {"quote": "Different"}, "expected_version": 0},
        headers={"Idempotency-Key": key},
    )
    assert reused.status_code == 422 and problem(reused)["code"] == "idempotency_key_reused"
    demoted = people["priya"].actor(permissions=without(grants("admin"), "org.settings.manage"))
    lost = api.as_(demoted).put(
        "/api/v1/org/settings/document_terms",
        json={"value": {"quote": "Once"}, "expected_version": 0},
        headers={"Idempotency-Key": key},
    )
    assert lost.status_code == 403


def test_service_errors_are_typed(people) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(NotFound):
        service.get_setting(people["meera"].actor(), "nope")
    actor = people["priya"].actor()
    service.update_setting(actor, "document_terms", value={"quote": "1"}, expected_version=0)
    with pytest.raises(VersionConflict):
        service.update_setting(actor, "document_terms", value={"quote": "2"}, expected_version=0)
    with UnitOfWork(actor) as uow:
        assert service.stored_or_default(uow, "document_terms").quote == "1"  # type: ignore[attr-defined]
