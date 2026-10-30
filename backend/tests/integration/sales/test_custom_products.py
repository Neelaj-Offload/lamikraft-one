"""Custom products (LM-62..69, FG-CP-01..18, API-47..50, BR-09, LP-08.1..08.5): every legacy field, CP-NNNN codes from the
atomic allocator (never reused), list/search/filter/paging by product_name, the state machine with reasons, archive
rules, duplicate "X (Copy)", spec revisions with samples, quote links and the guarded CSV export."""

from __future__ import annotations

import csv
import io
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.core.errors import Conflict, Forbidden, InvalidTransition, NotFound, ValidationFailed
from app.modules.sales import service as sales
from app.modules.sales.models import CustomProduct
from app.modules.sales.schemas import (
    CostingCreate,
    CustomProductArchive,
    CustomProductCreate,
    CustomProductFilters,
    CustomProductTransition,
    CustomProductUpdate,
    QuoteLineCreate,
    SampleCreate,
    SpecOutcomeIn,
    SpecRevisionCreate,
)
from app.platform.events.models import DomainEvent
from app.seed.world import keys
from tests.integration.sales.world import SalesWorld

pytestmark = pytest.mark.db
MEERA, NEHA, SAHIL, RAVI, ANANYA, PRIYA = (keys.USERS.MEERA, keys.USERS.NEHA, keys.USERS.SAHIL, keys.USERS.RAVI,
                                           keys.USERS.ANANYA, keys.USERS.PRIYA)

FULL = {
    "custom_type": "modified_catalog",
    "base_product_id": None,  # set per test (the oak tray)
    "customer_specific_flag": True,
    "party_id": None,
    "inquiry_reference": "NH-RFQ-2026-118",
    "product_name": "Oak tray 520 with brass handles",
    "description": "Oak serving tray, longer, two brass handles, matt lacquer",
    "dimensions_text": "520 x 330 x 40 mm",
    "length_mm": "520", "width_mm": "330", "height_mm": "40",
    "thickness_mm": "12", "thickness_text": "12 mm",
    "decor_no": "0120", "decor_name": "Natural oak", "finish": "Matt lacquer", "shape": "Rectangle",
    "groove_count": 2, "bowl_count": 0, "handle_type": "Brass bar",
    "packaging_notes": "Each tray in a poly bag, 12 per carton",
    "packaging": {"carton_qty": 12, "inner_qty": 1, "packing_type": "poly bag", "unit_weight_g": "850", "cbm": "0.045"},
    "quoted_price": "31.5", "quoted_currency": "EUR",
    "unit_code": "pcs",
    "remarks": "Customer wants the sample before Diwali",
}


def create(world: SalesWorld, person: str = MEERA, **overrides: object):  # type: ignore[no-untyped-def]
    data = {**FULL, "base_product_id": str(world.ref("OAK_TRAY")), "party_id": str(world.ref("NORDHAUS")), **overrides}
    with world.uow(person) as uow:
        detail, _ = sales.create_custom_product_command(uow, CustomProductCreate.model_validate(data))
        return detail


def move(world: SalesWorld, person: str, custom_id, action: str, reason: str | None = None):  # type: ignore[no-untyped-def]
    with world.uow(person) as uow:
        version = sales.get_custom_product(uow, custom_id).version
        custom = sales.transition_custom_product(uow, custom_id, CustomProductTransition(action=action, expected_version=version, reason=reason))
        return sales.custom_product_detail(uow, custom)


def approved_spec(world: SalesWorld, custom_id, person: str = MEERA):  # type: ignore[no-untyped-def]
    with world.uow(person) as uow:
        rev = sales.record_spec_revision(uow, custom_id, SpecRevisionCreate(sample_reference="S-1", feedback="looks right"))
        sales.decide_spec_revision(uow, custom_id, rev.id, SpecOutcomeIn(outcome="approved", expected_version=rev.version))
        return rev.id


def test_custom_product_lifecycle_and_fields(world: SalesWorld) -> None:
    """FG-CP-01..18 round trip; created_by and timestamps from the actor and the Clock; updates are versioned."""
    c = create(world)
    assert c.custom_code == "CP-0001" and c.status == "inquiry" and c.custom_type == "modified_catalog"
    assert c.base_product_key == "LK-OT-0450" and c.party is not None and c.party.display_name.startswith("Nordhaus")
    assert (c.length_mm, c.width_mm, c.height_mm, c.thickness_mm) == (Decimal("520.000"), Decimal("330.000"), Decimal("40.000"), Decimal("12.000"))
    assert (c.decor_no, c.decor_name, c.finish, c.shape, c.groove_count, c.bowl_count, c.handle_type) == (
        "0120", "Natural oak", "Matt lacquer", "Rectangle", 2, 0, "Brass bar")
    assert c.packaging is not None and c.packaging.carton_qty == 12 and c.packaging.unit_weight_g == Decimal("850")
    assert c.quoted_price is not None and (c.quoted_price.amount, c.quoted_price.currency) == (Decimal("31.5000"), "EUR")
    assert (c.customer_specific_flag, c.inquiry_reference, c.remarks, c.unit_code) == (True, "NH-RFQ-2026-118", FULL["remarks"], "pcs")
    assert c.created_by is not None and c.created_by.id == world.user_id(MEERA) and c.owner.id == world.user_id(MEERA)
    assert "costing" in c.redacted_fields and not c.capabilities["read_costing"].allowed
    with world.uow(MEERA) as uow:
        updated = sales.update_custom_product(uow, c.id, CustomProductUpdate(expected_version=c.version, product_name="Oak tray 520 brass",
                                                                             groove_count=3))
        assert (updated.product_name, updated.groove_count, updated.version) == ("Oak tray 520 brass", 3, c.version + 1)
    with pytest.raises(Conflict), world.uow(MEERA) as uow:  # stale version
        sales.update_custom_product(uow, c.id, CustomProductUpdate(expected_version=c.version, remarks="x"))
    with pytest.raises(ValidationFailed), world.uow(MEERA) as uow:  # a modified catalogue product needs its base
        sales.update_custom_product(uow, c.id, CustomProductUpdate(expected_version=updated.version, base_product_id=None))
    with pytest.raises(ValidationFailed):  # price and currency come together
        create(world, quoted_currency=None)
    with world.uow(SAHIL) as uow:
        events = [r[0] for r in uow.session.execute(select(DomainEvent.event_type).where(DomainEvent.aggregate_id == c.id)
                                                    .order_by(DomainEvent.seq)).all()]
    assert events == ["sales.custom_product.created", "sales.custom_product.updated"]


def test_codes_unique_never_reused(world: SalesWorld) -> None:
    """BR-09 / BUG-13: CP-NNNN from the atomic allocator; an archived product keeps its code and the next one moves on;
    the code is immutable in the database."""
    first, second = create(world), create(world, product_name="Ash board custom", custom_type="fully_new", base_product_id=None)
    assert (first.custom_code, second.custom_code) == ("CP-0001", "CP-0002")
    with world.uow(SAHIL) as uow:
        sales.archive_custom_product(uow, second.id, CustomProductArchive(expected_version=second.version, reason="test"))
    third = create(world, product_name="Third")
    assert third.custom_code == "CP-0003"
    with pytest.raises(DBAPIError, match="immutable"), world.uow(SAHIL) as uow:
        uow.session.execute(text("UPDATE sales_custom_product SET custom_code = 'CP-0009' WHERE id = :i"), {"i": first.id})


def test_list_search_filter_paging(world: SalesWorld) -> None:
    """LM-63 / API-47: search by product_name (BUG-08), code, decor and customer; filters before paging; own scope."""
    create(world)
    create(world, product_name="Walnut board with groove", custom_type="fully_new", base_product_id=None, decor_no="0777")
    create(world, NEHA, product_name="Maple trivet round", custom_type="quote_only", base_product_id=None, party_id=str(world.ref("THORNBURY")))
    with world.uow(SAHIL) as uow:
        assert sales.list_custom_products(uow, CustomProductFilters()).total == 3
        assert [i.product_name for i in sales.list_custom_products(uow, CustomProductFilters(q="walnut")).items] == ["Walnut board with groove"]
        assert sales.list_custom_products(uow, CustomProductFilters(q="CP-0003")).items[0].product_name == "Maple trivet round"
        assert sales.list_custom_products(uow, CustomProductFilters(q="0777")).total == 1
        assert sales.list_custom_products(uow, CustomProductFilters(custom_type="quote_only")).total == 1  # type: ignore[arg-type]
        assert sales.list_custom_products(uow, CustomProductFilters(q="%_")).total == 0  # LIKE metacharacters are literal
        page = sales.list_custom_products(uow, CustomProductFilters(), limit=2, offset=2)
        assert (page.total, len(page.items)) == (3, 1)
        counts = sales.custom_status_counts(uow, CustomProductFilters())
    assert counts["inquiry"] == 3 and set(counts) == {s for s in counts}
    with world.uow(MEERA) as uow:  # sales users see their own products only
        assert {i.custom_code for i in sales.list_custom_products(uow, CustomProductFilters()).items} == {"CP-0001", "CP-0002"}
    with world.uow(RAVI) as uow:  # operations read all
        assert sales.list_custom_products(uow, CustomProductFilters()).total == 3


def test_transition_table_and_reasons(world: SalesWorld) -> None:
    """FG-CP-16 / LP-08.2: the eight states with valid transitions; reasons for reject, park (dormant) and reopen;
    ``approved`` needs an approved spec revision; dormant reactivates to the state it came from."""
    c = create(world)
    assert [t.action for t in c.allowed_transitions] == ["develop", "sample", "quote", "reject", "park"]
    move(world, MEERA, c.id, "develop")
    sample = move(world, MEERA, c.id, "sample")
    assert sample.status == "sample_stage" and "approve" not in [t.action for t in sample.allowed_transitions]
    with pytest.raises(Conflict) as exc:
        move(world, MEERA, c.id, "approve")
    assert exc.value.code == "spec_approval_required"
    with pytest.raises(ValidationFailed):
        move(world, MEERA, c.id, "park")
    parked = move(world, MEERA, c.id, "park", "Customer paused the project")
    assert (parked.status, parked.dormant_from_status, parked.status_reason) == ("dormant", "sample_stage", "Customer paused the project")
    assert [(t.action, t.to_status) for t in parked.allowed_transitions] == [("reactivate", "sample_stage")]
    assert move(world, MEERA, c.id, "reactivate").status == "sample_stage"
    approved_spec(world, c.id)
    approved = move(world, MEERA, c.id, "approve")
    assert approved.status == "approved"
    with pytest.raises(InvalidTransition):
        move(world, MEERA, c.id, "develop")
    rejected = move(world, MEERA, create(world).id, "reject", "Too costly to tool")
    assert rejected.status == "rejected" and [t.action for t in rejected.allowed_transitions] == ["reopen"]
    with pytest.raises(NotFound):  # Neha cannot touch Meera's product
        move(world, NEHA, c.id, "park", "x")
    with world.uow(MEERA) as uow:
        history = [(h.action.value, h.from_status, h.to_status) for h in sales.custom_history(uow, c.id)]
    assert history[0] == ("create", "inquiry", "inquiry") and history[-1] == ("transition", "sample_stage", "approved")


def test_archive_rules(world: SalesWorld) -> None:
    """LM-65: archive (the legacy admin delete) only when rejected, dormant, converted or never quoted; management only."""
    quoted = create(world)
    q = world.new_draft(MEERA, "NORDHAUS")
    with world.uow(MEERA) as uow:
        sales.add_line(uow, q.id, QuoteLineCreate(expected_version=q.version, line_type="custom", custom_product_id=quoted.id, quantity=Decimal("120")))
    with pytest.raises(Forbidden), world.uow(MEERA) as uow:  # sales cannot archive
        sales.archive_custom_product(uow, quoted.id, CustomProductArchive(expected_version=quoted.version))
    with pytest.raises(Conflict) as exc, world.uow(SAHIL) as uow:
        sales.archive_custom_product(uow, quoted.id, CustomProductArchive(expected_version=quoted.version))
    assert exc.value.code == "custom_product_in_use"
    with world.uow(SAHIL) as uow:
        assert not sales.get_custom_product(uow, quoted.id).capabilities["archive"].allowed
    parked = move(world, MEERA, quoted.id, "park", "On hold")
    with world.uow(SAHIL) as uow:
        sales.archive_custom_product(uow, quoted.id, CustomProductArchive(expected_version=parked.version, reason="cleanup"))
        archived = sales.get_custom_product(uow, quoted.id)
        assert archived.archived_at is not None and sales.list_custom_products(uow, CustomProductFilters()).total == 0
        assert sales.list_custom_products(uow, CustomProductFilters(include_archived=True)).total == 1
    with pytest.raises(Forbidden), world.uow(MEERA) as uow:  # archived products are read-only
        sales.update_custom_product(uow, quoted.id, CustomProductUpdate(expected_version=archived.version, remarks="x"))
    never = create(world)
    with world.uow(SAHIL) as uow:
        sales.archive_custom_product(uow, never.id, CustomProductArchive(expected_version=never.version))
        restored = sales.unarchive_custom_product(uow, never.id, CustomProductArchive(expected_version=never.version + 1))
        assert restored.archived_at is None


def test_duplicate_new_code_and_product_name_copy(world: SalesWorld) -> None:
    """LM-66 / API-50 / BUG-08: a new code and ``product_name`` "X (Copy)"; scoped (404 outside); no costing copied."""
    c = create(world)
    with world.uow(PRIYA) as uow:  # costing writers need the product in scope (admin here)
        sales.record_costing(uow, c.id, CostingCreate(cost_amount=Decimal("17.25"), cost_currency="EUR"))
    with world.uow(MEERA) as uow:
        copy, _ = sales.duplicate_custom_product_command(uow, c.id)
    assert copy.custom_code == "CP-0002" and copy.product_name == "Oak tray 520 with brass handles (Copy)"
    assert copy.status == "inquiry" and copy.duplicated_from_id == c.id and copy.decor_no == "0120" and copy.spec_revisions == []
    with world.uow(SAHIL) as uow:
        assert sales.list_costing(uow, copy.id) == []
    with pytest.raises(NotFound), world.uow(NEHA) as uow:
        sales.duplicate_custom_product_command(uow, c.id)


def test_csv_export_escaped_and_costing_guarded(world: SalesWorld) -> None:
    """LM-67 / API-48: export within scope, formula-escaped; costing columns only for cost readers who ask."""
    c = create(world, remarks="=cmd|' /C calc'!A0")
    create(world, NEHA, product_name="Neha's tray", custom_type="fully_new", base_product_id=None, party_id=str(world.ref("THORNBURY")))
    with world.uow(PRIYA) as uow:  # costing writers need the product in scope (admin here)
        sales.record_costing(uow, c.id, CostingCreate(cost_amount=Decimal("17.25"), cost_currency="EUR"))

    def rows(person: str, **kw: object) -> list[dict[str, str]]:
        with world.uow(person) as uow:
            content = sales.export_custom_products_csv(uow, CustomProductFilters(), **kw)
        assert content.startswith(b"\xef\xbb\xbf")
        return list(csv.DictReader(io.StringIO(content.decode("utf-8-sig"))))

    meera = rows(MEERA, include_costing=True)
    assert [r["Code"] for r in meera] == ["CP-0001"] and "Cost" not in meera[0]  # own scope; no cost read
    assert meera[0]["Remarks"].startswith("'=") and meera[0]["Product name"] == "Oak tray 520 with brass handles"
    assert "17.25" not in str(meera)
    sahil = rows(SAHIL)
    assert len(sahil) == 2 and "Cost" not in sahil[0]
    with_cost = rows(SAHIL, include_costing=True)
    assert next(r for r in with_cost if r["Code"] == "CP-0001")["Cost"] == "17.2500"
    with pytest.raises(Forbidden), world.uow(RAVI) as uow:
        sales.export_custom_products_csv(uow, CustomProductFilters())


def test_spec_revisions_and_quote_link(world: SalesWorld) -> None:
    """LP-08.5: spec revisions keep the sample history (approved revisions supersede earlier ones); quotes using the
    product are linked; issuing such a quote moves it forward to ``quoted`` (subscription, forward moves only)."""
    c = create(world)
    with world.uow(MEERA) as uow:
        smp = sales.create_sample(uow, SampleCreate(party_id=world.ref("NORDHAUS"), custom_product_id=c.id, quantity=Decimal("2")))
        rev1 = sales.record_spec_revision(uow, c.id, SpecRevisionCreate(sample_id=smp.id, sample_reference="DHL 123"))
        sales.decide_spec_revision(uow, c.id, rev1.id, SpecOutcomeIn(outcome="approved", expected_version=rev1.version))
        with pytest.raises(Conflict):  # a decided revision is immutable
            sales.decide_spec_revision(uow, c.id, rev1.id, SpecOutcomeIn(outcome="rejected", expected_version=rev1.version + 1))
        rev2 = sales.record_spec_revision(uow, c.id, SpecRevisionCreate(feedback="handles 5 mm thicker"))
        sales.decide_spec_revision(uow, c.id, rev2.id, SpecOutcomeIn(outcome="approved", expected_version=rev2.version))
        detail = sales.get_custom_product(uow, c.id)
    assert [(r.revision_no, r.outcome.value) for r in detail.spec_revisions] == [(1, "superseded"), (2, "approved")]
    assert detail.spec_revisions[0].sample_number is not None and detail.spec_revisions[0].spec_snapshot["product_name"] == c.product_name
    q = world.new_draft(MEERA, "NORDHAUS")
    with world.uow(MEERA) as uow:
        quote, line = sales.add_line(uow, q.id, QuoteLineCreate(expected_version=q.version, line_type="custom", custom_product_id=c.id,
                                                               quantity=Decimal("240")))
    world.transition(MEERA, q.id, "mark_sent")
    world.drain()
    with world.uow(MEERA) as uow:
        after = sales.get_custom_product(uow, c.id)
        history = sales.custom_history(uow, c.id)
    assert after.status == "quoted" and [(r.quote_number, r.line_no) for r in after.quotes] == [(quote.quote_number, 1)]
    assert history[-1].action.value == "auto_quoted" and history[-1].quote_id == q.id
    with world.uow(NEHA) as uow:  # quotes outside the actor's scope are not listed (and Neha cannot read the product)
        with pytest.raises(NotFound):
            sales.get_custom_product(uow, c.id)
    with world.uow(SAHIL) as uow:
        row = uow.session.get(CustomProduct, c.id)
        assert row is not None and row.status == "quoted"
    assert uuid.UUID(str(line.custom_product_id)) == c.id
