"""The delivery challan document (LM-90, LM-91, LM-92; BUG-03 output channels agree).

One snapshot feeds every channel: the PDF (``app.core.documents``: ReportLab Platypus, embedded Noto fonts, A4,
repeated table header, page x of y), the browser print view (``ChallanPrint``) and the CSV export
(``app.core.csv_safe``). A draft renders live with a DRAFT watermark; an issued challan renders from its frozen
revision snapshot, so the same snapshot always gives the same bytes (``document_sha256``). The company identity and
the terms come from the org settings (``company_identity``, ``document_terms``), never from code. Internal notes
live in ``platform/collab`` and are never part of the snapshot.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.core.csv_safe import write_csv
from app.core.documents import (
    CompanyIdentity,
    address_columns,
    build_pdf,
    format_date,
    format_quantity,
    line_table,
    para,
    section_heading,
    signature_boxes,
    terms_block,
    totals_block,
)
from app.modules.challans import service
from app.modules.challans.common import company_zone, user_refs
from app.modules.challans.models import Challan, ChallanLine
from app.modules.challans.schemas import (
    DESTINATION_LABELS,
    RETURN_LABELS,
    STATUS_LABELS,
    TYPE_LABELS,
    ChallanPrint,
    ChallanStatus,
    ChallanType,
    DestinationType,
    PrintLine,
    PrintParty,
    ReturnType,
)
from app.platform.uow import UnitOfWork

DOCUMENT_TITLE = "Delivery challan"
NOT_CONFIGURED = "Not configured — set in Settings › Company"
SIGNATURES = ("Delivered by", "Received by", "Authorised signatory")
TERMS_DEMO = (
    "Goods are dispatched as described above; please check the quantities on receipt and report shortages within 48 hours.",
    "This challan is a delivery document only; it carries no price, tax or invoice value.",
    "Returnable material remains the property of the sender and is to be returned by the expected return date.",
    "Demo terms placeholder: the company's own terms are set in Settings › Company.",
)
COLUMNS = ("#", "Item code", "Item", "HSN/SAC", "Quantity", "Remarks")
COLUMN_WIDTHS = (5, 16, 38, 11, 14, 16)
NUMERIC_COLUMNS = (0, 4)
CSV_HEADERS = (
    "Challan number",
    "Date",
    "Type",
    "Return type",
    "Status",
    "Source",
    "Destination type",
    "Destination party",
    "Party number",
    "Shipping name",
    "GSTIN",
    "Phone",
    "Email",
    "Reference",
    "Expected return",
    "Lines",
    "Total quantity",
    "Owner",
    "Created by",
    "Created at",
    "Issued at",
    "Remarks",
)


def sha256_of(pdf: bytes) -> str:
    return hashlib.sha256(pdf).hexdigest()


def document_filename(snapshot: dict[str, Any]) -> str:
    h = snapshot["header"]
    suffix = f"-r{h['revision_no']}" if h.get("revision_no") else "-draft"
    return f"{h['challan_number']}{suffix}.pdf"


# =====================================================================================================
# the snapshot
# =====================================================================================================
def _identity_setting(uow: UnitOfWork) -> dict[str, Any]:
    from app.platform.org.service import stored_or_default

    value = stored_or_default(uow, "company_identity")
    return value.model_dump(mode="json")


def _terms_setting(uow: UnitOfWork) -> tuple[list[str], bool, str | None]:
    from app.platform.org.service import stored_or_default

    value = stored_or_default(uow, "document_terms").model_dump(mode="json")
    text = (value.get("challan") or "").strip()
    footer = (value.get("footer") or "").strip() or None
    if not text or text.lower().startswith("demo terms"):
        return list(TERMS_DEMO), True, footer
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return lines, False, footer


def _company_block(identity: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Printed company lines and the labels of the identity values that are not configured."""
    missing: list[str] = []
    lines: list[str] = []
    address = identity.get("address_lines") or []
    if address:
        lines += list(address)
    else:
        missing.append("address")
        lines.append(NOT_CONFIGURED)
    if identity.get("gstin"):
        lines.append(f"GSTIN {identity['gstin']}")
    else:
        missing.append("gstin")
    contacts = identity.get("contacts") or {}
    contact = " · ".join(c for c in (contacts.get("phone"), contacts.get("email")) if c)
    if contact:
        lines.append(contact)
    return lines, missing


def _to_block(challan: Challan, party_number: str | None) -> list[str]:
    lines = [challan.destination_party]
    if challan.shipping_name and challan.shipping_name != challan.destination_party:
        lines.append(challan.shipping_name)
    if party_number:
        lines.append(party_number)
    if challan.address:
        lines += [ln.strip() for ln in challan.address.splitlines() if ln.strip()]
    if challan.gstin:
        lines.append(f"GSTIN {challan.gstin}")
    contact = " · ".join(c for c in (challan.phone, challan.email) if c)
    if contact:
        lines.append(contact)
    return lines


def build_snapshot(
    uow: UnitOfWork,
    challan: Challan,
    lines: Sequence[ChallanLine],
    *,
    revision_no: int,
    issued_at: datetime | None,
) -> dict[str, Any]:
    identity = _identity_setting(uow)
    terms, demo, footer = _terms_setting(uow)
    company_lines, missing = _company_block(identity)
    users = user_refs(uow, [challan.owner_user_id, uow.actor.user_id])
    party_number = None
    if challan.party_id is not None:
        from app.modules.parties import service as parties

        labels = parties.party_labels(uow, [challan.party_id])
        party_number = labels.get(challan.party_id, (None, None))[0]
    totals = service.quantity_by_unit(lines)
    return {
        "snapshot_version": 1,
        "company": {
            "legal_name": identity.get("legal_name") or "Company",
            "display_name": identity.get("display_name") or identity.get("legal_name") or "Company",
            "lines": company_lines,
            "not_configured": missing,
            "footer": footer,
            "time_zone": company_zone(uow),
        },
        "header": {
            "challan_id": str(challan.id),
            "challan_number": challan.challan_number,
            "revision_no": revision_no,
            "challan_date": challan.challan_date.isoformat(),
            "status": challan.status,
            "challan_type": challan.challan_type,
            "return_type": challan.return_type,
            "destination_type": challan.destination_type,
            "source_location": challan.source_location,
            "destination_party": challan.destination_party,
            "party_number": party_number,
            "shipping_name": challan.shipping_name,
            "gstin": challan.gstin,
            "phone": challan.phone,
            "email": challan.email,
            "address": challan.address,
            "reference_no": challan.reference_no,
            "remarks": challan.remarks,
            "expected_return_date": challan.expected_return_date.isoformat()
            if challan.expected_return_date
            else None,
            "inventory_effect": challan.inventory_effect,
            "issued_at": issued_at.isoformat() if issued_at else None,
            "issued_by": {
                "id": str(uow.actor.user_id) if uow.actor.user_id else None,
                "display_name": (
                    users.get(uow.actor.user_id).display_name
                    if uow.actor.user_id and users.get(uow.actor.user_id)
                    else None
                ),
            },
            "owner": {
                "id": str(challan.owner_user_id),
                "display_name": users.get(challan.owner_user_id).display_name
                if users.get(challan.owner_user_id)
                else None,
            },
        },
        "to_block": _to_block(challan, party_number),
        "lines": [
            {
                "line_no": ln.line_no,
                "line_type": ln.line_type,
                "item_code": ln.item_code,
                "item_name": ln.item_name,
                "hsn_sac": ln.hsn_sac,
                "quantity": format(service.plain(ln.quantity), "f"),
                "unit": ln.uom_code,
                "remarks": ln.remarks,
            }
            for ln in lines
        ],
        "total_quantity": {unit: format(qty, "f") for unit, qty in totals.items()},
        "terms": terms,
        "terms_are_demo": demo,
        "signatures": list(SIGNATURES),
    }


# =====================================================================================================
# rendering (pure: snapshot in, bytes out)
# =====================================================================================================
def _identity(snapshot: dict[str, Any]) -> CompanyIdentity:
    company = snapshot["company"]
    return CompanyIdentity(
        legal_name=company["legal_name"],
        display_name=company["display_name"],
        address_lines=tuple(company.get("lines") or (NOT_CONFIGURED,)),
        footer_terms=company.get("footer"),
    )


def _meta(snapshot: dict[str, Any]) -> list[tuple[str, str]]:
    h = snapshot["header"]
    meta = [
        ("Number", h["challan_number"]),
        ("Date", format_date(date.fromisoformat(h["challan_date"]))),
        (
            "Type",
            f"{TYPE_LABELS[ChallanType(h['challan_type'])]} · {RETURN_LABELS[ReturnType(h['return_type'])]}",
        ),
        ("Destination", DESTINATION_LABELS[DestinationType(h["destination_type"])]),
    ]
    if h.get("reference_no"):
        meta.append(("Reference", h["reference_no"]))
    if h.get("expected_return_date"):
        meta.append(("Expected return", format_date(date.fromisoformat(h["expected_return_date"]))))
    return meta


def _rows(snapshot: dict[str, Any]) -> list[list[str]]:
    return [
        [
            str(ln["line_no"]),
            ln.get("item_code") or "—",
            ln["item_name"],
            ln.get("hsn_sac") or "—",
            format_quantity(Decimal(ln["quantity"]), ln["unit"]),
            ln.get("remarks") or "",
        ]
        for ln in snapshot["lines"]
    ]


def total_text(total_quantity: dict[str, str]) -> str:
    return " · ".join(format_quantity(Decimal(q), unit) for unit, q in total_quantity.items()) or "—"


def render_pdf(snapshot: dict[str, Any]) -> bytes:
    """Deterministic PDF for a snapshot (A4, FROM/TO blocks, line table, total quantity, terms, signatures)."""
    h = snapshot["header"]
    draft = h["status"] == ChallanStatus.DRAFT.value or not h.get("revision_no")
    story: list[Any] = [
        address_columns(
            [("From", [h["source_location"], *snapshot["company"]["lines"]]), ("To", snapshot["to_block"])]
        )
    ]
    story += section_heading("Items", min_space_below=20)
    story.append(line_table(COLUMNS, _rows(snapshot), COLUMN_WIDTHS, numeric_cols=NUMERIC_COLUMNS))
    story.append(totals_block([("Total quantity", total_text(snapshot["total_quantity"]))]))
    story.append(para("Document only: no price, tax or stock movement is recorded on this challan.", "small"))
    if h.get("remarks"):
        story += section_heading("Remarks", min_space_below=12)
        story.append(para(h["remarks"]))
    story.append(terms_block(snapshot.get("terms") or list(TERMS_DEMO)))
    story.append(signature_boxes(snapshot.get("signatures") or SIGNATURES))
    status_mark = (
        None
        if h["status"] in (ChallanStatus.ISSUED.value, ChallanStatus.CLOSED.value)
        else STATUS_LABELS[ChallanStatus(h["status"])].upper()
    )
    return build_pdf(
        DOCUMENT_TITLE,
        _identity(snapshot),
        _meta(snapshot),
        story,
        watermark="DRAFT" if draft else status_mark,
        reference=h["challan_number"],
        subject=f"{DOCUMENT_TITLE} {h['challan_number']}"
        + (f" issued {h['issued_at']}" if h.get("issued_at") else " (draft)"),
    )


# =====================================================================================================
# print view data (the same snapshot, typed for the browser)
# =====================================================================================================
def print_data(snapshot: dict[str, Any]) -> ChallanPrint:
    h = snapshot["header"]
    company = snapshot["company"]
    draft = h["status"] == ChallanStatus.DRAFT.value
    return ChallanPrint(
        challan_id=uuid.UUID(h["challan_id"]),
        challan_number=h["challan_number"],
        challan_date=date.fromisoformat(h["challan_date"]),
        status=ChallanStatus(h["status"]),
        type_label=TYPE_LABELS[ChallanType(h["challan_type"])],
        return_label=RETURN_LABELS[ReturnType(h["return_type"])],
        destination_label=DESTINATION_LABELS[DestinationType(h["destination_type"])],
        reference_no=h.get("reference_no"),
        expected_return_date=date.fromisoformat(h["expected_return_date"])
        if h.get("expected_return_date")
        else None,
        company_name=company["display_name"],
        company_lines=list(company["lines"]),
        not_configured=list(company.get("not_configured") or []),
        from_block=PrintParty(title="From", lines=[h["source_location"], *company["lines"]]),
        to_block=PrintParty(title="To", lines=list(snapshot["to_block"])),
        lines=[
            PrintLine(
                line_no=ln["line_no"],
                item_code=ln.get("item_code"),
                item_name=ln["item_name"],
                hsn_sac=ln.get("hsn_sac"),
                quantity=Decimal(ln["quantity"]),
                unit=ln["unit"],
                remarks=ln.get("remarks"),
            )
            for ln in snapshot["lines"]
        ],
        total_quantity={u: Decimal(q) for u, q in snapshot["total_quantity"].items()},
        remarks=h.get("remarks"),
        terms=list(snapshot["terms"]),
        terms_are_demo=bool(snapshot.get("terms_are_demo")),
        signatures=list(snapshot["signatures"]),
        watermark="DRAFT"
        if draft
        else (
            None if h["status"] in ("issued", "closed") else STATUS_LABELS[ChallanStatus(h["status"])].upper()
        ),
    )


def current_snapshot(
    uow: UnitOfWork, challan: Challan, lines: Sequence[ChallanLine]
) -> tuple[dict[str, Any], str | None]:
    """The issued revision snapshot (with its recorded hash) or a live draft snapshot (no hash)."""
    if challan.revision_no > 0:
        row = service.revision_row(uow, challan, challan.revision_no)
        snapshot = dict(row.snapshot)
        snapshot["header"] = {
            **snapshot["header"],
            "status": challan.status,
        }  # closed/cancelled after issue shows as such
        return snapshot, row.document_sha256 if challan.status == ChallanStatus.ISSUED.value else None
    return build_snapshot(uow, challan, lines, revision_no=0, issued_at=None), None


# =====================================================================================================
# CSV export (one row per challan; every text cell goes through csv_safe)
# =====================================================================================================
def csv_bytes(
    uow: UnitOfWork, rows: Sequence[Challan], lines_map: dict[uuid.UUID, list[ChallanLine]]
) -> bytes:
    from app.modules.parties import service as parties

    users = user_refs(uow, [c.owner_user_id for c in rows] + [c.created_by for c in rows])
    labels = parties.party_labels(uow, [c.party_id for c in rows])
    out: list[list[Any]] = []
    for c in rows:
        lines = lines_map.get(c.id, [])
        out.append(
            [
                c.challan_number,
                c.challan_date,
                TYPE_LABELS[ChallanType(c.challan_type)],
                RETURN_LABELS[ReturnType(c.return_type)],
                STATUS_LABELS[ChallanStatus(c.status)],
                c.source_location,
                DESTINATION_LABELS[DestinationType(c.destination_type)],
                c.destination_party,
                labels.get(c.party_id, ("", ""))[0] if c.party_id else "",
                c.shipping_name,
                c.gstin,
                c.phone,
                c.email,
                c.reference_no,
                c.expected_return_date,
                len(lines),
                total_text({u: format(q, "f") for u, q in service.quantity_by_unit(lines).items()}),
                (users.get(c.owner_user_id).display_name if users.get(c.owner_user_id) else None),
                (users.get(c.created_by).display_name if c.created_by and users.get(c.created_by) else None),
                c.created_at,
                c.issued_at,
                c.remarks,
            ]
        )
    return write_csv(CSV_HEADERS, out)


__all__ = [
    "CSV_HEADERS",
    "DOCUMENT_TITLE",
    "NOT_CONFIGURED",
    "SIGNATURES",
    "TERMS_DEMO",
    "build_snapshot",
    "csv_bytes",
    "current_snapshot",
    "document_filename",
    "print_data",
    "render_pdf",
    "sha256_of",
    "total_text",
]
