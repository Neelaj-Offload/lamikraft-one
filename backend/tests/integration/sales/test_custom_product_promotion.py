"""Promotion of a custom product to a catalogue master product (LM-70, FG-CP-05, LP-08.4, REUSE-04): an approved product
with an approved spec revision is requested (payload validated, bound to an approval by hash), approved by a second
person who may create products, executed through the catalogue service with lineage; execution is idempotent and a
specification change after the request needs a fresh one."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.errors import Conflict, Forbidden, ValidationFailed
from app.modules.approvals import service as approvals
from app.modules.catalogue import service as catalogue
from app.modules.catalogue.models import Product
from app.modules.sales import service as sales
from app.modules.sales.schemas import (
    CustomProductCreate,
    CustomProductTransition,
    CustomProductUpdate,
    PromotionRequest,
    SpecOutcomeIn,
    SpecRevisionCreate,
)
from app.platform.events.models import DomainEvent
from app.seed.world import keys
from tests.integration.sales.world import SalesWorld

pytestmark = pytest.mark.db
MEERA, SAHIL, PRIYA, RAVI = keys.USERS.MEERA, keys.USERS.SAHIL, keys.USERS.PRIYA, keys.USERS.RAVI


def _approved_product(world: SalesWorld):  # type: ignore[no-untyped-def]
    with world.uow(MEERA) as uow:
        c = sales.create_custom_product(uow, CustomProductCreate(
            custom_type="fully_new", product_name="Teak tray 600", category_id=world.ref(keys.CATEGORIES.SERVEWARE),  # type: ignore[arg-type]
            dimensions_text="600 x 400 mm", decor_no="0310", finish="Oiled", quoted_price=Decimal("38"), quoted_currency="EUR",
        ))
        for action in ("develop", "sample"):
            sales.transition_custom_product(uow, c.id, CustomProductTransition(action=action, expected_version=c.version))
        rev = sales.record_spec_revision(uow, c.id, SpecRevisionCreate(sample_reference="S-TEAK-1"))
        sales.decide_spec_revision(uow, c.id, rev.id, SpecOutcomeIn(outcome="approved", expected_version=rev.version))
        sales.transition_custom_product(uow, c.id, CustomProductTransition(action="approve", expected_version=c.version))
        return c.id


def _request(world: SalesWorld, custom_id, person: str = SAHIL, key: str = "LK-TT-0600"):  # type: ignore[no-untyped-def]
    with world.uow(person) as uow:
        return sales.request_promotion(uow, custom_id, PromotionRequest(product_key=key, display_sku=key, unit_of_sale="pcs"))


def _decide(world: SalesWorld, person: str, proposal_id, decision: str = "approve"):  # type: ignore[no-untyped-def]
    with world.uow(person) as uow:
        proposal = approvals.get(uow, proposal_id)
        return approvals.decide(uow, proposal_id, decision=decision, content_hash_seen=proposal.content_hash,
                                expected_version=proposal.version, reason="ok").status


def test_request_approve_execute_idempotent(world: SalesWorld) -> None:
    custom_id = _approved_product(world)
    with pytest.raises(Forbidden):  # sales cannot promote (management can)
        _request(world, custom_id, MEERA)
    with pytest.raises(ValidationFailed):  # the payload is validated before the request (key exists)
        _request(world, custom_id, key="LK-OT-0450")
    promo = _request(world, custom_id)
    assert promo.status == "pending_approval" and promo.proposal_id is not None
    assert promo.payload["lineage"]["custom_code"] == "CP-0001" and promo.payload_hash == approvals.content_hash(promo.payload)
    with pytest.raises(Forbidden):  # the requester never approves
        _decide(world, SAHIL, promo.proposal_id)
    with pytest.raises(Exception):  # noqa: B017  operations is not an eligible approver (404 or 403)
        _decide(world, RAVI, promo.proposal_id)
    assert _decide(world, PRIYA, promo.proposal_id) == "approved"
    with world.uow(MEERA) as uow:
        detail = sales.get_custom_product(uow, custom_id)
    executed = detail.promotions[-1]
    assert executed.status == "executed" and executed.executed_product_id is not None
    assert detail.status == "converted_to_standard" and detail.promoted_product_id == executed.executed_product_id
    assert detail.allowed_transitions == [] and not detail.capabilities["update"].allowed
    with world.uow(PRIYA) as uow:
        product = catalogue.get_product(uow, executed.executed_product_id)
        row = uow.session.get(Product, executed.executed_product_id)
        assert (product.product_key, product.product_name, product.decor.decor_no) == ("LK-TT-0600", "Teak tray 600", "0310")
        assert row is not None and row.origin == "promotion" and row.origin_ref == "CP-0001"
        assert row.source_extra["promotion"]["custom_product_id"] == str(custom_id)
        again = sales.execute_promotion(uow, custom_id, executed.id)  # idempotent
        assert again.executed_product_id == executed.executed_product_id
        count = uow.session.scalar(select(Product.id).where(Product.product_key == "LK-TT-0600").with_only_columns(Product.id).limit(2))
        assert count is not None
    with world.uow(SAHIL) as uow:
        names = [r[0] for r in uow.session.execute(select(DomainEvent.event_type).where(DomainEvent.aggregate_id == custom_id)
                                                   .order_by(DomainEvent.seq)).all()]
    assert "sales.custom_product.promotion_requested" in names and names[-1] == "sales.custom_product.promoted"


def test_spec_change_after_request_needs_a_fresh_request(world: SalesWorld) -> None:
    custom_id = _approved_product(world)
    promo = _request(world, custom_id)
    with world.uow(MEERA) as uow:
        version = sales.get_custom_product(uow, custom_id).version
        sales.update_custom_product(uow, custom_id, CustomProductUpdate(expected_version=version, finish="Lacquered"))
    with world.uow(SAHIL) as uow:
        assert sales.get_custom_product(uow, custom_id).promotions[-1].status == "withdrawn"
    with pytest.raises(Conflict):  # the proposal was invalidated with the request
        _decide(world, PRIYA, promo.proposal_id)
    rejected = _request(world, custom_id)
    assert _decide(world, PRIYA, rejected.proposal_id, "reject") == "rejected"
    with world.uow(SAHIL) as uow:
        detail = sales.get_custom_product(uow, custom_id)
    assert detail.status == "approved" and detail.promotions[-1].status == "rejected"
