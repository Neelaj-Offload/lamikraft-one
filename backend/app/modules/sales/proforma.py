"""Proforma invoices: create from a quotation, edit while draft, issue, cancel, enter from history (module 3).

Spec: docs/superpowers/specs/2026-11-25-proforma-invoices-design.md. Scope follows quotations: a PI belongs to the
quotation owner (``owner_user_id``) and its branch; the ``sales.proforma`` policy gives own < team < branch < company.
Lines and totals come from the quotation revision the PI was made from and never change on the PI; to change them,
revise the quotation and make a new PI.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import ColumnElement, or_, select

from app.core.db.base import new_id
from app.core.errors import Conflict, ValidationFailed
from app.core.http.capabilities import Capability
from app.core.http.pagination import MAX_LIMIT, Page
from app.core.text import LIKE_ESCAPE, contains_pattern, tokens
from app.modules.sales.common import business_date, company_names, company_zone, party_refs, user_refs
from app.modules.sales.models import Quote, QuoteRevision
from app.modules.sales.proforma_models import PI_NUMBER_PATTERN, ProformaInvoice
from app.modules.sales.schemas import PartyRef, UserRef
from app.platform.numbering.defs import SequenceDef
from app.platform.service import query
from app.platform.uow import UnitOfWork

READ = "sales.proforma.read"
CREATE = "sales.proforma.create"
ISSUE = "sales.proforma.issue"
CANCEL = "sales.proforma.reverse"
BACKFILL = "sales.proforma.import"
CREATED = "sales.proforma.created"
ISSUED = "sales.proforma.issued"
CANCELLED = "sales.proforma.cancelled"
QUOTE_STATUSES_FOR_PI = ("sent", "revised", "won")

PROFORMA_SEQUENCE = SequenceDef(
    key="sales.proforma_invoice",
    name="Proforma invoice number",
    format_template="PI-{yyyy}-{seq:04}",
    reset_policy="yearly",
    resource_type="sales.proforma",
)

Short = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


# ---- schemas -------------------------------------------------------------------------------------------------
class ProformaFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    port_of_loading: Short | None = None
    port_of_discharge: Short | None = None
    payment_terms: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)] | None = None
    delivery_terms: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)] | None = None
    bank_account_label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)] | None = None
    declaration: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)] | None = None
    notes: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)] | None = None


class ProformaCreate(ProformaFields):
    """Header fields for a new draft. ``pi_number`` + ``pi_date`` enter an already issued PI from history."""

    pi_number: Annotated[str, StringConstraints(strip_whitespace=True, pattern=PI_NUMBER_PATTERN)] | None = None
    pi_date: date | None = None


class ProformaUpdate(ProformaFields):
    expected_version: int = Field(ge=1)


class ProformaIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    #: the document date; today when omitted, never in the future
    pi_date: date | None = None


class ProformaCancel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]


class ProformaFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    q: Annotated[str, StringConstraints(max_length=200)] | None = None
    status: Literal["draft", "issued", "cancelled"] | None = None
    party_id: uuid.UUID | None = None
    quote_id: uuid.UUID | None = None


class ProformaSummary(BaseModel):
    id: uuid.UUID
    pi_number: str | None
    draft_ref: str
    status: Literal["draft", "issued", "cancelled"]
    pi_date: date | None
    party: PartyRef
    owner: UserRef
    quote_id: uuid.UUID
    quote_number: str
    revision_no: int
    currency: str
    grand_total: str | None
    backfilled: bool
    updated_at: datetime
    path: str


class ProformaDetail(ProformaSummary):
    port_of_loading: str | None
    port_of_discharge: str | None
    payment_terms: str | None
    delivery_terms: str | None
    bank_account_label: str | None
    declaration: str | None
    notes: str | None
    lines: list[dict[str, Any]]
    totals: dict[str, Any]
    customer: dict[str, Any] | None
    customer_reference: str | None
    issued_at: datetime | None
    issued_by: UserRef | None
    cancelled_at: datetime | None
    cancel_reason: str | None
    bank_accounts: list[str]
    version: int
    created_at: datetime
    capabilities: dict[str, Capability]


# ---- helpers -------------------------------------------------------------------------------------------------
def proforma_path(proforma_id: uuid.UUID) -> str:
    return f"/sales/proforma-invoices/{proforma_id}"


def draft_ref(pi: ProformaInvoice) -> str:
    return f"PI-DRAFT-{str(pi.id)[-6:].upper()}"


def _invalid(field: str, code: str, msg: str) -> ValidationFailed:
    return ValidationFailed(msg, errors=[{"loc": ["body", field], "msg": msg, "code": code}])


def _bank_labels(uow: UnitOfWork) -> list[dict[str, Any]]:
    from app.platform.org.service import stored_or_default

    return list(stored_or_default(uow, "bank_details").model_dump(mode="json").get("accounts") or [])


def _default_bank(uow: UnitOfWork, currency: str) -> str | None:
    accounts = _bank_labels(uow)
    chosen = next((a for a in accounts if a.get("currency") == currency), None) or next(
        (a for a in accounts if a.get("is_default")), accounts[0] if accounts else None)
    return chosen.get("label") if chosen else None


def _check_bank(uow: UnitOfWork, label: str | None) -> None:
    if label is None:
        return
    if label.casefold() not in {str(a.get("label", "")).casefold() for a in _bank_labels(uow)}:
        raise _invalid("bank_account_label", "bank_account_unknown",
                       "Pick a bank account from Settings, Company, Bank details")


def _company_block(uow: UnitOfWork) -> dict[str, Any]:
    from app.platform.org.service import stored_or_default

    ident = stored_or_default(uow, "company_identity").model_dump(mode="json")
    terms = stored_or_default(uow, "document_terms").model_dump(mode="json")
    legal, display = company_names(uow)
    contacts = ident.get("contacts") or {}
    return {
        "legal_name": ident.get("legal_name") or legal,
        "display_name": ident.get("display_name") or display,
        "address_lines": ident.get("address_lines") or [],
        "gstin": ident.get("gstin"),
        "pan": ident.get("pan"),
        "iec": ident.get("iec"),
        "phone": contacts.get("phone"),
        "email": contacts.get("email"),
        "website": contacts.get("website"),
        "footer": terms.get("footer"),
        "time_zone": company_zone(uow),
    }


def _source_revision(uow: UnitOfWork, quote: Quote) -> QuoteRevision:
    stmt = select(QuoteRevision).where(QuoteRevision.quote_id == quote.id, QuoteRevision.kind == "issued")
    if quote.status == "won" and quote.accepted_revision_id is not None:
        row = uow.session.get(QuoteRevision, quote.accepted_revision_id)
        if row is not None:
            return row
    row = uow.session.scalars(stmt.order_by(QuoteRevision.revision_no.desc())).first()
    if row is None:
        raise Conflict("Issue the quotation before making a proforma invoice from it", code="quote_not_issued")
    return row


def _set_fields(pi: ProformaInvoice, data: ProformaFields, *, only_set: bool) -> list[str]:
    values = data.model_dump(exclude_unset=only_set, exclude={"expected_version", "pi_number", "pi_date"})
    changed = []
    for name, value in values.items():
        if getattr(pi, name) != value:
            setattr(pi, name, value)
            changed.append(name)
    return changed


def _freeze(uow: UnitOfWork, pi: ProformaInvoice, pi_date: date) -> None:
    pi.snapshot = {**pi.snapshot, "company": _company_block(uow)}
    pi.pi_date = pi_date
    pi.status = "issued"
    pi.issued_at = uow.now()
    pi.issued_by = uow.actor.user_id


def _emit(uow: UnitOfWork, name: str, pi: ProformaInvoice, **extra: Any) -> None:
    uow.emit(
        name,
        aggregate_id=pi.id,
        aggregate_version=pi.version,
        payload={"proforma_id": str(pi.id), "pi_number": pi.pi_number, "quote_id": str(pi.quote_id),
                 "party_id": str(pi.party_id), **extra},
    )


def _label(pi: ProformaInvoice) -> str:
    return pi.pi_number or draft_ref(pi)


# ---- commands ------------------------------------------------------------------------------------------------
def create_proforma(uow: UnitOfWork, quote_id: uuid.UUID, data: ProformaCreate) -> ProformaInvoice:
    actor = uow.actor
    actor.require(CREATE)
    quote = uow.repo(Quote).get(quote_id)  # 404 outside the caller's quote scope
    if quote.status not in QUOTE_STATUSES_FOR_PI:
        raise Conflict("Send the quotation before making a proforma invoice from it", code="quote_not_sent",
                       current_status=quote.status)
    revision = _source_revision(uow, quote)
    snap = revision.snapshot or {}
    header = snap.get("header") or {}
    _check_bank(uow, data.bank_account_label)
    today = business_date(uow)
    if data.pi_number is not None or data.pi_date is not None:
        actor.require(BACKFILL)
        if data.pi_number is None or data.pi_date is None:
            raise _invalid("pi_number", "backfill_needs_number_and_date",
                           "An issued PI from the past needs both its original number and its date")
        if data.pi_date > today:
            raise _invalid("pi_date", "pi_date_in_future", "Pick today or an earlier date")
        taken = uow.session.scalar(select(ProformaInvoice.id).where(
            ProformaInvoice.company_id == actor.company_id, ProformaInvoice.pi_number == data.pi_number))
        if taken is not None:
            raise Conflict("A proforma invoice with this number already exists", code="pi_number_taken")
    incoterm = " ".join(x for x in (header.get("incoterm"), header.get("incoterm_place")) if x) or None
    pi = ProformaInvoice(
        id=new_id(),
        company_id=actor.company_id,
        branch_id=quote.branch_id,
        quote_id=quote.id,
        revision_no=revision.revision_no,
        party_id=quote.party_id,
        owner_user_id=quote.owner_user_id,
        status="draft",
        currency=quote.currency,
        snapshot={
            "quote": {
                "quote_number": quote.quote_number,
                "revision_no": revision.revision_no,
                "issued_at": header.get("issued_at"),
                "customer_reference": header.get("customer_reference"),
                "incoterm": header.get("incoterm"),
                "incoterm_place": header.get("incoterm_place"),
                "brand": header.get("brand"),
            },
            "party": snap.get("party"),
            "lines": snap.get("lines") or [],
            "totals": snap.get("totals") or {},
        },
        payment_terms=header.get("payment_terms"),
        delivery_terms=incoterm,
        bank_account_label=_default_bank(uow, quote.currency),
    )
    _set_fields(pi, data, only_set=True)
    if data.pi_number is not None and data.pi_date is not None:
        pi.pi_number = data.pi_number
        pi.backfilled = True
        _freeze(uow, pi, data.pi_date)
    uow.add(pi)
    uow.flush()
    _emit(uow, CREATED, pi)
    if pi.status == "issued":
        _emit(uow, ISSUED, pi)  # backfilled PIs are told apart by the record, not the event
    uow.audit("sales.proforma.created", resource_type="sales.proforma", resource_id=pi.id, resource_label=_label(pi),
              details={"quote_number": quote.quote_number, "backfilled": pi.backfilled})
    return pi


def _locked(uow: UnitOfWork, proforma_id: uuid.UUID, version: int) -> ProformaInvoice:
    pi = uow.repo(ProformaInvoice).get(proforma_id, "update", for_update=True)
    uow.expect_version(pi, version)
    return pi


def update_proforma(uow: UnitOfWork, proforma_id: uuid.UUID, data: ProformaUpdate) -> ProformaInvoice:
    pi = _locked(uow, proforma_id, data.expected_version)
    if pi.status != "draft":
        raise Conflict("An issued proforma invoice cannot change. Cancel it and make a new one.", code="not_draft")
    _check_bank(uow, data.bank_account_label)
    changed = _set_fields(pi, data, only_set=True)
    if changed:
        pi.updated_at = uow.now()
        uow.flush()
        uow.audit("sales.proforma.updated", resource_type="sales.proforma", resource_id=pi.id,
                  resource_label=_label(pi), details={"changed_fields": sorted(changed)})
    return pi


def issue_proforma(uow: UnitOfWork, proforma_id: uuid.UUID, data: ProformaIssue) -> ProformaInvoice:
    uow.actor.require(ISSUE)
    pi = _locked(uow, proforma_id, data.expected_version)
    if pi.status != "draft":
        raise Conflict("This proforma invoice is already issued or cancelled", code="not_draft")
    today = business_date(uow)
    pi_date = data.pi_date or today
    if pi_date > today:
        raise _invalid("pi_date", "pi_date_in_future", "Pick today or an earlier date")
    pi.pi_number = uow.allocate_number(PROFORMA_SEQUENCE.key, document_date=pi_date, resource_type="sales.proforma",
                                       resource_id=pi.id)
    _freeze(uow, pi, pi_date)
    pi.updated_at = uow.now()
    uow.flush()
    _emit(uow, ISSUED, pi)
    uow.audit("sales.proforma.issued", resource_type="sales.proforma", resource_id=pi.id, resource_label=_label(pi))
    return pi


def cancel_proforma(uow: UnitOfWork, proforma_id: uuid.UUID, data: ProformaCancel) -> ProformaInvoice:
    uow.actor.require(CANCEL)
    pi = _locked(uow, proforma_id, data.expected_version)
    if pi.status == "cancelled":
        raise Conflict("This proforma invoice is already cancelled", code="already_cancelled")
    pi.status = "cancelled"
    pi.cancelled_at = uow.now()
    pi.cancel_reason = data.reason
    pi.updated_at = uow.now()
    uow.flush()
    _emit(uow, CANCELLED, pi)
    uow.audit("sales.proforma.cancelled", resource_type="sales.proforma", resource_id=pi.id, resource_label=_label(pi),
              reason=data.reason)
    return pi


# ---- reads ---------------------------------------------------------------------------------------------------
def _quote_numbers(uow: UnitOfWork, ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    return dict(uow.session.execute(select(Quote.id, Quote.quote_number).where(Quote.id.in_(set(ids)))).all())


def _summaries(uow: UnitOfWork, rows: list[ProformaInvoice]) -> list[dict[str, Any]]:
    parties = party_refs(uow, [r.party_id for r in rows], {
        r.party_id: (str((r.snapshot.get("party") or {}).get("party_number") or ""),
                     str((r.snapshot.get("party") or {}).get("display_name") or (r.snapshot.get("party") or {}).get("legal_name") or ""),
                     str((r.snapshot.get("party") or {}).get("country_code") or "")) for r in rows})
    owners = user_refs(uow, [r.owner_user_id for r in rows])
    quotes = _quote_numbers(uow, [r.quote_id for r in rows])
    out = []
    for r in rows:
        out.append({
            "id": r.id, "pi_number": r.pi_number, "draft_ref": draft_ref(r), "status": r.status, "pi_date": r.pi_date,
            "party": parties[r.party_id], "owner": owners.get(r.owner_user_id) or UserRef(id=r.owner_user_id, display_name=None),
            "quote_id": r.quote_id, "quote_number": quotes.get(r.quote_id) or (r.snapshot.get("quote") or {}).get("quote_number", ""),
            "revision_no": r.revision_no, "currency": r.currency,
            "grand_total": (r.snapshot.get("totals") or {}).get("grand_total"), "backfilled": r.backfilled,
            "updated_at": r.updated_at, "path": proforma_path(r.id),
        })
    return out


def _capabilities(uow: UnitOfWork, pi: ProformaInvoice) -> dict[str, Capability]:
    repo = uow.repo(ProformaInvoice)
    can_update = repo.can(pi, "update")

    def cap(ok: bool, reason: str) -> Capability:
        return Capability(allowed=ok, reason_code=None if ok else reason)

    draft = pi.status == "draft"
    return {
        "update": cap(can_update and draft, "permission_denied" if not can_update else "not_draft"),
        "issue": cap(can_update and draft and uow.actor.can(ISSUE), "permission_denied" if draft else "not_draft"),
        "cancel": cap(can_update and pi.status != "cancelled" and uow.actor.can(CANCEL),
                      "already_cancelled" if pi.status == "cancelled" else "permission_denied"),
        "download": Capability(allowed=True),
    }


def read_detail(uow: UnitOfWork, pi: ProformaInvoice) -> ProformaDetail:
    base = _summaries(uow, [pi])[0]
    issued_by = user_refs(uow, [pi.issued_by]).get(pi.issued_by) if pi.issued_by else None
    return ProformaDetail(
        **base,
        port_of_loading=pi.port_of_loading, port_of_discharge=pi.port_of_discharge, payment_terms=pi.payment_terms,
        delivery_terms=pi.delivery_terms, bank_account_label=pi.bank_account_label, declaration=pi.declaration,
        notes=pi.notes, lines=list(pi.snapshot.get("lines") or []), totals=dict(pi.snapshot.get("totals") or {}),
        customer=pi.snapshot.get("party"), customer_reference=(pi.snapshot.get("quote") or {}).get("customer_reference"),
        issued_at=pi.issued_at, issued_by=issued_by, cancelled_at=pi.cancelled_at, cancel_reason=pi.cancel_reason,
        bank_accounts=[str(a.get("label")) for a in _bank_labels(uow) if a.get("label")],
        version=pi.version, created_at=pi.created_at, capabilities=_capabilities(uow, pi),
    )


@query(READ)
def get_proforma(uow: UnitOfWork, proforma_id: uuid.UUID) -> ProformaDetail:
    return read_detail(uow, uow.repo(ProformaInvoice).get(proforma_id))


def _conditions(f: ProformaFilters) -> list[ColumnElement[bool]]:
    conds: list[ColumnElement[bool]] = []
    if f.status:
        conds.append(ProformaInvoice.status == f.status)
    if f.party_id:
        conds.append(ProformaInvoice.party_id == f.party_id)
    if f.quote_id:
        conds.append(ProformaInvoice.quote_id == f.quote_id)
    if f.q:
        for tok in tokens(f.q):
            pattern = contains_pattern(tok)
            conds.append(or_(
                ProformaInvoice.pi_number.ilike(pattern, escape=LIKE_ESCAPE),
                ProformaInvoice.snapshot["party"]["display_name"].astext.ilike(pattern, escape=LIKE_ESCAPE),
                ProformaInvoice.snapshot["party"]["legal_name"].astext.ilike(pattern, escape=LIKE_ESCAPE),
                ProformaInvoice.snapshot["quote"]["quote_number"].astext.ilike(pattern, escape=LIKE_ESCAPE),
            ))
    return conds


@query(READ)
def list_proformas(uow: UnitOfWork, filters: ProformaFilters, *, limit: int = 25, offset: int = 0) -> Page[ProformaSummary]:
    page = uow.repo(ProformaInvoice).list(
        *_conditions(filters),
        order_by=[ProformaInvoice.created_at.desc(), ProformaInvoice.id.desc()],
        limit=max(1, min(limit, MAX_LIMIT)),
        offset=max(0, offset),
    )
    return Page[ProformaSummary](
        items=[ProformaSummary(**s) for s in _summaries(uow, list(page.items))],
        total=page.total, limit=page.limit, offset=page.offset,
    )


def amount_in_words(amount: str | Decimal | None, currency: str) -> str | None:
    """"12,345.50 USD" → "US dollars twelve thousand three hundred forty-five and cents fifty only"."""
    if amount is None:
        return None
    value = Decimal(str(amount)).quantize(Decimal("0.01"))
    whole, fraction = int(value), int((value - int(value)) * 100)
    names = {"INR": ("Indian rupees", "paise"), "USD": ("US dollars", "cents"), "EUR": ("Euros", "cents"),
             "GBP": ("Pounds sterling", "pence")}
    major, minor = names.get(currency, (currency, "hundredths"))
    text = f"{major} {_words(whole)}"
    if fraction:
        text += f" and {minor} {_words(fraction)}"
    return text + " only"


_ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
         "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def _words(n: int) -> str:
    if n < 20:
        return _ONES[n]
    if n < 100:
        return _TENS[n // 10] + ("-" + _ONES[n % 10] if n % 10 else "")
    if n < 1000:
        return _ONES[n // 100] + " hundred" + (" " + _words(n % 100) if n % 100 else "")
    for size, name in ((10**9, "billion"), (10**6, "million"), (1000, "thousand")):
        if n >= size:
            return _words(n // size) + " " + name + (" " + _words(n % size) if n % size else "")
    return str(n)
