"""The fixture world for the finance lane: the Slice-4 world (personas, parties, catalogue, quotes, challans,
inventory) plus helpers for delivered orders, invoice drafts, the issue configuration (company identity, a verified
tax profile entered by Ananya and verified by Priya), approvals, issue, receipts and allocations.

Personas: Ananya (finance, company scope) drafts, records and issues; Sahil (management) approves; Priya (admin) is
the second person who verifies a tax profile; Meera and Ravi hold no finance keys."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import func, select

from app.modules.finance import config, invoices, receipts
from app.modules.finance.models import Invoice
from app.modules.finance.schemas import (
    AllocationCreate,
    InvoiceCreate,
    InvoiceTransition,
    ReceiptCreate,
    TaxProfileCreate,
    Versioned,
)
from app.modules.orders import service as orders
from app.modules.orders.schemas import ChallanFromOrder
from app.platform.events.models import DomainEvent
from app.platform.org import service as org
from app.seed.world import keys
from tests.integration.catalogue.world import World
from tests.integration.inventory.world import InvWorld, build_inv_world

ANANYA, SAHIL, PRIYA, MEERA, RAVI = (keys.USERS.ANANYA, keys.USERS.SAHIL, keys.USERS.PRIYA, keys.USERS.MEERA,
                                    keys.USERS.RAVI)
GSTIN = "27AABCL1234F1Z5"


class FinWorld(InvWorld):
    # ---- operations side ---------------------------------------------------------------------------------------
    def delivered(self, qty: str = "100", *, ordered: str = "240", party: str = "NORDHAUS") -> dict[str, Any]:
        """A won quote → confirmed order (OAK_TRAY × ``ordered`` at EUR 24) → an issued challan for ``qty`` → drained,
        so the invoice suggestion exists. Returns ids."""
        order_id = self.order(MEERA, self.won_quote(MEERA, party, ("OAK_TRAY", ordered)))
        line_id = self.get_order(MEERA, order_id).lines[0].id
        with self.uow(RAVI) as uow:
            challan_id = orders.create_challan_for_order(uow, order_id, ChallanFromOrder(quantities={line_id: Decimal(qty)}))
        self.transition_challan(RAVI, challan_id, "issue")
        self.drain()
        return {"order_id": order_id, "order_line_id": line_id, "challan_id": challan_id}

    # ---- configuration -----------------------------------------------------------------------------------------
    def configure_identity(self) -> None:
        with self.uow(PRIYA, step_up=True) as uow:
            current = org.get_setting(uow, "company_identity")
            org.update_setting(uow, "company_identity", expected_version=current.version or 0, value={
                "legal_name": "Lamikraft Industries Private Limited", "display_name": "Lamikraft",
                "address_lines": ["Plot 12, MIDC Industrial Area", "Pune 411019, Maharashtra, India"], "gstin": GSTIN,
            })

    def verified_profile(self, *, requires_e_invoice: bool = False, rate: str = "0", code: str | None = None) -> uuid.UUID:
        """A business-entered profile (test values, entered by Ananya) verified by Priya."""
        with self.uow(ANANYA, step_up=True) as uow:
            p = config.create_tax_profile(uow, TaxProfileCreate(
                code=code or f"EXP-LUT-{uuid.uuid7().hex[-6:].upper()}", name="Export under LUT", scenario="Export of goods under LUT (test fixture)",
                rate_percent=Decimal(rate), requires_e_invoice=requires_e_invoice,
                source_reference="Test fixture entered by the finance lane"))
            pid, version = p.id, p.version
        with self.uow(PRIYA, step_up=True) as uow:
            config.verify_tax_profile(uow, pid, Versioned(expected_version=version))
        return pid

    # ---- documents ---------------------------------------------------------------------------------------------
    def draft(self, person: str = ANANYA, **body: Any) -> Any:
        with self.uow(person) as uow:
            return invoices.detail(uow, invoices.create_invoice(uow, InvoiceCreate(**body)))

    def get(self, invoice_id: uuid.UUID, person: str = ANANYA) -> Any:
        with self.uow(person) as uow:
            return invoices.detail(uow, uow.repo(Invoice).get(invoice_id))

    def act(self, person: str, invoice_id: uuid.UUID, action: str, **extra: Any) -> Any:
        with self.uow(person, idempotency_key=str(uuid.uuid7()), step_up=True) as uow:
            version = uow.repo(Invoice).get(invoice_id).version
            out = invoices.transition(uow, invoice_id, InvoiceTransition(action=action, expected_version=version, **extra))
            return out if isinstance(out, invoices.IssueResult) else invoices.detail(uow, out)

    def set_profile(self, invoice_id: uuid.UUID, profile_id: uuid.UUID, person: str = ANANYA) -> Any:
        from app.modules.finance.schemas import InvoiceUpdate

        with self.uow(person) as uow:
            version = uow.repo(Invoice).get(invoice_id).version
            return invoices.detail(uow, invoices.update_invoice(uow, invoice_id, InvoiceUpdate(expected_version=version, tax_profile_id=profile_id)))

    def issued_invoice(self, qty: str = "100", **draft: Any) -> Any:
        """Configured world → delivered challan → draft from the suggestion → submit → Sahil approves → Ananya issues."""
        ids = self.delivered(qty)
        profile = self.ctx.refs.get("FIN_PROFILE") or self.verified_profile()
        self.ctx.refs["FIN_PROFILE"] = profile
        d = self.draft(challan_id=ids["challan_id"], tax_profile_id=profile, **draft)
        self.act(ANANYA, d.id, "submit")
        self.act(SAHIL, d.id, "approve")
        result = self.act(ANANYA, d.id, "issue")
        assert result.issued, [b.code for b in result.blockers]
        return result.detail

    def receipt(self, amount: str, currency: str = "EUR", party: str = "NORDHAUS", person: str = ANANYA) -> Any:
        with self.uow(person) as uow:
            r = receipts.record_receipt(uow, ReceiptCreate(party_id=self.ref(party), amount=Decimal(amount), currency=currency,  # type: ignore[arg-type]
                                                           received_on=self.ctx.clock.now().date()))
            return receipts.receipt_detail(uow, r)

    def allocate(self, receipt_id: uuid.UUID, invoice_id: uuid.UUID, amount: str, person: str = ANANYA) -> Any:
        with self.uow(person) as uow:
            return receipts.allocate_receipt(uow, receipt_id, AllocationCreate(invoice_id=invoice_id, amount=Decimal(amount)))

    def events(self, name: str) -> list[DomainEvent]:
        with self.system() as uow:
            return list(uow.session.scalars(select(DomainEvent).where(DomainEvent.company_id == self.company_id,
                                                                      DomainEvent.event_type == name).order_by(DomainEvent.occurred_at)))

    def count(self, model: type, *conds: Any) -> int:
        with self.system() as uow:
            return int(uow.session.scalar(select(func.count()).select_from(model).where(*conds)) or 0)


def build_fin_world(personas: World) -> FinWorld:
    base = build_inv_world(personas)
    return FinWorld(base.company_id, base.branch_id, base.ctx, base.actors)


@pytest.fixture
def fin_world(personas: World) -> FinWorld:
    return build_fin_world(personas)
