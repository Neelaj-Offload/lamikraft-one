"""Opening stock (operations.md §3, ADR-021): only through an approved batch, approved by a second person with MFA
step-up (never the creator, also a database CHECK), one posting per batch from the opening location, rejected where
non-opening movements already exist unless the line is a late opening; legacy challans never create stock."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.core.errors import Forbidden, ValidationFailed
from app.modules.inventory import documents
from app.modules.inventory.models import OpeningBatch, StockMovement, StockPosting
from app.modules.inventory.schemas import Decision, OpeningBatchCreate, OpeningLineIn, Versioned
from app.platform.authz.stepup import MfaRequired, ReauthRequired
from app.seed.world import keys
from tests.integration.inventory.world import InvWorld, assert_ledger_consistent

pytestmark = pytest.mark.db
RAVI, SAHIL, PRIYA = keys.USERS.RAVI, keys.USERS.SAHIL, keys.USERS.PRIYA


def test_opening_requires_approval_by_other_user_and_legacy_challans_create_no_stock(inv_world: InvWorld) -> None:
    w = inv_world
    # the seeded batch: created by Ravi, approved by Sahil, one posting from the opening location
    with w.system() as uow:
        seeded = uow.session.get(OpeningBatch, w.ref(keys.OPENING_BATCH_REFS.MAIN))
        assert seeded is not None and seeded.number == keys.OPENING_BATCHES.MAIN and seeded.status == "posted"
        assert seeded.created_by == w.ref(RAVI) and seeded.decided_by == w.ref(SAHIL)
        moves = list(uow.session.scalars(select(StockMovement).where(StockMovement.posting_id == seeded.posting_id)))
        assert len(moves) == 4 and all(m.from_warehouse_id is None for m in moves)
    # the legacy fixture challans (documents only) never posted stock
    assert w.postings("challan") == 0
    assert w.summary("WALNUT_BOARD")[0] == Decimal(40)
    # a new batch for a product that already moved (a bin relocation) is refused unless marked late
    from app.modules.inventory import service as inventory
    from app.modules.inventory.schemas import RelocationCreate

    with w.system() as uow:
        stock = inventory.default_location(uow, w.warehouse_id).id
    with w.uow(RAVI) as uow:
        documents.relocate(uow, RelocationCreate(product_id=w.ref("OAK_TRAY"), from_location_id=stock,
                                                 to_location_id=w.ref(keys.WAREHOUSE_REFS.BIN_A12), quantity=Decimal(1), unit="pcs"))
    line = OpeningLineIn(product_id=w.ref("OAK_TRAY"), quantity=Decimal(10))
    with pytest.raises(ReauthRequired), w.uow(RAVI) as uow:  # RA step-up for creating a batch
        documents.create_opening_batch(uow, OpeningBatchCreate(warehouse_id=w.warehouse_id, lines=[line]))
    with pytest.raises(ValidationFailed) as exc, w.uow(RAVI, step_up=True) as uow:
        documents.create_opening_batch(uow, OpeningBatchCreate(warehouse_id=w.warehouse_id, lines=[line]))
    assert exc.value.extra["errors"][0]["code"] == "movements_exist"
    with w.uow(PRIYA, step_up=True) as uow:  # admin: holds both create and approve
        batch = documents.create_opening_batch(uow, OpeningBatchCreate(warehouse_id=w.warehouse_id, lines=[
            OpeningLineIn(product_id=w.ref("OAK_TRAY"), quantity=Decimal(10), late_opening=True)]))
        documents.submit_opening_batch(uow, batch.id, Versioned(expected_version=batch.version))
        batch_id = batch.id
    with w.system() as uow:
        v = uow.session.get(OpeningBatch, batch_id).version  # type: ignore[union-attr]
    # the creator can never approve (a second person, also a DB CHECK); operations cannot approve; the approver needs MFA
    with pytest.raises(Forbidden) as forbidden, w.uow(PRIYA, step_up=True) as uow:
        documents.decide_opening_batch(uow, batch_id, Decision(expected_version=v), approve=True)
    assert forbidden.value.code == "approver_is_creator"
    with pytest.raises(Forbidden) as forbidden, w.uow(RAVI, step_up=True) as uow:
        documents.decide_opening_batch(uow, batch_id, Decision(expected_version=v), approve=True)
    assert forbidden.value.code == "permission_denied"
    with pytest.raises(MfaRequired), w.uow(SAHIL, recent_auth_at=w.ctx.clock.now()) as uow:
        documents.decide_opening_batch(uow, batch_id, Decision(expected_version=v), approve=True)
    with w.uow(SAHIL, step_up=True) as uow:
        posted = documents.decide_opening_batch(uow, batch_id, Decision(expected_version=v), approve=True)
        assert posted.status == "posted" and posted.posting_id is not None
    assert w.summary("OAK_TRAY")[0] == Decimal(610)
    with w.system() as uow:
        assert uow.session.scalar(select(StockPosting.source_type).where(StockPosting.id == posted.posting_id)) == "opening_batch"
        uow.session.execute(text("SAVEPOINT sod"))
        with pytest.raises(DBAPIError):
            uow.session.execute(text("UPDATE inventory_opening_batch SET decided_by = created_by WHERE id = :id"), {"id": batch_id})
        uow.session.execute(text("ROLLBACK TO SAVEPOINT sod"))
    assert_ledger_consistent(w)
