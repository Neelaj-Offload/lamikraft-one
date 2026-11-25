"""Party services (minimal Slice-1 master): create, update, read, list, search, resolve.

Visibility is the ``parties.party`` ResourcePolicy (own/team/branch/company on ``owner_user_id`` and
``branch_id``); a party outside the actor's scope is a 404, a visible party the actor may not edit is a 403.
Party numbers come from the platform allocator (``P-NNNNN``, never reset).
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from pydantic import BaseModel
from sqlalchemy import ColumnElement, Select, and_, func, or_, select

from app.core.clock import local_date
from app.core.db.base import new_id
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.core.http.pagination import MAX_LIMIT, Page
from app.core.text import LIKE_ESCAPE, contains_pattern, normalize_search_text, tokens
from app.modules.parties import events as ev
from app.modules.parties.customer_types import ensure_customer_type
from app.modules.parties.lead_sources import ensure_lead_source, labels_for
from app.modules.parties.models import Party, PartyAddress, PartyContact, PartyTaxIdentifier
from app.modules.parties.schemas import (
    AddressIn,
    AddressKind,
    AddressRead,
    Capability,
    ContactIn,
    ContactRead,
    CustomerType,
    LeadSourceRef,
    PartyCandidate,
    PartyCreate,
    PartyDetail,
    PartyFilters,
    PartyResolution,
    PartyRole,
    PartyStatus,
    PartySummary,
    PartyUpdate,
    TaxIdentifierIn,
    TaxIdentifierRead,
    TaxScheme,
    UserRef,
)
from app.platform.idempotency.service import run_idempotent
from app.platform.identity.models import AppUser, Membership
from app.platform.org.models import Branch
from app.platform.service import query
from app.platform.sources import SourceFacts
from app.platform.uow import UnitOfWork

READ = "parties.party.read"
_PARTY_NUMBER = re.compile(r"^P-\d{5,}$")


def party_path(party_id: uuid.UUID) -> str:
    return f"/sales/parties/{party_id}"


def name_key(name: str) -> str:
    return " ".join(name.split()).casefold()


class _Errors:
    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    def add(self, loc: Sequence[str | int], code: str, msg: str) -> None:
        self.items.append({"loc": ["body", *loc], "msg": msg, "code": code})

    def raise_if_any(self) -> None:
        if self.items:
            raise ValidationFailed("Some party values are not valid", errors=self.items)


# =====================================================================================================
# validation helpers
# =====================================================================================================
def _check_member(uow: UnitOfWork, user_id: uuid.UUID, errors: _Errors) -> None:
    active = uow.session.scalar(
        select(Membership.id).where(
            Membership.company_id == uow.actor.company_id, Membership.user_id == user_id, Membership.status == "active"
        )
    )
    if active is None:
        errors.add(["owner_user_id"], "owner_not_member", "The owner must be an active member of the company")


def _check_branch(uow: UnitOfWork, branch_id: uuid.UUID, errors: _Errors) -> None:
    found = uow.session.scalar(
        select(Branch.id).where(Branch.id == branch_id, Branch.company_id == uow.actor.company_id, Branch.archived_at.is_(None))
    )
    if found is None:
        errors.add(["branch_id"], "branch_not_found", "The branch does not exist")


def _check_children(
    contacts: Sequence[ContactIn] | None,
    addresses: Sequence[AddressIn] | None,
    roles: Sequence[PartyRole],
    customer_type: CustomerType | None,
    errors: _Errors,
) -> None:
    if contacts is not None and sum(1 for c in contacts if c.is_primary) > 1:
        errors.add(["contacts"], "multiple_primary_contacts", "Only one contact can be primary")
    if addresses is not None:
        for kind in AddressKind:
            if sum(1 for a in addresses if a.kind == kind and a.is_default) > 1:
                errors.add(["addresses"], "multiple_default_addresses", f"Only one default {kind.value} address")
    if customer_type is not None and PartyRole.CUSTOMER not in roles:
        errors.add(["customer_type"], "customer_type_requires_customer_role", "Only customers have a customer type")


def _check_tax_unique(
    uow: UnitOfWork, items: Sequence[TaxIdentifierIn] | None, party_id: uuid.UUID | None, errors: _Errors
) -> None:
    if not items:
        return
    seen: set[tuple[str, str]] = set()
    for i, item in enumerate(items):
        key = (item.scheme.value, item.value)
        if key in seen:
            errors.add(["tax_identifiers", i, "value"], "duplicate_tax_identifier", "The identifier is listed twice")
        seen.add(key)
        clash = uow.session.scalar(
            select(PartyTaxIdentifier.party_id).where(
                PartyTaxIdentifier.company_id == uow.actor.company_id,
                PartyTaxIdentifier.scheme == key[0],
                PartyTaxIdentifier.value == key[1],
                PartyTaxIdentifier.archived_at.is_(None),
            )
        )
        if clash is not None and clash != party_id:
            errors.add(["tax_identifiers", i, "value"], "tax_identifier_in_use", "Another party already has this identifier")


def _search_text(party: Party, contact_names: Sequence[str]) -> str:
    return normalize_search_text(" ".join([party.party_number, party.legal_name, party.display_name, *contact_names]))


def _live_contacts(uow: UnitOfWork, party_id: uuid.UUID) -> list[PartyContact]:
    return list(
        uow.session.scalars(
            select(PartyContact)
            .where(PartyContact.party_id == party_id, PartyContact.archived_at.is_(None))
            .order_by(PartyContact.sort_order, PartyContact.id)
        )
    )


# =====================================================================================================
# child synchronisation (replace semantics; rows left out are archived, never deleted)
# =====================================================================================================
_CONTACT_FIELDS = ("name", "job_title", "email", "phone", "is_primary")
_ADDRESS_FIELDS = ("kind", "line1", "line2", "city", "region", "postal_code", "country_code", "is_default")
_TAX_FIELDS = ("scheme", "value", "country_code")
_FLAG = {PartyContact: "is_primary", PartyAddress: "is_default"}


def _sync_children(
    uow: UnitOfWork,
    model: type[Any],
    party_id: uuid.UUID,
    items: Sequence[BaseModel],
    fields: Sequence[str],
    errors: _Errors,
    loc: str,
) -> list[tuple[Any, Any]]:
    """Returns (before, after) value tuples of every row that was added, changed or archived."""
    existing = {
        row.id: row
        for row in uow.session.scalars(select(model).where(model.party_id == party_id, model.archived_at.is_(None)))
    }
    for i, item in enumerate(items):
        item_id = getattr(item, "id", None)
        if item_id is not None and item_id not in existing:
            errors.add([loc, i, "id"], "child_not_found", "This row does not belong to the party")
    errors.raise_if_any()
    changes: list[tuple[Any, Any]] = []
    flag = _FLAG.get(model)
    now, user = uow.now(), uow.actor.user_id
    kept = {getattr(item, "id", None) for item in items}
    updates: list[tuple[Any, dict[str, Any]]] = []
    for row_id, row in existing.items():
        if row_id not in kept:
            changes.append((row, None))
            row.archived_at, row.archived_by = now, user
            if flag:
                setattr(row, flag, False)
    for item in items:
        values = {f: getattr(item, f) for f in fields}
        values = {k: (v.value if hasattr(v, "value") else v) for k, v in values.items()}
        item_id = getattr(item, "id", None)
        if item_id is None:
            continue
        row = existing[item_id]
        before = {f: getattr(row, f) for f in fields}
        if before != values:
            updates.append((row, values))
            changes.append((dict(before), dict(values)))
    # clear flags first so partial unique indexes never see two primaries/defaults mid-flush
    if flag:
        for row, values in updates:
            if getattr(row, flag) and not values.get(flag):
                setattr(row, flag, False)
    uow.flush()
    for row, values in updates:
        for f, v in values.items():
            setattr(row, f, v)
    uow.flush()
    for order, item in enumerate(items):
        if getattr(item, "id", None) is not None:
            continue
        values = {f: getattr(item, f) for f in fields}
        values = {k: (v.value if hasattr(v, "value") else v) for k, v in values.items()}
        row = model(id=new_id(), company_id=uow.actor.company_id, party_id=party_id, **values)
        if model is PartyContact:
            row.sort_order = order
        uow.add(row)
        changes.append((None, values))
    uow.flush()
    return changes


def _address_kinds(changes: Sequence[tuple[Any, Any]]) -> set[str]:
    kinds: set[str] = set()
    for before, after in changes:
        for side in (before, after):
            if side is None:
                continue
            kinds.add(side["kind"] if isinstance(side, dict) else side.kind)
    return kinds


# =====================================================================================================
# commands
# =====================================================================================================
def create_party(uow: UnitOfWork, data: PartyCreate, *, origin: str | None = None) -> PartyDetail:
    actor = uow.actor
    actor.require("parties.party.create")
    errors = _Errors()
    owner_id = data.owner_user_id or actor.user_id
    if owner_id is None:
        errors.add(["owner_user_id"], "required", "A party needs an owner")
        errors.raise_if_any()
    assert owner_id is not None
    if owner_id != actor.user_id and not actor.can("parties.party.assign"):
        raise Forbidden("Assigning a party to someone else needs parties.party.assign", code="permission_denied",
                        permission="parties.party.assign")
    _check_member(uow, owner_id, errors)
    if data.branch_id is not None:
        _check_branch(uow, data.branch_id, errors)
    _check_children(data.contacts, data.addresses, data.roles, data.customer_type, errors)
    _check_tax_unique(uow, data.tax_identifiers, None, errors)
    errors.raise_if_any()
    ctype = ensure_customer_type(uow, data.customer_type.value if data.customer_type else None)
    is_lead = PartyRole.CUSTOMER in data.roles
    source = ensure_lead_source(uow, data.lead_source) if is_lead else None
    party = Party(
        id=new_id(),
        company_id=actor.company_id,
        legal_name=data.legal_name,
        display_name=data.display_name or data.legal_name,
        name_key=name_key(data.display_name or data.legal_name),
        country_code=data.country_code,
        default_currency=data.default_currency,
        customer_type=ctype,
        status=data.status.value,
        roles=sorted({r.value for r in data.roles}),
        owner_user_id=owner_id,
        branch_id=data.branch_id,
        search_text="",
        website=data.website,
        requirement=data.requirement,
    )
    if is_lead:
        party.lead_source_code = source
        party.interests = sorted({i.value for i in data.interests}) or None
        party.first_contact_on = data.first_contact_on or local_date(uow.now(), actor.time_zone)
        party.lead_stage = "new" if data.status == PartyStatus.PROSPECT else "won"
        party.priority = (data.priority.value if data.priority else "B")
        party.temperature = (data.temperature.value if data.temperature else "cold")
    party.party_number = uow.allocate_number(
        ev.PARTY_SEQUENCE.key,
        document_date=local_date(uow.now(), actor.time_zone),
        resource_type="parties.party",
        resource_id=party.id,
    )
    party.search_text = _search_text(party, [c.name for c in data.contacts])  # before the INSERT: version 1
    uow.add(party)
    uow.flush()
    _sync_children(uow, PartyContact, party.id, data.contacts, _CONTACT_FIELDS, errors, "contacts")
    _sync_children(uow, PartyAddress, party.id, data.addresses, _ADDRESS_FIELDS, errors, "addresses")
    _sync_children(uow, PartyTaxIdentifier, party.id, data.tax_identifiers, _TAX_FIELDS, errors, "tax_identifiers")
    uow.emit(
        ev.PARTY_CREATED,
        aggregate_id=party.id,
        aggregate_version=party.version,
        payload=ev.payload(
            ev.PartyCreatedPayload(party_id=party.id, party_number=party.party_number, owner_user_id=owner_id, origin=origin)
        ),
    )
    uow.audit(
        "parties.party.created",
        resource_type="parties.party",
        resource_id=party.id,
        resource_label=f"{party.party_number} · {party.display_name}",
    )
    return _detail(uow, party)


def update_party(uow: UnitOfWork, party_id: uuid.UUID, data: PartyUpdate, *, origin: str | None = None) -> PartyDetail:
    party = uow.repo(Party).get(party_id, "update", for_update=True)
    uow.expect_version(party, data.expected_version)
    errors = _Errors()
    fields = data.model_dump(exclude_unset=True, exclude={"expected_version", "contacts", "addresses", "tax_identifiers"})
    roles = [PartyRole(r) for r in (fields.get("roles") or party.roles)]
    ctype_value = fields["customer_type"] if "customer_type" in fields else party.customer_type
    _check_children(data.contacts, data.addresses, roles, CustomerType(ctype_value) if ctype_value else None, errors)
    if fields.get("branch_id") is not None:
        _check_branch(uow, fields["branch_id"], errors)
    _check_tax_unique(uow, data.tax_identifiers, party.id, errors)
    if "customer_type" in fields and fields["customer_type"] is not None:
        ensure_customer_type(uow, str(fields["customer_type"]), current=party.customer_type)
    if "lead_source" in fields:
        code = fields.pop("lead_source")
        fields["lead_source_code"] = ensure_lead_source(uow, code, current=party.lead_source_code) if code else None
    if "interests" in fields:
        values = fields["interests"]
        fields["interests"] = sorted({getattr(i, "value", i) for i in values}) or None if values is not None else None
    for cleared in ("priority", "temperature", "first_contact_on"):
        if cleared in fields and fields[cleared] is None:
            fields.pop(cleared)  # these always have a value on a lead; sending null keeps the current one
    for required in ("legal_name", "display_name", "country_code", "default_currency", "roles", "status"):
        if required in fields and fields[required] is None:
            errors.add([required], "required", f"{required} cannot be cleared")
    errors.raise_if_any()
    changed: set[str] = set()
    # child rows first: their flushes must not carry a dirty party row (one version bump per update)
    if data.contacts is not None and _sync_children(
        uow, PartyContact, party.id, data.contacts, _CONTACT_FIELDS, errors, "contacts"
    ):
        changed.add("contacts")
    if data.addresses is not None:
        address_changes = _sync_children(uow, PartyAddress, party.id, data.addresses, _ADDRESS_FIELDS, errors, "addresses")
        changed.update(f"addresses.{kind}" for kind in _address_kinds(address_changes))
    if data.tax_identifiers is not None and _sync_children(
        uow, PartyTaxIdentifier, party.id, data.tax_identifiers, _TAX_FIELDS, errors, "tax_identifiers"
    ):
        changed.add("tax_identifiers")
    for name, value in fields.items():
        if name == "roles":
            value = sorted({PartyRole(r).value for r in value})
        elif hasattr(value, "value"):
            value = value.value
        if getattr(party, name) != value:
            setattr(party, name, value)
            changed.add(name)
    if "display_name" in changed:
        party.name_key = name_key(party.display_name)
    _sync_lead_stage(uow, party, changed)
    if not changed:
        return _detail(uow, party)
    party.search_text = _search_text(party, [c.name for c in _live_contacts(uow, party.id)])
    party.updated_at = uow.now()  # bumps the optimistic version when only child rows changed
    uow.flush()
    uow.emit(
        ev.PARTY_UPDATED,
        aggregate_id=party.id,
        aggregate_version=party.version,
        payload=ev.payload(
            ev.PartyUpdatedPayload(
                party_id=party.id, party_number=party.party_number, changed_fields=sorted(changed), origin=origin
            )
        ),
    )
    uow.audit(
        "parties.party.updated",
        resource_type="parties.party",
        resource_id=party.id,
        resource_label=f"{party.party_number} · {party.display_name}",
        details={"changed_fields": sorted(changed)},
    )
    return _detail(uow, party)


def _sync_lead_stage(uow: UnitOfWork, party: Party, changed: set[str]) -> None:
    """Keep the pipeline consistent with role and status edits made through the general form: a party that gains
    the customer role gets lead defaults; turning a prospect into an active customer marks the lead won; turning a
    won customer back into a prospect reopens it as new."""
    if PartyRole.CUSTOMER.value not in party.roles:
        return
    if party.lead_stage is None:
        party.lead_stage = "new" if party.status == PartyStatus.PROSPECT.value else "won"
        party.priority = party.priority or "B"
        party.temperature = party.temperature or "cold"
        party.first_contact_on = party.first_contact_on or local_date(uow.now(), uow.actor.time_zone)
        changed.add("lead_stage")
    elif "status" in changed:
        if party.status == PartyStatus.ACTIVE.value and party.lead_stage not in ("won", "lost"):
            party.lead_stage = "won"
            changed.add("lead_stage")
        elif party.status == PartyStatus.PROSPECT.value and party.lead_stage == "won":
            party.lead_stage = "new"
            changed.add("lead_stage")


def _idempotent[T: BaseModel](
    uow: UnitOfWork, operation: str, body: BaseModel, fn: Callable[[], T], model: type[T], status: int = 200
) -> tuple[T, bool]:
    out, replayed = run_idempotent(
        uow,
        key=uow.actor.idempotency_key,
        operation=operation,
        body=body.model_dump(mode="json"),
        fn=lambda: fn().model_dump(mode="json"),
        status=status,
    )
    return model.model_validate(out), replayed


def create_party_command(uow: UnitOfWork, data: PartyCreate) -> tuple[PartyDetail, bool]:
    """HTTP entry point: the optional ``Idempotency-Key`` replays the stored response (still permission-checked)."""
    uow.actor.require("parties.party.create")
    return _idempotent(uow, "parties.create_party", data, lambda: create_party(uow, data), PartyDetail, status=201)


def update_party_command(uow: UnitOfWork, party_id: uuid.UUID, data: PartyUpdate) -> tuple[PartyDetail, bool]:
    uow.repo(Party).get(party_id, "update")  # 404 outside scope, 403 when visible but not editable
    return _idempotent(
        uow,
        f"parties.update_party:{party_id}",
        data,
        lambda: update_party(uow, party_id, data),
        PartyDetail,
    )


# =====================================================================================================
# reads
# =====================================================================================================
def _owner_names(uow: UnitOfWork, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    return dict(uow.session.execute(select(AppUser.id, AppUser.display_name).where(AppUser.id.in_(set(ids)))).all())


def _primary_contacts(uow: UnitOfWork, party_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not party_ids:
        return {}
    rows = uow.session.execute(
        select(PartyContact.party_id, PartyContact.name, PartyContact.is_primary)
        .where(PartyContact.party_id.in_(set(party_ids)), PartyContact.archived_at.is_(None))
        .order_by(PartyContact.party_id, PartyContact.is_primary.desc(), PartyContact.sort_order, PartyContact.id)
    ).all()
    out: dict[uuid.UUID, str] = {}
    for party_id, name, _primary in rows:
        out.setdefault(party_id, name)
    return out


def _summary(
    party: Party,
    owner_names: dict[uuid.UUID, str],
    contacts: dict[uuid.UUID, str],
    sources: dict[str, str] | None = None,
) -> dict[str, Any]:
    code = party.lead_source_code
    source = LeadSourceRef(code=code, label=(sources or {}).get(code, code)) if code else None
    return {
        "id": party.id,
        "party_number": party.party_number,
        "legal_name": party.legal_name,
        "display_name": party.display_name,
        "country_code": party.country_code,
        "default_currency": party.default_currency,
        "customer_type": party.customer_type,
        "roles": list(party.roles),
        "status": party.status,
        "owner": UserRef(id=party.owner_user_id, display_name=owner_names.get(party.owner_user_id)),
        "branch_id": party.branch_id,
        "primary_contact": contacts.get(party.id),
        "updated_at": party.updated_at,
        "path": party_path(party.id),
        "lead_stage": party.lead_stage,
        "lead_source": source,
        "interests": list(party.interests or []),
        "priority": party.priority,
        "temperature": party.temperature,
        "next_follow_up_on": party.next_follow_up_on,
    }


def _detail(uow: UnitOfWork, party: Party) -> PartyDetail:
    contacts = _live_contacts(uow, party.id)
    addresses = list(
        uow.session.scalars(
            select(PartyAddress)
            .where(PartyAddress.party_id == party.id, PartyAddress.archived_at.is_(None))
            .order_by(PartyAddress.kind, PartyAddress.is_default.desc(), PartyAddress.id)
        )
    )
    taxes = list(
        uow.session.scalars(
            select(PartyTaxIdentifier)
            .where(PartyTaxIdentifier.party_id == party.id, PartyTaxIdentifier.archived_at.is_(None))
            .order_by(PartyTaxIdentifier.scheme, PartyTaxIdentifier.id)
        )
    )
    repo = uow.repo(Party)
    can_update = repo.can(party, "update")
    base = _summary(
        party,
        _owner_names(uow, [party.owner_user_id]),
        _primary_contacts(uow, [party.id]),
        labels_for(uow, [party.lead_source_code]),
    )
    return PartyDetail(
        **base,
        contacts=[
            ContactRead(id=c.id, name=c.name, job_title=c.job_title, email=c.email, phone=c.phone, is_primary=c.is_primary)
            for c in contacts
        ],
        addresses=[
            AddressRead(
                id=a.id, kind=AddressKind(a.kind), line1=a.line1, line2=a.line2, city=a.city, region=a.region,
                postal_code=a.postal_code, country_code=a.country_code, is_default=a.is_default,
            )
            for a in addresses
        ],
        tax_identifiers=[
            TaxIdentifierRead(
                id=t.id, scheme=TaxScheme(t.scheme), value=t.value, country_code=t.country_code,
                verification_status="unverified",
            )
            for t in taxes
        ],
        version=party.version,
        created_at=party.created_at,
        archived_at=party.archived_at,
        capabilities={
            "update": Capability(allowed=can_update, reason_code=None if can_update else "permission_denied"),
            "archive": _archive_capability(uow, party, archived=False),
            "restore": _archive_capability(uow, party, archived=True),
            **lead_capabilities(uow, party, can_update=can_update),
        },
        website=party.website,
        requirement=party.requirement,
        first_contact_on=party.first_contact_on,
        lost_reason=party.lost_reason,
    )


def lead_capabilities(uow: UnitOfWork, party: Party, *, can_update: bool) -> dict[str, Capability]:
    """``change_stage`` (parties.party.update on an open or lost lead) and ``log_activity`` (parties.activity.create)."""
    if party.lead_stage is None:
        no = Capability(allowed=False, reason_code="not_a_lead")
        return {"change_stage": no, "log_activity": no}
    if party.archived_at is not None:
        archived = Capability(allowed=False, reason_code="archived")
        return {"change_stage": archived, "log_activity": archived}
    if not can_update:
        stage = Capability(allowed=False, reason_code="permission_denied")
    elif party.lead_stage == "won":
        stage = Capability(allowed=False, reason_code="lead_won")
    else:
        stage = Capability(allowed=True)
    can_log = uow.repo(Party).can(party, "read") and uow.actor.can("parties.activity.create")
    log = Capability(allowed=can_log, reason_code=None if can_log else "permission_denied")
    return {"change_stage": stage, "log_activity": log}


def _archive_capability(uow: UnitOfWork, party: Party, *, archived: bool) -> Capability:
    """``archive`` applies to a live party, ``restore`` to an archived one; both need ``parties.party.archive``."""
    if (party.archived_at is not None) != archived:
        return Capability(allowed=False, reason_code="archived" if not archived else "not_archived")
    if not uow.repo(Party).can(party, "archive"):
        return Capability(allowed=False, reason_code="permission_denied")
    return Capability(allowed=True)


def set_party_archived(uow: UnitOfWork, party_id: uuid.UUID, *, archived: bool, expected_version: int) -> PartyDetail:
    """Archive (or restore) a party; quotes keep their party snapshot. 409 when already in that state."""
    party = uow.repo(Party).get(party_id, "archive", for_update=True)
    uow.expect_version(party, expected_version)
    if (party.archived_at is not None) == archived:
        raise Conflict("The party is already " + ("archived" if archived else "active"), code="invalid_state")
    party.archived_at = uow.now() if archived else None
    party.archived_by = uow.actor.user_id if archived else None
    party.updated_at = uow.now()
    uow.flush()
    if archived:
        uow.emit(
            ev.PARTY_ARCHIVED,
            aggregate_id=party.id,
            aggregate_version=party.version,
            payload=ev.payload(ev.PartyArchivedPayload(party_id=party.id)),
        )
    else:
        uow.emit(
            ev.PARTY_UPDATED,
            aggregate_id=party.id,
            aggregate_version=party.version,
            payload=ev.payload(
                ev.PartyUpdatedPayload(party_id=party.id, party_number=party.party_number, changed_fields=["archived_at"])
            ),
        )
    uow.audit(
        "parties.party.archived" if archived else "parties.party.restored",
        resource_type="parties.party",
        resource_id=party.id,
        resource_label=f"{party.party_number} · {party.display_name}",
    )
    return _detail(uow, party)


@query(READ)
def get_party(uow: UnitOfWork, party_id: uuid.UUID) -> PartyDetail:
    return _detail(uow, uow.repo(Party).get(party_id))


@query(READ)
def get_party_by_number(uow: UnitOfWork, party_number: str) -> PartyDetail:
    return _detail(uow, uow.repo(Party).get_by_key(party_number.strip().upper()))


def _filter_conditions(f: PartyFilters, today: date | None = None) -> list[ColumnElement[bool]]:
    conds: list[ColumnElement[bool]] = []
    if f.q:
        for tok in tokens(f.q):
            conds.append(Party.search_text.ilike(contains_pattern(tok), escape=LIKE_ESCAPE))
    if f.role:
        conds.append(Party.roles.contains([f.role.value]))
    if f.country_code:
        conds.append(Party.country_code == f.country_code)
    if f.customer_type:
        conds.append(Party.customer_type == f.customer_type.value)
    if f.status:
        conds.append(Party.status.in_([s.value for s in f.status]))
    if f.owner_user_id:
        conds.append(Party.owner_user_id == f.owner_user_id)
    if f.lead_stage:
        conds.append(Party.lead_stage.in_([s.value for s in f.lead_stage]))
    if f.lead_source:
        conds.append(Party.lead_source_code == f.lead_source)
    if f.interest:
        conds.append(Party.interests.contains([f.interest.value]))
    if f.priority:
        conds.append(Party.priority == f.priority.value)
    if f.temperature:
        conds.append(Party.temperature == f.temperature.value)
    if f.follow_up and today is not None:
        if f.follow_up == "overdue":
            conds.append(Party.next_follow_up_on < today)
        elif f.follow_up == "today":
            conds.append(Party.next_follow_up_on == today)
        else:
            conds.append(Party.next_follow_up_on.between(today, today + timedelta(days=7)))
    return conds


def _order(sort: str) -> list[Any]:
    if sort == "follow_up":
        return [Party.next_follow_up_on.asc().nulls_last(), Party.name_key, Party.id]
    if sort == "recent":
        return [Party.first_contact_on.desc().nulls_last(), Party.created_at.desc(), Party.id]
    return [Party.name_key, Party.party_number, Party.id]


@query(READ)
def list_parties(uow: UnitOfWork, filters: PartyFilters, *, limit: int = 50, offset: int = 0) -> Page[PartySummary]:
    """Scoped list: own-scope users see only the parties they own; filters apply before pagination."""
    repo = uow.repo(Party)
    today = local_date(uow.now(), uow.actor.time_zone)
    page = repo.list(
        *_filter_conditions(filters, today),
        order_by=_order(filters.sort),
        limit=max(1, min(limit, MAX_LIMIT)),
        offset=max(0, offset),
        include_archived=filters.include_archived,
    )
    owners = _owner_names(uow, [p.owner_user_id for p in page.items])
    contacts = _primary_contacts(uow, [p.id for p in page.items])
    sources = labels_for(uow, [p.lead_source_code for p in page.items])
    return Page[PartySummary](
        items=[PartySummary(**_summary(p, owners, contacts, sources)) for p in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


def _candidate(party: Party, match: str) -> PartyCandidate:
    return PartyCandidate(
        party_id=party.id,
        party_number=party.party_number,
        display_name=party.display_name,
        legal_name=party.legal_name,
        country_code=party.country_code,
        default_currency=party.default_currency,
        customer_type=CustomerType(party.customer_type) if party.customer_type else None,
        roles=[PartyRole(r) for r in party.roles],
        match=match,  # type: ignore[arg-type]
    )


@query(READ)
def resolve_party(
    uow: UnitOfWork,
    text: str,
    *,
    role: PartyRole | None = None,
    country_code: str | None = None,
    limit: int = 10,
) -> PartyResolution:
    """Resolve a spoken or typed party reference within the actor's scope.

    A party number is an exact match. Otherwise every token must appear in the display or legal name; one match
    (or exactly one exact-name match among several) is ``unique``, several are ``ambiguous`` (never guessed).
    """
    q = " ".join(text.split())
    repo = uow.repo(Party)
    base: Select[Any] = repo.select("read").where(Party.status != PartyStatus.BLOCKED.value)
    if role:
        base = base.where(Party.roles.contains([role.value]))
    if country_code:
        base = base.where(Party.country_code == country_code.strip().upper())
    if _PARTY_NUMBER.match(q.upper()):
        party = uow.session.scalars(base.where(Party.party_number == q.upper())).first()
        return PartyResolution(
            status="unique" if party else "not_found",
            query=q,
            candidates=[_candidate(party, "party_number")] if party else [],
            total_matches=1 if party else 0,
        )
    parts = tokens(q)
    if not parts:
        return PartyResolution(status="not_found", query=q, candidates=[], total_matches=0)
    cond = and_(
        *[
            or_(
                Party.display_name.ilike(contains_pattern(t), escape=LIKE_ESCAPE),
                Party.legal_name.ilike(contains_pattern(t), escape=LIKE_ESCAPE),
            )
            for t in parts
        ]
    )
    matches = base.where(cond)
    total = uow.session.scalar(select(func.count()).select_from(matches.order_by(None).subquery())) or 0
    rows = list(uow.session.scalars(matches.order_by(Party.name_key, Party.party_number).limit(max(1, min(limit, 25)))))
    key = name_key(q)
    exact = [p for p in rows if p.name_key == key or name_key(p.legal_name) == key]
    if total == 0:
        return PartyResolution(status="not_found", query=q, candidates=[], total_matches=0)
    if total == 1:
        match = "exact_name" if rows[0] in exact else "name_tokens"
        return PartyResolution(status="unique", query=q, candidates=[_candidate(rows[0], match)], total_matches=1)
    if len(exact) == 1:
        return PartyResolution(status="unique", query=q, candidates=[_candidate(exact[0], "exact_name")], total_matches=int(total))
    return PartyResolution(
        status="ambiguous",
        query=q,
        candidates=[_candidate(p, "exact_name" if p in exact else "name_tokens") for p in rows],
        total_matches=int(total),
    )


# =====================================================================================================
# references for other modules (pricing, sales) and the source reader
# =====================================================================================================
@dataclass(frozen=True)
class PartyRef:
    id: uuid.UUID
    party_number: str
    display_name: str
    country_code: str
    default_currency: str
    customer_type: str | None
    owner_user_id: uuid.UUID
    branch_id: uuid.UUID | None


def get_party_ref(uow: UnitOfWork, party_id: uuid.UUID) -> PartyRef:
    """A party the actor may read; 404 when absent or outside the actor's scope (no existence leak)."""
    party = uow.repo(Party).get(party_id)
    return PartyRef(
        id=party.id,
        party_number=party.party_number,
        display_name=party.display_name,
        country_code=party.country_code,
        default_currency=party.default_currency,
        customer_type=party.customer_type,
        owner_user_id=party.owner_user_id,
        branch_id=party.branch_id,
    )


def party_labels(uow: UnitOfWork, party_ids: Sequence[uuid.UUID | None]) -> dict[uuid.UUID, tuple[str, str]]:
    """(party_number, display_name) of the given parties the actor may read; invisible ids are simply absent."""
    wanted = {i for i in party_ids if i is not None}
    if not wanted:
        return {}
    rows = uow.session.execute(
        select(Party.id, Party.party_number, Party.display_name).where(Party.id.in_(wanted), uow.repo(Party).clause("read"))
    ).all()
    return {r[0]: (r[1], r[2]) for r in rows}


def visible_party_ids(uow: UnitOfWork) -> Select[Any]:
    """Ids of the parties the actor may read (subquery for other modules' scoped filters)."""
    return uow.repo(Party).visible_ids("read")


def find_party_id_by_name(uow: UnitOfWork, legal_name: str) -> uuid.UUID | None:
    """Seed/idempotency helper: a visible party whose legal name matches exactly (case-insensitive)."""
    return uow.session.scalar(
        select(Party.id).where(uow.repo(Party).clause("read"), func.lower(Party.legal_name) == legal_name.strip().lower())
    )


def read_party_facts(uow: UnitOfWork, party_id: uuid.UUID) -> SourceFacts | None:
    try:
        party = uow.repo(Party).get(party_id)
    except NotFound:
        return None
    return SourceFacts(
        source_type="parties.party",
        source_id=party.id,
        version=party.version,
        label=f"{party.party_number} · {party.display_name}",
        status=party.status,
        owner_user_id=party.owner_user_id,
        branch_id=party.branch_id,
        required_permission=READ,
        canonical_path=party_path(party.id),
        is_closed=party.archived_at is not None or party.status in (PartyStatus.INACTIVE.value, PartyStatus.BLOCKED.value),
        updated_at=party.updated_at,
        facts={
            "party_number": party.party_number,
            "name": party.display_name,  # the name tasks/briefings titles use (work lane reader contract)
            "display_name": party.display_name,
            "legal_name": party.legal_name,
            "country_code": party.country_code,
            "default_currency": party.default_currency,
            "customer_type": party.customer_type,
            "roles": ",".join(party.roles),
            "lead_stage": party.lead_stage,
            "next_follow_up_on": party.next_follow_up_on.isoformat() if party.next_follow_up_on else None,
        },
    )
