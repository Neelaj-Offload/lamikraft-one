"""Price-list read APIs, breakdown field guard, protected product cost, append-only history and the no-overlap
constraint, on real PostgreSQL."""

from __future__ import annotations

import zlib
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import insert, select, text, update
from sqlalchemy.exc import DBAPIError

from app.core.db.base import new_id
from app.core.errors import Conflict, Forbidden, ValidationFailed
from app.core.money import Money
from app.modules.pricing import service as pricing
from app.modules.pricing.models import PriceList, PriceListItem, PriceListItemHistory, ProductCost
from app.modules.pricing.schemas import (
    CostComponent,
    PriceListCommand,
    PriceListCreate,
    PriceListDuplicate,
    PriceListItemCreate,
    PriceListItemUpdate,
    PriceListStatus,
    PriceListUpdate,
    ProductCostCreate,
    RetireItem,
    SupersedeItem,
    SupersedeItemCommand,
)
from app.platform.audit.models import AuditLog
from app.platform.authz.redaction import redact
from app.platform.uow import UnitOfWork
from app.seed.world import keys
from app.seed.world.pricing import item_ref
from tests.integration.catalogue.world import World

pytestmark = pytest.mark.db

SENTINEL = Decimal("13.5791")


def _record_cost(world: World, user: str = keys.USERS.ANANYA) -> None:
    with UnitOfWork(world.actor(user)) as uow:
        pricing.record_product_cost(
            uow, world.ref("OAK_TRAY"),
            ProductCostCreate(unit_cost_amount=SENTINEL, unit_cost_currency="EUR", unit_code="pcs",
                              effective_from=date(2026, 10, 1), cost_components=[CostComponent(label="veneer", amount=Decimal("9"))]),
        )


def test_lists_items_and_product_prices(world: World) -> None:
    meera = world.actor(keys.USERS.MEERA)
    page = pricing.list_price_lists(meera)
    assert [p.code for p in page.items] == sorted([keys.PRICE_LISTS.DOM_INR, keys.PRICE_LISTS.EXP_EUR, keys.PRICE_LISTS.EXP_GBP])
    assert page.total == 3 and all(p.status == PriceListStatus.ACTIVE for p in page.items)
    assert pricing.list_price_lists(meera, currency="GBP").total == 1
    assert pricing.list_price_lists(meera, on_date=date(2027, 1, 1)).total == 0
    eur = world.ref(keys.PRICE_LIST_REFS.EXP_EUR)
    detail = pricing.get_price_list(meera, eur)
    assert (detail.code, detail.currency, detail.item_count, detail.valid_to) == (keys.PRICE_LISTS.EXP_EUR, "EUR", 3,
                                                                                date(2026, 12, 31))
    items = pricing.list_price_list_items(meera, eur)
    assert [(i.product_key, format(i.unit_price.amount, "f"), i.unit_price.currency) for i in items.items] == [
        (keys.PRODUCTS.ASH_BOARD, keys.PRICES.ASH_BOARD_EUR, "EUR"),
        (keys.PRODUCTS.MAPLE_TRIVET, keys.PRICES.MAPLE_TRIVET_EUR, "EUR"),
        (keys.PRODUCTS.OAK_TRAY, keys.PRICES.OAK_TRAY_EUR, "EUR"),
    ]
    prices = pricing.product_prices(meera, world.ref("OAK_TRAY"))
    assert sorted((p.price_list_code, format(p.unit_price.amount, "f")) for p in prices.prices) == [
        (keys.PRICE_LISTS.EXP_EUR, keys.PRICES.OAK_TRAY_EUR), (keys.PRICE_LISTS.EXP_GBP, keys.PRICES.OAK_TRAY_GBP),
    ]
    assert prices.on_date == date(2026, 10, 12)


def test_price_list_capabilities_follow_permission_and_state(world: World) -> None:
    eur = world.ref(keys.PRICE_LIST_REFS.EXP_EUR)
    meera = pricing.get_price_list(world.actor(keys.USERS.MEERA), eur)
    assert {k: (c.allowed, c.reason_code) for k, c in meera.capabilities.items()} == {
        k: (False, "permission_denied") for k in ("update", "add_item", "edit_item", "supersede_item", "retire_item", "duplicate")
    }
    assert meera.allowed_transitions == []
    priya = world.actor(keys.USERS.PRIYA)
    active = pricing.get_price_list(priya, eur)
    assert {k: (c.allowed, c.reason_code) for k, c in active.capabilities.items()} == {
        "update": (True, None), "add_item": (False, "price_list_not_draft"), "edit_item": (False, "price_list_not_draft"),
        "supersede_item": (True, None), "retire_item": (True, None), "duplicate": (True, None),
    }
    assert [(t.action, t.to_status, t.requires_reason) for t in active.allowed_transitions] == [("retire", "retired", True)]
    with UnitOfWork(priya) as uow:
        draft_id = pricing.create_price_list(uow, PriceListCreate.model_validate({
            "code": "DRAFT-CAPS", "name": "Draft", "price_type": "export", "currency": "EUR", "valid_from": "2026-01-01",
        })).id
    draft = pricing.get_price_list(priya, draft_id)
    assert draft.capabilities["add_item"].allowed is True
    assert [(t.action, t.to_status, t.requires_reason) for t in draft.allowed_transitions] == [
        ("activate", "active", False), ("retire", "retired", True)]


def test_breakdown_fields_need_price_list_read(world: World) -> None:
    with UnitOfWork(world.actor(keys.USERS.PRIYA)) as uow:
        pl = pricing.create_price_list(uow, PriceListCreate.model_validate({
            "code": "DOM-INR-BRK", "name": "Breakdown", "price_type": "domestic", "currency": "INR",
            "valid_from": "2026-01-01", "price_basis": "per sheet",
        }))
        pricing.add_item(uow, pl.id, PriceListItemCreate(
            product_id=world.ref("WALNUT_BOARD"), unit_code="sheets", unit_price=Decimal("3600"),
            base_price=Decimal("3000"), base_price_label="Board", addon_price=Decimal("600"), addon_price_label="Veneer",
            yield_qty_per_board=Decimal("1"), thickness_mm=Decimal("18"), price_basis="per sheet",
        ))
    meera_item = pricing.list_price_list_items(world.actor(keys.USERS.MEERA), pl.id).items[0]
    assert meera_item.base_price is None and meera_item.addon_price is None and meera_item.yield_qty_per_board is None
    assert meera_item.redacted_fields == ["addon_price", "addon_price_label", "base_price", "base_price_label",
                                          "price_basis", "source_kind", "thickness_mm", "yield_qty_per_board"]
    assert meera_item.unit_price.model_dump(mode="json") == {"amount": "3600.0000", "currency": "INR"}
    sahil_item = pricing.list_price_list_items(world.actor(keys.USERS.SAHIL), pl.id).items[0]
    assert sahil_item.base_price is not None and sahil_item.addon_price is not None
    assert (format(sahil_item.base_price.amount, "f"), sahil_item.base_price_label, format(sahil_item.addon_price.amount, "f")) == (
        "3000.0000", "Board", "600.0000"
    )
    assert sahil_item.base_price.currency == sahil_item.addon_price.currency == "INR"
    assert sahil_item.redacted_fields == []
    assert pricing.get_price_list(world.actor(keys.USERS.MEERA), pl.id).price_basis is None
    assert pricing.get_price_list(world.actor(keys.USERS.SAHIL), pl.id).price_basis == "per sheet"


def test_product_cost_is_restricted_everywhere(world: World) -> None:
    _record_cost(world)
    with pytest.raises(Forbidden):  # sales cannot record or read costs
        _record_cost(world, keys.USERS.MEERA)
    with pytest.raises(Forbidden):
        pricing.list_product_costs(world.actor(keys.USERS.MEERA), world.ref("OAK_TRAY"))
    meera = pricing.product_prices(world.actor(keys.USERS.MEERA), world.ref("OAK_TRAY"))
    assert meera.current_cost is None and meera.redacted_fields == ["current_cost"]
    assert str(SENTINEL) not in meera.model_dump_json()
    ananya = pricing.product_prices(world.actor(keys.USERS.ANANYA), world.ref("OAK_TRAY"))
    assert ananya.current_cost is not None and ananya.current_cost.unit_cost == Money(amount=SENTINEL, currency="EUR")
    assert redact(ananya, world.actor(keys.USERS.ANANYA), for_model=True).current_cost is None  # never to a model
    history = pricing.list_product_costs(world.actor(keys.USERS.SAHIL), world.ref("OAK_TRAY"))
    assert history.total == 1 and [(c.cost_version, c.unit_cost) for c in history.items] == [
        (1, Money(amount=SENTINEL, currency="EUR"))
    ]
    with UnitOfWork(world.actor(keys.USERS.ANANYA)) as uow:
        cost_rows = uow.session.execute(
            select(ProductCost.cost_version).where(ProductCost.product_id == world.ref("OAK_TRAY"))
        ).all()
    assert len(cost_rows) == 1


def test_cost_reads_are_audited_without_values(world: World) -> None:
    """permissions.md §6: pricing.cost.read is sensitive (audited on use); the audit lists field names, never values."""
    _record_cost(world)
    pricing.list_product_costs(world.actor(keys.USERS.SAHIL), world.ref("OAK_TRAY"))
    pricing.product_prices(world.actor(keys.USERS.ANANYA), world.ref("OAK_TRAY"))
    pricing.product_prices(world.actor(keys.USERS.MEERA), world.ref("OAK_TRAY"))  # no cost returned: no audit
    pricing.list_product_costs(world.actor(keys.USERS.SAHIL), world.ref("MAPLE_TRIVET"))  # no rows: no audit
    with UnitOfWork(world.actor(keys.USERS.ANANYA)) as uow:
        rows = list(uow.session.scalars(
            select(AuditLog).where(AuditLog.action == "pricing.product_cost.read").order_by(AuditLog.occurred_at, AuditLog.id)
        ))
    assert [(r.actor_user_id, r.resource_id) for r in rows] == [
        (world.user_id(keys.USERS.SAHIL), world.ref("OAK_TRAY")), (world.user_id(keys.USERS.ANANYA), world.ref("OAK_TRAY")),
    ]
    assert all(r.restricted_fields == ["unit_cost", "cost_components"] and r.details == {"cost_versions": [1]} for r in rows)
    assert all(str(SENTINEL) not in str((r.changes, r.details)) for r in rows)


def test_history_and_cost_are_append_only(world: World) -> None:
    _record_cost(world)
    with pytest.raises(DBAPIError, match="append-only|permission denied"), UnitOfWork(world.actor(keys.USERS.PRIYA)) as uow:
        uow.session.execute(update(PriceListItemHistory).values(reason="tampered"))
    with pytest.raises(DBAPIError, match="append-only|permission denied"), UnitOfWork(world.actor(keys.USERS.PRIYA)) as uow:
        uow.session.execute(update(ProductCost).values(unit_cost_amount=Decimal(1)))


def test_items_never_overlap_for_the_same_list_product_and_unit(world: World) -> None:
    with UnitOfWork(world.actor(keys.USERS.PRIYA)) as uow:
        pl = pricing.create_price_list(uow, PriceListCreate.model_validate({
            "code": "DRAFT-EUR", "name": "Draft", "price_type": "export", "currency": "EUR", "valid_from": "2026-01-01",
        }))
        pricing.add_item(uow, pl.id, PriceListItemCreate(product_id=world.ref("OAK_TRAY"), unit_code="pcs", unit_price=Decimal(1)))
    with pytest.raises(Conflict), UnitOfWork(world.actor(keys.USERS.PRIYA)) as uow:
        pricing.add_item(uow, pl.id, PriceListItemCreate(product_id=world.ref("OAK_TRAY"), unit_code="pcs", unit_price=Decimal(2)))
    with pytest.raises(Conflict), UnitOfWork(world.actor(keys.USERS.PRIYA)) as uow:  # active lists change by supersede
        pricing.add_item(uow, world.ref(keys.PRICE_LIST_REFS.EXP_EUR),
                         PriceListItemCreate(product_id=world.ref("WALNUT_BOARD"), unit_code="sheets", unit_price=Decimal(1)))
    original = world.ref(item_ref(keys.PRICE_LIST_REFS.EXP_EUR, "OAK_TRAY"))
    with pytest.raises(DBAPIError, match="ex_pricing_price_list_item_no_overlap"), UnitOfWork(world.actor(keys.USERS.PRIYA)) as uow:
        row = uow.session.get(PriceListItem, original)
        assert row is not None
        uow.session.execute(insert(PriceListItem).values(
            id=new_id(), company_id=world.company_id, price_list_id=row.price_list_id, product_id=row.product_id,
            product_key=row.product_key, unit_code="pcs", unit_price=Decimal(5), valid_from=date(2026, 6, 1),
            status="active", source_kind="manual", version=1, created_at=row.created_at, updated_at=row.created_at,
        ))


def test_supersede_only_on_active_lists(world: World) -> None:
    """Draft items are edited before activation and retired lists are history: neither is superseded."""
    priya = world.actor(keys.USERS.PRIYA)
    with UnitOfWork(priya) as uow:
        draft = pricing.create_price_list(uow, PriceListCreate.model_validate({
            "code": "DRAFT-SUP", "name": "Draft", "price_type": "sample", "currency": "EUR", "valid_from": "2026-01-01",
        }))
        draft_item = pricing.add_item(uow, draft.id, PriceListItemCreate(
            product_id=world.ref("OAK_TRAY"), unit_code="pcs", unit_price=Decimal(30)))
        draft_id, draft_item_id = draft.id, draft_item.id
    caps = pricing.get_price_list(priya, draft_id).capabilities
    assert (caps["supersede_item"].allowed, caps["supersede_item"].reason_code) == (False, "price_list_not_active")
    with pytest.raises(Conflict) as excinfo, UnitOfWork(priya) as uow:
        pricing.supersede_item(uow, draft_item_id, SupersedeItem(unit_price=Decimal(31), valid_from=date(2026, 11, 1)))
    assert excinfo.value.code == "price_list_not_active"
    with UnitOfWork(priya) as uow:  # a retired list (Slice 2 retires lists; set directly here)
        uow.session.execute(update(PriceList).where(PriceList.id == world.ref(keys.PRICE_LIST_REFS.EXP_GBP)).values(status="retired"))
    retired = pricing.get_price_list(world.actor(keys.USERS.PRIYA), world.ref(keys.PRICE_LIST_REFS.EXP_GBP)).capabilities
    assert retired["supersede_item"].reason_code == "price_list_not_active"
    with pytest.raises(Conflict) as excinfo, UnitOfWork(priya) as uow:
        pricing.supersede_item(uow, world.ref(item_ref(keys.PRICE_LIST_REFS.EXP_GBP, "OAK_TRAY")),
                               SupersedeItem(unit_price=Decimal(21), valid_from=date(2026, 11, 1)))
    assert excinfo.value.code == "price_list_not_active"


def test_active_item_prices_are_immutable_in_the_database(world: World) -> None:
    """commercial.md §2.2 / ADR-018: once the list is active, the price columns cannot be updated, even by SQL; only
    shortening valid_to, retiring and setting superseded_by once are allowed. Draft items stay editable."""
    priya = world.actor(keys.USERS.PRIYA)
    item_id = world.ref(item_ref(keys.PRICE_LIST_REFS.EXP_EUR, "OAK_TRAY"))
    for values in ({"unit_price": Decimal(1)}, {"unit_code": "box"}, {"valid_from": date(2026, 2, 1)},
                   {"status": "draft"}):
        with pytest.raises(DBAPIError, match="immutable|only be"), UnitOfWork(priya) as uow:
            uow.session.execute(update(PriceListItem).where(PriceListItem.id == item_id).values(**values))
    with UnitOfWork(priya) as uow:  # shortening valid_to is allowed
        uow.session.execute(update(PriceListItem).where(PriceListItem.id == item_id).values(valid_to=date(2026, 11, 30)))
    for later in (date(2026, 12, 31), None):  # never extended or reopened
        with pytest.raises(DBAPIError, match="only be shortened"), UnitOfWork(priya) as uow:
            uow.session.execute(update(PriceListItem).where(PriceListItem.id == item_id).values(valid_to=later))
    with UnitOfWork(priya) as uow:
        draft = pricing.create_price_list(uow, PriceListCreate.model_validate({
            "code": "DRAFT-EDIT", "name": "Draft", "price_type": "sample", "currency": "EUR", "valid_from": "2026-01-01",
        }))
        draft_item = pricing.add_item(uow, draft.id, PriceListItemCreate(
            product_id=world.ref("OAK_TRAY"), unit_code="pcs", unit_price=Decimal(30)))
        uow.session.execute(update(PriceListItem).where(PriceListItem.id == draft_item.id).values(unit_price=Decimal(29)))
        assert uow.session.scalar(select(PriceListItem.unit_price).where(PriceListItem.id == draft_item.id)) == Decimal(29)


def test_activation_takes_the_target_lock(world: World) -> None:
    """Concurrent activations for the same scope, type and currency serialise on one advisory lock, so the overlap
    check cannot race under READ COMMITTED (the exclusion constraint only covers one list)."""
    with UnitOfWork(world.actor(keys.USERS.PRIYA)) as uow:
        pl = pricing.create_price_list(uow, PriceListCreate.model_validate({
            "code": "SMP-LOCK", "name": "Lock", "price_type": "sample", "currency": "EUR", "valid_from": "2026-01-01",
        }))
        pricing.add_item(uow, pl.id, PriceListItemCreate(product_id=world.ref("OAK_TRAY"), unit_code="pcs",
                                                         unit_price=Decimal(30)))
        pricing.activate_price_list(uow, pl.id)
        target = pricing._activation_target(pl)
        held = uow.session.scalar(text(
            "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND pid = pg_backend_pid() "
            "AND classid = :a AND objid = :b"
        ), {"a": zlib.crc32(b"pricing.activation") & 0x7FFFFFFF, "b": zlib.crc32(target.encode()) & 0x7FFFFFFF})
    assert held == 1
    assert target == f"{world.company_id}:standard:-:sample:EUR"


# =====================================================================================================
# Slice 2: price-list create/edit/retire, effective-dated supersede with history (LM-19, BUG-15, FG-PRC-13..15)
# =====================================================================================================
def _draft(world: World, code: str, **extra: object) -> PriceList:
    with UnitOfWork(world.actor(keys.USERS.PRIYA)) as uow:
        return pricing.create_price_list(uow, PriceListCreate.model_validate({
            "code": code, "name": f"List {code}", "price_type": "sample", "currency": "EUR", "valid_from": "2026-01-01",
            **extra,
        }))


def test_item_create_and_supersede_with_history(world: World) -> None:
    """LM-19 / API-17: a price is added to a draft list, the list is activated, the price is superseded from a date;
    resolution follows the dates and the history records every step with actor and reason."""
    priya = world.actor(keys.USERS.PRIYA)
    pl = _draft(world, "SMP-EUR-HIST")
    with UnitOfWork(priya) as uow:
        item = pricing.add_item(uow, pl.id, PriceListItemCreate(product_id=world.ref("OAK_TRAY"), unit_code="pcs", unit_price=Decimal("30")))
        item_id = item.id
        detail = pricing.get_price_list(uow, pl.id)
        pricing.activate_price_list_command(uow, pl.id, PriceListCommand(expected_version=detail.version))
    with UnitOfWork(priya) as uow:
        current = pricing.get_item(uow, item_id)
        new = pricing.supersede_item(uow, item_id, SupersedeItemCommand(
            unit_price=Decimal("32.5"), valid_from=date(2026, 11, 1), reason="Veneer cost increase", expected_version=current.version))
    assert format(new.unit_price.amount, "f") == "32.5000" and new.valid_from == date(2026, 11, 1)
    for day, price in ((date(2026, 10, 31), "30.0000"), (date(2026, 11, 1), "32.5000")):
        found = pricing.resolve_price(priya, currency="EUR", uom="pcs", product_id=world.ref("OAK_TRAY"), on_date=day,
                                      price_type="sample")  # type: ignore[arg-type]
        assert found.status == "found" and format(found.unit_price.amount, "f") == price  # type: ignore[union-attr]
    history = pricing.item_history(priya, new.id)
    assert [(h.change_kind.value, h.reason) for h in history] == [
        ("created", None), ("list_activated", None), ("superseded", "Veneer cost increase"), ("created", "Veneer cost increase"),
    ]
    assert history[2].before["unit_price"] == "30.0000" and history[2].after["valid_to"] == "2026-10-31"
    assert all(h.actor_name for h in history)
    # a stale supersede is a 409 (version conflict), not a silent second change
    with pytest.raises(Conflict), UnitOfWork(priya) as uow:
        pricing.supersede_item(uow, new.id, SupersedeItemCommand(unit_price=Decimal(33), valid_from=date(2026, 12, 1),
                                                                  expected_version=new.version + 5))
    # sales can read prices but not manage lists
    with pytest.raises(Forbidden), UnitOfWork(world.actor(keys.USERS.MEERA)) as uow:
        pricing.supersede_item(uow, new.id, SupersedeItem(unit_price=Decimal(34), valid_from=date(2026, 12, 1)))


def test_overlap_rejected_at_activation(world: World) -> None:
    """FG-PRC-13: two standard lists for the same type and currency may not overlap for a product unless both carry
    different explicit priorities; the activation returns a conflict report."""
    priya = world.actor(keys.USERS.PRIYA)
    first, second = _draft(world, "SMP-A"), _draft(world, "SMP-B")
    with UnitOfWork(priya) as uow:
        for pl in (first, second):
            pricing.add_item(uow, pl.id, PriceListItemCreate(product_id=world.ref("OAK_TRAY"), unit_code="pcs", unit_price=Decimal(30)))
        pricing.activate_price_list(uow, first.id)
    with pytest.raises(Conflict) as exc, UnitOfWork(priya) as uow:
        pricing.activate_price_list(uow, second.id)
    assert exc.value.code == "price_list_overlap"
    assert exc.value.extra["conflicts"][0]["price_list_code"] == "SMP-A"
    # moving the draft's validity after the active list's end clears the overlap only when the active list ends
    with UnitOfWork(priya) as uow:
        v = pricing.get_price_list(uow, first.id).version
        pricing.update_price_list(uow, first.id, PriceListUpdate(expected_version=v, valid_to=date(2026, 6, 30)))
        v2 = pricing.get_price_list(uow, second.id).version
        pricing.update_price_list(uow, second.id, PriceListUpdate(expected_version=v2, valid_from=date(2026, 7, 1)))
    with UnitOfWork(priya) as uow:  # items still start 2026-01-01 inside the list: edit the draft item's validity
        item = pricing.list_price_list_items(uow, second.id).items[0]
        pricing.update_item(uow, item.id, PriceListItemUpdate(expected_version=item.version, valid_from=date(2026, 7, 1)))
        pricing.activate_price_list(uow, second.id)
    assert pricing.get_price_list(priya, second.id).status == PriceListStatus.ACTIVE


def test_item_fields_round_trip(world: World) -> None:
    """FG-PRC-14 / LP-05.1: every item field (base/add-on breakdown and labels, basis, yield, thickness, MOQ, validity,
    notes, provenance) round-trips; draft edits are recorded as ``edited_draft`` history."""
    priya = world.actor(keys.USERS.PRIYA)
    pl = _draft(world, "SMP-FIELDS", price_basis="per piece", priority=5)
    with UnitOfWork(priya) as uow:
        item = pricing.add_item(uow, pl.id, PriceListItemCreate(
            product_id=world.ref("WALNUT_BOARD"), unit_code="sheets", unit_price=Decimal("1450.5"), final_price=Decimal("1450.5"),
            base_price=Decimal("1300"), base_price_label="Board", addon_price=Decimal("150.5"), addon_price_label="Lamination",
            price_basis="per sheet", yield_qty_per_board=Decimal("8"), thickness_mm=Decimal("18"), moq=Decimal("10"),
            notes="Imported row", valid_from=date(2026, 2, 1), valid_to=date(2026, 12, 31), source_ref="legacy:42",
            source_sheet="pricing_master", source_row="42",
        ))
        edited = pricing.update_item(uow, item.id, PriceListItemUpdate(expected_version=item.version, unit_price=Decimal("1500"),
                                                                      notes="Edited before activation"))
    read = pricing.list_price_list_items(priya, pl.id).items[0]
    assert (format(read.unit_price.amount, "f"), format(read.final_price.amount, "f")) == ("1500.0000", "1500.0000")  # type: ignore[union-attr]
    assert (read.base_price_label, read.addon_price_label, read.price_basis, read.source_sheet, read.source_row) == (
        "Board", "Lamination", "per sheet", "pricing_master", "42")
    assert (read.moq.value, read.moq.uom, read.valid_from, read.valid_to, read.notes) == (  # type: ignore[union-attr]
        Decimal("10.000000"), "sheets", date(2026, 2, 1), date(2026, 12, 31), "Edited before activation")
    assert edited.version == read.version
    assert [h.change_kind.value for h in pricing.item_history(priya, item.id)] == ["created", "edited_draft"]
    # sales users see the price but not the breakdown and provenance (field guard)
    meera_items = pricing.list_price_list_items(world.actor(keys.USERS.MEERA), pl.id).items[0]
    assert meera_items.base_price is None and "base_price" in meera_items.redacted_fields


def test_active_items_immutable_and_history_append_only(world: World) -> None:
    """BUG-15 / FG-PRC-15 / LP-05.3: an active list's prices change only by supersede (the edit path is refused and the
    database trigger blocks a direct UPDATE); retiring a price or a list keeps history; history is append-only."""
    priya = world.actor(keys.USERS.PRIYA)
    item_id = world.ref(item_ref(keys.PRICE_LIST_REFS.EXP_EUR, "OAK_TRAY"))
    with pytest.raises(Conflict) as exc, UnitOfWork(priya) as uow:
        current = pricing.get_item(uow, item_id)
        pricing.update_item(uow, item_id, PriceListItemUpdate(expected_version=current.version, unit_price=Decimal(1)))
    assert exc.value.code == "price_list_not_draft"
    with pytest.raises(DBAPIError, match="immutable"), UnitOfWork(priya) as uow:
        uow.session.execute(update(PriceListItem).where(PriceListItem.id == item_id).values(unit_price=Decimal(1)))
    # retire the ash board price from 2026-11-01: resolves before, not from that day
    ash = world.ref(item_ref(keys.PRICE_LIST_REFS.EXP_EUR, "ASH_BOARD"))
    with UnitOfWork(priya) as uow:
        retired = pricing.retire_item(uow, ash, RetireItem(retire_from=date(2026, 11, 1), reason="Discontinued finish"))
    assert retired.status.value == "retired" and retired.valid_to == date(2026, 10, 31)
    gone = pricing.resolve_price(priya, currency="EUR", uom="pcs", product_id=world.ref("ASH_BOARD"))
    assert gone.status == "not_found"
    # retire the GBP list: it stops resolving, keeps its items, and writes list_retired history
    gbp = world.ref(keys.PRICE_LIST_REFS.EXP_GBP)
    with pytest.raises(ValidationFailed), UnitOfWork(priya) as uow:
        pricing.retire_price_list(uow, gbp, PriceListCommand(expected_version=pricing.get_price_list(uow, gbp).version))
    with UnitOfWork(priya) as uow:
        pricing.retire_price_list(uow, gbp, PriceListCommand(expected_version=pricing.get_price_list(uow, gbp).version,
                                                             reason="GBP price list replaced"))
    detail = pricing.get_price_list(priya, gbp)
    assert detail.status == PriceListStatus.RETIRED and detail.retired_at is not None and detail.allowed_transitions == []
    assert pricing.resolve_price(priya, currency="GBP", uom="pcs", product_id=world.ref("OAK_TRAY")).status == "not_found"
    gbp_item = world.ref(item_ref(keys.PRICE_LIST_REFS.EXP_GBP, "OAK_TRAY"))
    assert [h.change_kind.value for h in pricing.item_history(priya, gbp_item)][-1] == "list_retired"
    with pytest.raises(Conflict), UnitOfWork(priya) as uow:
        pricing.update_price_list(uow, gbp, PriceListUpdate(expected_version=detail.version, name="x"))
    with pytest.raises(DBAPIError, match="append-only|permission denied"), UnitOfWork(priya) as uow:
        uow.session.execute(update(PriceListItemHistory).values(reason="tampered"))
    with UnitOfWork(world.actor(keys.USERS.SAHIL)) as uow:
        names = [r[0] for r in uow.session.execute(text(
            "SELECT event_type FROM domain_event WHERE event_type LIKE 'pricing.%retired' ORDER BY seq")).all()]
    assert names == ["pricing.price_list_item.retired", "pricing.price_list.retired"]


def test_duplicate_list_copies_current_prices_as_a_draft(world: World) -> None:
    priya = world.actor(keys.USERS.PRIYA)
    with UnitOfWork(priya) as uow:
        copy = pricing.duplicate_price_list(uow, world.ref(keys.PRICE_LIST_REFS.EXP_EUR), PriceListDuplicate(
            code="EXP-EUR-2027", name="Export EUR 2027", valid_from=date(2027, 1, 1), valid_to=date(2027, 12, 31)))
        copy_id = copy.id
    detail = pricing.get_price_list(priya, copy_id)
    assert (detail.status, detail.currency, detail.item_count, detail.valid_from) == (PriceListStatus.DRAFT, "EUR", 3, date(2027, 1, 1))
    assert {t.action for t in detail.allowed_transitions} == {"activate", "retire"}
    meera_caps = pricing.get_price_list(world.actor(keys.USERS.MEERA), copy_id).capabilities
    assert not meera_caps["update"].allowed and meera_caps["update"].reason_code == "permission_denied"
