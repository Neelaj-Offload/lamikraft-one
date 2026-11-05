"""The issue gate (operations.md §9 ``issuance_gate.check``): a list of blockers, evaluated on every read and again in
the issue transaction. Drafts are always allowed; while a configuration blocker remains they carry the label
"Draft — not valid for trade" on screen, in the PDF and in the CSV.

Blockers: an approval for the current content from someone other than the creator; the company's legal identity
(legal name, address, GSTIN); the party's billing details (legal name and a billing address); a tax profile chosen
and verified by a second person; when the profile requires e-invoicing, a **verified** e-invoice provider (none
exists in Demo mode, so such invoices stay blocked); totals recomputed from the lines equal the stored totals; per
order line ``quantity <= delivered - invoiced + credited``; per challan line the same against the challan quantity;
for credit notes, never more than is still creditable.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.modules.finance import common as c
from app.modules.finance.enums import Blocker, DocType, InvoiceStatus, TaxProfileStatus
from app.modules.finance.models import Invoice, InvoiceLine, TaxProfile
from app.modules.finance.schemas import GateBlocker, IssueGate
from app.platform.uow import UnitOfWork

#: blockers that are about configuration (they keep the "not valid for trade" label even once approved)
CONFIGURATION = frozenset(
    {
        Blocker.COMPANY_IDENTITY_INCOMPLETE,
        Blocker.PARTY_BILLING_INCOMPLETE,
        Blocker.TAX_PROFILE_MISSING,
        Blocker.TAX_PROFILE_UNVERIFIED,
        Blocker.E_INVOICE_PROVIDER_NOT_VERIFIED,
    }
)
FIX_PATHS = {
    Blocker.COMPANY_IDENTITY_INCOMPLETE: "/settings/company",
    Blocker.TAX_PROFILE_MISSING: "/finance/accounting-sync#tax-profiles",
    Blocker.TAX_PROFILE_UNVERIFIED: "/finance/accounting-sync#tax-profiles",
    Blocker.E_INVOICE_PROVIDER_NOT_VERIFIED: "/settings/integrations",
}


def company_identity_missing(uow: UnitOfWork) -> list[str]:
    from app.platform.org.service import stored_or_default

    ident = stored_or_default(uow, "company_identity").model_dump(mode="json")
    missing = []
    if not ident.get("legal_name"):
        missing.append("legal_name")
    if not ident.get("address_lines"):
        missing.append("address")
    if not ident.get("gstin"):
        missing.append("gstin")
    return missing


def billing_snapshot(uow: UnitOfWork, party_id: uuid.UUID) -> dict[str, Any]:
    """Legal name, number, billing address and tax identifiers of the party as of now (company-level read)."""
    from app.modules.parties.models import Party, PartyAddress, PartyTaxIdentifier

    party = uow.session.get(Party, party_id)
    if party is None or party.company_id != uow.actor.company_id:
        return {}
    addresses = list(
        uow.session.scalars(
            select(PartyAddress).where(
                PartyAddress.party_id == party.id, PartyAddress.archived_at.is_(None), PartyAddress.kind == "billing"
            ).order_by(PartyAddress.is_default.desc(), PartyAddress.created_at)
        )
    )
    taxes = list(
        uow.session.scalars(
            select(PartyTaxIdentifier).where(
                PartyTaxIdentifier.party_id == party.id, PartyTaxIdentifier.archived_at.is_(None)
            )
        )
    )
    addr = addresses[0] if addresses else None
    lines: list[str] = []
    if addr is not None:
        lines = [x for x in (addr.line1, addr.line2, " ".join(p for p in (addr.postal_code, addr.city) if p), addr.region, addr.country_code) if x]
    return {
        "legal_name": party.legal_name,
        "display_name": party.display_name,
        "party_number": party.party_number,
        "country_code": party.country_code,
        "address_lines": lines,
        "tax_ids": [{"scheme": t.scheme, "value": t.value} for t in taxes],
    }


def billing_missing(snapshot: dict[str, Any]) -> list[str]:
    missing = []
    if not snapshot.get("legal_name"):
        missing.append("legal_name")
    if not snapshot.get("address_lines"):
        missing.append("billing_address")
    return missing


def e_invoice_verified(uow: UnitOfWork) -> bool:
    from app.platform.system.service import effective_statuses

    for s in effective_statuses(uow):
        if s.key == "e_invoice":
            return s.mode == "live" and s.state == "connected"
    return False


def _quantity_blockers(uow: UnitOfWork, inv: Invoice, lines: list[InvoiceLine]) -> list[GateBlocker]:
    from app.modules.challans.models import ChallanLine
    from app.modules.orders.models import SalesOrderLine

    out: list[GateBlocker] = []
    if inv.doc_type == DocType.CREDIT_NOTE.value:
        credited_ids = [ln.credited_line_id for ln in lines if ln.credited_line_id]
        originals = {
            o.id: o for o in uow.session.scalars(select(InvoiceLine).where(InvoiceLine.id.in_(credited_ids)))
        } if credited_ids else {}
        already = c.credited_by_invoice_line(uow, credited_ids, exclude_invoice=inv.id)
        for ln in lines:
            orig = originals.get(ln.credited_line_id) if ln.credited_line_id else None
            if orig is None:
                continue
            room = Decimal(orig.quantity) - already.get(orig.id, c.ZERO)
            if Decimal(ln.quantity) > room:
                out.append(
                    GateBlocker(
                        code=Blocker.QUANTITY_EXCEEDS_CREDITABLE,
                        detail={"line_no": str(ln.line_no), "creditable": format(room.normalize(), "f")},
                    )
                )
        return out
    so_ids = [ln.so_line_id for ln in lines if ln.so_line_id]
    if so_ids:
        so_lines = {s.id: s for s in uow.session.scalars(select(SalesOrderLine).where(SalesOrderLine.id.in_(so_ids)))}
        invoiced = c.invoiced_by_so_line(uow, so_ids, exclude_invoice=inv.id)
        wanted: dict[uuid.UUID, Decimal] = {}
        for ln in lines:
            if ln.so_line_id:
                wanted[ln.so_line_id] = wanted.get(ln.so_line_id, c.ZERO) + Decimal(ln.quantity)
        for so_id, qty in wanted.items():
            so = so_lines.get(so_id)
            if so is None:
                continue
            room = Decimal(so.qty_delivered) - invoiced.get(so_id, c.ZERO)
            if qty > room:
                out.append(
                    GateBlocker(
                        code=Blocker.QUANTITY_EXCEEDS_DELIVERED,
                        detail={"order_line_no": str(so.line_no), "invoiceable": format(room.normalize(), "f")},
                    )
                )
    ch_ids = [ln.challan_line_id for ln in lines if ln.challan_line_id]
    if ch_ids:
        ch_lines = {x.id: x for x in uow.session.scalars(select(ChallanLine).where(ChallanLine.id.in_(ch_ids)))}
        invoiced = c.invoiced_by_challan_line(uow, ch_ids, exclude_invoice=inv.id)
        for ln in lines:
            ch = ch_lines.get(ln.challan_line_id) if ln.challan_line_id else None
            if ch is None:
                continue
            room = Decimal(ch.quantity) - invoiced.get(ch.id, c.ZERO)
            if Decimal(ln.quantity) > room and not any(b.code == Blocker.QUANTITY_EXCEEDS_DELIVERED for b in out):
                out.append(
                    GateBlocker(
                        code=Blocker.QUANTITY_EXCEEDS_DELIVERED,
                        detail={"challan_line_no": str(ch.line_no), "invoiceable": format(room.normalize(), "f")},
                    )
                )
    return out


def check(uow: UnitOfWork, inv: Invoice, lines: list[InvoiceLine] | None = None) -> IssueGate:
    lines = c.lines_of(uow, inv) if lines is None else lines
    blockers: list[GateBlocker] = []

    def add(code: Blocker, **detail: str) -> None:
        blockers.append(GateBlocker(code=code.value, fix_path=FIX_PATHS.get(code), detail=detail))

    if inv.status == InvoiceStatus.ISSUED.value:
        return IssueGate(can_issue=False, blockers=[], label=None)
    if not lines:
        add(Blocker.NO_LINES)
    if not (
        inv.status == InvoiceStatus.APPROVED.value
        and inv.approved_by is not None
        and inv.approved_by != inv.owner_user_id
    ):
        add(Blocker.NOT_APPROVED)
    if missing := company_identity_missing(uow):
        add(Blocker.COMPANY_IDENTITY_INCOMPLETE, missing=",".join(missing))
    if missing := billing_missing(billing_snapshot(uow, inv.party_id)):
        blockers.append(
            GateBlocker(
                code=Blocker.PARTY_BILLING_INCOMPLETE.value,
                fix_path=f"/sales/customers/{inv.party_id}",
                detail={"missing": ",".join(missing)},
            )
        )
    profile = uow.session.get(TaxProfile, inv.tax_profile_id) if inv.tax_profile_id else None
    if profile is None:
        add(Blocker.TAX_PROFILE_MISSING)
    else:
        if profile.status != TaxProfileStatus.VERIFIED.value:
            add(Blocker.TAX_PROFILE_UNVERIFIED, profile=profile.code)
        if profile.requires_e_invoice and not e_invoice_verified(uow):
            add(Blocker.E_INVOICE_PROVIDER_NOT_VERIFIED)
    subtotal, tax, total = c.recompute(lines, inv.currency, profile.rate_percent if profile else None)
    if (
        subtotal != Decimal(inv.subtotal_amount)
        or total != Decimal(inv.total_amount)
        or (tax is not None and inv.tax_amount is not None and tax != Decimal(inv.tax_amount))
        or ((tax is None) != (inv.tax_amount is None))
    ):
        add(Blocker.TOTALS_CHANGED)
    if lines and total <= 0:
        add(Blocker.ZERO_TOTAL)
    blockers += _quantity_blockers(uow, inv, lines)
    # anything not issued is a draft and is labelled as such, whatever the remaining blockers
    return IssueGate(can_issue=not blockers, blockers=blockers, label=c.DRAFT_LABEL)


def configuration_blocked(gate: IssueGate) -> bool:
    return any(b.code in {x.value for x in CONFIGURATION} for b in gate.blockers)
