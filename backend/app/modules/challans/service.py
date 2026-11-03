"""Challan commands and reads (Slice 2: documents only, ``inventory_effect = none``).

Every command is one unit of work: the challan row is locked, the header or lines change, the movement policy is
re-checked, ``line_count`` and the search text are maintained and the version bumps once. Numbers (``DC-YYYY-NNNN``,
yearly by the challan date in the company zone) are allocated at creation through the atomic allocator and never
reused; drafts are soft-deleted. Issued challans are immutable except for their internal note (``platform/collab``),
which is never printed.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.orm.attributes import flag_modified

from app.core.db.base import new_id
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.core.http.pagination import MAX_LIMIT, Page
from app.core.text import LIKE_ESCAPE, contains_pattern, normalize_search_text, tokens
from app.modules.catalogue import service as catalogue
from app.modules.catalogue.models import Product
from app.modules.challans import movement_policy as policy
from app.modules.challans.common import (
    Errors,
    branch_links,
    business_date,
    challan_path,
    defaults,
    idempotent,
    month_start,
    user_refs,
    week_start,
)
from app.modules.challans.events import CHALLAN_SEQUENCE
from app.modules.challans.models import (
    LINE_NO_CONSTRAINT,
    Challan,
    ChallanLine,
    ChallanReturnLink,
    ChallanRevision,
    ChallanStatusHistory,
)
from app.modules.challans.schemas import (
    DESTINATION_LABELS,
    STATUS_LABELS,
    TYPE_LABELS,
    Capability,
    ChallanCreate,
    ChallanDetail,
    ChallanDuplicate,
    ChallanFilters,
    ChallanLineAdd,
    ChallanLineCreate,
    ChallanLineRead,
    ChallanLineUpdate,
    ChallanLink,
    ChallanOrigin,
    ChallanRevisionRead,
    ChallanRevisionSummary,
    ChallanStatus,
    ChallanSummary,
    ChallanSummaryRow,
    ChallanType,
    ChallanUpdate,
    CountBucket,
    DestinationType,
    HistoryRead,
    InventoryEffect,
    LineType,
    PartyLink,
    Period,
    ReturnLinkKind,
    ReturnLinkRead,
    ReturnType,
    TransitionRead,
    UserRef,
)
from app.modules.challans.state import transitions_from
from app.modules.parties import service as parties
from app.modules.parties.models import Party
from app.platform.org.models import Branch
from app.platform.org.reference import validate_quantity
from app.platform.service import query
from app.platform.uow import UnitOfWork

READ = "challans.challan.read"
CREATE = "challans.challan.create"
DEFAULT_UNIT = "pcs"
RESOURCE = "challans.challan"
NOT_EDITABLE = "challan_not_editable"

# ---- a party's label and roles (visible parties only; an invisible id is a 404, never an existence leak) --------


def _party(uow: UnitOfWork, party_id: uuid.UUID) -> tuple[str, str, list[str]]:
    ref = parties.get_party_ref(uow, party_id)
    roles = uow.session.scalar(select(Party.roles).where(Party.id == party_id)) or []
    return ref.party_number, ref.display_name, list(roles)


def _party_links(
    uow: UnitOfWork, ids: Sequence[uuid.UUID | None], fallback: dict[uuid.UUID, str]
) -> dict[uuid.UUID, PartyLink]:
    labels = parties.party_labels(uow, list(ids))
    out: dict[uuid.UUID, PartyLink] = {}
    for pid in {i for i in ids if i is not None}:
        number, name = labels.get(pid, (None, fallback.get(pid)))
        out[pid] = PartyLink(id=pid, party_number=number, display_name=name)
    return out


def _branch(uow: UnitOfWork, branch_id: uuid.UUID) -> Branch | None:
    return uow.session.scalars(
        select(Branch).where(Branch.id == branch_id, Branch.company_id == uow.actor.company_id)
    ).first()


# =====================================================================================================
# header validation (the movement policy on every save; destination requirements)
# =====================================================================================================
def _validate_header(uow: UnitOfWork, c: Challan, errors: Errors, *, original: Challan | None) -> None:
    ctype, rtype, dtype = (
        ChallanType(c.challan_type),
        ReturnType(c.return_type),
        DestinationType(c.destination_type),
    )
    for problem in policy.check_combination(ctype, rtype, dtype):
        errors.add([problem.field], problem.code, problem.message)
    if c.party_id is not None:
        number, name, roles = _party(uow, c.party_id)
        if dtype in policy.PARTY_ROLES and not policy.party_role_ok(dtype, roles):
            errors.add(
                ["party_id"], "party_role_mismatch", f"The party is not a {DESTINATION_LABELS[dtype].lower()}"
            )
        if not c.destination_party:
            c.destination_party = name
    if c.consignee_party_id is not None:
        parties.get_party_ref(uow, c.consignee_party_id)
    if c.office_branch_id is not None:
        branch = _branch(uow, c.office_branch_id)
        if branch is None:
            errors.add(
                ["office_branch_id"], "unknown_branch", "The office location is not a branch of the company"
            )
        elif not c.destination_party:
            c.destination_party = branch.name
    if c.source_branch_id is not None and _branch(uow, c.source_branch_id) is None:
        errors.add(["source_branch_id"], "unknown_branch", "The source is not a branch of the company")
    if dtype in policy.LOCATION_DESTINATIONS and c.party_id is not None:
        errors.add(
            ["party_id"],
            "party_not_for_location",
            f"A {DESTINATION_LABELS[dtype].lower()} destination has no party",
        )
    if not c.destination_party:
        errors.add(["destination_party"], "required", "The destination party is required")
    if rtype == ReturnType.NON_RETURNABLE:
        c.expected_return_date = None
    elif c.expected_return_date is not None and c.expected_return_date < c.challan_date:
        errors.add(
            ["expected_return_date"],
            "before_challan_date",
            "The expected return date cannot be before the challan date",
        )
    if c.original_challan_id is not None:
        if ctype != ChallanType.RETURN:
            errors.add(
                ["original_challan_id"],
                "original_only_on_return",
                "Only a Return challan refers to an original challan",
            )
        elif original is not None:
            if original.status not in (ChallanStatus.ISSUED.value, ChallanStatus.CLOSED.value):
                errors.add(
                    ["original_challan_id"],
                    "original_not_issued",
                    "Goods can only be returned against an issued challan",
                )
            if original.id == c.id:
                errors.add(
                    ["original_challan_id"], "original_not_self", "A challan cannot return against itself"
                )


def _apply_header_defaults(uow: UnitOfWork, c: Challan, data: Any, *, original: Challan | None) -> None:
    cfg = defaults(uow)
    if not c.source_location:
        c.source_location = cfg.source_location
    if data.return_type is None and original is not None and c.challan_type == ChallanType.RETURN.value:
        c.return_type = original.return_type
    if c.return_type is None:
        c.return_type = policy.default_return_type(ChallanType(c.challan_type)).value
    if original is not None and c.party_id is None and original.party_id is not None:
        c.party_id = original.party_id
        if not c.destination_party:
            c.destination_party = original.destination_party
    if (
        c.return_type == ReturnType.RETURNABLE.value
        and c.expected_return_date is None
        and cfg.expected_return_days > 0
    ):
        c.expected_return_date = c.challan_date + timedelta(days=cfg.expected_return_days)


def _search_text(c: Challan) -> str:
    return normalize_search_text(
        " ".join(
            p
            for p in (c.challan_number, c.destination_party, c.shipping_name or "", c.reference_no or "")
            if p
        )
    )


def _original(uow: UnitOfWork, original_id: uuid.UUID | None) -> Challan | None:
    if original_id is None:
        return None
    return uow.repo(Challan).get(original_id, include_archived=False)


# =====================================================================================================
# lines
# =====================================================================================================
def lines_of(uow: UnitOfWork, challan: Challan) -> list[ChallanLine]:
    return list(
        uow.session.scalars(
            select(ChallanLine)
            .where(ChallanLine.challan_id == challan.id)
            .order_by(ChallanLine.line_no, ChallanLine.id)
        )
    )


def _check_quantity(
    uow: UnitOfWork, quantity: Decimal, unit: str | None, errors: Errors, prefix: Sequence[str | int]
) -> tuple[Decimal, str]:
    """``(quantity, uom_code)`` under the entry rule of the unit master (whole numbers for integer units, <= 4 dp)."""
    try:
        return validate_quantity(uow, Decimal(quantity), unit or DEFAULT_UNIT)
    except ValidationFailed as exc:
        errors.extend(prefix, exc)
        return Decimal(quantity), unit or DEFAULT_UNIT


def _product_fill(
    uow: UnitOfWork, product_id: uuid.UUID, errors: Errors, prefix: Sequence[str | int]
) -> dict[str, Any]:
    ref = catalogue.get_product_ref(uow, product_id=product_id)
    if ref.archived:
        errors.add([*prefix, "product_id"], "product_archived", "The product is archived")
    hsn = uow.session.scalar(select(Product.hsn_sac).where(Product.id == ref.id))
    return {
        "item_code": ref.product_key,
        "item_name": ref.product_name,
        "hsn_sac": hsn,
        "unit": ref.unit_of_sale or DEFAULT_UNIT,
    }


def _original_line(
    uow: UnitOfWork, challan: Challan, line_id: uuid.UUID, errors: Errors, prefix: Sequence[str | int]
) -> ChallanLine | None:
    if challan.original_challan_id is None:
        errors.add(
            [*prefix, "original_line_id"],
            "no_original_challan",
            "Set the original challan before linking lines",
        )
        return None
    row = uow.session.scalars(
        select(ChallanLine).where(
            ChallanLine.id == line_id, ChallanLine.challan_id == challan.original_challan_id
        )
    ).first()
    if row is None:
        errors.add(
            [*prefix, "original_line_id"],
            "not_an_original_line",
            "The line does not belong to the original challan",
        )
    return row


def _build_line(
    uow: UnitOfWork, challan: Challan, data: ChallanLineCreate, errors: Errors, prefix: Sequence[str | int]
) -> ChallanLine:
    fill: dict[str, Any] = {}
    if data.line_type == LineType.CATALOG:
        if data.product_id is None:
            errors.add([*prefix, "product_id"], "required", "A catalog line needs a product")
        else:
            fill = _product_fill(uow, data.product_id, errors, prefix)
    elif data.line_type == LineType.CUSTOM and data.custom_product_id is None:
        errors.add([*prefix, "custom_product_id"], "required", "A custom line needs a custom product")
    item_name = data.item_name or fill.get("item_name")
    if not item_name:
        errors.add([*prefix, "item_name"], "required", "The item name is required")
    quantity, unit_code = _check_quantity(uow, data.quantity, data.unit or fill.get("unit"), errors, prefix)
    original = (
        _original_line(uow, challan, data.original_line_id, errors, prefix)
        if data.original_line_id is not None
        else None
    )
    if original is not None and quantity > original.quantity - original.returned_qty:
        errors.add(
            [*prefix, "quantity"],
            "excess_return",
            "The returned quantity exceeds what is still out on the original line",
        )
    return ChallanLine(
        id=new_id(),
        company_id=uow.actor.company_id,
        challan_id=challan.id,
        line_type=data.line_type.value,
        product_id=data.product_id if data.line_type == LineType.CATALOG else None,
        custom_product_id=data.custom_product_id if data.line_type == LineType.CUSTOM else None,
        item_code=data.item_code if data.item_code is not None else fill.get("item_code"),
        item_name=item_name or "",
        hsn_sac=data.hsn_sac if data.hsn_sac is not None else fill.get("hsn_sac"),
        quantity=quantity,
        uom_code=unit_code,
        remarks=data.remarks,
        original_line_id=original.id if original is not None else None,
        returned_qty=Decimal(0),
    )


def _touch(uow: UnitOfWork, challan: Challan, lines: Sequence[ChallanLine] | None = None) -> None:
    if lines is not None:
        challan.line_count = len(lines)
    challan.search_text = _search_text(challan)
    challan.updated_at = uow.now()
    # a line-only change must still bump the challan's version (optimistic concurrency covers the whole document)
    flag_modified(challan, "updated_at")


def _locked(uow: UnitOfWork, challan_id: uuid.UUID, action: str = "update") -> Challan:
    challan = uow.repo(Challan).get(challan_id, action, for_update=True, include_archived=False)
    if action == "update" and challan.status != ChallanStatus.DRAFT.value:
        raise Conflict(
            f"An {challan.status} challan cannot be edited; only its internal note can change",
            code=NOT_EDITABLE,
        )
    return challan


# =====================================================================================================
# commands
# =====================================================================================================
def create_challan(
    uow: UnitOfWork, data: ChallanCreate, *, origin: str | None = None, origin_ref: str | None = None
) -> Challan:
    actor = uow.actor
    actor.require(CREATE)
    if actor.user_id is None:
        raise Forbidden("A challan needs a user as its owner", code="permission_denied", permission=CREATE)
    errors = Errors()
    original = _original(uow, data.original_challan_id)
    challan = Challan(
        id=new_id(),
        company_id=actor.company_id,
        challan_number="DC-0000-0000",  # replaced by the allocator below (NOT NULL column)
        challan_date=data.challan_date or business_date(uow),
        challan_type=data.challan_type.value,
        return_type=data.return_type.value if data.return_type else None,
        source_location=data.source_location or "",
        source_branch_id=data.source_branch_id,
        source_warehouse_id=data.source_warehouse_id,
        destination_type=data.destination_type.value,
        destination_party=data.destination_party or "",
        party_id=data.party_id,
        consignee_party_id=data.consignee_party_id,
        destination_warehouse_id=data.destination_warehouse_id,
        office_branch_id=data.office_branch_id,
        shipping_name=data.shipping_name,
        gstin=data.gstin,
        phone=data.phone,
        email=data.email,
        address=data.address,
        reference_no=data.reference_no,
        remarks=data.remarks,
        expected_return_date=data.expected_return_date,
        original_challan_id=original.id if original is not None else None,
        status=ChallanStatus.DRAFT.value,
        inventory_effect=InventoryEffect.NONE.value,
        owner_user_id=actor.user_id,
        branch_id=data.source_branch_id or (sorted(actor.branch_ids)[0] if actor.branch_ids else None),
        origin=origin
        or (ChallanOrigin.AGENT.value if actor.actor_type == "agent" else ChallanOrigin.USER.value),
        origin_ref=origin_ref,
        line_count=0,
        revision_no=0,
        search_text="",
    )
    _apply_header_defaults(uow, challan, data, original=original)
    _validate_header(uow, challan, errors, original=original)
    lines = [_build_line(uow, challan, ln, errors, ["lines", i]) for i, ln in enumerate(data.lines)]
    errors.raise_if_any()
    challan.challan_number = uow.allocate_number(
        CHALLAN_SEQUENCE.key,
        document_date=challan.challan_date,
        resource_type=RESOURCE,
        resource_id=challan.id,
    )
    for position, line in enumerate(lines, start=1):
        line.line_no = position
    _touch(uow, challan, lines)
    uow.add(challan)
    uow.flush()
    uow.add_all(lines)
    uow.flush()
    uow.audit(
        "challans.challan.created",
        resource_type=RESOURCE,
        resource_id=challan.id,
        resource_label=f"{challan.challan_number} · {challan.destination_party}",
        details={"challan_type": challan.challan_type},
    )
    return challan


_ENUM_FIELDS = {"challan_type", "return_type", "destination_type"}


def update_challan(uow: UnitOfWork, challan_id: uuid.UUID, data: ChallanUpdate) -> Challan:
    challan = _locked(uow, challan_id)
    uow.expect_version(challan, data.expected_version)
    fields = data.model_dump(exclude_unset=True, exclude={"expected_version"})
    changed: set[str] = set()
    for name, value in fields.items():
        if name in _ENUM_FIELDS and value is None:
            continue
        if name == "challan_date" and value is None:
            continue
        if hasattr(value, "value"):
            value = value.value
        if getattr(challan, name) != value:
            setattr(challan, name, value)
            changed.add(name)
    if not changed:
        return challan
    if "challan_type" in changed and "return_type" not in fields:
        rule = policy.POLICY[ChallanType(challan.challan_type)]
        if ReturnType(challan.return_type) not in rule.return_types:
            challan.return_type = rule.default_return.value
    errors = Errors()
    original = _original(uow, challan.original_challan_id)
    _apply_header_defaults(uow, challan, data, original=original)
    _validate_header(uow, challan, errors, original=original)
    if "challan_date" in changed and challan.challan_date.year != int(challan.challan_number.split("-")[1]):
        errors.add(
            ["challan_date"], "number_year_mismatch", "The challan date must stay in the year of its number"
        )
    if errors.items:
        uow.session.expire(challan)  # discard the rejected values: the row stays as it was
        errors.raise_if_any()
    _touch(uow, challan)
    uow.flush()
    uow.audit(
        "challans.challan.updated",
        resource_type=RESOURCE,
        resource_id=challan.id,
        resource_label=challan.challan_number,
        details={"changed_fields": sorted(changed)},
    )
    return challan


def add_line(uow: UnitOfWork, challan_id: uuid.UUID, data: ChallanLineAdd) -> tuple[Challan, ChallanLine]:
    challan = _locked(uow, challan_id)
    uow.expect_version(challan, data.expected_version)
    errors = Errors()
    lines = lines_of(uow, challan)
    if len(lines) >= 200:
        raise Conflict("A challan holds at most 200 lines", code="too_many_lines")
    line = _build_line(
        uow, challan, ChallanLineCreate(**data.model_dump(exclude={"expected_version"})), errors, []
    )
    errors.raise_if_any()
    line.line_no = (max((ln.line_no for ln in lines), default=0)) + 1
    uow.add(line)
    lines.append(line)
    _touch(uow, challan, lines)
    uow.flush()
    uow.audit(
        "challans.challan.line_added",
        resource_type=RESOURCE,
        resource_id=challan.id,
        resource_label=challan.challan_number,
        details={"line_no": line.line_no, "line_type": line.line_type},
    )
    return challan, line


def _line_of(uow: UnitOfWork, challan: Challan, line_id: uuid.UUID) -> ChallanLine:
    line = uow.session.scalars(
        select(ChallanLine).where(ChallanLine.id == line_id, ChallanLine.challan_id == challan.id)
    ).first()
    if line is None:
        raise NotFound(code="not_found", resource_type="challans.challan_line")
    return line


def update_line(
    uow: UnitOfWork, challan_id: uuid.UUID, line_id: uuid.UUID, data: ChallanLineUpdate
) -> tuple[Challan, ChallanLine]:
    challan = _locked(uow, challan_id)
    uow.expect_version(challan, data.expected_version)
    line = _line_of(uow, challan, line_id)
    errors = Errors()
    sent = data.model_fields_set - {"expected_version"}
    changed: set[str] = set()
    if "quantity" in sent or "unit" in sent:
        quantity = data.quantity if "quantity" in sent and data.quantity is not None else line.quantity
        unit = data.unit if "unit" in sent and data.unit else line.uom_code
        quantity, unit_code = _check_quantity(uow, Decimal(quantity), unit, errors, [])
        if "original_line_id" not in sent and line.original_line_id is not None and not errors.items:
            original = _original_line(uow, challan, line.original_line_id, errors, [])
            if original is not None and quantity > original.quantity - original.returned_qty:
                errors.add(
                    ["quantity"],
                    "excess_return",
                    "The returned quantity exceeds what is still out on the original line",
                )
        errors.raise_if_any()
        if quantity != line.quantity:
            line.quantity, changed = quantity, changed | {"quantity"}
        if unit_code != line.uom_code:
            line.uom_code, changed = unit_code, changed | {"unit"}
    for name in ("item_code", "item_name", "hsn_sac", "remarks"):
        if name in sent and getattr(data, name) != getattr(line, name):
            if name == "item_name" and not getattr(data, name):
                errors.add(["item_name"], "required", "The item name is required")
                continue
            setattr(line, name, getattr(data, name))
            changed.add(name)
    if "original_line_id" in sent and data.original_line_id != line.original_line_id:
        if data.original_line_id is None:
            line.original_line_id = None
        else:
            original = _original_line(uow, challan, data.original_line_id, errors, [])
            if original is not None and line.quantity > original.quantity - original.returned_qty:
                errors.add(
                    ["quantity"],
                    "excess_return",
                    "The returned quantity exceeds what is still out on the original line",
                )
            line.original_line_id = original.id if original is not None else None
        changed.add("original_line_id")
    if errors.items:
        uow.session.expire(line)  # discard the rejected values: the row stays as it was
        errors.raise_if_any()
    if not changed:
        return challan, line
    _touch(uow, challan)
    uow.flush()
    uow.audit(
        "challans.challan.line_changed",
        resource_type=RESOURCE,
        resource_id=challan.id,
        resource_label=challan.challan_number,
        details={"line_no": line.line_no, "changed_fields": sorted(changed)},
    )
    return challan, line


def remove_line(
    uow: UnitOfWork, challan_id: uuid.UUID, line_id: uuid.UUID, *, expected_version: int | None
) -> Challan:
    """Delete a line and renumber the remaining lines atomically (deferred unique constraint)."""
    challan = _locked(uow, challan_id)
    uow.expect_version(challan, expected_version)
    line = _line_of(uow, challan, line_id)
    removed_no = line.line_no
    uow.session.delete(line)
    uow.flush()
    uow.defer_constraints(LINE_NO_CONSTRAINT)
    remaining = lines_of(uow, challan)
    for position, ln in enumerate(remaining, start=1):
        if ln.line_no != position:
            ln.line_no = position
    _touch(uow, challan, remaining)
    uow.flush()
    uow.audit(
        "challans.challan.line_removed",
        resource_type=RESOURCE,
        resource_id=challan.id,
        resource_label=challan.challan_number,
        details={"line_no": removed_no},
    )
    return challan


def duplicate_challan(
    uow: UnitOfWork, challan_id: uuid.UUID, data: ChallanDuplicate | None = None
) -> Challan:
    """A new draft (new number, today's date, status draft) copying the header and the lines (LM-89)."""
    uow.actor.require(CREATE)
    source = uow.repo(Challan).get(challan_id, include_archived=False)
    lines = lines_of(uow, source)
    body = ChallanCreate(
        challan_date=(data.challan_date if data else None) or business_date(uow),
        challan_type=ChallanType(source.challan_type),
        return_type=ReturnType(source.return_type),
        source_location=source.source_location,
        source_branch_id=source.source_branch_id,
        source_warehouse_id=source.source_warehouse_id,
        destination_type=DestinationType(source.destination_type),
        destination_party=source.destination_party,
        party_id=source.party_id,
        consignee_party_id=source.consignee_party_id,
        destination_warehouse_id=source.destination_warehouse_id,
        office_branch_id=source.office_branch_id,
        shipping_name=source.shipping_name,
        gstin=source.gstin,
        phone=source.phone,
        email=source.email,
        address=source.address,
        reference_no=source.reference_no,
        remarks=source.remarks,
        original_challan_id=source.original_challan_id,
        lines=[
            ChallanLineCreate(
                line_type=LineType(ln.line_type),
                product_id=ln.product_id,
                custom_product_id=ln.custom_product_id,
                item_code=ln.item_code,
                item_name=ln.item_name,
                hsn_sac=ln.hsn_sac,
                quantity=ln.quantity,
                unit=ln.uom_code,
                remarks=ln.remarks,
                original_line_id=ln.original_line_id,
            )
            for ln in lines
        ],
    )
    copy = create_challan(uow, body, origin=ChallanOrigin.DUPLICATE.value)
    copy.duplicated_from_id = source.id
    uow.flush()
    uow.audit(
        "challans.challan.duplicated",
        resource_type=RESOURCE,
        resource_id=copy.id,
        resource_label=copy.challan_number,
        details={"duplicated_from": str(source.id)},
    )
    return copy


def delete_challan(uow: UnitOfWork, challan_id: uuid.UUID, *, expected_version: int | None) -> Challan:
    """Soft-delete a draft (``challans.challan.delete``: admin template only); the number is never reused (LM-93)."""
    challan = uow.repo(Challan).get(challan_id, "delete", for_update=True, include_archived=False)
    uow.expect_version(challan, expected_version)
    challan.deleted_at = uow.now()
    challan.deleted_by = uow.actor.user_id
    challan.updated_at = uow.now()
    uow.flush()
    uow.audit(
        "challans.challan.deleted",
        resource_type=RESOURCE,
        resource_id=challan.id,
        resource_label=challan.challan_number,
    )
    return challan


# =====================================================================================================
# reads
# =====================================================================================================
def plain(value: Decimal | int | str) -> Decimal:
    """A quantity without the storage scale (``12.000000`` -> ``12``, ``2.500000`` -> ``2.5``) for DecimalStr output."""
    d = Decimal(value)
    return d.quantize(Decimal(1)) if d == d.to_integral_value() else d.normalize()


def quantity_by_unit(lines: Sequence[ChallanLine]) -> dict[str, Decimal]:
    out: dict[str, Decimal] = {}
    for ln in lines:
        out[ln.uom_code] = out.get(ln.uom_code, Decimal(0)) + Decimal(ln.quantity)
    return {unit: plain(qty) for unit, qty in sorted(out.items())}


def outstanding_by_unit(challan: Challan, lines: Sequence[ChallanLine]) -> dict[str, Decimal]:
    """Returnable quantity still out, per unit (issued returnable challans only; a document figure, not stock)."""
    if challan.status != ChallanStatus.ISSUED.value or challan.return_type != ReturnType.RETURNABLE.value:
        return {}
    out: dict[str, Decimal] = {}
    for ln in lines:
        left = Decimal(ln.quantity) - Decimal(ln.returned_qty)
        if left > 0:
            out[ln.uom_code] = out.get(ln.uom_code, Decimal(0)) + left
    return {unit: plain(qty) for unit, qty in sorted(out.items())}


def _lines_by_challan(uow: UnitOfWork, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, list[ChallanLine]]:
    out: dict[uuid.UUID, list[ChallanLine]] = {i: [] for i in ids}
    if not ids:
        return out
    for ln in uow.session.scalars(
        select(ChallanLine).where(ChallanLine.challan_id.in_(list(ids))).order_by(ChallanLine.line_no)
    ):
        out.setdefault(ln.challan_id, []).append(ln)
    return out


def _rows(
    uow: UnitOfWork, rows: Sequence[Challan], lines_map: dict[uuid.UUID, list[ChallanLine]] | None = None
) -> list[ChallanSummaryRow]:
    if not rows:
        return []
    lines_map = lines_map if lines_map is not None else _lines_by_challan(uow, [c.id for c in rows])
    users = user_refs(uow, [c.owner_user_id for c in rows] + [c.created_by for c in rows])
    links = _party_links(
        uow, [c.party_id for c in rows], {c.party_id: c.destination_party for c in rows if c.party_id}
    )
    out: list[ChallanSummaryRow] = []
    for c in rows:
        lines = lines_map.get(c.id, [])
        outstanding = outstanding_by_unit(c, lines)
        out.append(
            ChallanSummaryRow(
                id=c.id,
                challan_number=c.challan_number,
                revision_no=c.revision_no,
                challan_date=c.challan_date,
                challan_type=ChallanType(c.challan_type),
                return_type=ReturnType(c.return_type),
                destination_type=DestinationType(c.destination_type),
                destination_party=c.destination_party,
                party=links.get(c.party_id) if c.party_id else None,
                reference_no=c.reference_no,
                status=ChallanStatus(c.status),
                line_count=c.line_count,
                quantity_by_unit=quantity_by_unit(lines),
                outstanding_quantity=plain(sum(outstanding.values(), Decimal(0))),
                expected_return_date=c.expected_return_date,
                owner=users.get(c.owner_user_id) or UserRef(id=c.owner_user_id, display_name=None),
                created_by=users.get(c.created_by) if c.created_by else None,
                branch_id=c.branch_id,
                created_at=c.created_at,
                updated_at=c.updated_at,
                deleted_at=c.deleted_at,
                version=c.version,
                path=challan_path(c.id),
            )
        )
    return out


def _challan_links(uow: UnitOfWork, ids: Sequence[uuid.UUID | None]) -> dict[uuid.UUID, ChallanLink]:
    wanted = {i for i in ids if i is not None}
    if not wanted:
        return {}
    rows = uow.session.execute(
        select(Challan.id, Challan.challan_number, Challan.status).where(
            Challan.id.in_(wanted), uow.repo(Challan).clause("read")
        )
    ).all()
    return {
        r[0]: ChallanLink(id=r[0], challan_number=r[1], status=ChallanStatus(r[2]), path=challan_path(r[0]))
        for r in rows
    }


def line_reads(lines: Sequence[ChallanLine]) -> list[ChallanLineRead]:
    return [
        ChallanLineRead(
            id=ln.id,
            line_no=ln.line_no,
            line_type=LineType(ln.line_type),
            product_id=ln.product_id,
            custom_product_id=ln.custom_product_id,
            item_code=ln.item_code,
            item_name=ln.item_name,
            hsn_sac=ln.hsn_sac,
            quantity=plain(ln.quantity),
            unit=ln.uom_code,
            remarks=ln.remarks,
            original_line_id=ln.original_line_id,
            returned_quantity=plain(ln.returned_qty),
            outstanding_quantity=plain(max(Decimal(ln.quantity) - Decimal(ln.returned_qty), Decimal(0))),
        )
        for ln in lines
    ]


def _return_links(uow: UnitOfWork, challan: Challan) -> list[ReturnLinkRead]:
    rows = list(
        uow.session.scalars(
            select(ChallanReturnLink)
            .where(
                or_(
                    ChallanReturnLink.return_challan_id == challan.id,
                    ChallanReturnLink.original_challan_id == challan.id,
                )
            )
            .order_by(ChallanReturnLink.created_at, ChallanReturnLink.id)
        )
    )
    links = _challan_links(uow, [r.return_challan_id for r in rows] + [r.original_challan_id for r in rows])
    out: list[ReturnLinkRead] = []
    for r in rows:
        ret, orig = links.get(r.return_challan_id), links.get(r.original_challan_id)
        if ret is None or orig is None:  # the other side is outside the actor's scope: not listed
            continue
        out.append(
            ReturnLinkRead(
                id=r.id,
                return_challan=ret,
                original_challan=orig,
                return_line_id=r.return_line_id,
                original_line_id=r.original_line_id,
                quantity=r.quantity,
                kind=ReturnLinkKind(r.kind),
                created_at=r.created_at,
                reversed_at=r.reversed_at,
            )
        )
    return out


def history_of(uow: UnitOfWork, challan: Challan) -> list[HistoryRead]:
    rows = list(
        uow.session.scalars(
            select(ChallanStatusHistory)
            .where(ChallanStatusHistory.challan_id == challan.id)
            .order_by(ChallanStatusHistory.occurred_at, ChallanStatusHistory.id)
        )
    )
    users = user_refs(uow, [r.actor_user_id for r in rows])
    return [
        HistoryRead(
            action=r.action,
            from_status=r.from_status,
            to_status=r.to_status,
            actor=users.get(r.actor_user_id) if r.actor_user_id else None,
            reason_code=r.reason_code,
            reason=r.reason,
            occurred_at=r.occurred_at,
        )
        for r in rows
    ]


def issue_blockers(uow: UnitOfWork, challan: Challan, lines: Sequence[ChallanLine]) -> str | None:
    """Why ``issue`` is not available right now (None when it is): the guard the transition re-checks under lock."""
    if not lines:
        return "no_lines"
    problems = policy.check_combination(
        ChallanType(challan.challan_type),
        ReturnType(challan.return_type),
        DestinationType(challan.destination_type),
    )
    if problems:
        return problems[0].code
    if challan.challan_type == ChallanType.RETURN.value:
        if challan.original_challan_id is None:
            return "original_required"
        if any(ln.original_line_id is None for ln in lines):
            return "lines_need_original_lines"
    return None


def allowed_transitions(
    uow: UnitOfWork, challan: Challan, lines: Sequence[ChallanLine]
) -> list[TransitionRead]:
    repo = uow.repo(Challan)
    if challan.deleted_at is not None:
        return []
    out: list[TransitionRead] = []
    for t in transitions_from(challan.status):
        if not repo.can(challan, t.permission_action):
            continue
        if t.guard == "issue_ready" and issue_blockers(uow, challan, lines) is not None:
            continue
        if t.guard == "no_return_links" and has_return_links(uow, challan):
            continue
        out.append(TransitionRead(action=t.action, to_status=t.to_status, requires_reason=t.requires_reason))
    return out


def has_return_links(uow: UnitOfWork, challan: Challan) -> bool:
    return (
        uow.session.scalar(
            select(func.count())
            .select_from(ChallanReturnLink)
            .where(
                ChallanReturnLink.original_challan_id == challan.id, ChallanReturnLink.reversed_at.is_(None)
            )
        )
        > 0
    )


def detail(uow: UnitOfWork, challan: Challan, lines: Sequence[ChallanLine] | None = None) -> ChallanDetail:
    lines = list(lines) if lines is not None else lines_of(uow, challan)
    base = _rows(uow, [challan], {challan.id: lines})[0]
    repo = uow.repo(Challan)
    caps = repo.capabilities(challan, ["update", "delete", "export", "issue", "transition", "reverse"])
    if caps["update"]["allowed"] and challan.status != ChallanStatus.DRAFT.value:
        caps["update"] = {"allowed": False, "reason_code": NOT_EDITABLE}
    if caps["issue"]["allowed"] and (blocker := issue_blockers(uow, challan, lines)) is not None:
        caps["issue"] = {"allowed": False, "reason_code": blocker}
    if caps["reverse"]["allowed"] and has_return_links(uow, challan):
        caps["reverse"] = {"allowed": False, "reason_code": "has_return_links"}
    caps["add_line"] = dict(caps["update"])
    caps["duplicate"] = {
        "allowed": uow.actor.can(CREATE),
        "reason_code": None if uow.actor.can(CREATE) else "permission_denied",
    }
    caps["note"] = {
        "allowed": repo.can(challan, "update"),
        "reason_code": None if repo.can(challan, "update") else "permission_denied",
    }
    users = user_refs(uow, [challan.issued_by, challan.updated_by])
    branches = branch_links(uow, [challan.source_branch_id, challan.office_branch_id])
    consignee = _party_links(uow, [challan.consignee_party_id], {}) if challan.consignee_party_id else {}
    links = _challan_links(uow, [challan.original_challan_id, challan.duplicated_from_id])
    return ChallanDetail(
        **base.model_dump(),
        source_location=challan.source_location,
        source_branch=branches.get(challan.source_branch_id) if challan.source_branch_id else None,
        source_warehouse_id=challan.source_warehouse_id,
        consignee_party=consignee.get(challan.consignee_party_id) if challan.consignee_party_id else None,
        destination_warehouse_id=challan.destination_warehouse_id,
        office_branch=branches.get(challan.office_branch_id) if challan.office_branch_id else None,
        shipping_name=challan.shipping_name,
        gstin=challan.gstin,
        phone=challan.phone,
        email=challan.email,
        address=challan.address,
        remarks=challan.remarks,
        direction=policy.direction(ChallanType(challan.challan_type)),  # type: ignore[arg-type]
        inventory_effect=InventoryEffect(challan.inventory_effect),
        original_challan=links.get(challan.original_challan_id) if challan.original_challan_id else None,
        duplicated_from=links.get(challan.duplicated_from_id) if challan.duplicated_from_id else None,
        issued_at=challan.issued_at,
        issued_by=users.get(challan.issued_by) if challan.issued_by else None,
        closed_at=challan.closed_at,
        close_reason=challan.close_reason,
        cancelled_at=challan.cancelled_at,
        cancel_reason_code=challan.cancel_reason_code,
        cancel_reason=challan.cancel_reason,
        updated_by=users.get(challan.updated_by) if challan.updated_by else None,
        origin=ChallanOrigin(challan.origin),
        lines=line_reads(lines),
        return_links=_return_links(uow, challan),
        history=history_of(uow, challan),
        capabilities={k: Capability(**v) for k, v in caps.items()},
        allowed_transitions=allowed_transitions(uow, challan, lines),
    )


def _visible(uow: UnitOfWork, challan_id: uuid.UUID, *, include_deleted: bool = False) -> Challan:
    return uow.repo(Challan).get(challan_id, include_archived=include_deleted)


@query(READ)
def get_challan(uow: UnitOfWork, challan_id: uuid.UUID) -> ChallanDetail:
    return detail(uow, _visible(uow, challan_id, include_deleted=True))


@query(READ)
def get_challan_by_number(uow: UnitOfWork, challan_number: str) -> ChallanDetail:
    challan = uow.repo(Challan).get_by_key(challan_number.strip().upper())
    if challan.deleted_at is not None:
        raise NotFound(code="not_found", resource_type=RESOURCE)
    return detail(uow, challan)


def _period_bounds(uow: UnitOfWork, period: Period) -> tuple[date, date]:
    today = business_date(uow)
    if period == Period.THIS_WEEK:
        start = week_start(today)
        return start, start + timedelta(days=6)
    start = month_start(today)
    nxt = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    return start, nxt - timedelta(days=1)


def _conditions(uow: UnitOfWork, f: ChallanFilters) -> list[ColumnElement[bool]]:
    conds: list[ColumnElement[bool]] = []
    if f.q:
        for tok in tokens(f.q):
            conds.append(Challan.search_text.ilike(contains_pattern(tok), escape=LIKE_ESCAPE))
    if f.status:
        conds.append(Challan.status.in_([s.value for s in f.status]))
    if f.challan_type:
        conds.append(Challan.challan_type.in_([t.value for t in f.challan_type]))
    if f.return_type:
        conds.append(Challan.return_type == f.return_type.value)
    if f.destination_type:
        conds.append(Challan.destination_type.in_([d.value for d in f.destination_type]))
    if f.party_id:
        conds.append(Challan.party_id == f.party_id)
    if f.destination:
        conds.append(
            Challan.destination_party.ilike(
                contains_pattern(normalize_search_text(f.destination)), escape=LIKE_ESCAPE
            )
        )
    if f.period:
        start, end = _period_bounds(uow, f.period)
        conds += [Challan.challan_date >= start, Challan.challan_date <= end]
    if f.date_from:
        conds.append(Challan.challan_date >= f.date_from)
    if f.date_to:
        conds.append(Challan.challan_date <= f.date_to)
    if f.pending_returnable:
        conds += [
            Challan.status == ChallanStatus.ISSUED.value,
            Challan.return_type == ReturnType.RETURNABLE.value,
        ]
    if f.scope == "mine" and uow.actor.user_id is not None:
        conds.append(Challan.owner_user_id == uow.actor.user_id)
    return conds


@query(READ)
def list_challans(
    uow: UnitOfWork, filters: ChallanFilters, *, limit: int = 50, offset: int = 0
) -> Page[ChallanSummaryRow]:
    """Scoped list (``scope=all`` is still bounded by the actor's read scope); filters apply before pagination."""
    page = uow.repo(Challan).list(
        *_conditions(uow, filters),
        order_by=[Challan.challan_date.desc(), Challan.challan_number.desc()],
        limit=max(1, min(limit, MAX_LIMIT)),
        offset=max(0, offset),
        include_archived=filters.include_deleted,
    )
    return Page[ChallanSummaryRow](
        items=_rows(uow, page.items), total=page.total, limit=page.limit, offset=page.offset
    )


def _buckets(rows: Sequence[tuple[str, int]], labels: dict[Any, str], enum: Any) -> list[CountBucket]:
    counts = {e.value: 0 for e in enum}
    for key, n in rows:
        counts[key] = int(n)
    return [CountBucket(key=k, label=labels[enum(k)], count=v) for k, v in counts.items()]


@query(READ)
def summary(uow: UnitOfWork, filters: ChallanFilters) -> ChallanSummary:
    """The legacy summary cards over the same filters and the same read scope as the list (LM-88, UI-28)."""
    f = filters.model_copy(update={"period": None, "pending_returnable": False})
    repo = uow.repo(Challan)
    base = repo.select(include_archived=filters.include_deleted).where(*_conditions(uow, f))
    today = business_date(uow)
    ws, ms = week_start(today), month_start(today)

    def count(*extra: ColumnElement[bool]) -> int:
        return int(
            uow.session.scalar(select(func.count()).select_from(base.where(*extra).order_by(None).subquery()))
            or 0
        )

    def grouped(column: Any) -> list[tuple[str, int]]:
        stmt = base.with_only_columns(column, func.count(Challan.id)).group_by(column).order_by(None)
        return [(r[0], int(r[1])) for r in uow.session.execute(stmt).all()]

    pending_ids = list(
        uow.session.scalars(
            base.with_only_columns(Challan.id)
            .where(
                Challan.status == ChallanStatus.ISSUED.value,
                Challan.return_type == ReturnType.RETURNABLE.value,
            )
            .order_by(None)
        )
    )
    pending_qty: dict[str, Decimal] = {}
    pending_count = 0
    if pending_ids:
        pending = {c.id: c for c in uow.session.scalars(select(Challan).where(Challan.id.in_(pending_ids)))}
        for cid, lines in _lines_by_challan(uow, pending_ids).items():
            out = outstanding_by_unit(pending[cid], lines)
            if out:
                pending_count += 1
                for unit, qty in out.items():
                    pending_qty[unit] = pending_qty.get(unit, Decimal(0)) + qty
    return ChallanSummary(
        total=count(),
        this_week=count(Challan.challan_date >= ws, Challan.challan_date <= ws + timedelta(days=6)),
        this_month=count(
            Challan.challan_date >= ms,
            Challan.challan_date
            <= (ms.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1),
        ),
        pending_returnable=pending_count,
        pending_returnable_quantity=dict(sorted(pending_qty.items())),
        issued=count(Challan.status == ChallanStatus.ISSUED.value),
        by_type=_buckets(grouped(Challan.challan_type), TYPE_LABELS, ChallanType),
        by_destination=_buckets(grouped(Challan.destination_type), DESTINATION_LABELS, DestinationType),
        by_status=_buckets(grouped(Challan.status), STATUS_LABELS, ChallanStatus),
        week_start=ws,
        month_start=ms,
        today=today,
    )


def _revision_summary(
    uow: UnitOfWork, challan: Challan, rows: Sequence[ChallanRevision]
) -> list[ChallanRevisionSummary]:
    users = user_refs(uow, [r.issued_by for r in rows])
    return [
        ChallanRevisionSummary(
            id=r.id,
            revision_no=r.revision_no,
            kind=r.kind,
            issued_at=r.issued_at,
            issued_by=users.get(r.issued_by) if r.issued_by else None,
            document_sha256=r.document_sha256,
            document_path=f"/api/v1/challans/challans/{challan.id}/revisions/{r.revision_no}/document.pdf",
        )
        for r in rows
    ]


@query(READ)
def list_revisions(uow: UnitOfWork, challan_id: uuid.UUID) -> list[ChallanRevisionSummary]:
    challan = _visible(uow, challan_id)
    rows = list(
        uow.session.scalars(
            select(ChallanRevision)
            .where(ChallanRevision.challan_id == challan.id)
            .order_by(ChallanRevision.revision_no)
        )
    )
    return _revision_summary(uow, challan, rows)


def revision_row(uow: UnitOfWork, challan: Challan, revision_no: int) -> ChallanRevision:
    row = uow.session.scalars(
        select(ChallanRevision).where(
            ChallanRevision.challan_id == challan.id, ChallanRevision.revision_no == revision_no
        )
    ).first()
    if row is None:
        raise NotFound(code="not_found", resource_type="challans.challan_revision")
    return row


@query(READ)
def get_revision(uow: UnitOfWork, challan_id: uuid.UUID, revision_no: int) -> ChallanRevisionRead:
    challan = _visible(uow, challan_id)
    row = revision_row(uow, challan, revision_no)
    return ChallanRevisionRead(
        **_revision_summary(uow, challan, [row])[0].model_dump(), snapshot=row.snapshot
    )


@query(READ)
def exportable(uow: UnitOfWork, challan_id: uuid.UUID) -> tuple[Challan, list[ChallanLine]]:
    """The challan and its lines for an actor who may export it (404 outside read scope, 403 without export)."""
    challan = uow.repo(Challan).get(challan_id, "export", include_archived=False)
    return challan, lines_of(uow, challan)


@query(READ)
def export_rows(
    uow: UnitOfWork, filters: ChallanFilters
) -> tuple[list[Challan], dict[uuid.UUID, list[ChallanLine]]]:
    """Every challan of the filtered set the actor may export (bounded by the export scope), oldest first."""
    rows = list(
        uow.session.scalars(
            uow.repo(Challan)
            .select("export", include_archived=filters.include_deleted)
            .where(*_conditions(uow, filters))
            .order_by(Challan.challan_date, Challan.challan_number)
            .limit(5000)
        )
    )
    return rows, _lines_by_challan(uow, [c.id for c in rows])


# =====================================================================================================
# HTTP command wrappers (optional Idempotency-Key replay; the parent is authorised before the replay)
# =====================================================================================================
def create_challan_command(uow: UnitOfWork, data: ChallanCreate) -> tuple[ChallanDetail, bool]:
    uow.actor.require(CREATE)
    return idempotent(
        uow,
        "challans.create",
        data,
        lambda: detail(uow, create_challan(uow, data)),
        ChallanDetail,
        status=201,
    )


def update_challan_command(
    uow: UnitOfWork, challan_id: uuid.UUID, data: ChallanUpdate
) -> tuple[ChallanDetail, bool]:
    uow.repo(Challan).get(challan_id, "update", include_archived=False)
    return idempotent(
        uow,
        f"challans.update:{challan_id}",
        data,
        lambda: detail(uow, update_challan(uow, challan_id, data)),
        ChallanDetail,
    )


def add_line_command(
    uow: UnitOfWork, challan_id: uuid.UUID, data: ChallanLineAdd
) -> tuple[ChallanDetail, bool]:
    uow.repo(Challan).get(challan_id, "update", include_archived=False)
    return idempotent(
        uow,
        f"challans.add_line:{challan_id}",
        data,
        lambda: detail(uow, add_line(uow, challan_id, data)[0]),
        ChallanDetail,
        status=201,
    )


def update_line_command(
    uow: UnitOfWork, challan_id: uuid.UUID, line_id: uuid.UUID, data: ChallanLineUpdate
) -> tuple[ChallanDetail, bool]:
    uow.repo(Challan).get(challan_id, "update", include_archived=False)
    return idempotent(
        uow,
        f"challans.update_line:{challan_id}:{line_id}",
        data,
        lambda: detail(uow, update_line(uow, challan_id, line_id, data)[0]),
        ChallanDetail,
    )


def remove_line_command(
    uow: UnitOfWork, challan_id: uuid.UUID, line_id: uuid.UUID, expected_version: int | None
) -> tuple[ChallanDetail, bool]:
    uow.repo(Challan).get(challan_id, "update", include_archived=False)
    return idempotent(
        uow,
        f"challans.remove_line:{challan_id}:{line_id}",
        {"expected_version": expected_version},
        lambda: detail(uow, remove_line(uow, challan_id, line_id, expected_version=expected_version)),
        ChallanDetail,
    )


def duplicate_challan_command(
    uow: UnitOfWork, challan_id: uuid.UUID, data: ChallanDuplicate
) -> tuple[ChallanDetail, bool]:
    uow.actor.require(CREATE)
    uow.repo(Challan).get(challan_id, include_archived=False)
    return idempotent(
        uow,
        f"challans.duplicate:{challan_id}",
        data,
        lambda: detail(uow, duplicate_challan(uow, challan_id, data)),
        ChallanDetail,
        status=201,
    )


def delete_challan_command(
    uow: UnitOfWork, challan_id: uuid.UUID, expected_version: int | None
) -> tuple[ChallanDetail, bool]:
    uow.repo(Challan).get(challan_id, "delete", include_archived=False)
    return idempotent(
        uow,
        f"challans.delete:{challan_id}",
        {"expected_version": expected_version},
        lambda: detail(uow, delete_challan(uow, challan_id, expected_version=expected_version)),
        ChallanDetail,
    )


__all__ = [
    "CREATE",
    "READ",
    "add_line",
    "add_line_command",
    "allowed_transitions",
    "create_challan",
    "create_challan_command",
    "delete_challan",
    "delete_challan_command",
    "detail",
    "duplicate_challan",
    "duplicate_challan_command",
    "export_rows",
    "exportable",
    "get_challan",
    "get_challan_by_number",
    "get_revision",
    "has_return_links",
    "history_of",
    "issue_blockers",
    "line_reads",
    "lines_of",
    "list_challans",
    "list_revisions",
    "outstanding_by_unit",
    "quantity_by_unit",
    "remove_line",
    "remove_line_command",
    "revision_row",
    "summary",
    "update_challan",
    "update_challan_command",
    "update_line",
    "update_line_command",
]
