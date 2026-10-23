"""SettingDef contract and the built-in value models (no database)."""

from __future__ import annotations

import json
import uuid

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from app.platform.authz.context import ActorContext
from app.platform.authz.permissions import Scope
from app.platform.authz.redaction import Restricted, redact
from app.platform.org.service import not_configured_fields, setting_defs
from app.platform.org.settings import (
    BANK_GUARD,
    BUILTIN_SETTINGS,
    BankAccount,
    BankDetails,
    Brands,
    CompanyIdentity,
    DocumentTerms,
    QuoteDefaults,
    SettingDef,
    restricted_guards,
)
from app.registry import get_registry
from app.seed.world import keys


def _actor(*perms: str) -> ActorContext:
    return ActorContext(
        actor_type="user",
        company_id=uuid.uuid7(),
        user_id=uuid.uuid7(),
        permissions={p: Scope.COMPANY for p in perms},
    )


def test_builtin_definitions_are_registered_through_the_manifest() -> None:
    keys_ = {d.key for d in get_registry().settings}
    assert {"company_identity", "bank_details", "document_terms", "quote_defaults", "brands"} <= keys_
    defs = setting_defs()
    assert defs["bank_details"].manage_permission == "org.bank_account.update"
    assert defs["company_identity"].manage_permission == "org.company.update"
    assert all(d.scope == "company" for d in BUILTIN_SETTINGS)


def test_definitions_reference_only_catalogue_permissions() -> None:
    perms = set(get_registry().permissions)
    for d in setting_defs().values():
        assert {d.read_permission, d.manage_permission, *d.guard_keys} <= perms


def test_setting_keys_are_snake_case() -> None:
    with pytest.raises(ValueError, match="snake_case"):
        SettingDef(key="Bad-Key", model=DocumentTerms, description="x", read_permission="a", manage_permission="b")


def test_restricted_paths_come_from_the_field_guard_registry() -> None:
    guards = restricted_guards(BankDetails)
    assert guards == {"accounts[].account_number": Restricted(BANK_GUARD, model_exposure="deny")}
    assert setting_defs()["bank_details"].guard_keys == frozenset({BANK_GUARD})
    assert setting_defs()["document_terms"].guard_keys == frozenset()


def test_quote_defaults_follow_the_fixture_world() -> None:
    d = QuoteDefaults()
    assert (d.currency, d.incoterm, d.validity_days, d.brand, d.price_type, d.duplicate_copies_assignee) == (
        "EUR", "FOB", 30, keys.BRANDS.LK, "export", True,
    )
    with pytest.raises(ValidationError):
        QuoteDefaults(currency="JPY")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        QuoteDefaults(validity_days=0)


def test_brands_default_and_uniqueness() -> None:
    assert Brands().tokens() == {keys.BRANDS.LK, keys.BRANDS.CR}
    with pytest.raises(ValidationError):
        Brands.model_validate({"brands": [{"token": "LK", "name": "A"}, {"token": "LK", "name": "B"}]})
    with pytest.raises(ValidationError):
        Brands.model_validate({"brands": []})


def test_company_identity_normalises_codes_and_reports_gaps() -> None:
    value = CompanyIdentity.model_validate(
        {"legal_name": "  Crown Decor  ", "gstin": " 27aapcc1234d1zv ", "pan": "", "contacts": {"email": " "}}
    )
    assert value.legal_name == "Crown Decor" and value.gstin == "27AAPCC1234D1ZV" and value.pan is None
    assert value.contacts.email is None
    missing = not_configured_fields(value)
    assert "gstin" not in missing
    assert {"display_name", "pan", "iec", "address_lines", "logo_file_id", "contacts.email"} <= set(missing)
    for bad in ({"gstin": "27AAPCC1234D1Z"}, {"pan": "ABCDE12345"}, {"iec": "12"}, {"extra": "x"},
                {"contacts": {"website": "ftp://x"}}, {"address_lines": ["x"] * 7}):
        with pytest.raises(ValidationError):
            CompanyIdentity.model_validate(bad)


def test_round_trip_of_a_dumped_value_validates_again() -> None:
    for model in (CompanyIdentity, DocumentTerms, BankDetails, QuoteDefaults, Brands):
        value = model()
        assert model.model_validate(value.model_dump(mode="json")) == value


def test_bank_account_rules() -> None:
    account = BankAccount.model_validate(
        {"label": "Main", "bank_name": "Demo Bank", "account_number": "5020 0012 3456 78", "account_number_last4": "x"}
    )
    assert account.account_number == "50200012345678" and account.account_number_last4 == "5678"
    with pytest.raises(ValidationError):
        BankDetails.model_validate(
            {"accounts": [{"label": "A", "bank_name": "B", "is_default": True},
                          {"label": "C", "bank_name": "D", "is_default": True}]}
        )
    with pytest.raises(ValidationError):
        BankDetails.model_validate({"accounts": [{"label": "A", "bank_name": "B"}, {"label": "a", "bank_name": "C"}]})
    with pytest.raises(ValidationError):
        BankAccount.model_validate({"label": "A", "bank_name": "B", "ifsc": "BAD"})


@settings(max_examples=80, derandomize=True, deadline=None)
@given(number=st.from_regex(r"^[A-Z0-9]{6,34}$", fullmatch=True))
def test_account_numbers_never_reach_actors_without_the_guard(number: str) -> None:
    details = BankDetails.model_validate({"accounts": [{"label": "A", "bank_name": "B", "account_number": number}]})
    hidden = redact(details, _actor("org.settings.read"))
    dumped = json.dumps(hidden.model_dump(mode="json"))
    assert number not in dumped
    assert hidden.accounts[0].account_number_last4 == number[-4:]
    shown = redact(details, _actor("org.settings.read", BANK_GUARD))
    assert shown.accounts[0].account_number == number
    # model exposure is denied even for permitted users
    for_model = redact(details, _actor(BANK_GUARD), for_model=True)
    assert number not in json.dumps(for_model.model_dump(mode="json"))
