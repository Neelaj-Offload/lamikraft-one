"""The proforma invoice PDF (module 3). Rendered on download from the PI record; nothing is invented.

Company identity comes from the PI (frozen at issue) or, for a draft, from Settings › Company; anything missing prints
a labelled placeholder. A draft carries the "DRAFT - NOT VALID FOR TRADE" watermark; a cancelled PI says so. Bank
account numbers follow the restricted-field rule (``org.bank_account.read``; otherwise the last four digits).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.core.documents import (
    CompanyIdentity,
    address_columns,
    build_pdf,
    format_date,
    line_table,
    para,
    section_heading,
    signature_boxes,
    totals_block,
)
from app.modules.sales.documents import (
    COLUMN_WIDTHS,
    COLUMNS,
    NOT_CONFIGURED,
    NUMERIC_COLUMNS,
    _party_block,
    _rows,
    _totals_rows,
)
from app.modules.sales.proforma import _company_block, amount_in_words, draft_ref
from app.modules.sales.proforma_models import ProformaInvoice
from app.platform.uow import UnitOfWork

TITLE = "Proforma invoice"
WATERMARK = "DRAFT - NOT VALID FOR TRADE"


def _identity(company: dict[str, Any]) -> CompanyIdentity:
    regs = tuple((label, company[key]) for label, key in (("PAN", "pan"), ("IEC", "iec")) if company.get(key))
    return CompanyIdentity(
        legal_name=company.get("legal_name") or "Company",
        display_name=company.get("display_name") or company.get("legal_name") or "Company",
        address_lines=tuple(company.get("address_lines") or (NOT_CONFIGURED,)),
        gstin=company.get("gstin"),
        phone=company.get("phone"),
        email=company.get("email"),
        website=company.get("website"),
        footer_terms=company.get("footer") or None,
        registrations=regs,
    )


def _bank_lines(uow: UnitOfWork, label: str | None) -> list[str]:
    from app.platform.org.service import stored_or_default

    accounts = stored_or_default(uow, "bank_details").model_dump(mode="json").get("accounts") or []
    chosen = next((a for a in accounts if label and str(a.get("label", "")).casefold() == label.casefold()), None)
    if chosen is None:
        return ["Bank details: " + NOT_CONFIGURED]
    full = uow.actor.can("org.bank_account.read")
    number = chosen.get("account_number") if full else None
    shown = number or (f"ending {chosen['account_number_last4']}" if chosen.get("account_number_last4") else "not configured")
    lines = [f"{chosen.get('bank_name')} — {chosen.get('label')}"]
    if chosen.get("account_name"):
        lines.append(f"Account name: {chosen['account_name']}")
    lines.append(f"Account: {shown}")
    for text, key in (("IFSC", "ifsc"), ("SWIFT/BIC", "swift_bic")):
        if chosen.get(key):
            lines.append(f"{text}: {chosen[key]}")
    return lines


def filename(pi: ProformaInvoice) -> str:
    number = pi.pi_number or draft_ref(pi)
    return f"{number.replace('/', '-')}{'' if pi.pi_number else '-draft'}.pdf"


def render(uow: UnitOfWork, pi: ProformaInvoice) -> bytes:
    snap = pi.snapshot or {}
    company = snap.get("company") or _company_block(uow)
    quote = snap.get("quote") or {}
    zone = company.get("time_zone") or "Asia/Kolkata"
    number = pi.pi_number or f"{draft_ref(pi)} (draft — no number)"
    meta: list[tuple[str, str]] = [
        ("Number", number),
        ("Date", format_date(pi.pi_date, zone) if pi.pi_date else "Not issued"),
        ("Currency", pi.currency),
        ("Quotation", f"{quote.get('quote_number', '')} r{pi.revision_no}"),
    ]
    if quote.get("customer_reference"):
        meta.append(("Your reference", str(quote["customer_reference"])))
    story: list[Any] = []
    if snap.get("party"):
        story.append(address_columns(_party_block({"party": snap["party"]})))
    if pi.status == "cancelled":
        story.append(para(f"Cancelled: {pi.cancel_reason or 'no reason recorded'}.", "body"))
    elif pi.status == "draft":
        story.append(para("Draft — not valid for trade. This proforma invoice has not been issued.", "body"))
    story += section_heading("Items", min_space_below=20)
    story.append(line_table(COLUMNS, _rows({"header": {"currency": pi.currency}, "lines": snap.get("lines") or []}),
                            COLUMN_WIDTHS, numeric_cols=NUMERIC_COLUMNS))
    totals = snap.get("totals") or {}
    if totals.get("gross_subtotal") is not None:
        rows, note = _totals_rows({"totals": totals})
        story.append(totals_block(rows))
        words = amount_in_words(Decimal(totals["grand_total"]), pi.currency) if totals.get("grand_total") else None
        if words:
            story.append(para(f"Amount in words: {words[:1].upper()}{words[1:]}.", "small"))
        if note:
            story.append(para(note, "small"))
    shipping = [(label, value) for label, value in (
        ("Delivery terms", pi.delivery_terms), ("Port of loading", pi.port_of_loading),
        ("Port of discharge", pi.port_of_discharge), ("Payment terms", pi.payment_terms)) if value]
    if shipping:
        story += section_heading("Terms", min_space_below=12)
        story += [para(f"{label}: {value}", "small") for label, value in shipping]
    story += section_heading("Bank details", min_space_below=12)
    story += [para(line, "small") for line in _bank_lines(uow, pi.bank_account_label)]
    if pi.declaration:
        story += section_heading("Declaration", min_space_below=12)
        story.append(para(pi.declaration, "small"))
    if pi.notes:
        story += section_heading("Notes", min_space_below=12)
        story.append(para(pi.notes))
    story.append(signature_boxes(("Prepared by", "Authorised signatory")))
    return build_pdf(
        TITLE,
        _identity(company),
        meta,
        story,
        watermark=WATERMARK if pi.status == "draft" else None,
        reference=pi.pi_number or draft_ref(pi),
        subject=f"{TITLE} {pi.pi_number or draft_ref(pi)}",
    )
