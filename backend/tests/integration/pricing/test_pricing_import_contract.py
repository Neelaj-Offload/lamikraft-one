"""The pricing import contract (FG-PRC-16, LM-30 pricing side): ``pricing.service.import_standard_price`` writes one
imported standard price into the list ``STD-{TYPE}-{CUR}``; the catalogue lane's import workbench calls it per row."""

from __future__ import annotations

from datetime import date

import pytest

from app.core.db.base import new_id
from app.core.errors import Conflict, Forbidden
from app.modules.pricing import service as pricing
from app.modules.pricing.schemas import (
    PriceListCommand,
    PriceListStatus,
    StandardPriceImport,
    standard_list_code,
)
from app.platform.uow import UnitOfWork
from app.seed.world import keys
from tests.integration.catalogue.world import World

pytestmark = pytest.mark.db


def _row(world: World, product: str, price: str, valid_from: date, **extra: object) -> StandardPriceImport:
    return StandardPriceImport.model_validate({
        "product_id": world.ref(product), "price_type": "domestic", "currency": "USD", "unit_code": "pcs",
        "unit_price": price, "valid_from": valid_from.isoformat(), "source_sheet": "pricing_master", **extra,
    })


def test_import_supersedes_into_standard_list(world: World) -> None:
    priya = world.actor(keys.USERS.PRIYA)
    assert standard_list_code("domestic", "usd") == "STD-DOMESTIC-USD"
    with UnitOfWork(priya) as uow:
        first = pricing.import_standard_price(uow, _row(world, "OAK_TRAY", "26", date(2026, 1, 1), source_row="2", moq="24"))
        again = pricing.import_standard_price(uow, _row(world, "OAK_TRAY", "26.0000", date(2026, 1, 1), source_row="2"))
        draft_edit = pricing.import_standard_price(uow, _row(world, "OAK_TRAY", "26.5", date(2026, 1, 1), source_row="3"))
    assert (first.outcome, first.price_list_code, first.price_list_status) == ("created", "STD-DOMESTIC-USD", PriceListStatus.DRAFT)
    assert again.outcome == "unchanged" and again.item_id == first.item_id
    assert draft_edit.outcome == "updated_draft" and draft_edit.item_id == first.item_id
    with UnitOfWork(priya) as uow:
        pricing.activate_price_list_command(uow, first.price_list_id, PriceListCommand(
            expected_version=pricing.get_price_list(uow, first.price_list_id).version))
    # on the active list: a new product is added, a changed price supersedes from its date, a back-dated change is refused
    with UnitOfWork(priya) as uow:
        added = pricing.import_standard_price(uow, _row(world, "MAPLE_TRIVET", "9.5", date(2026, 3, 1), import_job_id=new_id()))
        superseded = pricing.import_standard_price(uow, _row(world, "OAK_TRAY", "27", date(2026, 11, 1), source_row="9"))
    assert added.outcome == "created" and superseded.outcome == "superseded" and superseded.superseded_item_id == first.item_id
    with pytest.raises(Conflict) as exc, UnitOfWork(priya) as uow:
        pricing.import_standard_price(uow, _row(world, "OAK_TRAY", "28", date(2026, 10, 1)))
    assert exc.value.code == "price_import_backdated"
    new_item = pricing.get_item(priya, superseded.item_id)
    assert (new_item.source_kind, new_item.source_sheet, new_item.source_row) == ("import", "pricing_master", "9")
    for day, price in ((date(2026, 10, 31), "26.5000"), (date(2026, 11, 2), "27.0000")):
        r = pricing.resolve_price(priya, currency="USD", uom="pcs", product_id=world.ref("OAK_TRAY"), on_date=day,
                                  price_type="domestic")  # type: ignore[arg-type]
        assert r.status == "found" and r.price_list_code == "STD-DOMESTIC-USD" and format(r.unit_price.amount, "f") == price  # type: ignore[union-attr]
    kinds = [h.change_kind.value for h in pricing.item_history(priya, superseded.item_id)]
    assert kinds == ["created", "edited_draft", "list_activated", "superseded", "created"]
    # the contract needs pricing.price_list.manage
    with pytest.raises(Forbidden), UnitOfWork(world.actor(keys.USERS.MEERA)) as uow:
        pricing.import_standard_price(uow, _row(world, "OAK_TRAY", "30", date(2026, 12, 1)))
