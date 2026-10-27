"""Party request validation (no database): roles, countries, currencies, tax identifiers, tool input."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.modules.parties.schemas import (
    PartyCreate,
    PartyRole,
    PartyUpdate,
    ResolvePartyInput,
    TaxIdentifierIn,
)
from app.modules.parties.tools import RESOLVE_PARTY
from app.platform.tools import FORBIDDEN_INPUT_FIELDS
from app.seed.world import keys


def _create(**kw: object) -> PartyCreate:
    data: dict[str, object] = {
        "legal_name": keys.PARTY_NAMES["NORDHAUS"], "country_code": "de", "default_currency": "EUR", "roles": ["customer"],
    }
    data.update(kw)
    return PartyCreate.model_validate(data)


def test_country_is_upper_cased_and_roles_are_the_slice_one_set() -> None:
    party = _create()
    assert party.country_code == "DE" and party.roles == [PartyRole.CUSTOMER]
    assert {r.value for r in PartyRole} == {"customer", "vendor", "fabricator", "job_worker"}


@pytest.mark.parametrize(
    "bad",
    [
        {"roles": []},
        {"roles": ["transporter"]},
        {"default_currency": "CHF"},
        {"country_code": "DEU"},
        {"legal_name": "  "},
        {"unexpected": "field"},
    ],
)
def test_invalid_party_input_is_rejected(bad: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _create(**bad)


def test_tax_identifiers_are_normalised_and_optional() -> None:
    assert _create().tax_identifiers == []
    tax = TaxIdentifierIn(scheme="vat", value=" de 123 456 789 ")  # type: ignore[arg-type]
    assert tax.value == "DE123456789"


def test_update_needs_an_expected_version() -> None:
    with pytest.raises(ValidationError):
        PartyUpdate.model_validate({"display_name": "x"})
    assert PartyUpdate.model_validate({"expected_version": 3}).model_dump(exclude_unset=True) == {"expected_version": 3}


def test_resolve_party_tool_carries_no_identity_fields() -> None:
    assert not FORBIDDEN_INPUT_FIELDS & set(ResolvePartyInput.model_fields)
    assert RESOLVE_PARTY.effect == "read" and RESOLVE_PARTY.permission == "parties.party.read"
    with pytest.raises(ValidationError):
        ResolvePartyInput.model_validate({"query": "Nordhaus", "user_id": "x"})
