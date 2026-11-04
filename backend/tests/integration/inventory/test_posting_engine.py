"""The posting engine: no silent negative stock, reserved stock is protected, one posting per source (replay-safe),
validation of products, lots, units and location pairs, and reversals at most once."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.core.errors import Conflict, ValidationFailed
from app.modules.inventory import service as inventory
from app.modules.inventory.enums import LocationType
from app.modules.inventory.posting import NegativeStockError, PostingConflict, ReservedStockConflict
from app.seed.world import keys
from tests.integration.inventory.world import InvWorld, assert_ledger_consistent

pytestmark = pytest.mark.db
RAVI = keys.USERS.RAVI


def _out(w: InvWorld, product: str, qty: str, *, source_id: uuid.UUID | None = None, unit: str = "pcs") -> inventory.PostingRequest:
    with w.system() as uow:
        stock = inventory.default_location(uow, w.warehouse_id).id
        customer = inventory.company_location(uow, LocationType.CUSTOMER).id
    return inventory.PostingRequest(
        source_type="relocation", source_id=source_id or uuid.uuid7(), purpose="relocate",
        lines=(inventory.PostingLine(product_id=w.ref(product), quantity=Decimal(qty), uom_code=unit, from_location_id=stock, to_location_id=customer),),
    )


def test_no_silent_negative_stock_and_reserved_stock_conflict(inv_world: InvWorld) -> None:
    w = inv_world
    before = w.postings()
    # beyond on-hand (600): NegativeStockError and the ledger is unchanged
    req = _out(w, "OAK_TRAY", "601")
    with pytest.raises(NegativeStockError) as exc, w.uow(RAVI) as uow:
        inventory.post_movement(uow, req)
    assert exc.value.extra["shortfall"] == "1" and w.postings() == before
    assert w.summary("OAK_TRAY") == (Decimal(600), Decimal(0))
    # reserve 550, then an unreserved outbound of 60 would eat into it: ReservedStockConflict
    with w.uow(RAVI) as uow:
        inventory.reserve(uow, demand_type="so_line", demand_id=uuid.uuid7(), demand_parent_id=None, demand_label="t",
                          product_id=w.ref("OAK_TRAY"), warehouse_id=w.warehouse_id, quantity=Decimal(550))
    req = _out(w, "OAK_TRAY", "60")
    with pytest.raises(ReservedStockConflict), w.uow(RAVI) as uow:
        inventory.post_movement(uow, req)
    req = _out(w, "OAK_TRAY", "50")
    with w.uow(RAVI) as uow:  # the free 50 can still move
        inventory.post_movement(uow, req)
    assert w.summary("OAK_TRAY") == (Decimal(550), Decimal(550))
    assert_ledger_consistent(w)


def test_one_posting_per_source_and_replays_return_it(inv_world: InvWorld) -> None:
    w = inv_world
    source = uuid.uuid7()
    req = _out(w, "ASH_BOARD", "5", source_id=source)
    with w.uow(RAVI) as uow:
        first = inventory.post_movement(uow, req)
    req = _out(w, "ASH_BOARD", "5", source_id=source)
    with w.uow(RAVI) as uow:
        again = inventory.post_movement(uow, req)
    assert again.replayed and again.posting.id == first.posting.id
    req = _out(w, "ASH_BOARD", "6", source_id=source)
    with pytest.raises(PostingConflict), w.uow(RAVI) as uow:
        inventory.post_movement(uow, req)
    assert w.summary("ASH_BOARD")[0] == Decimal(195) and w.postings("relocation", source) == 1
    # reversal: once, swapped from/to, never a reversal of a reversal
    with w.uow(RAVI) as uow:
        rev = inventory.reverse_posting(uow, first.posting.id, reason_code="mistake")
    with w.uow(RAVI) as uow:
        assert inventory.reverse_posting(uow, first.posting.id, reason_code="mistake").replayed
    with pytest.raises(Conflict) as exc, w.uow(RAVI) as uow:
        inventory.reverse_posting(uow, rev.posting.id, reason_code="mistake")
    assert exc.value.code == "reversal_of_reversal" and w.summary("ASH_BOARD")[0] == Decimal(200)
    assert_ledger_consistent(w)


def test_validation_units_lots_and_location_pairs(inv_world: InvWorld) -> None:
    w = inv_world
    req = _out(w, "OAK_TRAY", "1.5")
    with pytest.raises(ValidationFailed) as exc, w.uow(RAVI) as uow:
        inventory.post_movement(uow, req)  # pcs are whole numbers
    assert exc.value.extra["errors"][0]["code"] == "not_integer"
    req = _out(w, "OAK_TRAY", "1", unit="kg")
    with pytest.raises(ValidationFailed) as exc, w.uow(RAVI) as uow:
        inventory.post_movement(uow, req)  # no conversion pcs -> kg: never guessed
    assert exc.value.extra["errors"][0]["code"] == "uom_conversion_missing"
    req = _out(w, "WALNUT_BOARD", "1", unit="sheets")
    with pytest.raises(ValidationFailed) as exc, w.uow(RAVI) as uow:
        inventory.post_movement(uow, req)  # lot-tracked
    assert exc.value.extra["errors"][0]["code"] == "lot_required"
    with w.system() as uow:
        opening = inventory.company_location(uow, LocationType.OPENING).id
        customer = inventory.company_location(uow, LocationType.CUSTOMER).id
    with pytest.raises(ValidationFailed) as exc, w.uow(RAVI) as uow:
        inventory.post_movement(uow, inventory.PostingRequest(source_type="relocation", source_id=uuid.uuid7(), purpose="relocate", lines=(
            inventory.PostingLine(product_id=w.ref("OAK_TRAY"), quantity=Decimal(1), uom_code="pcs", from_location_id=opening, to_location_id=customer),)))
    assert exc.value.extra["errors"][0]["code"] == "transition_not_allowed"
