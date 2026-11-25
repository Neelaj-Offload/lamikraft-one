"""Sales record scope (permissions.md §3, §7.4).

- ``sales.quote``: own/team/branch/company on ``owner_user_id`` and ``branch_id``; lines, status history, issued
  revisions and dispatches are children authorised only through their quote (IDOR: an invisible quote is a 404 for
  every child path, including the PDF).
- ``sales.enquiry``: own scope on ``owner_user_id``; ``sales.customer_message``: own scope on ``assignee_user_id``.
- Object rules (state guards) feed ``capabilities`` and ``ScopedRepository.require_action``: drafts and revised working copies are
  editable, never-issued drafts are deletable, issued quotes are exportable.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.modules.sales.models import (
    CustomerMessage,
    CustomProduct,
    CustomProductCosting,
    CustomProductPromotion,
    CustomProductSpecRevision,
    CustomProductStatusHistory,
    Enquiry,
    Quote,
    QuoteDispatch,
    QuoteLine,
    QuoteRevision,
    QuoteStatusHistory,
    Sample,
)
from app.modules.sales.proforma_models import ProformaInvoice
from app.modules.sales.schemas import QuoteStatus
from app.platform.authz.context import ActorContext
from app.platform.authz.policy import Decision, ParentRef, ResourcePolicy

EDITABLE = frozenset({QuoteStatus.DRAFT.value, QuoteStatus.REVISED.value})
ISSUABLE = frozenset({QuoteStatus.DRAFT.value, QuoteStatus.INTERNAL_REVIEW.value, QuoteStatus.REVISED.value})
TRANSITIONABLE = frozenset(
    {QuoteStatus.DRAFT.value, QuoteStatus.INTERNAL_REVIEW.value, QuoteStatus.SENT.value, QuoteStatus.REVISED.value}
)
CLOSED = frozenset({QuoteStatus.WON.value, QuoteStatus.LOST.value, QuoteStatus.CANCELLED.value})


def quote_rules(_ctx: ActorContext, q: Any) -> Mapping[str, Decision]:
    deleted = q.deleted_at is not None
    draft = q.status == QuoteStatus.DRAFT.value and not deleted
    editable = q.status in EDITABLE and not deleted
    never_issued = q.revision_no == 0
    issued = q.revision_no >= 1
    archivable = q.status in CLOSED | {QuoteStatus.ARCHIVED.value} and not deleted
    correctable = q.status in CLOSED and not deleted
    return {
        "update": Decision(editable, None if editable else ("quote_deleted" if deleted else f"quote_{q.status}_not_editable")),
        "archive": Decision(archivable, None if archivable else "quote_not_closed"),
        "correct": Decision(correctable, None if correctable else "quote_not_closed"),
        "delete": Decision(
            draft and never_issued,
            None if draft and never_issued else ("issued_documents_cannot_be_deleted" if issued else "quote_not_draft"),
        ),
        "export": Decision(issued and not deleted, None if issued and not deleted else "quote_not_issued"),
        "issue": Decision(q.status in ISSUABLE and not deleted, None if q.status in ISSUABLE and not deleted else "invalid_status"),
        "transition": Decision(
            q.status in TRANSITIONABLE and not deleted,
            None if q.status in TRANSITIONABLE and not deleted else "invalid_status",
        ),
    }


def enquiry_rules(_ctx: ActorContext, e: Any) -> Mapping[str, Decision]:
    open_ = e.status != "closed"
    return {"update": Decision(open_, None if open_ else "enquiry_closed")}


def message_rules(_ctx: ActorContext, m: Any) -> Mapping[str, Decision]:
    open_ = m.status != "replied"
    return {"update": Decision(open_, None if open_ else "message_replied")}


QUOTE_POLICY = ResourcePolicy(
    resource_type="sales.quote",
    model=Quote,
    permission_prefix="sales.quote",
    owner_columns=("owner_user_id",),
    branch_column="branch_id",
    business_key_column="quote_number",
    label=lambda q: f"{q.quote_number} · {q.party_name}",
    canonical_path=lambda q: f"/sales/quotes/{q.id}",
    rules=quote_rules,
    archived_column="deleted_at",
)
QUOTE_LINE_POLICY = ResourcePolicy(
    resource_type="sales.quote_line",
    model=QuoteLine,
    permission_prefix="sales.quote",
    parent=ParentRef("sales.quote", "quote_id"),
    archived_column=None,
)
QUOTE_HISTORY_POLICY = ResourcePolicy(
    resource_type="sales.quote_status_history",
    model=QuoteStatusHistory,
    permission_prefix="sales.quote",
    parent=ParentRef("sales.quote", "quote_id"),
    archived_column=None,
)
QUOTE_REVISION_POLICY = ResourcePolicy(
    resource_type="sales.quote_revision",
    model=QuoteRevision,
    permission_prefix="sales.quote",
    parent=ParentRef("sales.quote", "quote_id", {"export": "export", "download": "export"}),
    archived_column=None,
)
QUOTE_DISPATCH_POLICY = ResourcePolicy(
    resource_type="sales.quote_dispatch",
    model=QuoteDispatch,
    permission_prefix="sales.quote",
    parent=ParentRef("sales.quote", "quote_id"),
    archived_column=None,
)
ENQUIRY_POLICY = ResourcePolicy(
    resource_type="sales.enquiry",
    model=Enquiry,
    permission_prefix="sales.enquiry",
    owner_columns=("owner_user_id",),
    branch_column="branch_id",
    business_key_column="enquiry_number",
    label=lambda e: f"{e.enquiry_number}",
    canonical_path=lambda e: f"/sales/enquiries/{e.id}",
    rules=enquiry_rules,
    archived_column=None,
)
MESSAGE_POLICY = ResourcePolicy(
    resource_type="sales.customer_message",
    model=CustomerMessage,
    permission_prefix="sales.customer_message",
    owner_columns=("assignee_user_id",),
    branch_column="branch_id",
    canonical_path=lambda m: f"/sales/messages/{m.id}",
    rules=message_rules,
    archived_column=None,
)

def custom_product_rules(_ctx: ActorContext, c: Any) -> Mapping[str, Decision]:
    archived = c.archived_at is not None
    converted = c.status == "converted_to_standard"
    editable = not archived and not converted
    return {
        "update": Decision(editable, None if editable else ("custom_product_archived" if archived else "custom_product_converted")),
        "transition": Decision(editable, None if editable else ("custom_product_archived" if archived else "custom_product_converted")),
        "promote": Decision(not archived and c.status == "approved", None if not archived and c.status == "approved" else "custom_product_not_approved"),
    }


def sample_rules(_ctx: ActorContext, s: Any) -> Mapping[str, Decision]:
    open_ = s.status not in ("closed", "cancelled")
    return {
        "update": Decision(open_, None if open_ else f"sample_{s.status}"),
        "transition": Decision(open_, None if open_ else f"sample_{s.status}"),
    }


CUSTOM_PRODUCT_POLICY = ResourcePolicy(
    resource_type="sales.custom_product",
    model=CustomProduct,
    permission_prefix="sales.custom_product",
    owner_columns=("owner_user_id",),
    branch_column="branch_id",
    business_key_column="custom_code",
    label=lambda c: f"{c.custom_code} · {c.product_name}",
    canonical_path=lambda c: f"/sales/custom-products/{c.id}",
    rules=custom_product_rules,
    archived_column="archived_at",
)
CUSTOM_PRODUCT_CHILD = {"promote": "promote", "approve": "approve"}
CUSTOM_PRODUCT_SPEC_POLICY = ResourcePolicy(
    resource_type="sales.custom_product_spec_revision",
    model=CustomProductSpecRevision,
    permission_prefix="sales.custom_product",
    parent=ParentRef("sales.custom_product", "custom_product_id", CUSTOM_PRODUCT_CHILD),
    archived_column=None,
)
CUSTOM_PRODUCT_HISTORY_POLICY = ResourcePolicy(
    resource_type="sales.custom_product_status_history",
    model=CustomProductStatusHistory,
    permission_prefix="sales.custom_product",
    parent=ParentRef("sales.custom_product", "custom_product_id"),
    archived_column=None,
)
CUSTOM_PRODUCT_PROMOTION_POLICY = ResourcePolicy(
    resource_type="sales.custom_product_promotion",
    model=CustomProductPromotion,
    permission_prefix="sales.custom_product",
    parent=ParentRef("sales.custom_product", "custom_product_id", CUSTOM_PRODUCT_CHILD),
    archived_column=None,
)
#: protected costing: reached only through a readable custom product, and only with ``pricing.cost.read``
CUSTOM_PRODUCT_COSTING_POLICY = ResourcePolicy(
    resource_type="sales.custom_product_costing",
    model=CustomProductCosting,
    permission_prefix="sales.custom_product",
    parent=ParentRef("sales.custom_product", "custom_product_id"),
    archived_column=None,
)
SAMPLE_POLICY = ResourcePolicy(
    resource_type="sales.sample",
    model=Sample,
    permission_prefix="sales.sample",
    owner_columns=("owner_user_id",),
    branch_column="branch_id",
    business_key_column="sample_number",
    label=lambda s: f"{s.sample_number} · {s.description}",
    canonical_path=lambda s: f"/sales/samples/{s.id}",
    rules=sample_rules,
    archived_column=None,
)

PROFORMA_POLICY = ResourcePolicy(
    resource_type="sales.proforma",
    model=ProformaInvoice,
    permission_prefix="sales.proforma",
    owner_columns=("owner_user_id",),
    branch_column="branch_id",
    business_key_column="pi_number",
    label=lambda p: p.pi_number or f"PI-DRAFT-{str(p.id)[-6:].upper()}",
    canonical_path=lambda p: f"/sales/proforma-invoices/{p.id}",
    archived_column=None,
)

POLICIES = [
    PROFORMA_POLICY,
    QUOTE_POLICY,
    QUOTE_LINE_POLICY,
    QUOTE_HISTORY_POLICY,
    QUOTE_REVISION_POLICY,
    QUOTE_DISPATCH_POLICY,
    ENQUIRY_POLICY,
    MESSAGE_POLICY,
    CUSTOM_PRODUCT_POLICY,
    CUSTOM_PRODUCT_SPEC_POLICY,
    CUSTOM_PRODUCT_HISTORY_POLICY,
    CUSTOM_PRODUCT_PROMOTION_POLICY,
    CUSTOM_PRODUCT_COSTING_POLICY,
    SAMPLE_POLICY,
]
