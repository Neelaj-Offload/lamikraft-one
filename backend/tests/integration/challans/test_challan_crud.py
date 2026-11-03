"""Challan header, lines, filters and duplicate (LM-80..82, LM-84, LM-86, LM-87, LM-89; FG-DC-*, FG-DCL-*, API-57/62/63/65,
UI-78, UI-81, FG-REL-04)."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.core.errors import NotFound, ValidationFailed, VersionConflict
from app.modules.challans import service as challans
from app.modules.challans.schemas import (
    ChallanCreate,
    ChallanFilters,
    ChallanLineAdd,
    ChallanLineCreate,
    ChallanLineUpdate,
    ChallanStatus,
    ChallanType,
    ChallanUpdate,
    DestinationType,
    LineType,
    ReturnType,
)
from app.modules.sales import service as sales
from app.modules.sales.schemas import CustomProductCreate
from app.seed.world import keys
from tests.integration.challans.conftest import CHALLANS, as_, problem
from tests.integration.challans.world import ChallanWorld

pytestmark = pytest.mark.db
RAVI, PRIYA, SAHIL = keys.USERS.RAVI, keys.USERS.PRIYA, keys.USERS.SAHIL
GSTIN = "27AAPFU0939F1ZV"


def _codes(exc: ValidationFailed) -> set[tuple[str, str]]:
    return {(".".join(str(p) for p in e["loc"][1:]), e["code"]) for e in exc.extra["errors"]}


def test_all_types_return_types_destinations(world: ChallanWorld) -> None:
    """LM-80/81/82, FG-DC-03/05: every legacy type, return type and destination; Job Work is forced returnable; the
    matrix rejects invalid combinations with field locations; destination parties take the party's role."""
    nordhaus = world.ref("NORDHAUS")
    combos = [
        (ChallanType.OUTWARD, ReturnType.NON_RETURNABLE, DestinationType.CUSTOMER, {"party_id": nordhaus}),
        (ChallanType.OUTWARD, ReturnType.RETURNABLE, DestinationType.TRANSPORTER, {"destination_party": "BlueDart Express"}),
        (ChallanType.INWARD, ReturnType.NON_RETURNABLE, DestinationType.VENDOR, {"destination_party": "Kaveri Timber Supplies"}),
        (ChallanType.JOB_WORK, ReturnType.RETURNABLE, DestinationType.FABRICATOR, {"destination_party": "Precision Edge Fabricators"}),
        (ChallanType.TRANSFER, ReturnType.NON_RETURNABLE, DestinationType.WAREHOUSE, {"destination_party": "Main Warehouse"}),
        (ChallanType.TRANSFER, ReturnType.NON_RETURNABLE, DestinationType.OFFICE, {"office_branch_id": world.branch_id}),
        (ChallanType.SAMPLE, ReturnType.RETURNABLE, DestinationType.CUSTOMER, {"party_id": nordhaus}),
        (ChallanType.SAMPLE, ReturnType.NON_RETURNABLE, DestinationType.OFFICE, {"office_branch_id": world.branch_id}),
    ]
    with world.uow(RAVI) as uow:
        for ctype, rtype, dtype, extra in combos:
            c = challans.create_challan(uow, ChallanCreate(challan_type=ctype, return_type=rtype, destination_type=dtype, **extra))
            d = challans.detail(uow, c)
            assert (d.challan_type, d.return_type, d.destination_type) == (ctype, rtype, dtype), (ctype, dtype)
            assert d.destination_party, (ctype, dtype)
            assert d.inventory_effect == "none" and d.status == ChallanStatus.DRAFT
        # defaults per type: Job Work and Sample are returnable, the others non-returnable; office name from the branch
        jw = challans.create_challan(uow, ChallanCreate(challan_type=ChallanType.JOB_WORK, destination_type=DestinationType.VENDOR, destination_party="Kaveri"))
        assert jw.return_type == "returnable" and jw.expected_return_date is not None
        office = challans.create_challan(uow, ChallanCreate(challan_type=ChallanType.TRANSFER, destination_type=DestinationType.OFFICE, office_branch_id=world.branch_id))
        assert office.destination_party == "Head office" and office.return_type == "non_returnable"
        # the customer's name fills the printed destination
        cust = challans.create_challan(uow, ChallanCreate(party_id=nordhaus))
        assert cust.destination_party == keys.PARTY_NAMES["NORDHAUS"]
        # invalid combinations: 422 with the field
        with pytest.raises(ValidationFailed) as exc:
            challans.create_challan(uow, ChallanCreate(challan_type=ChallanType.JOB_WORK, return_type=ReturnType.NON_RETURNABLE,
                                                        destination_type=DestinationType.CUSTOMER, party_id=nordhaus))
        assert _codes(exc.value) >= {("return_type", "job_work_must_be_returnable"), ("destination_type", "destination_not_allowed")}
        with pytest.raises(ValidationFailed) as exc:
            challans.create_challan(uow, ChallanCreate(challan_type=ChallanType.OUTWARD, destination_type=DestinationType.WAREHOUSE, destination_party="WH"))
        assert ("destination_type", "destination_not_allowed") in _codes(exc.value)
        with pytest.raises(ValidationFailed) as exc:  # a customer is not a vendor
            challans.create_challan(uow, ChallanCreate(challan_type=ChallanType.INWARD, destination_type=DestinationType.VENDOR, party_id=nordhaus))
        assert ("party_id", "party_role_mismatch") in _codes(exc.value)
        with pytest.raises(ValidationFailed) as exc:  # a location destination has no party
            challans.create_challan(uow, ChallanCreate(challan_type=ChallanType.TRANSFER, destination_type=DestinationType.OFFICE, party_id=nordhaus))
        assert ("party_id", "party_not_for_location") in _codes(exc.value)
        with pytest.raises(ValidationFailed) as exc:  # destination party text is the one required field (UI-78)
            challans.create_challan(uow, ChallanCreate(destination_type=DestinationType.TRANSPORTER))
        assert ("destination_party", "required") in _codes(exc.value)


def test_header_fields_round_trip(world: ChallanWorld) -> None:
    """LM-84, FG-DC-02/04/06/08/09/13, UI-78: every legacy header field is stored and read back; the source location
    defaults from settings; actor stamps and the owner are set; drafts are editable with ``expected_version``."""
    body = ChallanCreate(
        challan_date=date(2026, 10, 9),
        challan_type=ChallanType.OUTWARD,
        destination_type=DestinationType.CUSTOMER,
        party_id=world.ref("MAISON"),
        shipping_name="Maison Atelier — Entrepôt B",
        gstin=GSTIN.lower(),
        phone="+33 4 72 00 00 00",
        email="camille.laurent@maison-atelier.test",
        address="Entrepôt B\n40 avenue des Docks\n69007 Lyon",
        reference_no="PO-MA-7781",
        remarks="Fragile — keep upright.",
    )
    with world.uow(RAVI) as uow:
        created = challans.detail(uow, challans.create_challan(uow, body))
    assert created.challan_number.startswith("DC-2026-") and created.challan_date == date(2026, 10, 9)
    assert created.source_location == "Crown / Lamikraft Office"  # FG-DC-04 default from challan_defaults
    assert created.destination_party == keys.PARTY_NAMES["MAISON"] and created.party and created.party.party_number == keys.PARTIES.MAISON
    assert created.shipping_name == "Maison Atelier — Entrepôt B" and created.gstin == GSTIN and created.gstin_verified is False
    assert (created.phone, created.email, created.reference_no) == ("+33 4 72 00 00 00", "camille.laurent@maison-atelier.test", "PO-MA-7781")
    assert created.address and "69007 Lyon" in created.address and created.remarks == "Fragile — keep upright."
    assert created.owner.id == world.user_id(RAVI) and created.created_by and created.created_by.id == world.user_id(RAVI)
    assert created.created_at == created.updated_at and created.version == 1 and created.direction == "outward"
    assert created.capabilities["update"].allowed and created.capabilities["issue"].allowed is False  # no lines yet
    assert created.capabilities["issue"].reason_code == "no_lines"
    assert created.expected_return_date is None  # non-returnable
    with world.uow(RAVI) as uow:
        updated = challans.detail(uow, challans.update_challan(uow, created.id, ChallanUpdate(
            expected_version=1, source_location="Factory gate 2", remarks="Palletised.", return_type=ReturnType.RETURNABLE,
            expected_return_date=date(2026, 10, 20),
        )))
    assert updated.version == 2 and updated.source_location == "Factory gate 2" and updated.remarks == "Palletised."
    assert updated.return_type == ReturnType.RETURNABLE and updated.expected_return_date == date(2026, 10, 20)
    assert updated.updated_by and updated.updated_by.id == world.user_id(RAVI)
    with world.uow(RAVI) as uow:
        with pytest.raises(VersionConflict):
            challans.update_challan(uow, created.id, ChallanUpdate(expected_version=1, remarks="stale"))
        with pytest.raises(ValidationFailed) as exc:
            challans.update_challan(uow, created.id, ChallanUpdate(expected_version=2, expected_return_date=date(2026, 10, 1)))
        assert ("expected_return_date", "before_challan_date") in _codes(exc.value)
        with pytest.raises(ValidationFailed) as exc:  # the number is yearly: the date cannot leave its year
            challans.update_challan(uow, created.id, ChallanUpdate(expected_version=2, challan_date=date(2027, 1, 5)))
        assert ("challan_date", "number_year_mismatch") in _codes(exc.value)
        with pytest.raises(NotFound):  # an invisible party is a 404, never an existence leak
            challans.create_challan(uow, ChallanCreate(party_id=uuid.uuid4()))


def test_gstin_format_checked_not_verified(world: ChallanWorld) -> None:
    """FG-DC-07: the GSTIN is format-checked (upper-cased) and never reported as verified."""
    with world.uow(RAVI) as uow:
        c = challans.detail(uow, challans.create_challan(uow, ChallanCreate(party_id=world.ref("NORDHAUS"), gstin=GSTIN.lower())))
        assert c.gstin == GSTIN and c.gstin_verified is False
        assert "gstin_verified" not in {f for f in ChallanCreate.model_fields}
    with pytest.raises(ValueError):
        ChallanCreate(party_id=world.ref("NORDHAUS"), gstin="not-a-gstin")
    with pytest.raises(ValueError):
        ChallanCreate(party_id=world.ref("NORDHAUS"), gstin="27AAPFU0939F1Z")  # 14 characters


def test_lines_with_product_lookup_and_uom_rules(world: ChallanWorld) -> None:
    """LM-86, FG-DCL-02..07, UI-81, FG-REL-04: a catalog line fills code, name, HSN/SAC and unit from the product
    (overridable), manual and custom lines are free text, quantities follow the UOM integer rule, lines renumber."""
    # a real commercial-2 custom product: the line's custom_product_id is a foreign key since the Slice-2 merge (0015)
    with world.uow(keys.USERS.MEERA) as uow:
        custom_id = sales.create_custom_product(uow, CustomProductCreate(product_name="Custom panel 1800×600")).id
    with world.uow(RAVI) as uow:
        with pytest.raises(ValidationFailed):  # an unknown custom product is a field error, not a database error
            draft = challans.create_challan(uow, ChallanCreate(party_id=world.ref("NORDHAUS")))
            challans.add_line(uow, draft.id, ChallanLineAdd(expected_version=draft.version, line_type=LineType.CUSTOM,
                                                            custom_product_id=uuid.uuid4(), item_name="Unknown", quantity=Decimal("1")))
    with world.uow(RAVI) as uow:
        c = challans.create_challan(uow, ChallanCreate(party_id=world.ref("NORDHAUS")))
        c, catalog = challans.add_line(uow, c.id, ChallanLineAdd(expected_version=c.version, line_type=LineType.CATALOG,
                                                                  product_id=world.ref("OAK_TRAY"), quantity=Decimal("40")))
        assert (catalog.item_code, catalog.item_name, catalog.uom_code) == (keys.PRODUCTS.OAK_TRAY, keys.PRODUCT_NAMES["OAK_TRAY"], "pcs")
        assert catalog.product_id == world.ref("OAK_TRAY") and catalog.line_no == 1
        c, manual = challans.add_line(uow, c.id, ChallanLineAdd(expected_version=c.version, line_type=LineType.MANUAL, item_name="Edge banding roll",
                                                                 item_code="EB-22", hsn_sac="3920", quantity=Decimal("2.5"), unit="KG", remarks="2 rolls"))
        assert (manual.line_no, manual.uom_code, manual.hsn_sac, manual.quantity) == (2, "kg", "3920", Decimal("2.5"))
        c, custom = challans.add_line(uow, c.id, ChallanLineAdd(expected_version=c.version, line_type=LineType.CUSTOM, custom_product_id=custom_id,
                                                                 item_name="Custom panel 1800×600", quantity=Decimal("3")))
        assert custom.custom_product_id == custom_id and custom.product_id is None and custom.line_no == 3
        d = challans.detail(uow, c)
        assert d.line_count == 3 and d.quantity_by_unit == {"kg": Decimal("2.5"), "pcs": Decimal("43")}
        version = c.version
        # UOM rules: whole numbers for pcs, at most 4 dp otherwise, unknown units rejected, catalog needs a product
        for body, code in (
            (ChallanLineAdd(expected_version=version, line_type=LineType.MANUAL, item_name="x", quantity=Decimal("1.5"), unit="pcs"), "not_integer"),
            (ChallanLineAdd(expected_version=version, line_type=LineType.MANUAL, item_name="x", quantity=Decimal("1.23456"), unit="kg"), "too_many_decimals"),
            (ChallanLineAdd(expected_version=version, line_type=LineType.MANUAL, item_name="x", quantity=Decimal("1"), unit="furlong"), "uom_unknown"),
            (ChallanLineAdd(expected_version=version, line_type=LineType.CATALOG, quantity=Decimal("1")), "required"),
            (ChallanLineAdd(expected_version=version, line_type=LineType.MANUAL, quantity=Decimal("1")), "required"),
        ):
            with pytest.raises(ValidationFailed) as exc:
                challans.add_line(uow, c.id, body)
            assert code in {e["code"] for e in exc.value.extra["errors"]}, body
        with pytest.raises(ValueError):  # the schema itself refuses non-positive quantities
            ChallanLineCreate(item_name="x", quantity=Decimal("0"))
        # remove the middle line: the rest renumbers atomically
        c = challans.remove_line(uow, c.id, manual.id, expected_version=c.version)
        lines = challans.lines_of(uow, c)
        assert [(ln.line_no, ln.item_name) for ln in lines] == [(1, keys.PRODUCT_NAMES["OAK_TRAY"]), (2, "Custom panel 1800×600")]
        assert c.line_count == 2
        with pytest.raises(NotFound):
            challans.remove_line(uow, c.id, manual.id, expected_version=c.version)


def test_line_edit_version_conflict_and_validation(world: ChallanWorld) -> None:
    """API-63, UI-83: a versioned line PATCH; a stale version is 409, a broken quantity 422, and nothing is swallowed."""
    d = world.new_draft(RAVI, ("OAK_TRAY", "40"), party_id=world.ref("NORDHAUS"))
    line = d.lines[0]
    with world.uow(RAVI) as uow:
        c, changed = challans.update_line(uow, d.id, line.id, ChallanLineUpdate(expected_version=d.version, quantity=Decimal("48"), remarks="2 cartons"))
        assert changed.quantity == Decimal("48") and changed.remarks == "2 cartons" and c.version == d.version + 1
        with pytest.raises(VersionConflict):
            challans.update_line(uow, d.id, line.id, ChallanLineUpdate(expected_version=d.version, quantity=Decimal("1")))
        with pytest.raises(ValidationFailed) as exc:
            challans.update_line(uow, d.id, line.id, ChallanLineUpdate(expected_version=c.version, quantity=Decimal("1.5")))
        assert "not_integer" in {e["code"] for e in exc.value.extra["errors"]}
        unchanged, _ = challans.update_line(uow, d.id, line.id, ChallanLineUpdate(expected_version=c.version, remarks="2 cartons"))
        assert unchanged.version == c.version  # a no-op edit does not bump the version
        with pytest.raises(NotFound):
            challans.update_line(uow, d.id, uuid.uuid4(), ChallanLineUpdate(expected_version=c.version, quantity=Decimal("2")))


def test_line_edit_over_http_replays_and_reports_failures(challan_client, challan_world: ChallanWorld) -> None:  # type: ignore[no-untyped-def]
    """The web's debounced PATCH: the same Idempotency-Key replays the stored answer; 409 and 422 are problem+json."""
    d = challan_world.new_draft(RAVI, ("OAK_TRAY", "40"), party_id=challan_world.ref("NORDHAUS"))
    url = f"{CHALLANS}/{d.id}/lines/{d.lines[0].id}"
    key = str(uuid.uuid7())
    first = challan_client.patch(url, json={"expected_version": d.version, "quantity": "41"}, headers=as_(RAVI, **{"Idempotency-Key": key}))
    assert first.status_code == 200 and first.json()["lines"][0]["quantity"] == "41"
    again = challan_client.patch(url, json={"expected_version": d.version, "quantity": "41"}, headers=as_(RAVI, **{"Idempotency-Key": key}))
    assert again.status_code == 200 and again.headers.get("Idempotent-Replayed") == "true"
    assert again.json()["version"] == first.json()["version"]
    stale = challan_client.patch(url, json={"expected_version": d.version, "quantity": "42"}, headers=as_(RAVI))
    problem(stale, 409, "version_conflict")
    bad = challan_client.patch(url, json={"expected_version": first.json()["version"], "quantity": "1.5"}, headers=as_(RAVI))
    body = problem(bad, 422, "validation_failed")
    assert any(e["code"] == "not_integer" for e in body["errors"])


def test_list_filters_before_paging(challan_world: ChallanWorld) -> None:
    """LM-87, API-57: search, status, type, return type, destination type / party, week, month and date range narrow
    the scoped set before paging; totals count the filtered set."""
    w = challan_world
    with w.uow(SAHIL) as uow:
        everything = challans.list_challans(uow, ChallanFilters(), limit=100)
        numbers = {c.challan_number for c in everything.items}
        assert {keys.CHALLANS.JOB_WORK, keys.CHALLANS.SAMPLE_MAISON, keys.CHALLANS.OUTWARD_DRAFT} <= numbers
        assert everything.items[0].challan_date >= everything.items[-1].challan_date  # newest first
        by_status = challans.list_challans(uow, ChallanFilters(status=[ChallanStatus.DRAFT]))
        assert {c.status for c in by_status.items} == {ChallanStatus.DRAFT} and by_status.total == 1
        by_type = challans.list_challans(uow, ChallanFilters(challan_type=[ChallanType.JOB_WORK, ChallanType.SAMPLE]))
        assert {c.challan_number for c in by_type.items} == {keys.CHALLANS.JOB_WORK, keys.CHALLANS.SAMPLE_MAISON}
        assert challans.list_challans(uow, ChallanFilters(return_type=ReturnType.NON_RETURNABLE)).total == 1
        assert {c.challan_number for c in challans.list_challans(uow, ChallanFilters(destination_type=[DestinationType.FABRICATOR])).items} == {keys.CHALLANS.JOB_WORK}
        assert challans.list_challans(uow, ChallanFilters(party_id=w.ref("MAISON"))).total == 1
        assert challans.list_challans(uow, ChallanFilters(destination="precision")).total == 1
        assert challans.list_challans(uow, ChallanFilters(q="JW-0918")).total == 1  # reference
        assert challans.list_challans(uow, ChallanFilters(q="maison atelier")).total == 1  # destination name
        assert challans.list_challans(uow, ChallanFilters(q=keys.CHALLANS.OUTWARD_DRAFT)).total == 1  # number
        assert challans.list_challans(uow, ChallanFilters(q="=cmd")).total == 0  # a bare token, never a formula
        this_week = challans.list_challans(uow, ChallanFilters(period="this_week"))  # type: ignore[arg-type]
        assert {c.challan_number for c in this_week.items} == {keys.CHALLANS.OUTWARD_DRAFT}  # D0 is a Monday
        this_month = challans.list_challans(uow, ChallanFilters(period="this_month"))  # type: ignore[arg-type]
        assert {keys.CHALLANS.JOB_WORK, keys.CHALLANS.SAMPLE_MAISON, keys.CHALLANS.OUTWARD_DRAFT} <= {c.challan_number for c in this_month.items}
        d0 = date(2026, 10, 12)
        ranged = challans.list_challans(uow, ChallanFilters(date_from=d0 - timedelta(days=4), date_to=d0 - timedelta(days=1)))
        assert {c.challan_number for c in ranged.items} == {keys.CHALLANS.SAMPLE_MAISON}
        pending = challans.list_challans(uow, ChallanFilters(pending_returnable=True))
        assert {c.challan_number for c in pending.items} == {keys.CHALLANS.JOB_WORK, keys.CHALLANS.SAMPLE_MAISON}
        page = challans.list_challans(uow, ChallanFilters(), limit=2, offset=0)
        assert len(page.items) == 2 and page.total == everything.total and page.limit == 2
        rest = challans.list_challans(uow, ChallanFilters(), limit=2, offset=2)
        assert {c.id for c in page.items}.isdisjoint({c.id for c in rest.items})
    with w.uow(RAVI) as uow:  # scope=mine narrows to the actor's own
        assert challans.list_challans(uow, ChallanFilters(scope="mine")).total == everything.total  # Ravi owns all three


def test_duplicate_with_lines_new_number(challan_world: ChallanWorld) -> None:
    """LM-89, API-65: duplicating copies the header and the lines into a new draft with the next number."""
    w = challan_world
    source = w.challan(RAVI, keys.CHALLAN_REFS.JOB_WORK)
    with w.uow(RAVI) as uow:
        copy = challans.detail(uow, challans.duplicate_challan(uow, source.id))
    assert copy.id != source.id and copy.challan_number != source.challan_number and copy.challan_number == "DC-2026-0004"
    assert copy.status == ChallanStatus.DRAFT and copy.revision_no == 0 and copy.origin == "duplicate"
    assert copy.duplicated_from and copy.duplicated_from.id == source.id and copy.challan_date == date(2026, 10, 12)
    assert (copy.challan_type, copy.return_type, copy.destination_type, copy.destination_party) == (
        source.challan_type, source.return_type, source.destination_type, source.destination_party)
    assert [(ln.line_no, ln.item_code, ln.quantity, ln.unit) for ln in copy.lines] == [(ln.line_no, ln.item_code, ln.quantity, ln.unit) for ln in source.lines]
    assert all(ln.id not in {s.id for s in source.lines} for ln in copy.lines)
    assert copy.return_links == [] and copy.history == []
    with w.uow(RAVI) as uow:  # the original is untouched
        assert challans.get_challan(uow, source.id).version == source.version
