"""Samples sent to customers (``SMP-YYYY-NNNN``) with lineage to quotes, custom products and spec revisions.

Lifecycle: ``requested -> dispatched -> delivered -> feedback_received -> closed``; ``cancel`` before dispatch, ``close``
from any later state. A dispatch records a courier reference or the delivery challan that carried the sample (the
``challans.challan.issued`` subscription ``sales.sample_dispatch`` dispatches a sample automatically when its challan is
issued). Feedback on a custom-product sample is copied onto the linked spec revision so the sample history and the
specification history stay together (LP-08.5).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import ColumnElement, func, or_, select

from app.core.db.base import new_id
from app.core.errors import InvalidTransition, ValidationFailed
from app.core.http.pagination import MAX_LIMIT, Page
from app.core.money import quantize_quantity
from app.core.text import LIKE_ESCAPE, contains_pattern, tokens
from app.modules.catalogue import service as catalogue
from app.modules.catalogue.schemas import quantity_entry_problem
from app.modules.sales import events as ev
from app.modules.sales.common import (
    Errors,
    business_date,
    check_member,
    company_zone,
    idempotent,
    party_ref,
    party_refs,
    user_ref,
    user_refs,
)
from app.modules.sales.models import CustomProduct, CustomProductSpecRevision, Quote, Sample
from app.modules.sales.schemas import (
    Capability,
    DeliveryEvidence,
    FeedbackOutcome,
    SampleCreate,
    SampleFilters,
    SampleRead,
    SampleStatus,
    SampleTransition,
    SampleUpdate,
    TransitionRead,
)
from app.platform.service import query
from app.platform.uow import UnitOfWork

READ = "sales.sample.read"
SS = SampleStatus
#: action -> (from statuses, to status, required fields)
SAMPLE_TRANSITIONS: dict[str, tuple[frozenset[str], str]] = {
    "dispatch": (frozenset({SS.REQUESTED.value}), SS.DISPATCHED.value),
    "deliver": (frozenset({SS.DISPATCHED.value}), SS.DELIVERED.value),
    "record_feedback": (frozenset({SS.DELIVERED.value, SS.FEEDBACK_RECEIVED.value}), SS.FEEDBACK_RECEIVED.value),
    "close": (frozenset({SS.DISPATCHED.value, SS.DELIVERED.value, SS.FEEDBACK_RECEIVED.value}), SS.CLOSED.value),
    "cancel": (frozenset({SS.REQUESTED.value}), SS.CANCELLED.value),
}


BACKFILL_REFERENCE = "Sent before Lamikraft One"


def _noon(uow: UnitOfWork, day: date) -> datetime:
    """A business date entered for history becomes noon that day in the company zone (no time-of-day guess)."""
    return datetime.combine(day, time(12), ZoneInfo(company_zone(uow)))


def _step_floor(sample: Sample, action: str) -> date | None:
    """The earliest date a step may carry: never before the step it follows."""
    if action == "dispatch":
        return sample.requested_on
    if action == "deliver":
        return sample.dispatched_at.date() if sample.dispatched_at else sample.requested_on
    if action == "record_feedback":
        last = sample.delivered_at or sample.dispatched_at
        return last.date() if last else sample.requested_on
    return None


def sample_path(sample_id: uuid.UUID) -> str:
    return f"/sales/samples/{sample_id}"


def create_sample(uow: UnitOfWork, data: SampleCreate, *, origin: str | None = None) -> Sample:
    actor = uow.actor
    actor.require("sales.sample.create")
    errors = Errors()
    party = party_ref(uow, data.party_id)
    owner = data.owner_user_id or actor.user_id
    assert owner is not None
    check_member(uow, owner, errors, "owner_user_id")
    description = data.description
    quote = uow.repo(Quote).get(data.quote_id) if data.quote_id else None  # lineage only to records the actor can see
    if quote is not None and quote.party_id != party.id:
        errors.add(["quote_id"], "quote_of_other_party", "The quote belongs to another customer")
    custom = uow.repo(CustomProduct).get(data.custom_product_id) if data.custom_product_id else None
    if data.spec_revision_id is not None:
        spec = uow.session.get(CustomProductSpecRevision, data.spec_revision_id)
        if spec is None or custom is None or spec.custom_product_id != custom.id:
            errors.add(["spec_revision_id"], "spec_revision_not_of_product", "The spec revision belongs to another custom product")
    product = catalogue.get_product_ref(uow, product_id=data.product_id) if data.product_id else None
    if description is None:
        description = (custom.product_name if custom else None) or (product.product_name if product else None)  # type: ignore[union-attr]
    if not description:
        errors.add(["description"], "required", "Describe the sample (or link a product or custom product)")
    qty = quantize_quantity(data.quantity)
    if (problem := quantity_entry_problem(qty, data.unit_code)) is not None:
        errors.add(["quantity"], problem[0], problem[1])
    today = business_date(uow)
    if data.sent_on is not None and data.sent_on > today:
        errors.add(["sent_on"], "sent_on_in_future", "A sample already sent needs today's date or an earlier one")
    if data.sent_on is None and data.dispatch_reference:
        errors.add(["dispatch_reference"], "reference_without_sent_on", "Give the date it was sent, or dispatch it later")
    errors.raise_if_any()
    sample = Sample(
        id=new_id(), company_id=actor.company_id, party_id=party.id, owner_user_id=owner,
        branch_id=data.branch_id or party.branch_id or (sorted(actor.branch_ids)[0] if actor.branch_ids else None),
        quote_id=quote.id if quote else None, custom_product_id=custom.id if custom else None,
        spec_revision_id=data.spec_revision_id, product_id=product.id if product else None, description=description,
        quantity=qty, unit_code=data.unit_code, status=SS.REQUESTED.value, requested_on=data.sent_on or today, notes=data.notes,
    )
    if data.sent_on is not None:  # history: recorded as already dispatched on that date
        sample.status = SS.DISPATCHED.value
        sample.dispatched_at = _noon(uow, data.sent_on)
        sample.dispatch_reference = data.dispatch_reference or BACKFILL_REFERENCE
    sample.sample_number = uow.allocate_number(ev.SAMPLE_SEQUENCE.key, document_date=business_date(uow),
                                               resource_type="sales.sample", resource_id=sample.id)
    uow.add(sample)
    uow.flush()
    uow.emit(ev.SAMPLE_CREATED, aggregate_id=sample.id, aggregate_version=sample.version,
             payload=ev.payload(ev.SampleCreatedPayload(sample_id=sample.id, sample_number=sample.sample_number, party_id=party.id,
                                                        owner_user_id=owner, origin=origin)))
    if data.sent_on is not None:
        uow.emit(ev.SAMPLE_DISPATCHED, aggregate_id=sample.id, aggregate_version=sample.version,
                 payload=ev.payload(ev.SampleDispatchedPayload(sample_id=sample.id, challan_id=None, origin="backfill")))
    uow.audit("sales.sample.created", resource_type="sales.sample", resource_id=sample.id, resource_label=sample.sample_number,
              details={"sent_on": data.sent_on.isoformat()} if data.sent_on else None)
    return sample


def update_sample(uow: UnitOfWork, sample_id: uuid.UUID, data: SampleUpdate) -> Sample:
    sample = uow.repo(Sample).get(sample_id, "update", for_update=True)
    uow.expect_version(sample, data.expected_version)
    sent = data.model_fields_set - {"expected_version"}
    changed = []
    for name in sorted(sent):
        value = getattr(data, name)
        if name == "quantity" and value is not None:
            if sample.status != SS.REQUESTED.value:
                raise ValidationFailed("The quantity is fixed once the sample is dispatched",
                                       errors=[{"loc": ["body", "quantity"], "msg": "dispatched", "code": "sample_dispatched"}])
            value = quantize_quantity(value)
        if value is None and name in ("description", "quantity"):
            continue
        if getattr(sample, name) != value:
            setattr(sample, name, value)
            changed.append(name)
    if changed:
        sample.updated_at = uow.now()
        uow.flush()
        uow.audit("sales.sample.updated", resource_type="sales.sample", resource_id=sample.id, resource_label=sample.sample_number,
                  details={"changed_fields": changed})
    return sample


def allowed_sample_transitions(uow: UnitOfWork, sample: Sample) -> list[TransitionRead]:
    if not uow.repo(Sample).can(sample, "transition"):
        return []
    return [
        TransitionRead(action=action, to_status=to, requires_reason=action == "cancel")
        for action, (frm, to) in SAMPLE_TRANSITIONS.items()
        if sample.status in frm
    ]


def transition_sample(uow: UnitOfWork, sample_id: uuid.UUID, data: SampleTransition, *, origin: str | None = None) -> Sample:
    repo = uow.repo(Sample)
    sample = repo.get(sample_id, for_update=True)
    spec = SAMPLE_TRANSITIONS[data.action]
    if sample.status not in spec[0]:
        raise InvalidTransition(f"{data.action} is not allowed while the sample is {sample.status}",
                                allowed_transitions=[t.model_dump() for t in allowed_sample_transitions(uow, sample)],
                                current_status=sample.status)
    repo.require_action(sample, "transition")
    uow.expect_version(sample, data.expected_version)
    errors = Errors()
    if data.action == "dispatch" and not (data.dispatch_reference or data.challan_id):
        errors.add(["dispatch_reference"], "dispatch_reference_required", "Give a courier reference or the delivery challan")
    if data.action == "deliver" and data.evidence_kind is None:
        errors.add(["evidence_kind"], "evidence_required", "How do we know it arrived?")
    if data.action == "record_feedback" and (data.feedback_outcome is None or not data.feedback):
        errors.add(["feedback"], "feedback_required", "Record the customer's feedback and its outcome")
    if data.action == "cancel" and not data.reason:
        errors.add(["reason"], "reason_required", "Cancelling a sample needs a reason")
    if data.occurred_on is not None:
        floor = _step_floor(sample, data.action)
        if data.action not in ("dispatch", "deliver", "record_feedback"):
            errors.add(["occurred_on"], "occurred_on_not_allowed", "Only dispatch, delivery and feedback take a date")
        elif data.occurred_on > business_date(uow):
            errors.add(["occurred_on"], "occurred_on_in_future", "Pick today or an earlier date")
        elif floor is not None and data.occurred_on < floor:
            errors.add(["occurred_on"], "occurred_on_before_previous_step",
                       f"Pick {floor.isoformat()} or later: the step before happened then")
    errors.raise_if_any()
    if data.action == "dispatch" and data.challan_id is not None:
        from app.modules.sales.sample_lineage import checked_challan

        uow.actor.require("challans.challan.read")
        checked_challan(uow, sample, data.challan_id)  # visible, same customer, outbound, not cancelled
    now = uow.now()
    at = _noon(uow, data.occurred_on) if data.occurred_on is not None else now
    event: tuple[str, Any] | None = None
    if data.action == "dispatch":
        sample.dispatched_at = at
        sample.dispatch_reference = data.dispatch_reference
        sample.challan_id = data.challan_id
        event = (ev.SAMPLE_DISPATCHED, ev.SampleDispatchedPayload(sample_id=sample.id, challan_id=data.challan_id, origin=origin))
    elif data.action == "deliver":
        sample.delivered_at = at
        sample.delivery_evidence_kind = data.evidence_kind.value  # type: ignore[union-attr]
        event = (ev.SAMPLE_DELIVERED, ev.SampleDeliveredPayload(sample_id=sample.id, evidence_kind=sample.delivery_evidence_kind, origin=origin))
    elif data.action == "record_feedback":
        sample.feedback = data.feedback
        sample.feedback_outcome = data.feedback_outcome.value  # type: ignore[union-attr]
        sample.feedback_at = at
        if sample.spec_revision_id is not None:
            rev = uow.session.get(CustomProductSpecRevision, sample.spec_revision_id)
            if rev is not None and rev.outcome == "pending":
                rev.feedback = data.feedback
        event = (ev.SAMPLE_FEEDBACK_RECORDED, ev.SamplePayload(sample_id=sample.id, origin=origin))
    elif data.action in ("close", "cancel"):
        sample.closed_at = now
        sample.close_reason = data.reason
        if data.action == "close":
            event = (ev.SAMPLE_CLOSED, ev.SamplePayload(sample_id=sample.id, origin=origin))
    from_status = sample.status
    sample.status = spec[1]
    sample.updated_at = now
    uow.flush()
    if event is not None:
        uow.emit(event[0], aggregate_id=sample.id, aggregate_version=sample.version, payload=ev.payload(event[1]))
    uow.audit(f"sales.sample.{data.action}", resource_type="sales.sample", resource_id=sample.id, resource_label=sample.sample_number,
              reason=data.reason, details={"from_status": from_status, "to_status": sample.status})
    return sample


def dispatch_by_challan(uow: UnitOfWork, sample_id: uuid.UUID, challan_id: uuid.UUID, *, at: Any = None) -> bool:
    """``sales.sample_dispatch``: a challan carrying the sample was issued (idempotent; only from ``requested``).
    ``at`` is the dispatch time (the challan's issue time when an issued challan is linked later; now otherwise)."""
    sample = uow.session.scalars(select(Sample).where(Sample.id == sample_id, Sample.company_id == uow.actor.company_id).with_for_update()).first()
    if sample is None or sample.status != SS.REQUESTED.value:
        return False
    sample.status = SS.DISPATCHED.value
    sample.dispatched_at = at or uow.now()
    sample.challan_id = challan_id
    sample.updated_at = uow.now()
    uow.flush()
    uow.emit(ev.SAMPLE_DISPATCHED, aggregate_id=sample.id, aggregate_version=sample.version,
             payload=ev.payload(ev.SampleDispatchedPayload(sample_id=sample.id, challan_id=challan_id)))
    return True


# =====================================================================================================
# reads
# =====================================================================================================
def _conditions(f: SampleFilters) -> list[ColumnElement[bool]]:
    conds: list[ColumnElement[bool]] = []
    for tok in tokens(f.q or ""):
        pattern = contains_pattern(tok)
        conds.append(or_(Sample.sample_number.ilike(pattern, escape=LIKE_ESCAPE), Sample.description.ilike(pattern, escape=LIKE_ESCAPE),
                         Sample.dispatch_reference.ilike(pattern, escape=LIKE_ESCAPE)))
    if f.status:
        conds.append(Sample.status.in_([s.value for s in f.status]))
    if f.party_id:
        conds.append(Sample.party_id == f.party_id)
    if f.quote_id:
        conds.append(Sample.quote_id == f.quote_id)
    if f.custom_product_id:
        conds.append(Sample.custom_product_id == f.custom_product_id)
    return conds


def _link_capability(uow: UnitOfWork, sample: Sample, update: dict[str, Any]) -> dict[str, Any]:
    """Linking a delivery challan: ``update`` on the sample, still requested, and challan read access."""
    if not update.get("allowed"):
        return {"allowed": False, "reason_code": update.get("reason_code") or "permission_denied"}
    if sample.status != SS.REQUESTED.value:
        return {"allowed": False, "reason_code": "sample_not_requested"}
    if not uow.actor.can("challans.challan.read"):
        return {"allowed": False, "reason_code": "permission_denied"}
    return {"allowed": True, "reason_code": None}


def _reads(uow: UnitOfWork, rows: Sequence[Sample]) -> list[SampleRead]:
    if not rows:
        return []
    users = user_refs(uow, [r.owner_user_id for r in rows])
    refs = party_refs(uow, [r.party_id for r in rows], {})
    quote_ids = [r.quote_id for r in rows if r.quote_id]
    visible_quotes = dict(uow.session.execute(
        select(Quote.id, Quote.quote_number).where(Quote.id.in_(quote_ids), Quote.id.in_(uow.repo(Quote).visible_ids()))
    ).all()) if quote_ids else {}
    custom_ids = [r.custom_product_id for r in rows if r.custom_product_id]
    codes = dict(uow.session.execute(
        select(CustomProduct.id, CustomProduct.custom_code).where(CustomProduct.id.in_(custom_ids),
                                                                  CustomProduct.id.in_(uow.repo(CustomProduct).visible_ids()))
    ).all()) if custom_ids else {}
    out = []
    for r in rows:
        caps = uow.repo(Sample).capabilities(r, ["update", "transition"])
        caps["link_challan"] = _link_capability(uow, r, caps["update"])
        out.append(SampleRead(
            id=r.id, sample_number=r.sample_number, party=refs[r.party_id], owner=users.get(r.owner_user_id) or user_ref(uow, r.owner_user_id),  # type: ignore[arg-type]
            quote_id=r.quote_id, quote_number=visible_quotes.get(r.quote_id) if r.quote_id else None,
            custom_product_id=r.custom_product_id, custom_code=codes.get(r.custom_product_id) if r.custom_product_id else None,
            spec_revision_id=r.spec_revision_id, product_id=r.product_id, description=r.description, quantity=r.quantity,
            unit_code=r.unit_code, status=SampleStatus(r.status), requested_on=r.requested_on, dispatched_at=r.dispatched_at,
            dispatch_reference=r.dispatch_reference, challan_id=r.challan_id, delivered_at=r.delivered_at,
            delivery_evidence_kind=DeliveryEvidence(r.delivery_evidence_kind) if r.delivery_evidence_kind else None,
            feedback=r.feedback, feedback_outcome=FeedbackOutcome(r.feedback_outcome) if r.feedback_outcome else None,
            feedback_at=r.feedback_at, closed_at=r.closed_at, close_reason=r.close_reason, notes=r.notes, branch_id=r.branch_id,
            created_at=r.created_at, updated_at=r.updated_at, version=r.version, path=sample_path(r.id),
            capabilities={k: Capability(**v) for k, v in caps.items()},
            allowed_transitions=allowed_sample_transitions(uow, r),
        ))
    return out


@query(READ)
def list_samples(uow: UnitOfWork, filters: SampleFilters, *, limit: int = 50, offset: int = 0) -> Page[SampleRead]:
    page = uow.repo(Sample).list(*_conditions(filters), order_by=[Sample.created_at.desc(), Sample.id.desc()],
                                 limit=max(1, min(limit, MAX_LIMIT)), offset=max(0, offset))
    return Page[SampleRead](items=_reads(uow, page.items), total=page.total, limit=page.limit, offset=page.offset)


@query(READ)
def sample_status_counts(uow: UnitOfWork, filters: SampleFilters) -> dict[str, int]:
    f = filters.model_copy(update={"status": None})
    stmt = uow.repo(Sample).select().where(*_conditions(f)).with_only_columns(Sample.status, func.count(Sample.id)).group_by(Sample.status)
    counts = {s.value: 0 for s in SampleStatus}
    for status, n in uow.session.execute(stmt).all():
        counts[status] = int(n)
    return counts


@query(READ)
def get_sample(uow: UnitOfWork, sample_id: uuid.UUID) -> SampleRead:
    return _reads(uow, [uow.repo(Sample).get(sample_id)])[0]


def read(uow: UnitOfWork, sample: Sample) -> SampleRead:
    return _reads(uow, [sample])[0]


def create_command(uow: UnitOfWork, data: SampleCreate) -> tuple[SampleRead, bool]:
    uow.actor.require("sales.sample.create")
    return idempotent(uow, "sales.create_sample", data, lambda: read(uow, create_sample(uow, data)), SampleRead, status=201)


def transition_command(uow: UnitOfWork, sample_id: uuid.UUID, data: SampleTransition) -> tuple[SampleRead, bool]:
    uow.repo(Sample).get(sample_id)
    return idempotent(uow, f"sales.transition_sample:{sample_id}", data, lambda: read(uow, transition_sample(uow, sample_id, data)), SampleRead)
