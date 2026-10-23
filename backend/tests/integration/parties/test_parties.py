"""Parties on real PostgreSQL: own/team/branch/company scope (404 outside scope, 403 visible but forbidden),
P-NNNNN numbering, events with changed field names, resolve_party, search provider and source reader."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.core.errors import Forbidden, NotFound, ValidationFailed, VersionConflict
from app.modules.parties import service as parties
from app.modules.parties.schemas import (
    AddressIn,
    ContactIn,
    PartyCreate,
    PartyFilters,
    PartyRole,
    PartyUpdate,
    ResolvePartyInput,
    TaxIdentifierIn,
)
from app.modules.parties.tools import RESOLVE_PARTY
from app.platform import sources
from app.platform.events.models import DomainEvent
from app.platform.uow import UnitOfWork
from app.registry import get_registry
from app.seed.world import keys
from tests.integration.catalogue.world import World, build_personas

pytestmark = pytest.mark.db

MEERAS = ("NORDHAUS", "MAISON", "BERG")


def _numbers(world: World, user: str, **filters: object) -> list[str]:
    page = parties.list_parties(world.actor(user), PartyFilters(**filters))
    assert page.total == len(page.items)
    return sorted(p.party_number for p in page.items)


def _new_party(world: World, user: str, name: str, **kw: object) -> parties.PartyDetail:  # type: ignore[name-defined]
    data: dict[str, object] = {"legal_name": name, "country_code": "CH", "default_currency": "EUR", "roles": ["customer"]}
    data.update(kw)
    with UnitOfWork(world.actor(user)) as uow:
        return parties.create_party(uow, PartyCreate.model_validate(data))


# ---- scope -------------------------------------------------------------------------------------------------
def test_sales_users_see_only_their_own_parties(world: World) -> None:
    meera, neha = world.actor(keys.USERS.MEERA), world.actor(keys.USERS.NEHA)
    assert _numbers(world, keys.USERS.MEERA) == sorted(getattr(keys.PARTIES, k) for k in MEERAS)
    assert _numbers(world, keys.USERS.NEHA) == [keys.PARTIES.THORNBURY]
    with pytest.raises(NotFound):  # Neha's party is not visible to Meera: 404, no existence leak
        parties.get_party(meera, world.ref("THORNBURY"))
    with pytest.raises(NotFound):
        parties.get_party(neha, world.ref("NORDHAUS"))
    with pytest.raises(NotFound):
        parties.get_party_by_number(meera, keys.PARTIES.THORNBURY)
    with pytest.raises(NotFound), UnitOfWork(meera) as uow:
        parties.update_party(uow, world.ref("THORNBURY"), PartyUpdate(expected_version=1, display_name="x"))
    assert parties.get_party(meera, world.ref("NORDHAUS")).capabilities["update"].allowed is True


def test_company_scope_and_visible_but_forbidden(world: World) -> None:
    every = sorted(getattr(keys.PARTIES, k) for k in (*MEERAS, "THORNBURY"))
    assert _numbers(world, keys.USERS.SAHIL) == every  # management: company scope
    assert _numbers(world, keys.USERS.RAVI) == every  # operations: read at company scope, no update
    ravi = world.actor(keys.USERS.RAVI)
    detail = parties.get_party(ravi, world.ref("NORDHAUS"))
    assert detail.capabilities["update"].allowed is False and detail.allowed_transitions == []
    with pytest.raises(Forbidden), UnitOfWork(ravi) as uow:  # visible but forbidden: 403
        parties.update_party(uow, world.ref("NORDHAUS"), PartyUpdate(expected_version=detail.version, display_name="x"))
    with pytest.raises(Forbidden):
        parties.list_parties(world.actor(keys.USERS.KABIR), PartyFilters())  # warehouse holds no party key
    other = build_personas()
    assert _numbers(other, keys.USERS.SAHIL) == []
    with pytest.raises(NotFound):
        parties.get_party(other.actor(keys.USERS.SAHIL), world.ref("NORDHAUS"))


def test_filters_apply_before_pagination(world: World) -> None:
    assert _numbers(world, keys.USERS.SAHIL, country_code="GB") == [keys.PARTIES.THORNBURY]
    assert _numbers(world, keys.USERS.SAHIL, customer_type="dealer") == [keys.PARTIES.THORNBURY]
    assert _numbers(world, keys.USERS.SAHIL, q="lena") == [keys.PARTIES.NORDHAUS]  # contact names are searchable
    assert _numbers(world, keys.USERS.SAHIL, q="co ab") == [keys.PARTIES.BERG]
    assert _numbers(world, keys.USERS.SAHIL, role=PartyRole.VENDOR) == []
    assert _numbers(world, keys.USERS.SAHIL, owner_user_id=world.user_id(keys.USERS.NEHA)) == [keys.PARTIES.THORNBURY]
    page = parties.list_parties(world.actor(keys.USERS.SAHIL), PartyFilters(), limit=3, offset=3)
    assert page.total == 4 and len(page.items) == 1
    assert _numbers(world, keys.USERS.SAHIL, q="%") == []


# ---- commands ----------------------------------------------------------------------------------------------
def test_create_allocates_the_next_number_and_emits_created(world: World) -> None:
    created = _new_party(
        world, keys.USERS.MEERA, "Nordhaus Logistik AG",
        contacts=[ContactIn(name="Jonas Weber", is_primary=True)],
        addresses=[AddressIn(kind="billing", line1="Industriestrasse 9", city="Basel", country_code="CH")],  # type: ignore[arg-type]
        tax_identifiers=[TaxIdentifierIn(scheme="vat", value="CHE 123 456 789")],  # type: ignore[arg-type]
    )
    assert created.party_number == "P-00005"  # never reset; follows the four world customers
    assert created.owner.id == world.user_id(keys.USERS.MEERA) and created.version == 1
    assert created.tax_identifiers[0].value == "CHE123456789"
    assert created.tax_identifiers[0].verification_status == "unverified"
    with UnitOfWork(world.actor(keys.USERS.MEERA)) as uow:
        event = uow.session.scalars(
            select(DomainEvent).where(DomainEvent.event_type == "parties.party.created", DomainEvent.aggregate_id == created.id)
        ).one()
    assert event.payload == {"party_id": str(created.id), "party_number": "P-00005",
                             "owner_user_id": str(world.user_id(keys.USERS.MEERA)), "origin": "user"}
    assert _numbers(world, keys.USERS.NEHA) == [keys.PARTIES.THORNBURY]  # Neha still sees only her own party


def test_sales_cannot_assign_a_party_to_someone_else(world: World) -> None:
    with pytest.raises(Forbidden):
        _new_party(world, keys.USERS.MEERA, "Assigned Elsewhere GmbH", owner_user_id=world.user_id(keys.USERS.NEHA))
    with pytest.raises(ValidationFailed):
        _new_party(world, keys.USERS.SAHIL, "Ghost Owner GmbH", owner_user_id=uuid.UUID(int=1))
    with pytest.raises(ValidationFailed):
        _new_party(world, keys.USERS.MEERA, "Typed Vendor", roles=["vendor"], customer_type="standard")


def test_update_reports_changed_field_names_and_checks_versions(world: World) -> None:
    meera = world.actor(keys.USERS.MEERA)
    current = parties.get_party(meera, world.ref("BERG"))
    shipping = next(a for a in current.addresses if a.kind == "shipping")
    billing = next(a for a in current.addresses if a.kind == "billing")
    with UnitOfWork(meera) as uow:
        updated = parties.update_party(
            uow, current.id,
            PartyUpdate(
                expected_version=current.version,
                display_name="Berg & Co",
                addresses=[
                    AddressIn(id=billing.id, kind="billing", line1=billing.line1, city=billing.city,  # type: ignore[arg-type]
                              postal_code=billing.postal_code, country_code=billing.country_code),
                    AddressIn(id=shipping.id, kind="shipping", line1="Hamngatan 7", city="Göteborg",  # type: ignore[arg-type]
                              postal_code=shipping.postal_code, country_code="SE"),
                ],
            ),
        )
    assert updated.version == current.version + 1 and updated.display_name == "Berg & Co"
    with UnitOfWork(meera) as uow:
        event = uow.session.scalars(
            select(DomainEvent).where(DomainEvent.event_type == "parties.party.updated", DomainEvent.aggregate_id == current.id)
        ).one()
    assert event.payload["changed_fields"] == ["addresses.shipping", "display_name"]
    assert event.aggregate_version == updated.version
    with pytest.raises(VersionConflict), UnitOfWork(meera) as uow:
        parties.update_party(uow, current.id, PartyUpdate(expected_version=current.version, display_name="stale"))
    with UnitOfWork(meera) as uow:  # no change: no version bump, no event
        same = parties.update_party(uow, current.id, PartyUpdate(expected_version=updated.version, display_name="Berg & Co"))
    assert same.version == updated.version


def test_maison_change_reads_back_as_the_new_shipping_address(world: World) -> None:
    maison = parties.get_party(world.actor(keys.USERS.MEERA), world.ref("MAISON"))
    shipping = [a for a in maison.addresses if a.kind == "shipping"]
    assert len(shipping) == 1 and shipping[0].line1.startswith("Entrepôt B")
    assert maison.version == 2


# ---- resolve_party, search, source reader -------------------------------------------------------------------
def test_resolve_party_unique_ambiguous_and_not_found(world: World) -> None:
    meera, neha = world.actor(keys.USERS.MEERA), world.actor(keys.USERS.NEHA)
    unique = parties.resolve_party(meera, "nordhaus")
    assert unique.status == "unique" and unique.candidates[0].party_number == keys.PARTIES.NORDHAUS
    assert parties.resolve_party(neha, "Nordhaus").status == "not_found"  # outside Neha's scope
    by_number = parties.resolve_party(meera, keys.PARTIES.MAISON.lower())
    assert by_number.status == "unique" and by_number.candidates[0].match == "party_number"
    _new_party(world, keys.USERS.MEERA, "Nordhaus Logistik AG")  # fixtures §11 scenario C ambiguity
    ambiguous = parties.resolve_party(meera, "Nordhaus")
    assert ambiguous.status == "ambiguous" and ambiguous.total_matches == 2
    assert {c.display_name for c in ambiguous.candidates} == {keys.PARTY_NAMES["NORDHAUS"], "Nordhaus Logistik AG"}
    exact = parties.resolve_party(meera, keys.PARTY_NAMES["NORDHAUS"])
    assert exact.status == "unique" and exact.candidates[0].match == "exact_name"
    assert parties.resolve_party(meera, "nordhaus", role=PartyRole.VENDOR).status == "not_found"
    with UnitOfWork(meera) as uow:
        tool_out = RESOLVE_PARTY.handler(uow, ResolvePartyInput(query="Berg"))
    assert tool_out.status == "unique" and tool_out.candidates[0].party_number == keys.PARTIES.BERG  # type: ignore[attr-defined]


def test_search_provider_and_source_reader_are_scoped(world: World) -> None:
    provider = next(p for p in get_registry().search_providers if p.resource_type == "parties.party")
    with UnitOfWork(world.actor(keys.USERS.NEHA)) as uow:
        assert provider.search(uow, "Nordhaus", 10) == []
        hits = provider.search(uow, "thornbury", 10)
        assert [h.resource_id for h in hits] == [world.ref("THORNBURY")]
        assert sources.read(uow, "parties.party", world.ref("NORDHAUS")) is None
        facts = sources.read(uow, "parties.party", world.ref("THORNBURY"))
    assert facts is not None and facts.owner_user_id == world.user_id(keys.USERS.NEHA)
    assert facts.label == f"{keys.PARTIES.THORNBURY} · {keys.PARTY_NAMES['THORNBURY']}"
    assert facts.facts["customer_type"] == "dealer" and facts.required_permission == "parties.party.read"
    assert facts.canonical_path == f"/sales/parties/{world.ref('THORNBURY')}"
