"""Proforma invoices on real PostgreSQL (module 3).

Spec: docs/superpowers/specs/2026-11-25-proforma-invoices-design.md
"""

from __future__ import annotations

import re
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed, VersionConflict
from app.modules.sales import proforma as pf
from app.modules.sales.common import business_date
from app.modules.sales.proforma_documents import render
from app.modules.sales.proforma_models import ProformaInvoice
from app.seed.world import keys
from tests.integration.sales.world import SalesWorld

pytestmark = pytest.mark.db

MEERA, NEHA, SAHIL, PRIYA = keys.USERS.MEERA, keys.USERS.NEHA, keys.USERS.SAHIL, keys.USERS.PRIYA


def _won_quote(world: SalesWorld) -> uuid.UUID:
    return world.ref(keys.QUOTE_REFS.BERG_WON)


def _create(world: SalesWorld, person: str, quote_id: uuid.UUID, **body: object) -> pf.ProformaDetail:
    with world.uow(person) as uow:
        pi = pf.create_proforma(uow, quote_id, pf.ProformaCreate.model_validate(body))
        return pf.read_detail(uow, pi)


def _owner(world: SalesWorld, quote_id: uuid.UUID) -> str:
    """The persona that owns the quotation (PIs follow the quotation's owner scope)."""
    with world.uow(PRIYA) as uow:
        owner = uow.session.execute(text("SELECT owner_user_id FROM sales_quote WHERE id = :id"), {"id": quote_id}).scalar()
    return next(k for k in (MEERA, NEHA, SAHIL) if world.user_id(k) == owner)


def test_create_from_won_quote_copies_the_revision(sales_world: SalesWorld) -> None:
    world = sales_world
    quote_id = _won_quote(world)
    who = _owner(world, quote_id)
    pi = _create(world, who, quote_id, port_of_loading="Mundra", port_of_discharge="Rotterdam")
    assert pi.status == "draft" and pi.pi_number is None and pi.draft_ref.startswith("PI-DRAFT-")
    with world.uow(PRIYA) as uow:
        rev = uow.session.execute(text(
            "SELECT snapshot FROM sales_quote_revision WHERE quote_id = :id ORDER BY revision_no DESC LIMIT 1"
        ), {"id": quote_id}).scalar()
    assert [ln["line_key"] for ln in pi.lines] == [ln["line_key"] for ln in rev["lines"]]
    assert pi.grand_total == rev["totals"]["grand_total"] and pi.port_of_loading == "Mundra"
    assert pi.capabilities["issue"].allowed and pi.capabilities["update"].allowed


def test_draft_quote_is_refused(sales_world: SalesWorld) -> None:
    world = sales_world
    draft = world.ref(keys.QUOTE_REFS.NORDHAUS_DRAFT)
    with pytest.raises(Conflict):
        _create(world, _owner(world, draft), draft)


def test_edit_issue_and_freeze(sales_world: SalesWorld) -> None:
    world = sales_world
    quote_id = _won_quote(world)
    who = _owner(world, quote_id)
    pi = _create(world, who, quote_id)
    with world.uow(who) as uow:
        edited = pf.update_proforma(uow, pi.id, pf.ProformaUpdate(expected_version=pi.version, payment_terms="30% advance"))
        version = edited.version
    with pytest.raises(VersionConflict):
        with world.uow(who) as uow:
            pf.update_proforma(uow, pi.id, pf.ProformaUpdate(expected_version=pi.version, notes="stale"))
    with world.uow(who) as uow:
        issued = pf.issue_proforma(uow, pi.id, pf.ProformaIssue(expected_version=version))
        assert issued.pi_number is not None and re.fullmatch(r"PI-\d{4}-\d{4}", issued.pi_number)
        assert issued.pi_date == business_date(uow) and issued.snapshot.get("company")
        detail = pf.read_detail(uow, issued)
    assert detail.capabilities["update"].allowed is False and detail.capabilities["issue"].allowed is False
    with pytest.raises(Conflict):
        with world.uow(who) as uow:
            pf.update_proforma(uow, pi.id, pf.ProformaUpdate(expected_version=detail.version, notes="too late"))
    with world.uow(who) as uow:
        pdf = render(uow, uow.session.get(ProformaInvoice, pi.id))  # type: ignore[arg-type]
    assert pdf.startswith(b"%PDF")


def test_cancel_needs_management_and_a_reason(sales_world: SalesWorld) -> None:
    world = sales_world
    quote_id = _won_quote(world)
    pi = _create(world, _owner(world, quote_id), quote_id)
    with pytest.raises(Forbidden):
        with world.uow(MEERA) as uow:
            pf.cancel_proforma(uow, pi.id, pf.ProformaCancel(expected_version=pi.version, reason="Client changed mind"))
    with world.uow(SAHIL) as uow:
        cancelled = pf.cancel_proforma(uow, pi.id, pf.ProformaCancel(expected_version=pi.version, reason="Client changed mind"))
    assert cancelled.status == "cancelled" and cancelled.cancel_reason == "Client changed mind"


def test_backfill_keeps_number_and_date(sales_world: SalesWorld) -> None:
    world = sales_world
    quote_id = _won_quote(world)
    with world.uow(SAHIL) as uow:
        past = business_date(uow) - timedelta(days=90)
    pi = _create(world, SAHIL, quote_id, pi_number="LK/PI/2026/007", pi_date=past.isoformat())
    assert (pi.status, pi.pi_number, pi.pi_date, pi.backfilled) == ("issued", "LK/PI/2026/007", past, True)
    with pytest.raises(Conflict):  # the number is taken
        _create(world, SAHIL, quote_id, pi_number="LK/PI/2026/007", pi_date=past.isoformat())
    with pytest.raises(ValidationFailed):  # future date
        _create(world, SAHIL, quote_id, pi_number="LK/PI/2026/008", pi_date=(past + timedelta(days=200)).isoformat())
    with pytest.raises(ValidationFailed):  # number without a date
        _create(world, SAHIL, quote_id, pi_number="LK/PI/2026/009")
    with pytest.raises(Forbidden):  # sales cannot backfill
        _create(world, _owner(world, quote_id) if _owner(world, quote_id) != SAHIL else MEERA, quote_id,
                pi_number="LK/PI/2026/010", pi_date=past.isoformat())


def test_scope_and_list(sales_world: SalesWorld) -> None:
    world = sales_world
    quote_id = _won_quote(world)
    who = _owner(world, quote_id)
    other = NEHA if who != NEHA else MEERA
    pi = _create(world, who, quote_id)
    mine = pf.list_proformas(world.actor(who), pf.ProformaFilters(quote_id=quote_id))
    assert pi.id in {p.id for p in mine.items}
    theirs = pf.list_proformas(world.actor(other), pf.ProformaFilters(quote_id=quote_id))
    assert pi.id not in {p.id for p in theirs.items}
    with pytest.raises(NotFound):
        pf.get_proforma(world.actor(other), pi.id)
    found = pf.list_proformas(world.actor(SAHIL), pf.ProformaFilters(q=pi.quote_number))
    assert pi.id in {p.id for p in found.items}


def test_number_constraint_in_database(sales_world: SalesWorld) -> None:
    world = sales_world
    quote_id = _won_quote(world)
    pi = _create(world, _owner(world, quote_id), quote_id)
    with pytest.raises(DBAPIError):
        with world.uow(PRIYA) as uow:
            uow.session.execute(text("UPDATE sales_proforma_invoice SET status = 'issued' WHERE id = :id"), {"id": pi.id})
            uow.session.flush()


def test_amount_in_words() -> None:
    assert pf.amount_in_words(Decimal("12345.50"), "USD") == (
        "US dollars twelve thousand three hundred forty-five and cents fifty only")
    assert pf.amount_in_words("100", "INR") == "Indian rupees one hundred only"
    assert pf.amount_in_words("2000000.05", "EUR") == "Euros two million and cents five only"
    assert pf.amount_in_words(None, "GBP") is None
