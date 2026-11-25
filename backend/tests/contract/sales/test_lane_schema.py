"""Sales lane contracts: database CHECKs mirror the StrEnums, every ``sales_`` table has forced RLS, the append-only
triggers match the model flags, emitted events and their payloads are in the frozen catalogue, the tools carry no
identity fields, and every contribution (policies, sequences, tools, readers, the approval handler, the job, the
seed) is registered."""

from __future__ import annotations

import re
from enum import StrEnum

import pytest
from pydantic import BaseModel
from sqlalchemy import text

from app.core.db.base import Base
from app.modules.approvals import service as approvals
from app.modules.pricing.models import FxRate
from app.modules.pricing.schemas import FxRateStatus, FxSourceKind, PriceType
from app.modules.sales import events as ev
from app.modules.sales.schemas import (
    Channel,
    CustomHistoryAction,
    CustomProductStatus,
    CustomType,
    DeliveryEvidence,
    DispatchChannel,
    EnquiryStatus,
    FeedbackOutcome,
    Incoterm,
    LineType,
    ManualPreset,
    MessageStatus,
    PromotionStatus,
    QuoteOrigin,
    QuoteStatus,
    RevisionKind,
    SampleStatus,
    SpecOutcome,
    TransitionAction,
)
from app.modules.sales.state import TRANSITIONS
from app.platform import sources
from app.platform.authz.catalogue_data import PERMISSIONS
from app.platform.authz.context import ActorContext
from app.platform.tools import FORBIDDEN_INPUT_FIELDS
from app.platform.uow import UnitOfWork
from app.registry import get_registry

ENUM_COLUMNS: dict[tuple[str, str], type[StrEnum]] = {
    ("sales_enquiry", "channel"): Channel,
    ("sales_enquiry", "status"): EnquiryStatus,
    ("sales_customer_message", "channel"): Channel,
    ("sales_customer_message", "status"): MessageStatus,
    ("sales_quote", "status"): QuoteStatus,
    ("sales_quote", "origin"): QuoteOrigin,
    ("sales_quote", "price_type"): PriceType,
    ("sales_quote", "incoterm"): Incoterm,
    ("sales_quote_line", "line_type"): LineType,
    ("sales_quote_line", "manual_preset"): ManualPreset,
    ("sales_quote_revision", "kind"): RevisionKind,
    ("sales_quote_dispatch", "channel"): DispatchChannel,
    ("sales_quote_status_history", "action"): TransitionAction,
    ("sales_custom_product", "custom_type"): CustomType,
    ("sales_custom_product", "status"): CustomProductStatus,
    ("sales_custom_product_spec_revision", "outcome"): SpecOutcome,
    ("sales_custom_product_status_history", "action"): CustomHistoryAction,
    ("sales_custom_product_promotion", "status"): PromotionStatus,
    ("sales_sample", "status"): SampleStatus,
    ("sales_sample", "delivery_evidence_kind"): DeliveryEvidence,
    ("sales_sample", "feedback_outcome"): FeedbackOutcome,
    ("pricing_fx_rate", "status"): FxRateStatus,
    ("pricing_fx_rate", "source_kind"): FxSourceKind,
}
PAYLOADS: dict[str, type[BaseModel]] = {
    ev.ENQUIRY_RECEIVED: ev.EnquiryReceivedPayload,
    ev.ENQUIRY_ASSIGNED: ev.EnquiryAssignedPayload,
    ev.ENQUIRY_QUOTED: ev.EnquiryQuotedPayload,
    ev.ENQUIRY_CLOSED: ev.EnquiryClosedPayload,
    ev.MESSAGE_RECEIVED: ev.MessageReceivedPayload,
    ev.MESSAGE_REPLIED: ev.MessageRepliedPayload,
    ev.QUOTE_CREATED: ev.QuoteCreatedPayload,
    ev.QUOTE_UPDATED: ev.QuoteUpdatedPayload,
    ev.QUOTE_REVIEW_REQUESTED: ev.QuoteProposalPayload,
    ev.QUOTE_REVIEW_WITHDRAWN: ev.QuoteProposalPayload,
    ev.QUOTE_ISSUED: ev.QuoteIssuedPayload,
    ev.QUOTE_MARKED_SENT: ev.QuoteMarkedSentPayload,
    ev.QUOTE_WON: ev.QuoteWonPayload,
    ev.QUOTE_LOST: ev.QuoteReasonPayload,
    ev.QUOTE_CANCELLED: ev.QuoteReasonPayload,
    ev.QUOTE_DELETED: ev.QuoteDeletedPayload,
    ev.QUOTE_STATUS_CHANGED: ev.QuoteStatusChangedPayload,
    ev.QUOTE_REVISED: ev.QuoteRevisedPayload,
    ev.QUOTE_VALIDITY_EXTENDED: ev.QuoteValidityExtendedPayload,
    ev.QUOTE_ARCHIVED: ev.QuoteArchivedPayload,
    ev.QUOTE_UNARCHIVED: ev.QuoteArchivedPayload,
    ev.QUOTE_STATUS_CORRECTED: ev.QuoteStatusCorrectedPayload,
    ev.QUOTE_OWNER_CHANGED: ev.QuoteOwnerChangedPayload,
    ev.QUOTE_DUPLICATED: ev.QuoteDuplicatedPayload,
    ev.QUOTE_RESTORED: ev.QuoteRestoredPayload,
    ev.QUOTE_CURRENCY_CHANGED: ev.QuoteCurrencyChangedPayload,
    ev.CUSTOM_CREATED: ev.CustomCreatedPayload,
    ev.CUSTOM_UPDATED: ev.CustomUpdatedPayload,
    ev.CUSTOM_STATUS_CHANGED: ev.CustomStatusChangedPayload,
    ev.CUSTOM_SPEC_RECORDED: ev.CustomSpecRecordedPayload,
    ev.CUSTOM_PROMOTION_REQUESTED: ev.CustomPromotionRequestedPayload,
    ev.CUSTOM_PROMOTED: ev.CustomPromotedPayload,
    ev.CUSTOM_PROMOTION_REJECTED: ev.CustomPromotionRejectedPayload,
    ev.CUSTOM_DUPLICATED: ev.CustomLineagePayload,
    ev.CUSTOM_ARCHIVED: ev.CustomLineagePayload,
    ev.SAMPLE_CREATED: ev.SampleCreatedPayload,
    ev.SAMPLE_DISPATCHED: ev.SampleDispatchedPayload,
    ev.SAMPLE_DELIVERED: ev.SampleDeliveredPayload,
    ev.SAMPLE_FEEDBACK_RECORDED: ev.SamplePayload,
    ev.SAMPLE_CLOSED: ev.SamplePayload,
}


def _sales_tables() -> dict[str, type]:
    return {m.class_.__tablename__: m.class_ for m in Base.registry.mappers if m.class_.__tablename__.startswith("sales_")}


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


@pytest.mark.db
def test_sales_tables_force_rls_and_append_only_matches_model_flags(db: None) -> None:
    tables = _sales_tables()
    assert set(tables) == {"sales_enquiry", "sales_customer_message", "sales_quote", "sales_quote_line",
                           "sales_quote_status_history", "sales_quote_revision", "sales_quote_dispatch",
                           "sales_custom_product", "sales_custom_product_costing", "sales_custom_product_spec_revision",
                           "sales_custom_product_status_history", "sales_custom_product_promotion", "sales_sample",
                           "sales_proforma_invoice"}
    tables["pricing_fx_rate"] = FxRate
    with UnitOfWork(ActorContext.system(None)) as uow:
        policies = set(uow.session.execute(text("SELECT tablename FROM pg_policies WHERE policyname = 'tenant_isolation'")).scalars())
        forced = set(uow.session.execute(text("SELECT relname FROM pg_class WHERE relforcerowsecurity")).scalars())
        triggers = set(uow.session.execute(text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal")).scalars())
        deferrable = uow.session.execute(text(
            "SELECT condeferrable FROM pg_constraint WHERE conrelid = CAST('sales_quote_line' AS regclass) AND contype = 'u'"
        )).scalars().all()
    assert set(tables) <= policies and set(tables) <= forced
    for name, model in tables.items():
        flagged = bool(getattr(model, "__append_only__", False))
        assert (f"trg_{name}_append_only" in triggers) is flagged, name
    assert True in deferrable  # (quote_id, line_no) is deferrable so lines renumber in one transaction


def test_emitted_events_and_payloads_are_in_the_frozen_catalogue() -> None:
    registry = get_registry()
    assert set(ev.EMITTED_EVENTS) == set(PAYLOADS)
    for name, payload in PAYLOADS.items():
        event = registry.events[name]
        assert event.fields is not None and set(payload.model_fields) - {"origin"} == set(event.fields), name


def test_state_table_uses_catalogued_keys_and_events() -> None:
    registry = get_registry()
    keys = {p["key"] for p in PERMISSIONS}
    for t in TRANSITIONS.values():
        assert f"sales.quote.{t.permission_action}" in keys, t
        assert t.event in registry.events, t
        assert t.action in {a.value for a in TransitionAction}


def test_lane_contributions_are_registered() -> None:
    registry = get_registry()
    tools = {t.name: t for t in registry.tools}
    assert tools["find_usual_order"].effect == "read" and tools["find_usual_order"].permission == "sales.quote.read"
    draft = tools["draft_quote"]
    assert (draft.effect, draft.permission, draft.requires_idempotency) == ("draft", "sales.quote.create", True)
    for name in ("find_usual_order", "draft_quote", "resolve_party", "resolve_price", "calculate_quote"):
        assert not FORBIDDEN_INPUT_FIELDS & set(tools[name].input_model.model_fields), name
    for source_type in ("sales.quote", "sales.quote_line", "sales.customer_message", "sales.enquiry"):
        assert sources.has_reader(source_type), source_type
    handler = approvals.handler_for("sales.quote.review")
    assert handler.approve_permission == "sales.quote.approve" and handler.can_decide is not None
    quote_seq, enquiry_seq = registry.sequences["sales.quote"], registry.sequences["sales.enquiry"]
    assert (quote_seq.format_template, quote_seq.reset_policy) == ("{brand}-QT-{yyyy}-{seq:04}", "never")
    assert (enquiry_seq.format_template, enquiry_seq.reset_policy) == ("ENQ-{yyyy}-{seq:04}", "yearly")
    custom_seq, sample_seq = registry.sequences["sales.custom_product"], registry.sequences["sales.sample"]
    assert (custom_seq.format_template, custom_seq.reset_policy) == ("CP-{seq:04}", "never")
    assert (sample_seq.format_template, sample_seq.reset_policy) == ("SMP-{yyyy}-{seq:04}", "yearly")
    for kind, permission in (("sales.custom_product.promotion", "sales.custom_product.approve"),
                             ("pricing.fx_rate.approve", "pricing.fx_rate.approve")):
        assert approvals.handler_for(kind).approve_permission == permission
    for resource in ("sales.custom_product", "sales.sample"):
        assert resource in registry.policies
    for child in ("sales.custom_product_costing", "sales.custom_product_spec_revision", "sales.custom_product_promotion"):
        assert registry.policies[child].parent is not None, child
    assert [(s.order, s.name) for s in registry.seeds if s.name.startswith("sales")] == [(50, "sales.world"), (56, "sales.world.messages"), (76, "sales.world.d0")]
    assert "sales.document_render" in registry.jobs
    for resource in ("sales.quote", "sales.enquiry", "sales.customer_message"):
        assert resource in registry.policies
    for child in ("sales.quote_line", "sales.quote_revision"):
        assert registry.policies[child].parent is not None, child  # authorised only through the quote
