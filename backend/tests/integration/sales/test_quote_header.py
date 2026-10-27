"""Quote header: defaults, party snapshot, optimistic versions, validity from the issue date (LM-44, FG-QUO-*)."""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from app.core.errors import NotFound, VersionConflict
from app.modules.parties import service as parties
from app.modules.parties.schemas import AddressIn, PartyUpdate
from app.modules.sales import service as sales
from app.modules.sales.schemas import QuoteCreate, QuoteUpdate
from app.seed.world import keys
from tests.integration.sales.world import SalesWorld

pytestmark = pytest.mark.db


def test_header_fields_round_trip_with_party_snapshot(world: SalesWorld) -> None:
    w = world
    with w.uow(keys.USERS.MEERA) as uow:
        quote = sales.create_quote(
            uow,
            QuoteCreate(
                party_id=w.ref("NORDHAUS"), brand="lk", incoterm="CIF", incoterm_place="Hamburg", validity_days=45,
                customer_reference="PO-778", remarks="Launch order", payment_terms="30 days net", apply_minimum_surcharge=True,
            ),
        )
        detail = sales.detail(uow, quote)
    assert detail.quote_number.startswith("LK-QT-2026-") and detail.brand == "LK" and detail.status == "draft"
    assert (detail.incoterm, detail.incoterm_place, detail.validity_days) == ("CIF", "Hamburg", 45)
    assert (detail.customer_reference, detail.remarks, detail.payment_terms) == ("PO-778", "Launch order", "30 days net")
    assert detail.apply_minimum_surcharge is True and detail.currency == "EUR" and detail.price_type == "export"
    assert detail.owner.id == w.user_id(keys.USERS.MEERA) and detail.origin == "user" and detail.revision_no == 0
    snap = detail.party_snapshot
    assert snap.display_name == keys.PARTY_NAMES["NORDHAUS"] and snap.country_code == "DE" and snap.party_number == keys.PARTIES.NORDHAUS
    assert snap.contact_name == "Lena Brandt" and {a.kind for a in snap.addresses} == {"billing", "shipping"}
    assert detail.party.display_name == keys.PARTY_NAMES["NORDHAUS"]
    assert detail.totals.grand_total is not None and detail.totals.grand_total.amount == 0 and detail.totals.line_count == 0

    # the party changes; the snapshot stays until an explicit refresh
    with w.uow(keys.USERS.PRIYA) as uow:
        party = parties.get_party(uow, w.ref("NORDHAUS"))
        addresses = [
            AddressIn(id=a.id, kind=a.kind, line1=a.line1 if a.kind != "shipping" else "Neuer Weg 9", line2=a.line2, city=a.city,
                      region=a.region, postal_code=a.postal_code, country_code=a.country_code, is_default=a.is_default)
            for a in party.addresses
        ]
        parties.update_party(uow, party.id, PartyUpdate(expected_version=party.version, display_name="Nordhaus Interiors", addresses=addresses))
    with w.uow(keys.USERS.MEERA) as uow:
        unchanged = sales.get_quote(uow, detail.id)
        assert unchanged.party_snapshot.display_name == keys.PARTY_NAMES["NORDHAUS"]
        assert unchanged.party.display_name == "Nordhaus Interiors"  # the live party label still resolves
        refreshed = sales.update_quote(uow, detail.id, QuoteUpdate(expected_version=unchanged.version, refresh_party_snapshot=True))
        after = sales.detail(uow, refreshed)
    assert after.party_snapshot.display_name == "Nordhaus Interiors"
    assert any("Neuer Weg 9" in ln for a in after.party_snapshot.addresses for ln in a.lines)
    assert after.version == unchanged.version + 1


def test_defaults_applied(world: SalesWorld) -> None:
    thornbury = world.new_draft(keys.USERS.NEHA, "THORNBURY")
    assert (thornbury.currency, thornbury.incoterm, thornbury.validity_days, thornbury.brand, thornbury.price_type) == ("GBP", "FOB", 30, "LK", "export")
    assert thornbury.apply_minimum_surcharge is False and thornbury.branch_id == world.branch_id
    assert thornbury.totals.minimum.status == "NOT_EVALUATED" and thornbury.totals.surcharge_applied is False


def test_optimistic_version_409(world: SalesWorld) -> None:
    draft = world.new_draft(keys.USERS.MEERA, "BERG", ("MAPLE_TRIVET", "600"))
    with world.uow(keys.USERS.MEERA) as uow:
        sales.update_quote(uow, draft.id, QuoteUpdate(expected_version=draft.version, remarks="first"))
    with pytest.raises(VersionConflict):
        with world.uow(keys.USERS.MEERA) as uow:
            sales.update_quote(uow, draft.id, QuoteUpdate(expected_version=draft.version, remarks="stale"))
    with world.uow(keys.USERS.MEERA) as uow:
        current = sales.get_quote(uow, draft.id)
    assert current.version == draft.version + 1 and current.remarks == "first"


def test_valid_until_from_issue_date(world: SalesWorld, frozen_clock) -> None:  # type: ignore[no-untyped-def]
    """Issue late in the evening IST: the validity counts from the company-zone date (not the UTC date)."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    draft = world.new_draft(keys.USERS.MEERA, "BERG", ("MAPLE_TRIVET", "600"), validity_days=30)
    world.at(datetime(2026, 10, 12, 23, 30, tzinfo=ZoneInfo("Asia/Kolkata")))  # 18:00Z, still 12 Oct in Kolkata
    sent = world.transition(keys.USERS.MEERA, draft.id, "mark_sent")
    assert sent.status == "sent" and sent.valid_until == date(2026, 11, 11) and sent.revision_no == 1
    assert sent.issued_at is not None and sent.sent_at == sent.issued_at


def test_issue_requires_linked_party(world: SalesWorld) -> None:
    """A quote is always linked to a party master record (no free-text customers); an invisible party is a 404."""
    with pytest.raises(NotFound):
        with world.uow(keys.USERS.MEERA) as uow:
            sales.create_quote(uow, QuoteCreate(party_id=uuid.uuid7()))
    with pytest.raises(NotFound):  # Thornbury belongs to Neha: outside Meera's own scope
        with world.uow(keys.USERS.MEERA) as uow:
            sales.create_quote(uow, QuoteCreate(party_id=world.ref("THORNBURY")))
