"""``lk import leads``: load the owner's leads spreadsheet (``LamiKraft Leads.xlsx``) into the lead pipeline.

Two halves:

- ``parse_sheet`` is pure: it reads the workbook into ``SheetRow`` values and reports what it cannot use (rejected
  rows, dropped values). It knows the sheet's layout: one row per company, up to five contact blocks
  (Contact Person / Designation / Email Id / Contact Number / Source, suffixed ``(2)`` … ``(5)``) and the address
  columns at the end.
- ``apply_rows`` writes through the normal party services (numbering, search text, events, audit, permissions).
  It is re-runnable: a lead is matched on its normalised name plus country. A match only gets what is missing
  (empty fields, new contacts, new note lines); stage, priority, temperature, owner and activities changed in the
  app are never overwritten. A dry run performs the same writes and rolls them back.

Spec: docs/superpowers/specs/2026-11-25-leads-module-design.md ("Import").
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.modules.parties import lead_sources, leads
from app.modules.parties import service as parties
from app.modules.parties.models import Party, PartyContact
from app.modules.parties.schemas import (
    AddressIn,
    ContactIn,
    LeadSourceCreate,
    LeadStageChange,
    PartyCreate,
    PartyUpdate,
)
from app.platform.uow import UnitOfWork

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

#: every country name used in the sheet → ISO 3166-1 alpha-2
COUNTRIES: dict[str, str] = {
    "albania": "AL", "anguilla": "AI", "antigua and barbuda": "AG", "argentina": "AR", "australia": "AU",
    "austria": "AT", "azerbaijan": "AZ", "bangladesh": "BD", "belgium": "BE", "brazil": "BR", "bulgaria": "BG",
    "canada": "CA", "chile": "CL", "china": "CN", "croatia": "HR", "cyprus": "CY", "czech republic": "CZ",
    "czechia": "CZ", "denmark": "DK", "dominican republic": "DO", "egypt": "EG", "finland": "FI", "france": "FR",
    "georgia": "GE", "germany": "DE", "greece": "GR", "guatemala": "GT", "honduras": "HN", "hong kong": "HK",
    "india": "IN", "ireland": "IE", "italy": "IT", "japan": "JP", "kuwait": "KW", "lebanon": "LB", "malaysia": "MY",
    "malta": "MT", "mauritius": "MU", "mexico": "MX", "montenegro": "ME", "morocco": "MA", "netherlands": "NL",
    "new zealand": "NZ", "north korea": "KP", "north macedonia": "MK", "norway": "NO", "peru": "PE",
    "poland": "PL", "portugal": "PT", "puerto rico": "PR", "qatar": "QA", "romania": "RO", "saudi arabia": "SA",
    "serbia": "RS", "singapore": "SG", "south africa": "ZA", "south korea": "KR", "spain": "ES", "sweden": "SE",
    "switzerland": "CH", "taiwan": "TW", "tanzania": "TZ", "thailand": "TH", "turkey": "TR", "turkiye": "TR",
    "united arab emirates": "AE", "uae": "AE", "united kingdom": "GB", "uk": "GB", "united states": "US",
    "usa": "US", "uzbekistan": "UZ", "vietnam": "VN",
}
#: the company enables INR, EUR, USD and GBP only (parties_party.default_currency_enabled)
EURO = {"AT", "BE", "BG", "HR", "CY", "DE", "EE", "ES", "FI", "FR", "GR", "IE", "IT", "LT", "LU", "LV", "ME", "MT",
        "NL", "PT", "SI", "SK"}

INTERESTS = {
    "lamikraft": "lamikraft",
    "table top": "table_top",
    "tabletop": "table_top",
    "standard decorative": "standard_decorative",
    "standard compact": "standard_compact",
}

#: sheet labels that mean a built-in source (anything else becomes a company source named after the label)
SOURCE_ALIASES: dict[str, str] = {
    "website": "website",
    "we": "website",
    "visiting card": "visiting_card",
    "visiting cards": "visiting_card",
}
#: words kept in capitals when a sheet label is turned into a display label
ACRONYMS = {"NRA", "HKTDC", "CIFF", "HORECA", "USA", "UK"}


def currency_for(country_code: str) -> str:
    if country_code == "IN":
        return "INR"
    if country_code == "GB":
        return "GBP"
    return "EUR" if country_code in EURO else "USD"


def pretty_label(raw: str) -> str:
    """"NRA CHICAGO 2026" → "NRA Chicago 2026"; "MAISON AND OBJET SHOW 2026" → "Maison and Objet Show 2026"."""
    words = []
    for word in raw.split():
        upper = word.upper()
        if upper in ACRONYMS:
            words.append(upper)
        elif upper in ("AND", "OF", "THE") and words:
            words.append(word.lower())
        else:
            words.append(word[:1].upper() + word[1:].lower())
    return " ".join(words)[:80]


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = re.sub(r"[ \t]+", " ", str(value)).strip()
    return text or None


def _key(header: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(header or "").lower())


# ---- parsed values ------------------------------------------------------------------------------------------------
@dataclass
class SheetContact:
    name: str
    job_title: str | None
    email: str | None
    phone: str | None
    source: str | None
    other_emails: list[str] = field(default_factory=list)


@dataclass
class SheetRow:
    row_no: int
    company: str
    country_code: str
    owner_name: str | None
    interests: list[str]
    source_label: str | None
    also_met_at: list[str]
    requirement: str | None
    website: str | None
    first_contact_on: date | None
    lead_action: str | None
    contacts: list[SheetContact]
    address: dict[str, str | None] | None
    notes: list[str] = field(default_factory=list)


@dataclass
class RowIssue:
    row_no: int
    company: str | None
    severity: str  # "rejected" (row skipped) or "warning" (value dropped, row kept)
    message: str


@dataclass
class ParsedSheet:
    rows: list[SheetRow]
    issues: list[RowIssue]


@dataclass
class ImportReport:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    sources_created: list[str] = field(default_factory=list)
    issues: list[RowIssue] = field(default_factory=list)

    @property
    def rejected(self) -> list[RowIssue]:
        return [i for i in self.issues if i.severity == "rejected"]


# ---- parsing ------------------------------------------------------------------------------------------------------
def _columns(header: tuple[Any, ...]) -> tuple[dict[str, int], list[dict[str, int]]]:
    keys = [_key(h) for h in header]
    single: dict[str, int] = {}
    for i, k in enumerate(keys):
        single.setdefault(k, i)
    blocks: list[dict[str, int]] = []
    for n in range(1, 6):
        suffix = "" if n == 1 else str(n)
        block = {}
        for field_name, header_key in (("name", "contactperson"), ("job_title", "designation"), ("email", "emailid"),
                                       ("phone", "contactnumber")):
            idx = single.get(header_key + suffix)
            if idx is not None:
                block[field_name] = idx
        if "phone" in block and block["phone"] + 1 < len(keys) and keys[block["phone"] + 1] == "source":
            block["source"] = block["phone"] + 1
        if block:
            blocks.append(block)
    return single, blocks


def _date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in ("%d-%b-%Y", "%d-%B-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d.%m.%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


_YEAR_END = re.compile(r"(19|20)\d{2}$")
_PHONE = re.compile(r"^\+?[\d\s().-]{6,}$")


def split_sources(raw: str | None) -> tuple[str | None, list[str]]:
    """"SPOGA 2022 & INTERGASTRA 2026" → ("SPOGA 2022", ["INTERGASTRA 2026"]). "&" splits only after a source that
    ends in a year or is a visiting card, so a show named "Maison & Objet …" stays whole."""
    if not raw:
        return None, []
    pieces = [raw.strip()]
    while "&" in pieces[-1]:
        head, _, tail = pieces[-1].partition("&")
        head, tail = head.strip(), tail.strip()
        if head and tail and (_YEAR_END.search(head) or head.lower() in SOURCE_ALIASES):
            pieces[-1:] = [head, tail]
        else:
            break
    return pieces[0], pieces[1:]


def _emails(raw: str | None) -> tuple[str | None, list[str], list[str]]:
    """(first valid email, other valid emails, invalid fragments) from a cell that may hold several."""
    if not raw:
        return None, [], []
    parts = [p.strip().strip(".") for p in re.split(r"[,;/\s]+", raw) if p.strip()]
    good = [p for p in parts if EMAIL.match(p) and len(p) <= 254]
    bad = [p for p in parts if p not in good]
    return (good[0] if good else None), good[1:], bad


def parse_sheet(path: Path | str) -> ParsedSheet:
    import openpyxl

    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    try:
        ws = wb.worksheets[0]
        rows = ws.iter_rows(values_only=True)
        header = next(rows, None)
        if header is None:
            return ParsedSheet([], [RowIssue(1, None, "rejected", "The sheet is empty")])
        single, blocks = _columns(header)
        out: list[SheetRow] = []
        issues: list[RowIssue] = []
        for row_no, values in enumerate(rows, start=2):
            if not any(v not in (None, "") for v in values):
                continue
            parsed = _row(row_no, values, single, blocks, issues)
            if parsed is not None:
                out.append(parsed)
        return ParsedSheet(out, issues)
    finally:
        wb.close()


def _cell(values: tuple[Any, ...], single: dict[str, int], key: str) -> str | None:
    idx = single.get(key)
    return _text(values[idx]) if idx is not None and idx < len(values) else None


def _row(
    row_no: int, values: tuple[Any, ...], single: dict[str, int], blocks: list[dict[str, int]], issues: list[RowIssue]
) -> SheetRow | None:
    company = _cell(values, single, "companybrandname") or _cell(values, single, "company")
    if not company:
        issues.append(RowIssue(row_no, None, "rejected", "No company name"))
        return None
    company = company[:200]
    country_name = _cell(values, single, "country")
    code = COUNTRIES.get((country_name or "").strip().lower())
    if code is None:
        issues.append(RowIssue(row_no, company, "rejected", f"Unknown country: {country_name or 'blank'}"))
        return None

    interests: list[str] = []
    for part in (_cell(values, single, "interestedin") or "").split(","):
        key = part.strip().lower()
        if not key:
            continue
        if key in INTERESTS:
            interests.append(INTERESTS[key])
        else:
            issues.append(RowIssue(row_no, company, "warning", f"Unknown interest dropped: {part.strip()}"))

    source_label, also = split_sources(_cell(values, single, "leadsource"))

    notes: list[str] = []
    contacts: list[SheetContact] = []
    for n, block in enumerate(blocks, start=1):
        def get(name: str, b: dict[str, int] = block) -> str | None:
            idx = b.get(name)
            return _text(values[idx]) if idx is not None and idx < len(values) else None

        name, job, raw_email, phone, csource = get("name"), get("job_title"), get("email"), get("phone"), get("source")
        if raw_email and "@" not in raw_email and _PHONE.match(raw_email):
            if not phone:  # a phone number typed into the email column
                phone = raw_email
            elif raw_email != phone:
                notes.append(f"Other phone for {name or f'contact {n}'}: {raw_email}")
            raw_email = None
        email, others, bad = _emails(raw_email)
        if bad:
            who = name or f"contact {n}"
            notes.append(f"Unverified email for {who}: {' '.join(bad)}")
            issues.append(RowIssue(row_no, company, "warning", f"Contact {n}: email kept in the note: {' '.join(bad)}"))
        if phone and len(phone) > 40:
            notes.append(f"Phone for {name or email or f'contact {n}'}: {phone}")
            phone = None
        if not (name or email or phone):
            continue
        contacts.append(
            SheetContact(
                name=(name or email or "Contact")[:200],
                job_title=job[:120] if job else None,
                email=email,
                phone=phone,
                source=csource,
                other_emails=others,
            )
        )

    address = None
    line1 = _cell(values, single, "addressline")
    if line1:
        full = line1
        if len(line1) > 200:
            notes.append(f"Full address: {full}")
            line1 = line1[:200]
        line2 = _cell(values, single, "addressline2")
        address = {
            "line1": line1,
            "line2": line2[:200] if line2 else None,
            "city": (_cell(values, single, "city") or "")[:120] or None,
            "region": (_cell(values, single, "state") or "")[:120] or None,
            "postal_code": (_cell(values, single, "pincode") or "")[:20] or None,
        }

    requirement = _cell(values, single, "requierment") or _cell(values, single, "requirement")
    if requirement and len(requirement) > 2000:
        notes.append(f"Requirement (full): {requirement}")
        requirement = requirement[:2000]
    website = _cell(values, single, "website")
    if website and len(website) > 200:
        issues.append(RowIssue(row_no, company, "warning", "Website longer than 200 characters dropped"))
        website = None
    created_raw_idx = single.get("createdate")
    created = _date(values[created_raw_idx]) if created_raw_idx is not None else None
    if created_raw_idx is not None and values[created_raw_idx] not in (None, "") and created is None:
        issues.append(RowIssue(row_no, company, "warning", f"Create date not understood: {values[created_raw_idx]}"))
    action = _cell(values, single, "leadaction")
    owner = _cell(values, single, "asignto") or _cell(values, single, "assignto")
    return SheetRow(
        row_no=row_no,
        company=company,
        country_code=code,
        owner_name=owner,
        interests=sorted(set(interests)),
        source_label=source_label,
        also_met_at=also,
        requirement=requirement,
        website=website,
        first_contact_on=created,
        lead_action=None if (action or "").upper() in ("", "NA", "N/A") else action,
        contacts=contacts,
        address=address,
        notes=notes,
    )


# ---- applying -----------------------------------------------------------------------------------------------------
def owner_key(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip().lower()


def _source_code(uow: UnitOfWork, label: str | None, report: ImportReport, cache: dict[str, str]) -> str | None:
    if not label:
        return None
    norm = label.strip().lower()
    if norm in cache:
        return cache[norm]
    lead_sources.ensure_system_sources(uow)
    if norm in SOURCE_ALIASES:
        cache[norm] = SOURCE_ALIASES[norm]
        return cache[norm]
    pretty = pretty_label(label)
    base = lead_sources.slug_code(label)
    code = base
    for n in range(2, 100):
        existing = uow.session.scalars(
            select(lead_sources.T).where(lead_sources.T.company_id == uow.actor.company_id, lead_sources.T.code == code)
        ).first()
        if existing is None:
            lead_sources.insert_lead_source(uow, LeadSourceCreate(code=code, label=pretty, display_order=50))
            report.sources_created.append(code)
            break
        if existing.label.strip().lower() == pretty.lower():
            break
        code = f"{base[:17].rstrip('_')}_{n}"  # same 20-character code, different show: keep both
    cache[norm] = code
    return code


def _note_lines(row: SheetRow, source_label: str | None) -> list[str]:
    lines = list(row.notes)
    lead = (source_label or "").strip().lower()
    for c in row.contacts:
        if c.source and c.source.strip().lower() != lead:
            lines.append(f"{c.name}: from {pretty_label(c.source)}")
        if c.other_emails:
            lines.append(f"{c.name}: other emails {', '.join(c.other_emails)}")
    for other in row.also_met_at:
        lines.append(f"Also met at {pretty_label(other)}")
    if row.lead_action:
        lines.append(f"Lead action in the sheet: {row.lead_action}")
    return lines


def _append_note(uow: UnitOfWork, party_id: uuid.UUID, lines: list[str]) -> bool:
    from app.platform.collab import service as collab

    if not lines:
        return False
    note = collab.get_note(uow, "parties.party", party_id)
    body = note.body or ""
    missing = [line for line in lines if line not in body]
    if not missing:
        return False
    header = "" if "From the leads sheet:" in body else ("\n\n" if body else "") + "From the leads sheet:"
    new_body = (body + header + "\n" + "\n".join(f"- {line}" for line in missing)).strip()
    collab.save_note(uow, "parties.party", party_id, body=new_body, expected_version=note.version)
    return True


def _contact_in(c: SheetContact, primary: bool) -> ContactIn:
    return ContactIn(name=c.name, job_title=c.job_title, email=c.email, phone=c.phone, is_primary=primary)


def _match(uow: UnitOfWork, row: SheetRow) -> Party | None:
    return uow.session.scalars(
        select(Party)
        .where(
            Party.company_id == uow.actor.company_id,
            Party.name_key == parties.name_key(row.company),
            Party.country_code == row.country_code,
            Party.archived_at.is_(None),
        )
        .order_by(Party.party_number)
    ).first()


def apply_rows(
    uow: UnitOfWork,
    sheet: ParsedSheet,
    owners: dict[str, uuid.UUID],
    *,
    default_owner: uuid.UUID | None = None,
) -> ImportReport:
    """Write the parsed rows. ``owners`` maps ``owner_key(name)`` to a member's user id."""
    report = ImportReport(issues=list(sheet.issues))
    sources: dict[str, str] = {}
    seen: set[tuple[str, str]] = set()
    for row in sheet.rows:
        label = f"row {row.row_no} · {row.company}"
        owner = owners.get(owner_key(row.owner_name)) if row.owner_name else None
        owner = owner or default_owner
        if owner is None:
            report.issues.append(
                RowIssue(row.row_no, row.company, "rejected", f"Owner not mapped: {row.owner_name or 'blank'}")
            )
            continue
        identity = (parties.name_key(row.company), row.country_code)
        if identity in seen:
            report.issues.append(
                RowIssue(row.row_no, row.company, "warning", "Same company and country as an earlier row: merged")
            )
        seen.add(identity)
        code = _source_code(uow, row.source_label, report, sources)
        lines = _note_lines(row, row.source_label)
        existing = _match(uow, row)
        if existing is None:
            created = parties.create_party(
                uow,
                PartyCreate(
                    legal_name=row.company,
                    country_code=row.country_code,
                    default_currency=currency_for(row.country_code),  # type: ignore[arg-type]
                    roles=["customer"],  # type: ignore[list-item]
                    status="prospect",  # type: ignore[arg-type]
                    owner_user_id=owner,
                    contacts=[_contact_in(c, i == 0) for i, c in enumerate(row.contacts)],
                    addresses=[AddressIn(kind="billing", country_code=row.country_code, **row.address)]  # type: ignore[arg-type]
                    if row.address else [],
                    website=row.website,
                    lead_source=code,
                    interests=row.interests,  # type: ignore[arg-type]
                    requirement=row.requirement,
                    first_contact_on=row.first_contact_on,
                ),
                origin="import",
            )
            if row.lead_action and "order form" in row.lead_action.lower():
                leads.change_lead_stage(
                    uow, created.id, LeadStageChange(expected_version=created.version, stage="negotiating")  # type: ignore[arg-type]
                )
            _append_note(uow, created.id, lines)
            report.created.append(label)
            continue
        changed = _fill(uow, existing, row, code)
        noted = _append_note(uow, existing.id, lines)
        (report.updated if changed or noted else report.unchanged).append(label)
    return report


def _fill(uow: UnitOfWork, party: Party, row: SheetRow, code: str | None) -> bool:
    """Fill only what is empty and add missing contacts; never touches stage, priority, temperature or owner."""
    fields: dict[str, Any] = {}
    if party.website is None and row.website:
        fields["website"] = row.website
    if party.lead_source_code is None and code:
        fields["lead_source"] = code
    if not party.interests and row.interests:
        fields["interests"] = row.interests
    if party.requirement is None and row.requirement:
        fields["requirement"] = row.requirement
    if row.first_contact_on and (party.first_contact_on is None or row.first_contact_on < party.first_contact_on):
        fields["first_contact_on"] = row.first_contact_on
    current = list(
        uow.session.scalars(
            select(PartyContact)
            .where(PartyContact.party_id == party.id, PartyContact.archived_at.is_(None))
            .order_by(PartyContact.sort_order, PartyContact.id)
        )
    )
    emails = {c.email.lower() for c in current if c.email}
    names = {c.name.strip().lower() for c in current}
    has_primary = any(c.is_primary for c in current)
    new = [
        c for c in row.contacts
        if not ((c.email and c.email.lower() in emails) or (not c.email and c.name.strip().lower() in names))
    ]
    if new:
        fields["contacts"] = [
            ContactIn(id=c.id, name=c.name, job_title=c.job_title, email=c.email, phone=c.phone, is_primary=c.is_primary)
            for c in current
        ] + [_contact_in(c, not has_primary and i == 0) for i, c in enumerate(new)]
    if not fields:
        return False
    parties.update_party(uow, party.id, PartyUpdate(expected_version=party.version, **fields), origin="import")
    return True
