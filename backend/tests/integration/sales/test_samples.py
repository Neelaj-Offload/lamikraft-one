"""Samples (SMP-YYYY-NNNN) with lineage to quotes, custom products and spec revisions: lifecycle, required evidence,
scope, the challan subscription and feedback copied to the spec revision."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.errors import InvalidTransition, NotFound, ValidationFailed
from app.modules.challans import service as challans
from app.modules.challans.schemas import ChallanCreate
from app.modules.sales import service as sales
from app.modules.sales.models import CustomProductSpecRevision
from app.modules.sales.samples import dispatch_by_challan
from app.modules.sales.schemas import (
    CustomProductCreate,
    SampleCreate,
    SampleFilters,
    SampleTransition,
    SpecRevisionCreate,
)
from app.platform.events.models import DomainEvent
from app.seed.world import keys
from tests.integration.catalogue.world import product_name
from tests.integration.sales.world import SalesWorld

pytestmark = pytest.mark.db
MEERA, NEHA, SAHIL, RAVI = keys.USERS.MEERA, keys.USERS.NEHA, keys.USERS.SAHIL, keys.USERS.RAVI


def _move(world: SalesWorld, person: str, sample_id, action: str, **kw):  # type: ignore[no-untyped-def]
    with world.uow(person) as uow:
        version = sales.get_sample(uow, sample_id).version
        detail, _ = sales.sample_transition_command(uow, sample_id, SampleTransition(action=action, expected_version=version, **kw))
        return detail


def test_sample_lifecycle_lineage_and_numbering(world: SalesWorld) -> None:
    q = world.new_draft(MEERA, "NORDHAUS", ("OAK_TRAY", "240"))
    with world.uow(MEERA) as uow:
        custom = sales.create_custom_product(uow, CustomProductCreate(product_name="Oak tray sample variant"))
        spec = sales.record_spec_revision(uow, custom.id, SpecRevisionCreate(sample_reference="first article"))
        s1, _ = sales.create_sample_command(uow, SampleCreate(party_id=world.ref("NORDHAUS"), quote_id=q.id, custom_product_id=custom.id,
                                                              spec_revision_id=spec.id, quantity=Decimal("2")))
        s2, _ = sales.create_sample_command(uow, SampleCreate(party_id=world.ref("NORDHAUS"), product_id=world.ref("OAK_TRAY"), quantity=Decimal("1")))
    assert (s1.sample_number, s2.sample_number) == ("SMP-2026-0001", "SMP-2026-0002")
    assert (s1.quote_number, s1.custom_code, s1.description, s1.status) == (q.quote_number, custom.custom_code, "Oak tray sample variant", "requested")
    assert s2.description == product_name("OAK_TRAY")  # the product name when no description is given
    assert [t.action for t in s1.allowed_transitions] == ["dispatch", "cancel"]
    with pytest.raises(ValidationFailed):  # a dispatch needs a courier reference or a challan
        _move(world, MEERA, s1.id, "dispatch")
    with pytest.raises(InvalidTransition):
        _move(world, MEERA, s1.id, "deliver", evidence_kind="courier_tracking")
    dispatched = _move(world, MEERA, s1.id, "dispatch", dispatch_reference="DHL 7781 2231")
    delivered = _move(world, MEERA, s1.id, "deliver", evidence_kind="courier_tracking")
    with pytest.raises(ValidationFailed):
        _move(world, MEERA, s1.id, "record_feedback", feedback="Nice")
    fed = _move(world, MEERA, s1.id, "record_feedback", feedback="Handles should be thicker", feedback_outcome="changes_requested")
    closed = _move(world, MEERA, s1.id, "close")
    assert (dispatched.status, delivered.status, fed.status, closed.status) == ("dispatched", "delivered", "feedback_received", "closed")
    assert closed.allowed_transitions == [] and closed.feedback_outcome == "changes_requested"
    with world.uow(SAHIL) as uow:
        rev = uow.session.get(CustomProductSpecRevision, spec.id)
        assert rev is not None and rev.feedback == "Handles should be thicker"  # feedback copied onto the spec revision
        names = [r[0] for r in uow.session.execute(select(DomainEvent.event_type).where(DomainEvent.aggregate_id == s1.id)
                                                   .order_by(DomainEvent.seq)).all()]
    assert names == ["sales.sample.created", "sales.sample.dispatched", "sales.sample.delivered", "sales.sample.feedback_recorded",
                     "sales.sample.closed"]
    cancelled = _move(world, MEERA, s2.id, "cancel", reason="Customer has one")
    assert cancelled.status == "cancelled"
    # scope: Neha cannot see Meera's samples; operations read and move them
    with pytest.raises(NotFound), world.uow(NEHA) as uow:
        sales.get_sample(uow, s1.id)
    with world.uow(RAVI) as uow:
        assert sales.list_samples(uow, SampleFilters()).total == 2
        assert sales.list_samples(uow, SampleFilters(q="DHL")).total == 1
        assert sales.sample_status_counts(uow, SampleFilters())["closed"] == 1


def test_challan_issue_dispatches_the_sample(world: SalesWorld) -> None:
    with world.uow(MEERA) as uow:
        s, _ = sales.create_sample_command(uow, SampleCreate(party_id=world.ref("NORDHAUS"), description="Decor chips", quantity=Decimal("5")))
    # a real draft challan: sales_sample.challan_id is a foreign key since the Slice-2 merge (migration 0015)
    with world.uow(keys.USERS.RAVI) as uow:
        challan = challans.create_challan(uow, ChallanCreate(party_id=world.ref("NORDHAUS"))).id
    with world.uow(SAHIL) as uow:
        assert dispatch_by_challan(uow, s.id, challan) is True
        assert dispatch_by_challan(uow, s.id, challan) is False  # idempotent
    with world.uow(MEERA) as uow:
        after = sales.get_sample(uow, s.id)
    assert (after.status, after.challan_id) == ("dispatched", challan)
