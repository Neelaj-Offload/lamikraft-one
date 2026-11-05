"""Finance record scope (permissions.md §7.8).

- Invoices and credit notes: ``finance.invoice.*`` on ``owner_user_id`` (the creator) and ``branch_id``; finance and
  management hold company scope; everyone else sees nothing (404 on a record, 403 on a list). Object rules: edits
  only while a draft; approval only while pending and **never by the creator**; issue only once approved.
- Receipts: ``finance.receipt.*`` on ``owner_user_id``/``branch_id``; reverse only while recorded.
- Lines and history are children authorised only through their invoice. Allocations, suggestions, tax profiles,
  accounting exports, sync items and margin exceptions are company-level finance records read with
  ``finance.receipt.read`` / ``finance.invoice.read`` (no owner columns: a scope below company sees none of them).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.modules.finance.enums import InvoiceStatus, ReceiptStatus
from app.modules.finance.models import (
    AccountingExport,
    AccountingSyncItem,
    Allocation,
    Invoice,
    InvoiceLine,
    InvoiceStatusHistory,
    InvoiceSuggestion,
    MarginException,
    Receipt,
    TaxProfile,
)
from app.platform.authz.context import ActorContext
from app.platform.authz.policy import Decision, ParentRef, ResourcePolicy

S = InvoiceStatus


def invoice_rules(ctx: ActorContext, inv: Any) -> Mapping[str, Decision]:
    is_draft = inv.status == S.DRAFT.value
    is_creator = ctx.user_id is not None and ctx.user_id == inv.owner_user_id
    pending = inv.status == S.PENDING_APPROVAL.value
    return {
        "update": Decision(is_draft, None if is_draft else "invoice_not_draft"),
        "approve": Decision(
            pending and not is_creator,
            None if pending and not is_creator else ("creator_cannot_approve" if is_creator else "invoice_not_pending"),
        ),
        "issue": Decision(
            inv.status == S.APPROVED.value, None if inv.status == S.APPROVED.value else "invoice_not_approved"
        ),
    }


def receipt_rules(_ctx: ActorContext, r: Any) -> Mapping[str, Decision]:
    ok = r.status == ReceiptStatus.RECORDED.value
    return {"reverse": Decision(ok, None if ok else "receipt_reversed")}


def invoice_label(inv: Any) -> str:
    return f"{inv.document_number or inv.draft_ref} · {inv.party_name}"


def invoice_path(inv: Any) -> str:
    base = "credit-notes" if inv.doc_type == "credit_note" else "invoices"
    return f"/finance/{base}/{inv.id}"


INVOICE_POLICY = ResourcePolicy(
    resource_type="finance.invoice",
    model=Invoice,
    permission_prefix="finance.invoice",
    owner_columns=("owner_user_id",),
    branch_column="branch_id",
    business_key_column="draft_ref",
    label=invoice_label,
    canonical_path=invoice_path,
    rules=invoice_rules,
    archived_column=None,
)
INVOICE_LINE_POLICY = ResourcePolicy(
    resource_type="finance.invoice_line",
    model=InvoiceLine,
    permission_prefix="finance.invoice",
    parent=ParentRef("finance.invoice", "invoice_id"),
    archived_column=None,
)
INVOICE_HISTORY_POLICY = ResourcePolicy(
    resource_type="finance.invoice_status_history",
    model=InvoiceStatusHistory,
    permission_prefix="finance.invoice",
    parent=ParentRef("finance.invoice", "invoice_id"),
    archived_column=None,
)
RECEIPT_POLICY = ResourcePolicy(
    resource_type="finance.receipt",
    model=Receipt,
    permission_prefix="finance.receipt",
    owner_columns=("owner_user_id",),
    branch_column="branch_id",
    business_key_column="receipt_number",
    label=lambda r: f"{r.receipt_number} · {r.party_name}",
    canonical_path=lambda r: f"/finance/receipts/{r.id}",
    rules=receipt_rules,
    archived_column=None,
)
ALLOCATION_POLICY = ResourcePolicy(
    resource_type="finance.allocation",
    model=Allocation,
    permission_prefix="finance.receipt",
    archived_column=None,
)
SUGGESTION_POLICY = ResourcePolicy(
    resource_type="finance.invoice_suggestion",
    model=InvoiceSuggestion,
    permission_prefix="finance.invoice",
    branch_column="branch_id",
    label=lambda s: f"{s.challan_number} · {s.party_name}",
    canonical_path=lambda _s: "/finance/invoices?view=suggestions",
    archived_column=None,
)
TAX_PROFILE_POLICY = ResourcePolicy(
    resource_type="finance.tax_profile",
    model=TaxProfile,
    permission_prefix="finance.invoice",
    business_key_column="code",
    archived_column=None,
)
EXPORT_POLICY = ResourcePolicy(
    resource_type="finance.accounting_export",
    model=AccountingExport,
    permission_prefix="finance.invoice",
    business_key_column="export_number",
    label=lambda e: e.export_number,
    canonical_path=lambda e: f"/finance/accounting-sync?export={e.id}",
    archived_column=None,
)
SYNC_ITEM_POLICY = ResourcePolicy(
    resource_type="finance.accounting_sync_item",
    model=AccountingSyncItem,
    permission_prefix="finance.invoice",
    parent=ParentRef("finance.accounting_export", "export_id"),
    archived_column=None,
)
MARGIN_EXCEPTION_POLICY = ResourcePolicy(
    resource_type="finance.margin_exception",
    model=MarginException,
    permission_prefix="finance.invoice",
    label=lambda m: f"{m.quote_number} · {m.party_name}",
    canonical_path=lambda _m: "/finance/exceptions",
    archived_column=None,
)

POLICIES = [
    INVOICE_POLICY,
    INVOICE_LINE_POLICY,
    INVOICE_HISTORY_POLICY,
    RECEIPT_POLICY,
    ALLOCATION_POLICY,
    SUGGESTION_POLICY,
    TAX_PROFILE_POLICY,
    EXPORT_POLICY,
    SYNC_ITEM_POLICY,
    MARGIN_EXCEPTION_POLICY,
]
