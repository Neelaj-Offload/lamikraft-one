"""Customer types as a reference table (SC-13) and party archive/restore (Slice 2)."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed, VersionConflict
from app.modules.parties import customer_types
from app.modules.parties import service as parties
from app.modules.parties.schemas import (
    AddressIn,
    ContactIn,
    CustomerTypeCreate,
    CustomerTypeUpdate,
    PartyCreate,
    PartyFilters,
    PartyUpdate,
)
from app.platform.events.models import DomainEvent
from app.platform.uow import UnitOfWork
from app.seed.world import keys
from tests.integration.catalogue.world import World

pytestmark = pytest.mark.db

PRIYA, SAHIL, MEERA, NEHA = keys.USERS.PRIYA, keys.USERS.SAHIL, keys.USERS.MEERA, keys.USERS.NEHA


def _create_type(world: World, code: str, label: str, **kw: object) -> customer_types.CustomerTypeRead:  # type: ignore[name-defined]
    with UnitOfWork(world.actor(PRIYA)) as uow:
        return customer_types.create_customer_type(uow, CustomerTypeCreate(code=code, label=label, **kw))  # type: ignore[arg-type]


def test_built_in_types_listed_with_live_party_counts(world: World) -> None:
    rows = customer_types.list_customer_types(world.actor(SAHIL))
    assert [r.code for r in rows] == ["standard", "dealer", "distributor"]
    assert all(r.is_system and r.is_active for r in rows)
    by_code = {r.code: r for r in rows}
    assert by_code["dealer"].party_count == 1  # Thornbury
    assert by_code["dealer"].capabilities["update"].allowed is False  # management lacks the manage key
    assert customer_types.list_customer_types(world.actor(PRIYA))[0].capabilities["update"].allowed is True


def test_new_type_is_assignable_and_enforced_by_foreign_key(world: World) -> None:
    created = _create_type(world, "Wholesale", "Wholesale buyer", display_order=40)
    assert created.code == "wholesale" and created.is_system is False
    with pytest.raises(Conflict):
        _create_type(world, "wholesale", "Again")
    with UnitOfWork(world.actor(MEERA)) as uow:
        party = parties.create_party(
            uow,
            PartyCreate.model_validate(
                {"legal_name": "Grossmarkt AG", "country_code": "DE", "default_currency": "EUR", "roles": ["customer"],
                 "customer_type": "wholesale"}
            ),
        )
    assert party.customer_type == "wholesale"
    page = parties.list_parties(world.actor(MEERA), PartyFilters(customer_type="wholesale"))  # type: ignore[arg-type]
    assert [p.id for p in page.items] == [party.id]
    with pytest.raises(ValidationFailed) as exc:
        with UnitOfWork(world.actor(MEERA)) as uow:
            parties.create_party(
                uow,
                PartyCreate.model_validate(
                    {"legal_name": "Unknown Type Ltd", "country_code": "GB", "default_currency": "GBP",
                     "roles": ["customer"], "customer_type": "nonexistent"}
                ),
            )
    assert exc.value.extra["errors"][0]["code"] == "customer_type_unknown"
    # the database refuses an unknown code even without the service
    with pytest.raises(IntegrityError), UnitOfWork(world.actor(PRIYA)) as uow:
        uow.session.execute(
            text("UPDATE parties_party SET customer_type = 'ghost' WHERE id = :id"), {"id": party.id}
        )


def test_inactive_type_cannot_be_newly_assigned_but_may_stay(world: World) -> None:
    dealer = next(r for r in customer_types.list_customer_types(world.actor(PRIYA)) if r.code == "dealer")
    with UnitOfWork(world.actor(PRIYA)) as uow:
        updated = customer_types.update_customer_type(
            uow, dealer.id, CustomerTypeUpdate(expected_version=dealer.version, is_active=False, label="Trade dealer")
        )
    assert updated.is_active is False and updated.label == "Trade dealer"
    with pytest.raises(VersionConflict), UnitOfWork(world.actor(PRIYA)) as uow:
        customer_types.update_customer_type(uow, dealer.id, CustomerTypeUpdate(expected_version=dealer.version, label="x"))
    with pytest.raises(Forbidden), UnitOfWork(world.actor(SAHIL)) as uow:
        customer_types.update_customer_type(uow, dealer.id, CustomerTypeUpdate(expected_version=updated.version, label="x"))
    # Thornbury keeps its (now inactive) dealer type through an unrelated edit
    thornbury = parties.get_party(world.actor(NEHA), world.ref("THORNBURY"))
    with UnitOfWork(world.actor(NEHA)) as uow:
        after = parties.update_party(
            uow, thornbury.id, PartyUpdate(expected_version=thornbury.version, display_name="Thornbury Kitchens")
        )
    assert after.customer_type == "dealer"
    nordhaus = parties.get_party(world.actor(MEERA), world.ref("NORDHAUS"))
    with pytest.raises(ValidationFailed) as exc, UnitOfWork(world.actor(MEERA)) as uow:
        parties.update_party(uow, nordhaus.id, PartyUpdate(expected_version=nordhaus.version, customer_type="dealer"))  # type: ignore[arg-type]
    assert exc.value.extra["errors"][0]["code"] == "customer_type_inactive"


def test_types_provisioned_for_a_company_created_after_the_migration(personas: World) -> None:
    rows = customer_types.list_customer_types(personas.actor(SAHIL))
    assert {r.code for r in rows} == {"standard", "dealer", "distributor"}


def test_archive_and_restore_need_the_archive_key_and_a_current_version(world: World) -> None:
    nordhaus = parties.get_party(world.actor(SAHIL), world.ref("NORDHAUS"))
    assert nordhaus.capabilities["archive"].allowed is True
    assert parties.get_party(world.actor(MEERA), nordhaus.id).capabilities["archive"].reason_code == "permission_denied"
    with pytest.raises(Forbidden), UnitOfWork(world.actor(MEERA)) as uow:
        parties.set_party_archived(uow, nordhaus.id, archived=True, expected_version=nordhaus.version)
    with pytest.raises(VersionConflict), UnitOfWork(world.actor(SAHIL)) as uow:
        parties.set_party_archived(uow, nordhaus.id, archived=True, expected_version=nordhaus.version + 5)
    with UnitOfWork(world.actor(SAHIL)) as uow:
        archived = parties.set_party_archived(uow, nordhaus.id, archived=True, expected_version=nordhaus.version)
    assert archived.archived_at is not None
    assert archived.capabilities["restore"].allowed and not archived.capabilities["archive"].allowed
    numbers = {p.party_number for p in parties.list_parties(world.actor(SAHIL), PartyFilters()).items}
    assert keys.PARTIES.NORDHAUS not in numbers
    with_archived = parties.list_parties(world.actor(SAHIL), PartyFilters(include_archived=True)).items
    assert keys.PARTIES.NORDHAUS in {p.party_number for p in with_archived}
    with pytest.raises(Conflict), UnitOfWork(world.actor(SAHIL)) as uow:
        parties.set_party_archived(uow, nordhaus.id, archived=True, expected_version=archived.version)
    with UnitOfWork(world.actor(SAHIL)) as uow:
        restored = parties.set_party_archived(uow, nordhaus.id, archived=False, expected_version=archived.version)
    assert restored.archived_at is None
    with UnitOfWork(world.actor(SAHIL)) as uow:
        names = [
            e.event_type
            for e in uow.session.query(DomainEvent).filter(DomainEvent.aggregate_id == nordhaus.id).all()
        ]
    assert "parties.party.archived" in names


def test_party_contacts_addresses_roles_scope(world: World) -> None:
    """GAP-01: a party with contacts and both address kinds round-trips; another sales user cannot see it."""
    with UnitOfWork(world.actor(MEERA)) as uow:
        created = parties.create_party(
            uow,
            PartyCreate(
                legal_name="Fjord Interiors AS",
                country_code="NO",
                default_currency="EUR",
                roles=["customer", "vendor"],  # type: ignore[list-item]
                customer_type="distributor",  # type: ignore[arg-type]
                contacts=[ContactIn(name="Ingrid Berg", email="ingrid@example.test", is_primary=True)],
                addresses=[
                    AddressIn(kind="billing", line1="Strandgata 1", city="Bergen", country_code="NO", is_default=True),  # type: ignore[arg-type]
                    AddressIn(kind="shipping", line1="Kaien 4", city="Bergen", country_code="NO", is_default=True),  # type: ignore[arg-type]
                ],
            ),
        )
    detail = parties.get_party(world.actor(MEERA), created.id)
    assert [c.name for c in detail.contacts] == ["Ingrid Berg"]
    assert sorted(a.kind.value for a in detail.addresses) == ["billing", "shipping"]
    assert sorted(r.value for r in detail.roles) == ["customer", "vendor"]
    assert detail.customer_type == "distributor"
    with pytest.raises(NotFound):
        parties.get_party(world.actor(NEHA), created.id)
