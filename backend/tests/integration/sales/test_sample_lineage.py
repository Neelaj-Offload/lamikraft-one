"""Sample lineage (Slice 5): a requested sample links the delivery challan that will carry it; issuing that challan
dispatches the sample even though ``challans.challan.issued`` carries ``sample_id = null``; the lineage view shows the
custom product, spec revision, quote, challan and catalogue product through each module's own scope.

Security: the challan must be visible to the actor (404 otherwise), for the sample's customer, outbound and not
cancelled (422); the challan is fixed once the sample is dispatched (409); a manual dispatch naming a challan gets the
same checks; lineage of a record outside the actor's scope is ``not_visible`` without its identity."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.errors import Conflict, NotFound, ValidationFailed
from app.modules.challans import service as challans
from app.modules.challans.schemas import (
    ChallanCreate,
    ChallanLineCreate,
    ChallanTransition,
    ChallanType,
    LineType,
    ReturnType,
)
from app.modules.challans.transitions import transition_challan_command
from app.modules.sales import service as sales
from app.modules.sales.samples import dispatch_by_challan
from app.modules.sales.schemas import (
    CustomProductCreate,
    SampleChallanLink,
    SampleCreate,
    SampleTransition,
    SpecRevisionCreate,
)
from app.platform.events.models import DomainEvent
from app.seed.world import keys
from tests.integration.challans.world import with_uoms
from tests.integration.sales.world import SalesWorld

pytestmark = pytest.mark.db
MEERA, NEHA, SAHIL, RAVI = keys.USERS.MEERA, keys.USERS.NEHA, keys.USERS.SAHIL, keys.USERS.RAVI


@pytest.fixture
def w(world: SalesWorld) -> SalesWorld:
    with_uoms(world)
    return world


def _challan(w: SalesWorld, person: str, party: str = "NORDHAUS", **header: object) -> uuid.UUID:
    with w.uow(person) as uow:
        body = ChallanCreate(party_id=w.ref(party), lines=[ChallanLineCreate(line_type=LineType.CATALOG,
                                                                              product_id=w.ref("OAK_TRAY"), quantity=Decimal(2))],
                             **header)  # type: ignore[arg-type]
        return challans.create_challan(uow, body).id


def _challan_move(w: SalesWorld, challan_id: uuid.UUID, action: str, **extra: object) -> None:
    with w.uow(RAVI, idempotency_key=str(uuid.uuid7())) as uow:
        version = challans.get_challan(uow, challan_id).version
        transition_challan_command(uow, challan_id, ChallanTransition(action=action, expected_version=version, **extra))  # type: ignore[arg-type]


def _sample(w: SalesWorld, person: str = MEERA, **extra: object):  # type: ignore[no-untyped-def]
    with w.uow(person) as uow:
        s, _ = sales.create_sample_command(uow, SampleCreate(party_id=w.ref("NORDHAUS"), quantity=Decimal(2), **extra))  # type: ignore[arg-type]
        return s


def _link(w: SalesWorld, person: str, sample_id: uuid.UUID, challan_id: uuid.UUID | None, key: str | None = None,  # type: ignore[no-untyped-def]
          version: int | None = None):
    with w.uow(person, idempotency_key=key or str(uuid.uuid7())) as uow:
        version = version if version is not None else sales.get_sample(uow, sample_id).version
        out, replayed = sales.sample_link_challan_command(uow, sample_id, SampleChallanLink(expected_version=version, challan_id=challan_id))
        return out, replayed


def _lineage(w: SalesWorld, person: str, sample_id: uuid.UUID):  # type: ignore[no-untyped-def]
    with w.uow(person) as uow:
        return sales.sample_lineage(uow, sample_id)


def test_linked_challan_issue_dispatches_and_lineage_shows_every_link(w: SalesWorld) -> None:
    q = w.new_draft(MEERA, "NORDHAUS", ("OAK_TRAY", "240"))
    with w.uow(MEERA) as uow:
        custom = sales.create_custom_product(uow, CustomProductCreate(product_name="Walnut tray variant"))
        spec = sales.record_spec_revision(uow, custom.id, SpecRevisionCreate(sample_reference="first article"))
    sample = _sample(w, quote_id=q.id, custom_product_id=custom.id, spec_revision_id=spec.id)
    sibling = _sample(w, custom_product_id=custom.id, description="Second finish")
    assert sample.capabilities["link_challan"].allowed
    before = _lineage(w, MEERA, sample.id)
    assert before.missing == ["challan"] and before.challan is None
    challan_id = _challan(w, MEERA, challan_type=ChallanType.SAMPLE)
    key = str(uuid.uuid7())
    linked, replayed = _link(w, MEERA, sample.id, challan_id, key, sample.version)
    again, replayed_again = _link(w, MEERA, sample.id, challan_id, key, sample.version)  # same request: the stored answer
    assert (linked.status, linked.challan_id, replayed, replayed_again) == ("requested", challan_id, False, True)
    assert again.version == linked.version
    _challan_move(w, challan_id, "issue")
    w.drain()  # sales.sample_dispatch on challans.challan.issued (its sample_id is null)
    with w.uow(MEERA) as uow:
        after = sales.get_sample(uow, sample.id)
        other = sales.get_sample(uow, sibling.id)
        dispatched = uow.session.scalars(select(DomainEvent).where(DomainEvent.aggregate_id == sample.id,
                                                                   DomainEvent.event_type == "sales.sample.dispatched")).all()
    assert (after.status, after.challan_id) == ("dispatched", challan_id)
    assert other.status == "requested"  # not linked: untouched
    assert [e.payload["challan_id"] for e in dispatched] == [str(challan_id)]
    view = _lineage(w, MEERA, sample.id)
    assert view.missing == []
    assert (view.custom_product.state, view.custom_product.label, view.custom_product.path) == (
        "linked", custom.custom_code, f"/sales/custom-products/{custom.id}")
    assert view.spec_revision.state == "linked" and view.spec_revision.facts["sample_reference"] == "first article"
    assert (view.quote.label, view.quote.status) == (q.quote_number, "draft")
    assert view.challan.state == "linked" and view.challan.status == "issued" and view.challan.facts["challan_type"] == "sample"
    assert view.challan.path == f"/operations/challans/{challan_id}"
    assert [r.label for r in view.related_samples] == [sibling.sample_number]
    kinds = [e.kind for e in view.timeline]
    assert kinds.index("custom_product_created") < kinds.index("sample_requested") < kinds.index("challan_issued")
    assert kinds[-1] == "sample_dispatched" and view.timeline[-1].label.startswith(f"Dispatched on {view.challan.label}")
    # the challan is fixed once dispatched
    with pytest.raises(Conflict) as exc:
        _link(w, MEERA, sample.id, None)
    assert exc.value.code == "sample_not_requested"


def test_linking_an_issued_challan_dispatches_at_its_issue_time_and_unlink_while_requested(w: SalesWorld) -> None:
    challan_id = _challan(w, MEERA)
    _challan_move(w, challan_id, "issue")
    with w.uow(MEERA) as uow:
        issued_at = challans.get_challan(uow, challan_id).issued_at
    draft_challan = _challan(w, MEERA, challan_type=ChallanType.SAMPLE)
    s = _sample(w, description="Edge band chips")
    linked, _ = _link(w, MEERA, s.id, draft_challan)
    unlinked, _ = _link(w, MEERA, s.id, None)
    assert (linked.challan_id, unlinked.challan_id, unlinked.status) == (draft_challan, None, "requested")
    out, _ = _link(w, MEERA, s.id, challan_id)
    assert (out.status, out.challan_id, out.dispatched_at) == ("dispatched", challan_id, issued_at)
    assert out.capabilities["link_challan"].allowed is False and out.capabilities["link_challan"].reason_code == "sample_not_requested"


def test_challan_checks_on_link_and_on_manual_dispatch(w: SalesWorld) -> None:
    s = _sample(w, description="Decor chips")
    other_party = _challan(w, MEERA, party="MAISON")
    inward = _challan(w, MEERA, challan_type=ChallanType.INWARD, return_type=ReturnType.NON_RETURNABLE)
    cancelled = _challan(w, MEERA)
    _challan_move(w, cancelled, "cancel", reason="wrong address")
    for challan_id, code in ((other_party, "challan_of_other_party"), (inward, "challan_not_outbound"),
                             (cancelled, "challan_cancelled")):
        with pytest.raises(ValidationFailed) as exc:
            _link(w, MEERA, s.id, challan_id)
        assert exc.value.extra["errors"][0]["code"] == code
    # a challan of another owner (sales reads challans at own scope) is not found: never confirmed
    ravis = _challan(w, RAVI)
    with pytest.raises(NotFound):
        _link(w, MEERA, s.id, ravis)
    with pytest.raises(NotFound):
        _link(w, MEERA, s.id, uuid.uuid7())
    # the manual dispatch naming a challan gets the same checks
    with w.uow(MEERA, idempotency_key=str(uuid.uuid7())) as uow:
        version = sales.get_sample(uow, s.id).version
        with pytest.raises(ValidationFailed) as exc:
            sales.sample_transition_command(uow, s.id, SampleTransition(action="dispatch", expected_version=version,
                                                                        challan_id=other_party))
    assert exc.value.extra["errors"][0]["code"] == "challan_of_other_party"
    # another salesperson cannot see the sample at all
    with pytest.raises(NotFound):
        _link(w, NEHA, s.id, None)
    with pytest.raises(NotFound):
        _lineage(w, NEHA, s.id)


def test_lineage_hides_records_outside_the_actors_scope(w: SalesWorld) -> None:
    s = _sample(w, product_id=w.ref("OAK_TRAY"))
    ravis = _challan(w, RAVI)  # Meera (sales, challans at own scope) cannot read it
    with w.uow(SAHIL) as uow:  # the subscription path, as in test_samples
        assert dispatch_by_challan(uow, s.id, ravis) is True
    mine = _lineage(w, MEERA, s.id)
    assert mine.challan is not None and mine.challan.state == "not_visible"
    assert (mine.challan.id, mine.challan.label, mine.challan.path) == (None, None, None)
    assert mine.product is not None and mine.product.state == "linked" and mine.product.id == w.ref("OAK_TRAY")
    assert mine.missing == ["custom_product", "quote"]
    management = _lineage(w, SAHIL, s.id)
    assert management.challan is not None and management.challan.state == "linked" and management.challan.id == ravis
