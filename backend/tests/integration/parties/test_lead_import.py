"""``lk import leads`` against real PostgreSQL: create, re-run without duplicates, keep edits made in the app."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.modules.parties import lead_import as li
from app.modules.parties import leads
from app.modules.parties import service as parties
from app.modules.parties.models import Party, PartyContact
from app.modules.parties.schemas import LeadStageChange, PartyFilters, PartyUpdate
from app.platform.collab import service as collab
from app.platform.uow import UnitOfWork
from app.seed.world import keys
from tests.integration.catalogue.world import World
from tests.unit.parties.test_lead_import_parse import build, row

pytestmark = pytest.mark.db

PRIYA, MEERA, NEHA = keys.USERS.PRIYA, keys.USERS.MEERA, keys.USERS.NEHA


def _apply(world: World, path: Path) -> li.ImportReport:
    owners = {li.owner_key("Owner One"): world.user_id(MEERA), li.owner_key("Owner Two"): world.user_id(NEHA)}
    with UnitOfWork(world.actor(PRIYA)) as uow:
        return li.apply_rows(uow, li.parse_sheet(path), owners)


def _find(world: World, name: str) -> Party:
    with UnitOfWork(world.actor(PRIYA)) as uow:
        party = uow.session.scalars(select(Party).where(Party.name_key == parties.name_key(name))).one()
        uow.session.expunge(party)
        return party


def _contacts(world: World, party_id: object) -> int:
    with UnitOfWork(world.actor(PRIYA)) as uow:
        return int(uow.session.scalar(
            select(func.count()).select_from(PartyContact)
            .where(PartyContact.party_id == party_id, PartyContact.archived_at.is_(None))
        ) or 0)


def test_import_creates_then_reruns_without_duplicates(world: World, tmp_path: Path) -> None:
    path = build(
        tmp_path,
        row(date="12-Mar-2026", company="Import Harbour Co", country="United States", owner="Owner One",
            source="NRA CHICAGO 2026", interests="LAMIKRAFT", req="RISERS", web="www.importharbour.example",
            c1="ROSA GRANT", e1="rosa@importharbour.example", s1="INTERGASTRA 2026", addr="1 Dock Road", city="Boston"),
        row(company="Import Alpen GmbH", country="Germany", owner="Owner Two", source="WEBSITE",
            action="Order Form Issued"),
        row(company="Import Nobody Ltd", country="Italy", owner="Someone Else"),
        row(company="Import Harbour Co", country="Canada", owner="Owner One", source="VISITING CARD"),
    )
    first = _apply(world, path)
    assert len(first.created) == 3 and [i.message for i in first.rejected] == ["Owner not mapped: Someone Else"]
    assert "nra_chicago_2026" in first.sources_created

    # two rows share the name (US and Canada): look the US one up by country
    with UnitOfWork(world.actor(PRIYA)) as uow:
        us = uow.session.scalars(select(Party).where(Party.name_key == parties.name_key("Import Harbour Co"),
                                                     Party.country_code == "US")).one()
        assert us.owner_user_id == world.user_id(MEERA) and us.default_currency == "USD"
        assert us.lead_source_code == "nra_chicago_2026" and us.interests == ["lamikraft"]
        assert us.lead_stage == "new" and str(us.first_contact_on) == "2026-03-12"
        note = collab.get_note(uow, "parties.party", us.id)
        assert "ROSA GRANT: from Intergastra 2026" in note.body
        harbour = us
        uow.session.expunge(us)
    alpen = _find(world, "Import Alpen GmbH")
    assert alpen.lead_stage == "negotiating" and alpen.default_currency == "EUR"
    assert alpen.owner_user_id == world.user_id(NEHA)

    second = _apply(world, path)
    assert second.created == [] and len(second.unchanged) == 3
    assert _contacts(world, harbour.id) == 1


def test_rerun_keeps_app_edits_and_adds_new_contacts(world: World, tmp_path: Path) -> None:
    base = dict(company="Import Keeper Srl", country="Italy", owner="Owner One", c1="LUCA", e1="luca@keeper.example")
    _apply(world, build(tmp_path, row(**base)))
    keeper = _find(world, "Import Keeper Srl")
    with UnitOfWork(world.actor(MEERA)) as uow:
        detail = parties.update_party(uow, keeper.id, PartyUpdate(expected_version=keeper.version, priority="A",
                                                                  temperature="hot"))  # type: ignore[arg-type]
        leads.change_lead_stage(uow, keeper.id, LeadStageChange(expected_version=detail.version, stage="qualified"))  # type: ignore[arg-type]

    again = build(tmp_path, row(**base, web="www.keeper.example", c2="GIULIA", e2="giulia@keeper.example"))
    report = _apply(world, again)
    assert len(report.updated) == 1
    after = _find(world, "Import Keeper Srl")
    assert (after.lead_stage, after.priority, after.temperature) == ("qualified", "A", "hot")
    assert after.website == "www.keeper.example" and _contacts(world, after.id) == 2
    page = parties.list_parties(world.actor(MEERA), PartyFilters(q="Import Keeper"))
    assert page.total == 1
