"""Lane contracts: database CHECKs mirror the StrEnums, unit codes are validated, RLS and append-only triggers are in
place, and every contribution (events, tools, search providers, source readers, sequences, seeds) is registered."""

from __future__ import annotations

import re
from enum import StrEnum

import pytest
from pydantic import BaseModel
from sqlalchemy import text

from app.modules.catalogue import events as catalogue_events
from app.modules.catalogue.schemas import (
    UOM_CODES,
    DimensionKind,
    ParseStatus,
    ProductOrigin,
    ProductStatus,
    SizeBasis,
    TaxonomyOrigin,
)
from app.modules.commercial.schemas import RuleSetStatus
from app.modules.parties import events as party_events
from app.modules.parties.schemas import AddressKind, CustomerType, PartyStatus, TaxScheme
from app.modules.pricing import events as pricing_events
from app.modules.pricing.schemas import (
    CostSourceKind,
    PriceHistoryKind,
    PriceItemStatus,
    PriceListStatus,
    PriceScope,
    PriceSourceKind,
    PriceType,
)
from app.platform import sources
from app.platform.authz.context import ActorContext
from app.platform.tools import FORBIDDEN_INPUT_FIELDS
from app.platform.uow import UnitOfWork
from app.registry import get_registry

LANE_TABLES = (
    "catalogue_category", "catalogue_subcategory", "catalogue_product", "catalogue_product_specification",
    "catalogue_product_packaging", "catalogue_product_dimension", "catalogue_lookup_reference", "parties_party",
    "parties_party_contact", "parties_party_address", "parties_party_tax_identifier", "pricing_price_list",
    "pricing_price_list_item", "pricing_price_list_item_history", "pricing_product_cost", "commercial_rule_set",
)
ENUM_COLUMNS: dict[tuple[str, str], type[StrEnum]] = {
    ("catalogue_category", "origin"): TaxonomyOrigin,
    ("catalogue_subcategory", "origin"): TaxonomyOrigin,
    ("catalogue_product", "status"): ProductStatus,
    ("catalogue_product", "origin"): ProductOrigin,
    ("catalogue_product", "size_basis"): SizeBasis,
    ("catalogue_product_dimension", "kind"): DimensionKind,
    ("catalogue_product_dimension", "parse_status"): ParseStatus,
    ("parties_party", "customer_type"): CustomerType,
    ("parties_party", "status"): PartyStatus,
    ("parties_party_address", "kind"): AddressKind,
    ("parties_party_tax_identifier", "scheme"): TaxScheme,
    ("pricing_price_list", "price_type"): PriceType,
    ("pricing_price_list", "scope_kind"): PriceScope,
    ("pricing_price_list", "customer_type"): CustomerType,
    ("pricing_price_list", "status"): PriceListStatus,
    ("pricing_price_list", "source_kind"): PriceSourceKind,
    ("pricing_price_list_item", "status"): PriceItemStatus,
    ("pricing_price_list_item", "source_kind"): PriceSourceKind,
    ("pricing_price_list_item_history", "change_kind"): PriceHistoryKind,
    ("pricing_product_cost", "source_kind"): CostSourceKind,
    ("commercial_rule_set", "status"): RuleSetStatus,
}
UOM_COLUMNS = (
    ("catalogue_product", "unit_of_sale"), ("catalogue_product", "stock_uom_code"),
    ("pricing_price_list", "default_unit_code"), ("pricing_price_list_item", "unit_code"),
    ("pricing_price_list_item", "moq_unit_code"), ("pricing_product_cost", "unit_code"),
)


def _check_values(uow: UnitOfWork, table: str, name: str) -> set[str]:
    definition = uow.session.execute(
        text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = CAST(:t AS regclass) AND conname = :n"),
        {"t": table, "n": name},
    ).scalar_one()
    return set(re.findall(r"'([^']*)'", definition))


@pytest.mark.db
def test_enum_checks_match_the_strenums(db: None) -> None:
    with UnitOfWork(ActorContext.system(None)) as uow:
        for (table, column), enum in ENUM_COLUMNS.items():
            assert _check_values(uow, table, f"ck_{table}_{column}_values") == {e.value for e in enum}, (table, column)
        for table, column in UOM_COLUMNS:
            assert _check_values(uow, table, f"ck_{table}_{column}_uom") == set(UOM_CODES), (table, column)


@pytest.mark.db
def test_lane_tables_have_forced_rls_and_append_only_triggers(db: None) -> None:
    with UnitOfWork(ActorContext.system(None)) as uow:
        policies = set(uow.session.execute(text(
            "SELECT tablename FROM pg_policies WHERE policyname = 'tenant_isolation'")).scalars())
        forced = set(uow.session.execute(text("SELECT relname FROM pg_class WHERE relforcerowsecurity")).scalars())
        triggers = set(uow.session.execute(text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal")).scalars())
        exclusion = uow.session.execute(text(
            "SELECT count(*) FROM pg_constraint WHERE conname = 'ex_pricing_price_list_item_no_overlap' AND contype = 'x'"
        )).scalar_one()
    assert set(LANE_TABLES) <= policies and set(LANE_TABLES) <= forced
    assert {"trg_pricing_price_list_item_history_append_only", "trg_pricing_product_cost_append_only",
            "trg_catalogue_product_key_immutable"} <= triggers
    assert exclusion == 1


PAYLOADS: dict[str, type[BaseModel]] = {
    catalogue_events.PRODUCT_CREATED: catalogue_events.ProductCreatedPayload,
    catalogue_events.PRODUCT_UPDATED: catalogue_events.ProductUpdatedPayload,
    catalogue_events.CATEGORY_CREATED: catalogue_events.CategoryCreatedPayload,
    catalogue_events.SUBCATEGORY_CREATED: catalogue_events.SubcategoryCreatedPayload,
    party_events.PARTY_CREATED: party_events.PartyCreatedPayload,
    party_events.PARTY_UPDATED: party_events.PartyUpdatedPayload,
    pricing_events.PRICE_LIST_CREATED: pricing_events.PriceListCreatedPayload,
    pricing_events.PRICE_LIST_ACTIVATED: pricing_events.PriceListActivatedPayload,
    pricing_events.ITEM_SUPERSEDED: pricing_events.ItemSupersededPayload,
    pricing_events.PRODUCT_COST_RECORDED: pricing_events.ProductCostRecordedPayload,
}


def test_emitted_events_and_payloads_are_in_the_frozen_catalogue() -> None:
    registry = get_registry()
    for name, payload in PAYLOADS.items():
        event = registry.events[name]
        assert event.fields is not None and set(payload.model_fields) - {"origin"} == set(event.fields), name
    assert "commercial.rule_set.activated" in registry.events


def test_lane_contributions_are_registered() -> None:
    registry = get_registry()
    tools = {t.name: t for t in registry.tools}
    for name, permission in (("resolve_party", "parties.party.read"), ("resolve_price", "pricing.price.read"),
                             ("calculate_quote", "pricing.price.read")):
        tool = tools[name]
        assert tool.permission == permission and tool.effect == "read"
        assert not FORBIDDEN_INPUT_FIELDS & set(tool.input_model.model_fields)
    providers = {p.resource_type: p for p in registry.search_providers}
    assert providers["catalogue.product"].permission == "catalogue.product.read"
    assert providers["parties.party"].permission == "parties.party.read"
    assert sources.has_reader("catalogue.product") and sources.has_reader("parties.party")
    sequence = registry.sequences["parties.party"]
    assert (sequence.format_template, sequence.reset_policy) == ("P-{seq:05}", "never")
    seeds = sorted((s.order, s.name) for s in registry.seeds if s.name.split(".")[0] in
                   {"parties", "catalogue", "pricing", "commercial"})
    assert seeds == [(20, "parties.world"), (30, "catalogue.world"), (40, "commercial.world"), (40, "pricing.world")]
    for resource in ("catalogue.product", "parties.party", "pricing.price_list", "pricing.product_cost",
                     "commercial.rule_set"):
        assert resource in registry.policies
    assert registry.policies["parties.party_contact"].parent is not None  # children only through their party
    assert registry.policies["pricing.price_list_item"].parent is not None
