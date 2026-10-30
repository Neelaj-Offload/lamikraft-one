"""The issued quotation document (LM-56, BUG-03).

The PDF is rendered from the **issued revision snapshot** only (header, lines without internal notes, the persisted
engine totals, terms and the company identity as it was at issue), through ``app.core.documents`` (ReportLab
Platypus, embedded Noto fonts, invariant mode). Rendering is a pure function of the snapshot: the same snapshot
gives the same bytes, so ``sales_quote_revision.document_sha256`` is written at issue and verified again by the
``sales.document_render`` job. Surcharge and threshold lines appear only when the persisted result says so.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.core.documents import (
    CompanyIdentity,
    address_columns,
    build_pdf,
    format_date,
    format_money,
    format_quantity,
    format_unit_price,
    line_table,
    para,
    section_heading,
    terms_block,
    totals_block,
)
from app.core.errors import PermanentJobError
from app.modules.sales.common import company_names, company_zone, user_ref
from app.modules.sales.models import Quote, QuoteLine, QuoteRevision
from app.platform.uow import UnitOfWork

NOT_CONFIGURED = "Not configured — set in Settings › Company"
DOCUMENT_TITLE = "Quotation"
TERMS_DEMO = (
    "Prices are quoted excluding taxes, duties and levies; these are charged as applicable.",
    "Prices are valid until the validity date stated above; orders after that date are re-quoted.",
    "Delivery terms follow the stated Incoterm; packaging as per the packaging specification of each item.",
    "Demo terms placeholder: the company's own terms are set in Settings › Company.",
)
COLUMNS = ("#", "Product", "Decor / size", "Qty", "Unit price", "Line total")
COLUMN_WIDTHS = (5, 34, 24, 11, 12, 14)
NUMERIC_COLUMNS = (0, 3, 4, 5)


# =====================================================================================================
# snapshot (the input of the document, stored immutably on the revision)
# =====================================================================================================
def line_snapshot(line: QuoteLine) -> dict[str, Any]:
    """Everything printed for a line; ``internal_note`` is deliberately absent (redacted from documents)."""
    product = line.product_snapshot or {}
    return {
        "line_no": line.line_no,
        "line_key": str(line.line_key),
        "line_type": line.line_type,
        "product_id": str(line.product_id) if line.product_id else None,
        "product_key": product.get("product_key"),
        "display_sku": product.get("display_sku"),
        "description": line.description,
        "decor_no": product.get("decor_no"),
        "decor_name": product.get("decor_name"),
        "size_text": product.get("size_text"),
        "finish": product.get("finish"),
        "specification_summary": product.get("specification_summary"),
        "packaging_summary": (line.packaging_snapshot or {}).get("summary"),
        "quantity": format(line.quantity, "f"),
        "unit_code": line.unit_code,
        "unit_price": format(line.unit_price, "f") if line.unit_price is not None else None,
        "default_unit_price": format(line.default_unit_price, "f") if line.default_unit_price is not None else None,
        "discount_pct": format(line.discount_pct, "f") if line.discount_pct is not None else None,
        "gross_amount": format(line.gross_amount, "f") if line.gross_amount is not None else None,
        "discount_amount": format(line.discount_amount, "f") if line.discount_amount is not None else None,
        "line_total": format(line.line_total, "f") if line.line_total is not None else None,
        "remarks": line.remarks,
    }


def build_revision_snapshot(
    uow: UnitOfWork, quote: Quote, lines: Sequence[QuoteLine], *, revision_no: int, issued_at: datetime, valid_until: date
) -> dict[str, Any]:
    from app.modules.sales.revisions import working_copy_of

    legal_name, display_name = company_names(uow)
    owner = user_ref(uow, quote.owner_user_id)
    issuer = user_ref(uow, uow.actor.user_id)
    calc = quote.calculation or {}
    return {
        "snapshot_version": 1,
        "company": {
            "legal_name": legal_name,
            "display_name": display_name,
            "address_lines": [NOT_CONFIGURED],
            "gstin": None,
            "email": None,
            "phone": None,
            "logo": None,
            "footer_terms": "Demo document · company identity not configured",
            "time_zone": company_zone(uow),
        },
        "header": {
            "quote_id": str(quote.id),
            "quote_number": quote.quote_number,
            "revision_no": revision_no,
            "brand": quote.brand,
            "status_at_issue": quote.status,
            "issued_at": issued_at.isoformat(),
            "valid_until": valid_until.isoformat(),
            "validity_days": quote.validity_days,
            "currency": quote.currency,
            "price_type": quote.price_type,
            "incoterm": quote.incoterm,
            "incoterm_place": quote.incoterm_place,
            "payment_terms": quote.payment_terms,
            "customer_reference": quote.customer_reference,
            "remarks": quote.remarks,
            "apply_minimum_surcharge": quote.apply_minimum_surcharge,
            "owner": {"id": str(quote.owner_user_id), "display_name": owner.display_name if owner else None},
            "issued_by": {"id": str(uow.actor.user_id) if uow.actor.user_id else None, "display_name": issuer.display_name if issuer else None},
        },
        "party": quote.party_snapshot,
        "lines": [line_snapshot(ln) for ln in lines],
        "totals": {
            "currency": quote.currency,
            "gross_subtotal": format(quote.gross_subtotal_amount, "f"),
            "discount_total": format(quote.discount_total_amount, "f"),
            "net_subtotal": format(quote.net_subtotal_amount, "f"),
            "applicable_subtotal": format(quote.applicable_subtotal_amount, "f"),
            "surcharge": format(quote.surcharge_amount, "f"),
            "surcharge_applied": quote.surcharge_applied,
            "surcharge_reason_code": quote.surcharge_reason_code,
            "surcharge_label": (calc.get("surcharge") or {}).get("label") or "Shipping surcharge",
            "grand_total": format(quote.grand_total_amount, "f") if quote.grand_total_amount is not None else None,
            "line_count": quote.line_count,
            "minimum": calc.get("minimum") or {"status": quote.minimum_status},
            "tax_status": calc.get("tax_status") or "not_calculated",
            "tax_label": calc.get("tax_label") or "Excludes taxes",
            "engine_version": quote.engine_version,
            "rule_set_version": quote.rule_set_version,
            "input_hash": quote.calc_input_hash,
        },
        "terms": list(TERMS_DEMO),
        "content_hash": quote.content_hash,
        # restorable content (priced fields and provenance; never internal notes): revision restore and compare
        "working_copy": working_copy_of(quote, list(lines)),
    }


# =====================================================================================================
# rendering (pure: snapshot in, bytes out)
# =====================================================================================================
def _identity(snapshot: dict[str, Any]) -> CompanyIdentity:
    company = snapshot["company"]
    return CompanyIdentity(
        legal_name=company["legal_name"],
        display_name=company["display_name"],
        address_lines=tuple(company.get("address_lines") or (NOT_CONFIGURED,)),
        gstin=company.get("gstin"),
        email=company.get("email"),
        phone=company.get("phone"),
        footer_terms=company.get("footer_terms"),
    )


def _dec(value: str | None) -> Decimal | None:
    return None if value is None else Decimal(value)


def _party_block(snapshot: dict[str, Any]) -> list[tuple[str, list[str]]]:
    party = snapshot["party"]
    blocks: list[tuple[str, list[str]]] = []
    by_kind = {a["kind"]: a["lines"] for a in party.get("addresses", [])}
    base = [party["display_name"]]
    if party.get("legal_name") and party["legal_name"] != party["display_name"]:
        base.append(party["legal_name"])
    contact = [c for c in (party.get("contact_name"), party.get("contact_email")) if c]
    blocks.append(("Customer", base + by_kind.get("billing", []) + ([" · ".join(contact)] if contact else [])))
    if "shipping" in by_kind:
        blocks.append(("Ship to", [party["display_name"], *by_kind["shipping"]]))
    return blocks


def _meta(snapshot: dict[str, Any]) -> list[tuple[str, str]]:
    header = snapshot["header"]
    zone = snapshot["company"].get("time_zone") or "Asia/Kolkata"
    issued = datetime.fromisoformat(header["issued_at"])
    meta = [
        ("Number", header["quote_number"]),
        ("Revision", str(header["revision_no"])),
        ("Date", format_date(issued, zone)),
        ("Valid until", format_date(date.fromisoformat(header["valid_until"]))),
        ("Currency", header["currency"]),
    ]
    if header.get("incoterm"):
        place = f" {header['incoterm_place']}" if header.get("incoterm_place") else ""
        meta.append(("Incoterm", f"{header['incoterm']}{place}"))
    if header.get("customer_reference"):
        meta.append(("Your reference", header["customer_reference"]))
    if header.get("payment_terms"):
        meta.append(("Payment", header["payment_terms"]))
    return meta


def _rows(snapshot: dict[str, Any]) -> list[list[str]]:
    currency = snapshot["header"]["currency"]
    rows: list[list[str]] = []
    for ln in snapshot["lines"]:
        product_bits = [b for b in (ln.get("product_key"), ln.get("description")) if b]
        product = "\n".join(dict.fromkeys(product_bits))
        if ln.get("remarks"):
            product += f"\n{ln['remarks']}"
        details = [b for b in (
            f"{ln['decor_no']} {ln['decor_name']}".strip() if ln.get("decor_no") or ln.get("decor_name") else None,
            ln.get("size_text"),
            ln.get("specification_summary"),
        ) if b]
        unit_price = _dec(ln.get("unit_price"))
        price_text = format_unit_price(unit_price, currency) if unit_price is not None else "—"
        if ln.get("discount_pct") and Decimal(ln["discount_pct"]) > 0:
            price_text += f"\nless {format(Decimal(ln['discount_pct']).normalize(), 'f')} %"
        total = _dec(ln.get("line_total"))
        rows.append([
            str(ln["line_no"]),
            product,
            "\n".join(details),
            format_quantity(Decimal(ln["quantity"]), ln["unit_code"]),
            price_text,
            format_money(total, currency) if total is not None else "—",
        ])
    return rows


def _totals_rows(snapshot: dict[str, Any]) -> tuple[list[tuple[str, str]], str | None]:
    t = snapshot["totals"]
    currency = t["currency"]
    rows = [("Subtotal", format_money(Decimal(t["gross_subtotal"]), currency))]
    if Decimal(t["discount_total"]) > 0:
        rows.append(("Discount", "-" + format_money(Decimal(t["discount_total"]), currency)))
        rows.append(("Net subtotal", format_money(Decimal(t["net_subtotal"]), currency)))
    if t["surcharge_applied"]:
        rows.append((t.get("surcharge_label") or "Shipping surcharge", format_money(Decimal(t["surcharge"]), currency)))
    grand = t.get("grand_total")
    rows.append((f"Grand total ({(t.get('tax_label') or 'Excludes taxes').lower()})", format_money(Decimal(grand), currency) if grand else "—"))
    note = None
    minimum = t.get("minimum") or {}
    minimum_value = minimum.get("minimum_order_value")
    if isinstance(minimum_value, dict):
        minimum_value = minimum_value.get("amount")
    if minimum.get("status") == "BELOW" and minimum_value:
        note = (
            f"Minimum invoice value: {format_money(Decimal(minimum_value), currency)}. "
            f"This quotation is below the minimum order value"
            + (f"; the {(t.get('surcharge_label') or 'surcharge').lower()} shown above applies." if t["surcharge_applied"] else ".")
        )
    return rows, note


def render_quote_pdf(snapshot: dict[str, Any]) -> bytes:
    """Deterministic PDF for an issued revision snapshot (A4, repeated table header, page x of y)."""
    header = snapshot["header"]
    story: list[Any] = [address_columns(_party_block(snapshot))]
    story += section_heading("Items", min_space_below=20)
    story.append(line_table(COLUMNS, _rows(snapshot), COLUMN_WIDTHS, numeric_cols=NUMERIC_COLUMNS))
    rows, note = _totals_rows(snapshot)
    story.append(totals_block(rows))
    if note:
        story.append(para(note, "small"))
    if header.get("remarks"):
        story += section_heading("Remarks", min_space_below=12)
        story.append(para(header["remarks"]))
    story.append(terms_block(snapshot.get("terms") or list(TERMS_DEMO)))
    reference = f"{header['quote_number']} r{header['revision_no']}"
    return build_pdf(
        DOCUMENT_TITLE,
        _identity(snapshot),
        _meta(snapshot),
        story,
        reference=reference,
        subject=f"{DOCUMENT_TITLE} {header['quote_number']} revision {header['revision_no']} issued {header['issued_at']}",
    )


def sha256_of(pdf: bytes) -> str:
    return hashlib.sha256(pdf).hexdigest()


def document_filename(snapshot: dict[str, Any]) -> str:
    header = snapshot["header"]
    return f"{header['quote_number']}-r{header['revision_no']}.pdf"


# =====================================================================================================
# storage seam and the render job
# =====================================================================================================
def store_rendered_document(uow: UnitOfWork, revision: QuoteRevision, pdf_bytes: bytes) -> str:
    """Seam for ``platform/files.store_generated`` (wired by the integrator after the platform lane merges).

    Today it only confirms the content hash; the PDF is re-rendered deterministically on download."""
    digest = sha256_of(pdf_bytes)
    if digest != revision.document_sha256:
        raise PermanentJobError(
            f"rendered document hash {digest[:12]} differs from the issued revision {revision.document_sha256[:12]}"
        )
    return digest


def enqueue_render(uow: UnitOfWork, event: Any) -> None:
    """Subscription handler for ``sales.quote.issued``: queue (idempotently) the render job for the revision."""
    payload = dict(event.payload or {})
    quote_id, revision_id = payload.get("quote_id"), payload.get("revision_id")
    if not quote_id or not revision_id:
        return
    uow.enqueue(
        "sales.document_render",
        {"quote_id": str(quote_id), "revision_id": str(revision_id)},
        dedupe_key=f"sales.document_render:{revision_id}",
        resource_type="sales.quote",
        resource_id=uuid.UUID(str(quote_id)),
    )


def render_job(ctx: Any, payload: dict[str, Any]) -> dict[str, Any] | None:
    """``sales.document_render``: render the issued revision again and verify its sha256 (system actor)."""
    uow: UnitOfWork = ctx.uow
    revision_id = uuid.UUID(str(payload["revision_id"]))
    revision = uow.session.scalars(
        select(QuoteRevision).where(QuoteRevision.id == revision_id, QuoteRevision.company_id == uow.actor.company_id)
    ).first()
    if revision is None:
        raise PermanentJobError(f"revision {revision_id} not found")
    pdf = render_quote_pdf(revision.snapshot)
    digest = store_rendered_document(uow, revision, pdf)
    return {"revision_id": str(revision.id), "sha256": digest, "bytes": len(pdf), "stored": False}


__all__ = [
    "NOT_CONFIGURED",
    "build_revision_snapshot",
    "document_filename",
    "enqueue_render",
    "render_job",
    "render_quote_pdf",
    "sha256_of",
    "store_rendered_document",
]
