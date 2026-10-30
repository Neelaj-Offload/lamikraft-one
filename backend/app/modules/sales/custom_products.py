"""Custom products (legacy library, spec 4.13; LM-62..70, FG-CP-01..18, LP-08.1..08.5, REUSE-04).

- ``CP-NNNN`` from the atomic, never-reset allocator ``sales.custom_product`` (BR-09, BUG-13); codes are immutable
  (trigger) and never reused (archive, never delete).
- ``product_name`` is the name everywhere (list search, duplicate ``"X (Copy)"``, global search: BUG-08).
- A state machine with reasons for reject, dormant and reopen; ``approved`` needs an approved spec revision; issuing a
  quote that contains the product moves it forward to ``quoted`` (subscription ``sales.custom_product_autoadvance``).
- Costing is protected: its own append-only, versioned table, read with ``pricing.cost.read`` (every read audited),
  written with ``pricing.cost.update``; never in the detail, list, CSV (unless permitted and asked), search or events.
- Promotion to a catalogue master product: requested by ``sales.custom_product.promote`` on an approved product with an
  approved spec revision; the payload is dry-run validated and bound to an approval by its hash; the approver
  (``sales.custom_product.approve`` + ``catalogue.product.create``, never the requester) approves and the product is
  created through ``catalogue.service.create_product`` with lineage (origin ``promotion``); execution is idempotent.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import ColumnElement, exists, func, or_, select

from app.core.csv_safe import write_csv
from app.core.db.base import new_id
from app.core.errors import AppError, Conflict, Forbidden, InvalidTransition, NotFound, ValidationFailed
from app.core.http.pagination import MAX_LIMIT, Page
from app.core.money import Money, quantize_unit_price
from app.core.text import LIKE_ESCAPE, contains_pattern, tokens
from app.modules.approvals import service as approvals
from app.modules.approvals.service import ApprovalHandler, TargetRef
from app.modules.catalogue import service as catalogue
from app.modules.catalogue.models import Category, Subcategory
from app.modules.catalogue.schemas import ProductCreate, ProductOrigin
from app.modules.sales import events as ev
from app.modules.sales.common import (
    Errors,
    business_date,
    check_member,
    idempotent,
    party_ref,
    party_refs,
    user_ref,
    user_refs,
)
from app.modules.sales.models import (
    CustomProduct,
    CustomProductCosting,
    CustomProductPromotion,
    CustomProductSpecRevision,
    CustomProductStatusHistory,
    Quote,
    QuoteLine,
    Sample,
)
from app.modules.sales.schemas import (
    PROMOTION_KIND,
    Capability,
    CostingCreate,
    CostingRead,
    CustomHistoryAction,
    CustomHistoryRead,
    CustomPackaging,
    CustomProductArchive,
    CustomProductCreate,
    CustomProductDetail,
    CustomProductFilters,
    CustomProductStatus,
    CustomProductSummary,
    CustomProductTransition,
    CustomProductUpdate,
    CustomQuoteRef,
    CustomType,
    PromotionRead,
    PromotionRequest,
    PromotionStatus,
    QuoteStatus,
    SpecOutcome,
    SpecOutcomeIn,
    SpecRevisionCreate,
    SpecRevisionRead,
    TransitionRead,
)
from app.platform.service import query
from app.platform.uow import UnitOfWork

READ = "sales.custom_product.read"
COST_READ = "pricing.cost.read"
COST_WRITE = "pricing.cost.update"
S = CustomProductStatus

#: action -> (from statuses, to status | None (dynamic), reason required)
CUSTOM_TRANSITIONS: dict[str, tuple[frozenset[str], str | None, bool]] = {
    "develop": (frozenset({S.INQUIRY, S.SAMPLE_STAGE, S.QUOTED}), S.UNDER_DEVELOPMENT, False),
    "sample": (frozenset({S.INQUIRY, S.UNDER_DEVELOPMENT, S.QUOTED}), S.SAMPLE_STAGE, False),
    "quote": (frozenset({S.INQUIRY, S.UNDER_DEVELOPMENT, S.SAMPLE_STAGE, S.APPROVED}), S.QUOTED, False),
    "approve": (frozenset({S.SAMPLE_STAGE, S.QUOTED}), S.APPROVED, False),
    "reject": (frozenset({S.INQUIRY, S.UNDER_DEVELOPMENT, S.SAMPLE_STAGE, S.QUOTED}), S.REJECTED, True),
    "park": (frozenset({S.INQUIRY, S.UNDER_DEVELOPMENT, S.SAMPLE_STAGE, S.QUOTED, S.APPROVED}), S.DORMANT, True),
    "reopen": (frozenset({S.REJECTED}), S.INQUIRY, True),
    "reactivate": (frozenset({S.DORMANT}), None, False),
}
#: forward moves made when a quote containing the product is issued
AUTO_QUOTED_FROM = frozenset({S.INQUIRY.value, S.UNDER_DEVELOPMENT.value, S.SAMPLE_STAGE.value})
ARCHIVABLE = frozenset({S.REJECTED.value, S.DORMANT.value, S.CONVERTED_TO_STANDARD.value})
SPEC_FIELDS = (
    "custom_type", "base_product_key", "product_name", "description", "dimensions_text", "length_mm", "width_mm", "height_mm",
    "thickness_mm", "thickness_text", "decor_no", "decor_name", "finish", "shape", "groove_count", "bowl_count", "handle_type",
    "packaging_notes", "packaging", "unit_code",
)
CSV_COLUMNS = (
    "Code", "Type", "Product name", "Status", "Customer", "Inquiry reference", "Base product", "Category", "Dimensions",
    "Thickness", "Decor no", "Decor name", "Finish", "Shape", "Grooves", "Bowls", "Handle", "Packaging notes",
    "Quoted price", "Currency", "Remarks", "Owner", "Created", "Updated",
)


def custom_path(custom_id: uuid.UUID) -> str:
    return f"/sales/custom-products/{custom_id}"


def _str(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def _spec(custom: CustomProduct) -> dict[str, Any]:
    return {name: _str(getattr(custom, name)) for name in SPEC_FIELDS}


def _history(
    uow: UnitOfWork, custom: CustomProduct, action: CustomHistoryAction, from_status: str, to_status: str, *,
    reason: str | None = None, quote_id: uuid.UUID | None = None,
) -> None:
    uow.add(CustomProductStatusHistory(
        company_id=uow.actor.company_id, custom_product_id=custom.id, action=action.value, from_status=from_status,
        to_status=to_status, reason=reason, actor_user_id=uow.actor.user_id, quote_id=quote_id, occurred_at=uow.now(),
    ))


def _status_event(uow: UnitOfWork, custom: CustomProduct, from_status: str, origin: str | None = None) -> None:
    uow.emit(ev.CUSTOM_STATUS_CHANGED, aggregate_id=custom.id, aggregate_version=custom.version,
             payload=ev.payload(ev.CustomStatusChangedPayload(custom_product_id=custom.id, from_status=from_status,
                                                              to_status=custom.status, origin=origin)))


# =====================================================================================================
# field validation shared by create and update
# =====================================================================================================
def _apply_fields(uow: UnitOfWork, custom: CustomProduct, data: Any, sent: set[str], errors: Errors) -> list[str]:
    changed: list[str] = []
    for name in sorted(sent):
        value = getattr(data, name)
        if name == "packaging":
            value = value.model_dump(mode="json", exclude_none=True) if isinstance(value, CustomPackaging) else None
        elif name == "custom_type" and value is not None:
            value = value.value
        elif name == "quoted_price" and value is not None:
            value = quantize_unit_price(value)
        if name in ("product_name", "custom_type", "unit_code") and value is None:
            errors.add([name], "required", f"{name} cannot be empty")
            continue
        if name == "base_product_id":
            if value is not None:
                ref = catalogue.get_product_ref(uow, product_id=value)
                if custom.base_product_key != ref.product_key:
                    custom.base_product_key = ref.product_key
                    changed.append("base_product_key")
            elif custom.base_product_key is not None:
                custom.base_product_key = None
                changed.append("base_product_key")
        if name == "party_id" and value is not None:
            party_ref(uow, value)
        if getattr(custom, name) != value:
            setattr(custom, name, value)
            changed.append(name)
    if custom.custom_type == CustomType.MODIFIED_CATALOG.value and custom.base_product_id is None:
        errors.add(["base_product_id"], "base_product_required", "A modified catalogue product needs its base product")
    if (custom.quoted_price is None) != (custom.quoted_currency is None):
        errors.add(["quoted_currency"], "quoted_price_pair", "A quoted price needs its currency (and the other way round)")
    if custom.category_id is not None:
        cat = uow.session.get(Category, custom.category_id)
        if cat is None or cat.company_id != uow.actor.company_id:
            errors.add(["category_id"], "unknown_category", "Unknown category")
    if custom.subcategory_id is not None:
        sub = uow.session.get(Subcategory, custom.subcategory_id)
        if sub is None or sub.company_id != uow.actor.company_id:
            errors.add(["subcategory_id"], "unknown_subcategory", "Unknown subcategory")
        elif custom.category_id is not None and sub.category_id != custom.category_id:
            errors.add(["subcategory_id"], "subcategory_not_in_category", "The subcategory belongs to another category")
    return changed


# =====================================================================================================
# commands
# =====================================================================================================
def create_custom_product(uow: UnitOfWork, data: CustomProductCreate, *, origin: str | None = None, origin_ref: str | None = None,
                          duplicated_from: uuid.UUID | None = None) -> CustomProduct:
    actor = uow.actor
    actor.require("sales.custom_product.create")
    errors = Errors()
    owner = data.owner_user_id or actor.user_id
    if owner is None:
        errors.add(["owner_user_id"], "required", "A custom product needs an owner")
        errors.raise_if_any()
    assert owner is not None
    if owner != actor.user_id and not actor.can("sales.quote.assign"):
        raise Forbidden("Assigning to someone else needs sales.quote.assign", code="permission_denied", permission="sales.quote.assign")
    check_member(uow, owner, errors, "owner_user_id")
    custom = CustomProduct(
        id=new_id(), company_id=actor.company_id, custom_type=data.custom_type.value, product_name=data.product_name,
        owner_user_id=owner, branch_id=data.branch_id or (sorted(actor.branch_ids)[0] if actor.branch_ids else None),
        status=S.INQUIRY.value, unit_code=data.unit_code or "pcs", customer_specific_flag=bool(data.customer_specific_flag),
        duplicated_from_id=duplicated_from, origin_ref=origin_ref,
    )
    sent = data.model_fields_set - {"owner_user_id", "branch_id", "custom_type", "product_name", "unit_code", "customer_specific_flag"}
    _apply_fields(uow, custom, data, sent, errors)
    errors.raise_if_any()
    custom.custom_code = uow.allocate_number(ev.CUSTOM_PRODUCT_SEQUENCE.key, document_date=business_date(uow),
                                             resource_type="sales.custom_product", resource_id=custom.id)
    uow.add(custom)
    uow.flush()
    _history(uow, custom, CustomHistoryAction.CREATE if duplicated_from is None else CustomHistoryAction.DUPLICATE,
             S.INQUIRY.value, S.INQUIRY.value)
    uow.emit(ev.CUSTOM_CREATED, aggregate_id=custom.id, aggregate_version=custom.version,
             payload=ev.payload(ev.CustomCreatedPayload(custom_product_id=custom.id, custom_code=custom.custom_code,
                                                        owner_user_id=owner, origin=origin)))
    uow.audit("sales.custom_product.created", resource_type="sales.custom_product", resource_id=custom.id,
              resource_label=f"{custom.custom_code} · {custom.product_name}")
    return custom


def update_custom_product(uow: UnitOfWork, custom_id: uuid.UUID, data: CustomProductUpdate, *, origin: str | None = None) -> CustomProduct:
    custom = uow.repo(CustomProduct).get(custom_id, "update", for_update=True)
    uow.expect_version(custom, data.expected_version)
    errors = Errors()
    changed = _apply_fields(uow, custom, data, data.model_fields_set - {"expected_version"}, errors)
    errors.raise_if_any()
    if not changed:
        return custom
    custom.updated_at = uow.now()
    uow.flush()
    # a spec change after approval needs a fresh spec approval and voids a pending promotion request
    if set(changed) & set(SPEC_FIELDS):
        for promo in _promotions(uow, custom, statuses=(PromotionStatus.PENDING_APPROVAL.value, PromotionStatus.APPROVED.value)):
            approvals.invalidate_for_target(uow, "sales.custom_product_promotion", promo.id, reason="spec_changed")
            promo.status = PromotionStatus.WITHDRAWN.value
            promo.failure_reason = "The specification changed after the request; request the promotion again"
    uow.emit(ev.CUSTOM_UPDATED, aggregate_id=custom.id, aggregate_version=custom.version,
             payload=ev.payload(ev.CustomUpdatedPayload(custom_product_id=custom.id, changed_fields=sorted(set(changed)), origin=origin)))
    uow.audit("sales.custom_product.updated", resource_type="sales.custom_product", resource_id=custom.id,
              resource_label=custom.custom_code, details={"changed_fields": sorted(set(changed))})
    return custom


def _approved_spec(uow: UnitOfWork, custom: CustomProduct) -> CustomProductSpecRevision | None:
    return uow.session.scalars(
        select(CustomProductSpecRevision).where(CustomProductSpecRevision.custom_product_id == custom.id,
                                                CustomProductSpecRevision.outcome == SpecOutcome.APPROVED.value)
        .order_by(CustomProductSpecRevision.revision_no.desc())
    ).first()


def _target(action: str, custom: CustomProduct) -> str | None:
    spec = CUSTOM_TRANSITIONS.get(action)
    if spec is None or custom.status not in spec[0]:
        return None
    return spec[1] or custom.dormant_from_status


def allowed_custom_transitions(uow: UnitOfWork, custom: CustomProduct) -> list[TransitionRead]:
    if not uow.repo(CustomProduct).can(custom, "transition"):
        return []
    out: list[TransitionRead] = []
    has_spec = None
    for action, (_frm, _to, reason) in CUSTOM_TRANSITIONS.items():
        target = _target(action, custom)
        if target is None:
            continue
        if action == "approve":
            has_spec = has_spec if has_spec is not None else _approved_spec(uow, custom) is not None
            if not has_spec:
                continue
        out.append(TransitionRead(action=action, to_status=str(target), requires_reason=reason))
    return out


def transition_custom_product(uow: UnitOfWork, custom_id: uuid.UUID, data: CustomProductTransition, *, origin: str | None = None) -> CustomProduct:
    repo = uow.repo(CustomProduct)
    custom = repo.get(custom_id, for_update=True)
    target = _target(data.action, custom)
    if target is None:
        raise InvalidTransition(
            f"{data.action} is not allowed while the custom product is {custom.status}",
            allowed_transitions=[t.model_dump() for t in allowed_custom_transitions(uow, custom)], current_status=custom.status,
        )
    repo.require_action(custom, "transition")
    uow.expect_version(custom, data.expected_version)
    if CUSTOM_TRANSITIONS[data.action][2] and not data.reason:
        raise ValidationFailed(f"{data.action} needs a reason",
                               errors=[{"loc": ["body", "reason"], "msg": "a reason is required", "code": "reason_required"}])
    if data.action == "approve" and _approved_spec(uow, custom) is None:
        raise Conflict("Approve a specification revision (sample feedback) before approving the product", code="spec_approval_required")
    from_status = custom.status
    custom.dormant_from_status = from_status if target == S.DORMANT.value else None
    custom.status = str(target)
    custom.status_reason = data.reason
    custom.updated_at = uow.now()
    uow.flush()
    _history(uow, custom, CustomHistoryAction.TRANSITION, from_status, custom.status, reason=data.reason)
    _status_event(uow, custom, from_status, origin)
    uow.audit(f"sales.custom_product.{data.action}", resource_type="sales.custom_product", resource_id=custom.id,
              resource_label=custom.custom_code, reason=data.reason, details={"from_status": from_status, "to_status": custom.status})
    return custom


def _ever_quoted(uow: UnitOfWork, custom: CustomProduct) -> bool:
    return bool(uow.session.scalar(select(exists().where(QuoteLine.custom_product_id == custom.id))))


def archive_custom_product(uow: UnitOfWork, custom_id: uuid.UUID, data: CustomProductArchive, *, origin: str | None = None) -> CustomProduct:
    """Archive (the legacy admin delete): only rejected, dormant or converted products, or ones never quoted."""
    custom = uow.repo(CustomProduct).get(custom_id, "archive", for_update=True)
    uow.expect_version(custom, data.expected_version)
    if custom.archived_at is not None:
        raise Conflict("The custom product is already archived", code="custom_product_archived")
    if custom.status not in ARCHIVABLE and _ever_quoted(uow, custom):
        raise Conflict(
            "A custom product that has been quoted can be archived only once it is rejected, dormant or converted",
            code="custom_product_in_use",
        )
    custom.archived_at = uow.now()
    custom.archived_by = uow.actor.user_id
    custom.updated_at = uow.now()
    uow.flush()
    _history(uow, custom, CustomHistoryAction.ARCHIVE, custom.status, custom.status, reason=data.reason)
    uow.emit(ev.CUSTOM_ARCHIVED, aggregate_id=custom.id, aggregate_version=custom.version,
             payload=ev.payload(ev.CustomLineagePayload(custom_product_id=custom.id, source_custom_product_id=None, origin=origin)))
    uow.audit("sales.custom_product.archived", resource_type="sales.custom_product", resource_id=custom.id,
              resource_label=custom.custom_code, reason=data.reason)
    return custom


def unarchive_custom_product(uow: UnitOfWork, custom_id: uuid.UUID, data: CustomProductArchive) -> CustomProduct:
    custom = uow.repo(CustomProduct).get(custom_id, "archive", for_update=True)
    uow.expect_version(custom, data.expected_version)
    if custom.archived_at is None:
        raise Conflict("The custom product is not archived", code="custom_product_not_archived")
    custom.archived_at = None
    custom.archived_by = None
    custom.updated_at = uow.now()
    uow.flush()
    _history(uow, custom, CustomHistoryAction.UNARCHIVE, custom.status, custom.status, reason=data.reason)
    uow.audit("sales.custom_product.unarchived", resource_type="sales.custom_product", resource_id=custom.id, resource_label=custom.custom_code)
    return custom


def duplicate_custom_product(uow: UnitOfWork, custom_id: uuid.UUID, *, origin: str | None = None) -> CustomProduct:
    """A new ``inquiry`` with a new code and ``product_name`` "X (Copy)" (legacy used a non-existent ``name``: BUG-08).
    Costing, spec revisions, history and promotion are not copied."""
    source = uow.repo(CustomProduct).get(custom_id)  # 404 outside read scope
    fields = {name: getattr(source, name) for name in (
        "base_product_id", "customer_specific_flag", "party_id", "legacy_customer_name", "inquiry_reference", "description",
        "category_id", "subcategory_id", "dimensions_text", "length_mm", "width_mm", "height_mm", "thickness_mm",
        "thickness_text", "decor_no", "decor_name", "finish", "shape", "groove_count", "bowl_count", "handle_type",
        "packaging_notes", "quoted_price", "quoted_currency", "unit_code", "remarks",
    )}
    fields["packaging"] = CustomPackaging.model_validate(source.packaging) if source.packaging else None
    name = f"{source.product_name} (Copy)"[:300]
    copy = create_custom_product(
        uow,
        CustomProductCreate(custom_type=CustomType(source.custom_type), product_name=name, **fields),
        origin=origin,
        duplicated_from=source.id,
    )
    uow.emit(ev.CUSTOM_DUPLICATED, aggregate_id=copy.id, aggregate_version=copy.version,
             payload=ev.payload(ev.CustomLineagePayload(custom_product_id=copy.id, source_custom_product_id=source.id, origin=origin)))
    return copy


# ---- protected costing ---------------------------------------------------------------------------------
def record_costing(uow: UnitOfWork, custom_id: uuid.UUID, data: CostingCreate) -> CostingRead:
    uow.actor.require(COST_WRITE)
    custom = uow.repo(CustomProduct).get(custom_id, for_update=True)
    current = uow.session.scalar(select(func.max(CustomProductCosting.cost_version)).where(CustomProductCosting.custom_product_id == custom.id))
    row = CustomProductCosting(
        company_id=uow.actor.company_id, custom_product_id=custom.id, cost_version=int(current or 0) + 1,
        cost_amount=quantize_unit_price(data.cost_amount), cost_currency=data.cost_currency, components=data.components or None,
        basis_note=data.basis_note, recorded_at=uow.now(), recorded_by=uow.actor.user_id,
    )
    uow.add(row)
    uow.flush()
    uow.audit("sales.custom_product.costing_recorded", resource_type="sales.custom_product", resource_id=custom.id,
              resource_label=custom.custom_code, restricted_fields=["cost_amount", "components"],
              details={"cost_version": row.cost_version})
    return _costing_read(uow, row)


def _costing_read(uow: UnitOfWork, row: CustomProductCosting) -> CostingRead:
    return CostingRead(
        id=row.id, cost_version=row.cost_version, cost=Money(amount=row.cost_amount, currency=row.cost_currency),  # type: ignore[arg-type]
        components=row.components, basis_note=row.basis_note, recorded_at=row.recorded_at, recorded_by=user_ref(uow, row.recorded_by),
    )


@query(COST_READ)
def list_costing(uow: UnitOfWork, custom_id: uuid.UUID) -> list[CostingRead]:
    """Costing versions, newest first: ``pricing.cost.read`` (403 without), 404 outside the product's read scope;
    every read returning values is audited (field names and versions only)."""
    custom = uow.repo(CustomProduct).get(custom_id)
    rows = list(uow.session.scalars(
        select(CustomProductCosting).where(CustomProductCosting.custom_product_id == custom.id)
        .order_by(CustomProductCosting.cost_version.desc())
    ))
    if rows:
        uow.audit("sales.custom_product.costing_read", resource_type="sales.custom_product", resource_id=custom.id,
                  resource_label=custom.custom_code, restricted_fields=["cost_amount", "components"],
                  details={"cost_versions": [r.cost_version for r in rows]})
    return [_costing_read(uow, r) for r in rows]


# ---- spec revisions (sample history) --------------------------------------------------------------------
def record_spec_revision(uow: UnitOfWork, custom_id: uuid.UUID, data: SpecRevisionCreate, *, origin: str | None = None) -> CustomProductSpecRevision:
    custom = uow.repo(CustomProduct).get(custom_id, "update", for_update=True)
    if data.sample_id is not None:
        sample = uow.repo(Sample).get(data.sample_id)
        if sample.custom_product_id not in (None, custom.id):
            raise ValidationFailed("The sample belongs to another custom product",
                                   errors=[{"loc": ["body", "sample_id"], "msg": "other custom product", "code": "sample_not_of_product"}])
    last = uow.session.scalar(select(func.max(CustomProductSpecRevision.revision_no)).where(CustomProductSpecRevision.custom_product_id == custom.id))
    row = CustomProductSpecRevision(
        id=new_id(), company_id=uow.actor.company_id, custom_product_id=custom.id, revision_no=int(last or 0) + 1,
        spec_snapshot=_spec(custom), sample_id=data.sample_id, sample_reference=data.sample_reference,
        sample_sent_on=data.sample_sent_on, feedback=data.feedback, outcome=SpecOutcome.PENDING.value,
    )
    uow.add(row)
    uow.flush()
    uow.emit(ev.CUSTOM_SPEC_RECORDED, aggregate_id=custom.id, aggregate_version=custom.version,
             payload=ev.payload(ev.CustomSpecRecordedPayload(custom_product_id=custom.id, spec_revision_id=row.id, origin=origin)))
    uow.audit("sales.custom_product.spec_recorded", resource_type="sales.custom_product", resource_id=custom.id,
              resource_label=custom.custom_code, details={"revision_no": row.revision_no})
    return row


def decide_spec_revision(uow: UnitOfWork, custom_id: uuid.UUID, revision_id: uuid.UUID, data: SpecOutcomeIn) -> CustomProductSpecRevision:
    """Record the outcome of a spec revision (customer approval of the sample); approving one supersedes earlier
    approvals. A decided revision is immutable except for moving to ``superseded``."""
    custom = uow.repo(CustomProduct).get(custom_id, "update", for_update=True)
    row = uow.session.scalars(
        select(CustomProductSpecRevision).where(CustomProductSpecRevision.id == revision_id,
                                                CustomProductSpecRevision.custom_product_id == custom.id).with_for_update()
    ).first()
    if row is None:
        raise NotFound(code="not_found", resource_type="sales.custom_product_spec_revision")
    uow.expect_version(row, data.expected_version)
    if row.outcome != SpecOutcome.PENDING.value:
        raise Conflict(f"The specification revision is already {row.outcome}", code="spec_revision_decided")
    if data.outcome == "approved":
        for earlier in uow.session.scalars(
            select(CustomProductSpecRevision).where(CustomProductSpecRevision.custom_product_id == custom.id,
                                                    CustomProductSpecRevision.outcome == SpecOutcome.APPROVED.value)
        ):
            earlier.outcome = SpecOutcome.SUPERSEDED.value
    row.outcome = data.outcome
    row.feedback = data.feedback if data.feedback is not None else row.feedback
    row.decided_at = uow.now()
    row.decided_by = uow.actor.user_id
    uow.flush()
    uow.audit("sales.custom_product.spec_decided", resource_type="sales.custom_product", resource_id=custom.id,
              resource_label=custom.custom_code, details={"revision_no": row.revision_no, "outcome": data.outcome})
    return row


# ---- promotion ----------------------------------------------------------------------------------------
def _promotions(uow: UnitOfWork, custom: CustomProduct, *, statuses: Sequence[str] | None = None) -> list[CustomProductPromotion]:
    stmt = select(CustomProductPromotion).where(CustomProductPromotion.custom_product_id == custom.id)
    if statuses:
        stmt = stmt.where(CustomProductPromotion.status.in_(list(statuses)))
    return list(uow.session.scalars(stmt.order_by(CustomProductPromotion.created_at, CustomProductPromotion.id)))


def _promotion_payload(custom: CustomProduct, spec: CustomProductSpecRevision, data: PromotionRequest) -> dict[str, Any]:
    category_id = data.category_id or custom.category_id
    return {
        "product_key": data.product_key.strip(),
        "display_sku": data.display_sku or data.product_key.strip(),
        "product_name": custom.product_name,
        "brand": data.brand,
        "category_id": str(category_id) if category_id else None,
        "subcategory_id": str(data.subcategory_id or custom.subcategory_id) if (data.subcategory_id or custom.subcategory_id) else None,
        "unit_of_sale": data.unit_of_sale or custom.unit_code,
        "hsn_sac": data.hsn_sac,
        "decor_no": custom.decor_no,
        "decor_name": custom.decor_name,
        "finish": custom.finish,
        "shape": custom.shape,
        "description": custom.description,
        "size_mm": custom.dimensions_text,
        "lineage": {"custom_product_id": str(custom.id), "custom_code": custom.custom_code, "spec_revision_id": str(spec.id),
                    "spec_revision_no": spec.revision_no, "base_product_id": str(custom.base_product_id) if custom.base_product_id else None},
    }


def _product_create(payload: dict[str, Any], promotion_id: uuid.UUID) -> ProductCreate:
    lineage = dict(payload["lineage"], promotion_id=str(promotion_id))
    return ProductCreate(
        product_key=payload["product_key"], display_sku=payload["display_sku"], product_name=payload["product_name"],
        brand=payload["brand"], category_id=uuid.UUID(payload["category_id"]),
        subcategory_id=uuid.UUID(payload["subcategory_id"]) if payload["subcategory_id"] else None,
        unit_of_sale=payload["unit_of_sale"], hsn_sac=payload["hsn_sac"], decor_no=payload["decor_no"],
        decor_name=payload["decor_name"], finish=payload["finish"], shape=payload["shape"], description=payload["description"],
        size_mm=payload["size_mm"], origin=ProductOrigin.PROMOTION, origin_ref=payload["lineage"]["custom_code"],
        source_extra={"promotion": lineage},
    )


def _validate_payload(uow: UnitOfWork, payload: dict[str, Any]) -> None:
    errors = Errors()
    if not payload.get("category_id"):
        errors.add(["category_id"], "required", "A master product needs a category")
    if catalogue.find_product_id(uow, payload["product_key"]) is not None:
        errors.add(["product_key"], "product_key_exists", "A catalogue product with this key already exists")
    errors.raise_if_any()


def request_promotion(uow: UnitOfWork, custom_id: uuid.UUID, data: PromotionRequest, *, origin: str | None = None) -> CustomProductPromotion:
    custom = uow.repo(CustomProduct).get(custom_id, "promote", for_update=True)
    if custom.status != S.APPROVED.value:
        raise Conflict("Only an approved custom product can be promoted", code="custom_product_not_approved")
    spec = _approved_spec(uow, custom)
    if spec is None:
        raise Conflict("Promotion needs an approved specification revision", code="spec_approval_required")
    payload = _promotion_payload(custom, spec, data)
    _validate_payload(uow, payload)
    try:  # dry-run of the catalogue's own input validation
        _product_create(payload, uuid.UUID(int=0))
    except ValueError as exc:
        raise ValidationFailed(f"The master product is not valid: {exc}", code="promotion_payload_invalid") from exc
    for pending in _promotions(uow, custom, statuses=(PromotionStatus.PENDING_APPROVAL.value,)):
        pending.status = PromotionStatus.WITHDRAWN.value
        pending.failure_reason = "Superseded by a new request"
    promo = CustomProductPromotion(
        id=new_id(), company_id=uow.actor.company_id, custom_product_id=custom.id, spec_revision_id=spec.id, payload=payload,
        payload_hash=approvals.content_hash(payload), status=PromotionStatus.PENDING_APPROVAL.value, requested_by=uow.actor.user_id,
    )
    proposal = approvals.submit(
        uow, kind=PROMOTION_KIND, targets=[TargetRef("sales.custom_product_promotion", promo.id, 1)], content=payload,
        title=f"Promote {custom.custom_code} · {custom.product_name} to {payload['product_key']}",
        facts={"custom_code": custom.custom_code, "product_key": payload["product_key"]}, expires_in=timedelta(days=14),
    )
    promo.proposal_id = proposal.id
    uow.add(promo)
    uow.flush()
    uow.emit(ev.CUSTOM_PROMOTION_REQUESTED, aggregate_id=custom.id, aggregate_version=custom.version,
             payload=ev.payload(ev.CustomPromotionRequestedPayload(custom_product_id=custom.id, promotion_id=promo.id,
                                                                    proposal_id=proposal.id, origin=origin)))
    uow.audit("sales.custom_product.promotion_requested", resource_type="sales.custom_product", resource_id=custom.id,
              resource_label=custom.custom_code, details={"product_key": payload["product_key"]})
    return promo


def execute_promotion(uow: UnitOfWork, custom_id: uuid.UUID, promotion_id: uuid.UUID, *, origin: str | None = None) -> CustomProductPromotion:
    """Create the master product (idempotent: an executed promotion returns as it is)."""
    custom = uow.repo(CustomProduct).get(custom_id, for_update=True)
    promo = uow.session.scalars(
        select(CustomProductPromotion).where(CustomProductPromotion.id == promotion_id,
                                             CustomProductPromotion.custom_product_id == custom.id).with_for_update()
    ).first()
    if promo is None:
        raise NotFound(code="not_found", resource_type="sales.custom_product_promotion")
    if promo.status == PromotionStatus.EXECUTED.value:
        return promo
    if promo.status not in (PromotionStatus.APPROVED.value, PromotionStatus.FAILED.value):
        raise Conflict(f"The promotion is {promo.status}; it needs an approval first", code="promotion_not_approved")
    uow.actor.require("catalogue.product.create")
    if approvals.content_hash(promo.payload) != promo.payload_hash:
        raise Conflict("The promotion payload changed after approval; request it again", code="promotion_payload_changed")
    try:
        _validate_payload(uow, promo.payload)
        with uow.session.begin_nested():
            result = catalogue.create_product(uow, _product_create(promo.payload, promo.id))
    except AppError as exc:
        promo.status = PromotionStatus.FAILED.value
        promo.failure_reason = (exc.detail or exc.code or "failed")[:500]
        uow.flush()
        return promo
    product_id = result.product.id
    promo.status = PromotionStatus.EXECUTED.value
    promo.executed_product_id = product_id
    promo.executed_at = uow.now()
    promo.executed_by = uow.actor.user_id
    promo.failure_reason = None
    from_status = custom.status
    custom.promoted_product_id = product_id
    custom.status = S.CONVERTED_TO_STANDARD.value
    custom.updated_at = uow.now()
    uow.flush()
    _history(uow, custom, CustomHistoryAction.PROMOTE, from_status, custom.status, reason=f"promoted to {promo.payload['product_key']}")
    _status_event(uow, custom, from_status, origin)
    uow.emit(ev.CUSTOM_PROMOTED, aggregate_id=custom.id, aggregate_version=custom.version,
             payload=ev.payload(ev.CustomPromotedPayload(custom_product_id=custom.id, product_id=product_id, origin=origin)))
    uow.audit("sales.custom_product.promoted", resource_type="sales.custom_product", resource_id=custom.id,
              resource_label=custom.custom_code, details={"product_id": str(product_id), "product_key": promo.payload["product_key"]})
    return promo


def _promo_target(uow: UnitOfWork, target: TargetRef) -> CustomProductPromotion | None:
    if target.target_type != "sales.custom_product_promotion":
        return None
    return uow.session.scalars(
        select(CustomProductPromotion).where(CustomProductPromotion.id == target.target_id,
                                             CustomProductPromotion.company_id == uow.actor.company_id)
    ).first()


def _promo_version(uow: UnitOfWork, target: TargetRef) -> int | None:
    promo = _promo_target(uow, target)
    return promo.version if promo is not None and promo.status == PromotionStatus.PENDING_APPROVAL.value else None


def _promo_can_decide(uow: UnitOfWork, _proposal: Any) -> bool:
    return uow.actor.can("catalogue.product.create")


def _promo_approved(uow: UnitOfWork, proposal: Any) -> None:
    for target in approvals.targets_of(uow, proposal):
        promo = _promo_target(uow, target)
        if promo is None:
            continue
        promo.status = PromotionStatus.APPROVED.value
        promo.decided_at = uow.now()
        promo.decision_reason = proposal.decision_reason
        uow.flush()
        execute_promotion(uow, promo.custom_product_id, promo.id)


def _promo_rejected(uow: UnitOfWork, proposal: Any) -> None:
    for target in approvals.targets_of(uow, proposal):
        promo = _promo_target(uow, target)
        if promo is None:
            continue
        promo.status = PromotionStatus.REJECTED.value
        promo.decided_at = uow.now()
        promo.decision_reason = proposal.decision_reason
        uow.flush()
        uow.emit(ev.CUSTOM_PROMOTION_REJECTED, aggregate_id=promo.custom_product_id, aggregate_version=promo.version,
                 payload=ev.payload(ev.CustomPromotionRejectedPayload(custom_product_id=promo.custom_product_id, promotion_id=promo.id)))


PROMOTION_HANDLER = ApprovalHandler(
    kind=PROMOTION_KIND,
    approve_permission="sales.custom_product.approve",
    current_version=_promo_version,
    on_approved=_promo_approved,
    on_rejected=_promo_rejected,
    can_decide=_promo_can_decide,
)


# ---- the quote-issued subscription (sales.custom_product_autoadvance) ------------------------------------
def advance_on_issue(uow: UnitOfWork, quote_id: uuid.UUID) -> int:
    """Move every custom product on the issued quote forward to ``quoted`` (forward moves only, with history)."""
    ids = list(uow.session.scalars(
        select(QuoteLine.custom_product_id).where(QuoteLine.quote_id == quote_id, QuoteLine.custom_product_id.is_not(None)).distinct()
    ))
    moved = 0
    for custom in uow.session.scalars(select(CustomProduct).where(CustomProduct.id.in_(ids)).order_by(CustomProduct.id).with_for_update()):
        if custom.status not in AUTO_QUOTED_FROM or custom.archived_at is not None:
            continue
        from_status = custom.status
        custom.status = S.QUOTED.value
        custom.updated_at = uow.now()
        uow.flush()
        _history(uow, custom, CustomHistoryAction.AUTO_QUOTED, from_status, custom.status, reason="quote issued", quote_id=quote_id)
        _status_event(uow, custom, from_status)
        moved += 1
    return moved


# =====================================================================================================
# reads
# =====================================================================================================
def _conditions(uow: UnitOfWork, f: CustomProductFilters) -> list[ColumnElement[bool]]:
    C = CustomProduct
    conds: list[ColumnElement[bool]] = []
    for tok in tokens(f.q or ""):
        pattern = contains_pattern(tok)
        conds.append(or_(
            C.product_name.ilike(pattern, escape=LIKE_ESCAPE), C.custom_code.ilike(pattern, escape=LIKE_ESCAPE),
            C.decor_no.ilike(pattern, escape=LIKE_ESCAPE), C.legacy_customer_name.ilike(pattern, escape=LIKE_ESCAPE),
            C.inquiry_reference.ilike(pattern, escape=LIKE_ESCAPE), C.base_product_key.ilike(pattern, escape=LIKE_ESCAPE),
        ))
    if f.status:
        conds.append(C.status.in_([s.value for s in f.status]))
    if f.custom_type:
        conds.append(C.custom_type == f.custom_type.value)
    if f.party_id:
        conds.append(C.party_id == f.party_id)
    if f.category_id:
        conds.append(C.category_id == f.category_id)
    if f.scope == "mine" and uow.actor.user_id is not None:
        conds.append(C.owner_user_id == uow.actor.user_id)
    return conds


def _summaries(uow: UnitOfWork, rows: Sequence[CustomProduct]) -> list[CustomProductSummary]:
    users = user_refs(uow, [r.owner_user_id for r in rows])
    party_ids = [r.party_id for r in rows if r.party_id]
    refs = party_refs(uow, party_ids, {}) if party_ids else {}
    return [
        CustomProductSummary(
            id=r.id, custom_code=r.custom_code, custom_type=CustomType(r.custom_type), product_name=r.product_name,
            status=CustomProductStatus(r.status), party=refs.get(r.party_id) if r.party_id else None,
            legacy_customer_name=r.legacy_customer_name, inquiry_reference=r.inquiry_reference, base_product_key=r.base_product_key,
            dimensions_text=r.dimensions_text, decor_no=r.decor_no, finish=r.finish,
            quoted_price=Money(amount=r.quoted_price, currency=r.quoted_currency) if r.quoted_price is not None else None,  # type: ignore[arg-type]
            owner=users.get(r.owner_user_id) or user_ref(uow, r.owner_user_id),  # type: ignore[arg-type]
            promoted_product_id=r.promoted_product_id, archived_at=r.archived_at, created_at=r.created_at, updated_at=r.updated_at,
            version=r.version, path=custom_path(r.id),
        )
        for r in rows
    ]


@query(READ)
def list_custom_products(uow: UnitOfWork, filters: CustomProductFilters, *, limit: int = 50, offset: int = 0) -> Page[CustomProductSummary]:
    page = uow.repo(CustomProduct).list(
        *_conditions(uow, filters), order_by=[CustomProduct.custom_code.desc(), CustomProduct.id],
        limit=max(1, min(limit, MAX_LIMIT)), offset=max(0, offset), include_archived=filters.include_archived,
    )
    return Page[CustomProductSummary](items=_summaries(uow, page.items), total=page.total, limit=page.limit, offset=page.offset)


@query(READ)
def custom_status_counts(uow: UnitOfWork, filters: CustomProductFilters) -> dict[str, int]:
    f = filters.model_copy(update={"status": None})
    stmt = (uow.repo(CustomProduct).select(include_archived=f.include_archived).where(*_conditions(uow, f))
            .with_only_columns(CustomProduct.status, func.count(CustomProduct.id)).group_by(CustomProduct.status))
    counts = {s.value: 0 for s in CustomProductStatus}
    for status, n in uow.session.execute(stmt).all():
        counts[status] = int(n)
    return counts


def _spec_reads(uow: UnitOfWork, custom: CustomProduct) -> list[SpecRevisionRead]:
    rows = list(uow.session.scalars(select(CustomProductSpecRevision).where(CustomProductSpecRevision.custom_product_id == custom.id)
                                    .order_by(CustomProductSpecRevision.revision_no)))
    samples = dict(uow.session.execute(select(Sample.id, Sample.sample_number).where(Sample.id.in_([r.sample_id for r in rows if r.sample_id]))).all()) if rows else {}
    users = user_refs(uow, [r.decided_by for r in rows])
    return [
        SpecRevisionRead(
            id=r.id, revision_no=r.revision_no, spec_snapshot=r.spec_snapshot, sample_id=r.sample_id,
            sample_number=samples.get(r.sample_id) if r.sample_id else None, sample_reference=r.sample_reference,
            sample_sent_on=r.sample_sent_on, feedback=r.feedback, outcome=SpecOutcome(r.outcome), decided_at=r.decided_at,
            decided_by=users.get(r.decided_by) if r.decided_by else None, created_at=r.created_at, version=r.version,
        )
        for r in rows
    ]


def _promotion_reads(uow: UnitOfWork, custom: CustomProduct) -> list[PromotionRead]:
    rows = _promotions(uow, custom)
    users = user_refs(uow, [r.requested_by for r in rows])
    return [
        PromotionRead(
            id=r.id, status=PromotionStatus(r.status), spec_revision_id=r.spec_revision_id, payload=r.payload, payload_hash=r.payload_hash,
            proposal_id=r.proposal_id, requested_by=users.get(r.requested_by) if r.requested_by else None, decided_at=r.decided_at,
            decision_reason=r.decision_reason, executed_product_id=r.executed_product_id, executed_at=r.executed_at,
            failure_reason=r.failure_reason, created_at=r.created_at, version=r.version,
        )
        for r in rows
    ]


def _quote_refs(uow: UnitOfWork, custom: CustomProduct) -> list[CustomQuoteRef]:
    """Quotes using the product that the actor may read (lines are authorised through their quote)."""
    visible = uow.repo(Quote).visible_ids()
    rows = uow.session.execute(
        select(Quote.id, Quote.quote_number, Quote.status, QuoteLine.line_no)
        .join(QuoteLine, QuoteLine.quote_id == Quote.id)
        .where(QuoteLine.custom_product_id == custom.id, Quote.id.in_(visible), Quote.deleted_at.is_(None))
        .order_by(Quote.quote_number, QuoteLine.line_no)
    ).all()
    return [CustomQuoteRef(quote_id=r[0], quote_number=r[1], status=QuoteStatus(r[2]), line_no=r[3]) for r in rows]


def detail(uow: UnitOfWork, custom: CustomProduct) -> CustomProductDetail:
    base = _summaries(uow, [custom])[0]
    repo = uow.repo(CustomProduct)
    caps = repo.capabilities(custom, ["update", "transition", "archive", "promote", "export"])
    has_spec = _approved_spec(uow, custom) is not None
    if caps["promote"]["allowed"] and not has_spec:
        caps["promote"] = {"allowed": False, "reason_code": "spec_approval_required"}
    archivable = custom.archived_at is None and (custom.status in ARCHIVABLE or not _ever_quoted(uow, custom))
    if caps["archive"]["allowed"] and not archivable:
        caps["archive"] = {"allowed": False, "reason_code": "custom_product_archived" if custom.archived_at else "custom_product_in_use"}
    caps["duplicate"] = {"allowed": uow.actor.can("sales.custom_product.create"),
                         "reason_code": None if uow.actor.can("sales.custom_product.create") else "permission_denied"}
    caps["read_costing"] = {"allowed": uow.actor.can(COST_READ), "reason_code": None if uow.actor.can(COST_READ) else "permission_denied"}
    caps["record_costing"] = {"allowed": uow.actor.can(COST_WRITE), "reason_code": None if uow.actor.can(COST_WRITE) else "permission_denied"}
    caps["execute_promotion"] = {"allowed": uow.actor.can("catalogue.product.create"), "reason_code": None}
    names: dict[uuid.UUID, str] = {}
    if custom.category_id:
        names.update(dict(uow.session.execute(select(Category.id, Category.name).where(Category.id == custom.category_id)).all()))
    if custom.subcategory_id:
        names.update(dict(uow.session.execute(select(Subcategory.id, Subcategory.name).where(Subcategory.id == custom.subcategory_id)).all()))
    return CustomProductDetail(
        **base.model_dump(),
        base_product_id=custom.base_product_id, customer_specific_flag=custom.customer_specific_flag, description=custom.description,
        category_id=custom.category_id, subcategory_id=custom.subcategory_id,
        category_name=names.get(custom.category_id) if custom.category_id else None,
        subcategory_name=names.get(custom.subcategory_id) if custom.subcategory_id else None,
        length_mm=custom.length_mm, width_mm=custom.width_mm, height_mm=custom.height_mm, thickness_mm=custom.thickness_mm,
        thickness_text=custom.thickness_text, decor_name=custom.decor_name, shape=custom.shape, groove_count=custom.groove_count,
        bowl_count=custom.bowl_count, handle_type=custom.handle_type, packaging_notes=custom.packaging_notes,
        packaging=CustomPackaging.model_validate(custom.packaging) if custom.packaging else None, unit_code=custom.unit_code,
        remarks=custom.remarks, status_reason=custom.status_reason, dormant_from_status=custom.dormant_from_status,
        duplicated_from_id=custom.duplicated_from_id, created_by=user_ref(uow, custom.created_by), branch_id=custom.branch_id,
        spec_revisions=_spec_reads(uow, custom), promotions=_promotion_reads(uow, custom), quotes=_quote_refs(uow, custom),
        capabilities={k: Capability(**v) for k, v in caps.items()},
        allowed_transitions=allowed_custom_transitions(uow, custom),
        redacted_fields=[] if uow.actor.can(COST_READ) else ["costing"],
    )


@query(READ)
def get_custom_product(uow: UnitOfWork, custom_id: uuid.UUID) -> CustomProductDetail:
    return detail(uow, uow.repo(CustomProduct).get(custom_id))


@query(READ)
def custom_history(uow: UnitOfWork, custom_id: uuid.UUID) -> list[CustomHistoryRead]:
    custom = uow.repo(CustomProduct).get(custom_id)
    rows = list(uow.session.scalars(select(CustomProductStatusHistory).where(CustomProductStatusHistory.custom_product_id == custom.id)
                                    .order_by(CustomProductStatusHistory.occurred_at, CustomProductStatusHistory.id)))
    users = user_refs(uow, [r.actor_user_id for r in rows])
    return [
        CustomHistoryRead(id=r.id, action=CustomHistoryAction(r.action), from_status=r.from_status, to_status=r.to_status,
                          reason=r.reason, actor=users.get(r.actor_user_id) if r.actor_user_id else None, quote_id=r.quote_id,
                          occurred_at=r.occurred_at)
        for r in rows
    ]


@query("sales.custom_product.export")
def export_custom_products_csv(uow: UnitOfWork, filters: CustomProductFilters, *, include_costing: bool = False) -> bytes:
    """The custom-product list as CSV within the actor's export scope. Costing columns appear only for actors holding
    ``pricing.cost.read`` who ask for them (``include_costing``); the read is audited."""
    stmt = uow.repo(CustomProduct).select("export", include_archived=filters.include_archived).where(*_conditions(uow, filters))
    rows = list(uow.session.scalars(stmt.order_by(CustomProduct.custom_code)))
    with_cost = include_costing and uow.actor.can(COST_READ)
    costs: dict[uuid.UUID, CustomProductCosting] = {}
    if with_cost and rows:
        for row in uow.session.scalars(
            select(CustomProductCosting).where(CustomProductCosting.custom_product_id.in_([r.id for r in rows]))
            .order_by(CustomProductCosting.custom_product_id, CustomProductCosting.cost_version)
        ):
            costs[row.custom_product_id] = row
        uow.audit("sales.custom_product.costing_exported", resource_type="sales.custom_product",
                  restricted_fields=["cost_amount"], details={"rows": len(costs)})
    users = user_refs(uow, [r.owner_user_id for r in rows])
    party_ids = [r.party_id for r in rows if r.party_id]
    refs = party_refs(uow, party_ids, {}) if party_ids else {}
    cats = dict(uow.session.execute(select(Category.id, Category.name).where(Category.id.in_({r.category_id for r in rows if r.category_id}))).all()) if rows else {}
    headers = list(CSV_COLUMNS) + (["Cost", "Cost currency", "Cost version"] if with_cost else [])
    data = []
    for r in rows:
        customer = refs[r.party_id].display_name if r.party_id in refs else r.legacy_customer_name
        row = [
            r.custom_code, r.custom_type, r.product_name, r.status, customer, r.inquiry_reference, r.base_product_key,
            cats.get(r.category_id) if r.category_id else None, r.dimensions_text,
            r.thickness_text or (format(r.thickness_mm.normalize(), "f") if r.thickness_mm is not None else None), r.decor_no, r.decor_name,
            r.finish, r.shape, r.groove_count, r.bowl_count, r.handle_type, r.packaging_notes, r.quoted_price, r.quoted_currency,
            r.remarks, users[r.owner_user_id].display_name if r.owner_user_id in users else None, r.created_at.date(), r.updated_at.date(),
        ]
        if with_cost:
            cost = costs.get(r.id)
            row += [cost.cost_amount if cost else None, cost.cost_currency if cost else None, cost.cost_version if cost else None]
        data.append(row)
    uow.audit("sales.custom_product.exported", resource_type="sales.custom_product", details={"rows": len(data), "costing": with_cost})
    return write_csv(headers, data)


# ---- HTTP command wrappers ------------------------------------------------------------------------------
def create_command(uow: UnitOfWork, data: CustomProductCreate) -> tuple[CustomProductDetail, bool]:
    uow.actor.require("sales.custom_product.create")
    return idempotent(uow, "sales.create_custom_product", data, lambda: detail(uow, create_custom_product(uow, data)), CustomProductDetail, status=201)


def duplicate_command(uow: UnitOfWork, custom_id: uuid.UUID) -> tuple[CustomProductDetail, bool]:
    uow.actor.require("sales.custom_product.create")
    uow.repo(CustomProduct).get(custom_id)
    return idempotent(uow, f"sales.duplicate_custom_product:{custom_id}", {}, lambda: detail(uow, duplicate_custom_product(uow, custom_id)),
                      CustomProductDetail, status=201)


__all__ = [
    "PROMOTION_HANDLER",
    "advance_on_issue",
    "archive_custom_product",
    "create_command",
    "create_custom_product",
    "custom_history",
    "custom_status_counts",
    "decide_spec_revision",
    "detail",
    "duplicate_command",
    "duplicate_custom_product",
    "execute_promotion",
    "export_custom_products_csv",
    "get_custom_product",
    "list_costing",
    "list_custom_products",
    "record_costing",
    "record_spec_revision",
    "request_promotion",
    "transition_custom_product",
    "unarchive_custom_product",
    "update_custom_product",
]

