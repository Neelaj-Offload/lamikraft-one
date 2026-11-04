"""Invoice and credit-note PDFs and the invoice-list CSV.

The PDF prints the company identity, bank details and invoice terms from the org settings (``company_identity``,
``bank_details``, ``document_terms.invoice``); anything not configured prints a labelled placeholder, never an
invented value. Every document that is not issued carries the watermark "DRAFT - NOT VALID FOR TRADE" and the
statement "Draft — not valid for trade"; when no verified tax profile applies the totals say that tax was not
calculated. Bank account numbers follow the restricted-field rule (``org.bank_account.read``; otherwise the last
four digits). The CSV goes through ``core/csv_safe`` (formula-inert).
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from app.core.csv_safe import write_csv
from app.core.documents import (
    CompanyIdentity,
    address_columns,
    bold,
    build_pdf,
    format_date,
    format_money,
    format_quantity,
    format_unit_price,
    join_markup,
    line_table,
    para,
    plain,
    section_heading,
    signature_boxes,
    terms_block,
    totals_block,
)
from app.modules.finance import common as c
from app.modules.finance.schemas import InvoiceDetail, InvoiceSummary
from app.platform.uow import UnitOfWork

NOT_CONFIGURED = "Not configured — set in Settings › Company"
WATERMARK = "DRAFT - NOT VALID FOR TRADE"
TERMS_PLACEHOLDER = (
    "Invoice terms are not configured. Set them in Settings › Company › Document terms.",
    "Placeholder text: this document is not a tax invoice until it is issued with a verified tax profile.",
)
COLUMNS = ("#", "Item", "HSN/SAC", "Quantity", "Unit price", "Amount")
WIDTHS = (5, 41, 11, 14, 14, 15)
CSV_HEADERS = (
    "Type", "Draft reference", "Document number", "Status", "Party", "Party number", "Currency", "Document date",
    "Due date", "Subtotal", "Tax", "Total", "Outstanding", "Tax status", "Label",
)


def _setting(uow: UnitOfWork, key: str) -> dict[str, Any]:
    from app.platform.org.service import stored_or_default

    return stored_or_default(uow, key).model_dump(mode="json")


def _identity(uow: UnitOfWork) -> tuple[CompanyIdentity, list[str]]:
    ident = _setting(uow, "company_identity")
    terms = _setting(uow, "document_terms")
    missing = [k for k in ("legal_name", "address_lines", "gstin") if not ident.get(k)]
    contacts = ident.get("contacts") or {}
    regs = tuple((label, ident[k]) for label, k in (("PAN", "pan"), ("IEC", "iec")) if ident.get(k))
    return CompanyIdentity(
        legal_name=ident.get("legal_name") or "Company",
        display_name=ident.get("display_name") or ident.get("legal_name") or "Company",
        address_lines=tuple(ident.get("address_lines") or (NOT_CONFIGURED,)),
        gstin=ident.get("gstin"), phone=contacts.get("phone"), email=contacts.get("email"),
        website=contacts.get("website"), footer_terms=(terms.get("footer") or None), registrations=regs,
    ), missing


def _bank_lines(uow: UnitOfWork, currency: str) -> list[str]:
    from app.platform.org.service import stored_or_default

    accounts = stored_or_default(uow, "bank_details").model_dump(mode="json").get("accounts") or []
    if not accounts:
        return ["Bank details: " + NOT_CONFIGURED]
    chosen = next((a for a in accounts if a.get("currency") == currency), None) or next(
        (a for a in accounts if a.get("is_default")), accounts[0])
    full = uow.actor.can("org.bank_account.read")
    number = chosen.get("account_number") if full else None
    shown = number or (f"ending {chosen['account_number_last4']}" if chosen.get("account_number_last4") else "not configured")
    lines = [f"{chosen.get('bank_name')} — {chosen.get('label')}"]
    if chosen.get("account_name"):
        lines.append(f"Account name: {chosen['account_name']}")
    lines.append(f"Account: {shown}")
    for label, key in (("IFSC", "ifsc"), ("SWIFT/BIC", "swift_bic")):
        if chosen.get(key):
            lines.append(f"{label}: {chosen[key]}")
    return lines


def _terms(uow: UnitOfWork) -> list[str]:
    text = (_setting(uow, "document_terms").get("invoice") or "").strip()
    if not text:
        return list(TERMS_PLACEHOLDER)
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def filename(d: InvoiceDetail) -> str:
    return f"{d.document_number or d.draft_ref}{'' if d.document_number else '-draft'}.pdf"


def render(uow: UnitOfWork, d: InvoiceDetail) -> bytes:
    identity, missing = _identity(uow)
    credit = d.doc_type.value == "credit_note"
    title = "Credit note" if credit else "Invoice"
    issued = d.status.value == "issued"
    meta: list[tuple[str, str]] = [
        ("Number", d.document_number or f"{d.draft_ref} (draft — no number)"),
        ("Date", format_date(d.document_date) if d.document_date else "Not issued"),
        ("Currency", d.currency),
    ]
    if not credit:
        meta.append(("Due", format_date(d.due_date) if d.due_date else ("Not set" if issued else f"{d.payment_due_days or 0} days after issue")))
    for r in d.related:
        if r.kind in ("sales_order", "invoice"):
            meta.append(("Order" if r.kind == "sales_order" else "Against invoice", r.number))
    bill = d.billing or {}
    to_lines = [str(bill.get("legal_name") or d.party.display_name)]
    to_lines += [str(x) for x in (bill.get("address_lines") or ["Billing address not configured"])]
    to_lines += [f"{t['scheme'].upper()} {t['value']}" for t in (bill.get("tax_ids") or [])]
    story: list[Any] = [address_columns([("From", list(identity.address_lines)), ("Bill to", to_lines)])]
    if not issued:
        story.append(para(join_markup([bold(c.DRAFT_LABEL + "."), plain(" This document has not been issued.")], ""), "body"))
    if missing:
        story.append(para("Company identity not configured: " + ", ".join(m.replace("_", " ") for m in missing) + ".", "small"))
    story += section_heading("Items", min_space_below=20)
    rows = [
        [str(ln.line_no), (ln.item_code + " · " if ln.item_code else "") + ln.description, ln.hsn_sac or "—",
         format_quantity(Decimal(ln.quantity), ln.uom_code), format_unit_price(ln.unit_price.amount, d.currency),
         format_money(ln.amount.amount, d.currency)]
        for ln in d.lines
    ]
    story.append(line_table(COLUMNS, rows, WIDTHS, numeric_cols=(0, 3, 4, 5)))
    totals = [("Subtotal", format_money(d.subtotal.amount, d.currency))]
    if d.tax is not None and d.tax_profile is not None:
        label = f"Tax {format(d.tax_profile.rate_percent.normalize(), 'f')}% ({d.tax_profile.code})"
        if d.tax_profile.status.value != "verified":
            label += " — unverified draft figure"
        totals.append((label, format_money(d.tax.amount, d.currency)))
    else:
        totals.append(("Tax", "Not calculated — no tax profile"))
    totals.append(("Credit total" if credit else "Total", format_money(d.total.amount, d.currency)))
    story.append(totals_block(totals))
    if not credit:
        story += section_heading("Payment", min_space_below=12)
        story += [para(x, "small") for x in _bank_lines(uow, d.currency)]
    if d.notes:
        story += section_heading("Notes", min_space_below=12)
        story.append(para(d.notes))
    story.append(terms_block(_terms(uow)))
    story.append(signature_boxes(("Prepared by", "Approved by", "Authorised signatory")))
    return build_pdf(
        title, identity, meta, story, watermark=None if issued else WATERMARK,
        reference=d.document_number or d.draft_ref,
        subject=f"{title} {d.document_number or d.draft_ref}" + ("" if issued else f" ({c.DRAFT_LABEL})"),
    )


def list_csv(rows: Sequence[InvoiceSummary]) -> bytes:
    return write_csv(CSV_HEADERS, [
        [
            "Credit note" if r.doc_type.value == "credit_note" else "Invoice", r.draft_ref, r.document_number,
            r.status.value, r.party.display_name, r.party.party_number, r.currency, r.document_date, r.due_date,
            None, None, r.total.amount, r.outstanding.amount if r.outstanding else None, r.tax_status.value,
            r.label,
        ]
        for r in rows
    ])
