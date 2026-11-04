"""Sample lineage (Slice 5): the delivery challan that carries a sample, and the lineage view of a sample.

- **Challan link** (``POST /sales/samples/{id}/challan``): while a sample is ``requested`` its owner links the delivery
  challan that will carry it (``sales.sample.update`` on the sample; the challan must be visible to the actor, for the
  sample's customer, outbound (``sample`` or ``outward``) and not cancelled). Issuing the challan dispatches every
  requested sample linked to it (``sales.sample_dispatch`` on ``challans.challan.issued``: the event's ``sample_id``
  is still ``null`` because a challan has no sample column, so the subscription looks the samples up by challan).
  Linking a challan that is already issued (or closed) dispatches the sample at once with the challan's issue time.
- **Lineage** (``GET /sales/samples/{id}/lineage``): the custom product and spec revision, the quote, the challan,
  the catalogue product (the sample's own or the one the custom product was promoted to) and other samples of the
  same custom product, each through its own module's read scope (archived records included: archiving is not a scope
  change). A link to a record the actor cannot see is shown as ``not_visible`` without its identity; ``missing`` names links the sample does not have yet.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import select

from app.core.errors import Conflict, ValidationFailed
from app.modules.sales.models import (
    CustomProduct,
    CustomProductPromotion,
    CustomProductSpecRevision,
    Quote,
    Sample,
)
from app.modules.sales.schemas import (
    LineageEvent,
    LineageNode,
    SampleChallanLink,
    SampleLineage,
    SampleStatus,
)
from app.platform.uow import UnitOfWork

OUTBOUND_TYPES = frozenset({"sample", "outward"})
CHALLAN_READ = "challans.challan.read"


def _problem(code: str, msg: str) -> ValidationFailed:
    return ValidationFailed(msg, errors=[{"loc": ["body", "challan_id"], "msg": msg, "code": code}])


def checked_challan(uow: UnitOfWork, sample: Sample, challan_id: uuid.UUID) -> Any:
    """The challan when it may carry this sample: visible to the actor (404 otherwise, never confirming another
    branch's challan), for the sample's customer, outbound and not cancelled (422 with the reason)."""
    from app.modules.challans.models import Challan

    challan = uow.repo(Challan).get(challan_id)
    if challan.party_id != sample.party_id:
        raise _problem("challan_of_other_party", "The challan is for another customer")
    if challan.challan_type not in OUTBOUND_TYPES:
        raise _problem("challan_not_outbound", "Only a sample or outward challan can carry a sample")
    if challan.status == "cancelled":
        raise _problem("challan_cancelled", "The challan is cancelled")
    return challan


def link_challan(uow: UnitOfWork, sample_id: uuid.UUID, data: SampleChallanLink) -> Sample:
    from app.modules.sales.samples import dispatch_by_challan

    sample = uow.repo(Sample).get(sample_id, "update", for_update=True)
    uow.expect_version(sample, data.expected_version)
    if sample.status != SampleStatus.REQUESTED.value:
        raise Conflict(f"{sample.sample_number} is {sample.status}; the challan is fixed once the sample is dispatched",
                       code="sample_not_requested", current_status=sample.status)
    if data.challan_id is None:
        if sample.challan_id is None:
            return sample
        old = sample.challan_id
        sample.challan_id = None
        sample.updated_at = uow.now()
        uow.flush()
        uow.audit("sales.sample.challan_unlinked", resource_type="sales.sample", resource_id=sample.id,
                  resource_label=sample.sample_number, details={"challan_id": str(old)})
        return sample
    uow.actor.require(CHALLAN_READ)
    challan = checked_challan(uow, sample, data.challan_id)
    if sample.challan_id == challan.id:
        return sample
    sample.challan_id = challan.id
    sample.updated_at = uow.now()
    uow.flush()
    uow.audit("sales.sample.challan_linked", resource_type="sales.sample", resource_id=sample.id,
              resource_label=sample.sample_number,
              details={"challan_id": str(challan.id), "challan_number": challan.challan_number, "challan_status": challan.status})
    if challan.status in ("issued", "closed"):
        dispatch_by_challan(uow, sample.id, challan.id, at=challan.issued_at)
    return sample


def dispatch_linked_samples(uow: UnitOfWork, challan_id: uuid.UUID) -> list[uuid.UUID]:
    """``sales.sample_dispatch`` when the issued event names no sample: every requested sample linked to the challan
    (company-scoped; idempotent, a dispatched sample is skipped)."""
    from app.modules.sales.samples import dispatch_by_challan

    ids = list(uow.session.scalars(select(Sample.id).where(
        Sample.company_id == uow.actor.company_id, Sample.challan_id == challan_id,
        Sample.status == SampleStatus.REQUESTED.value).order_by(Sample.sample_number)))
    return [sid for sid in ids if dispatch_by_challan(uow, sid, challan_id)]


# =====================================================================================================
# lineage
# =====================================================================================================
#: lifecycle order for events at the same instant
_ORDER = ("custom_product_created", "spec_revision_recorded", "quote_issued", "sample_requested", "challan_issued",
          "sample_dispatched", "sample_delivered", "feedback_recorded", "sample_closed", "product_promoted")


def _hidden(kind: str) -> LineageNode:
    return LineageNode(kind=kind, state="not_visible")  # type: ignore[arg-type]


def _day(value: datetime | None) -> date | None:
    return value.date() if value is not None else None


def lineage(uow: UnitOfWork, sample_id: uuid.UUID) -> SampleLineage:
    from app.modules.catalogue import service as catalogue

    sample = uow.repo(Sample).get(sample_id)
    events: list[LineageEvent] = []

    def event(kind: str, label: str, at: datetime | None, on: date | None = None, ref: str | None = None) -> None:
        day = on or _day(at)
        if day is not None:
            events.append(LineageEvent(at=at, on=day, kind=kind, label=label, ref_kind=ref))  # type: ignore[arg-type]

    custom_node = spec_node = quote_node = challan_node = product_node = None
    related: list[LineageNode] = []
    custom: CustomProduct | None = None
    if sample.custom_product_id is not None:
        repo = uow.repo(CustomProduct)
        custom = uow.session.scalars(repo.select(include_archived=True).where(CustomProduct.id == sample.custom_product_id)).first()
        if custom is None:
            custom_node = _hidden("custom_product")
        else:
            custom_node = LineageNode(kind="custom_product", state="linked", id=custom.id, label=custom.custom_code,
                                      title=custom.product_name, status=custom.status,
                                      path=f"/sales/custom-products/{custom.id}")
            event("custom_product_created", f"{custom.custom_code} created", custom.created_at, ref="custom_product")
            others = uow.session.scalars(
                uow.repo(Sample).select(include_archived=True).where(Sample.custom_product_id == custom.id, Sample.id != sample.id)
                .order_by(Sample.created_at, Sample.id).limit(20))
            related = [LineageNode(kind="sample", state="linked", id=o.id, label=o.sample_number, title=o.description,
                                   status=o.status, path=f"/sales/samples/{o.id}") for o in others]
    if sample.spec_revision_id is not None:
        rev = uow.session.get(CustomProductSpecRevision, sample.spec_revision_id) if custom is not None else None
        if rev is None or rev.company_id != uow.actor.company_id:
            spec_node = _hidden("spec_revision")
        else:
            facts = {"outcome": rev.outcome}
            if rev.sample_reference:
                facts["sample_reference"] = rev.sample_reference
            spec_node = LineageNode(kind="spec_revision", state="linked", id=rev.id, label=f"Spec revision {rev.revision_no}",
                                    status=rev.outcome, path=f"/sales/custom-products/{custom.id}" if custom else None,
                                    facts=facts)
            event("spec_revision_recorded", f"Spec revision {rev.revision_no} recorded", rev.created_at, ref="spec_revision")
    if sample.quote_id is not None:
        quote = uow.session.scalars(uow.repo(Quote).select(include_archived=True).where(Quote.id == sample.quote_id)).first()
        if quote is None:
            quote_node = _hidden("quote")
        else:
            facts = {"currency": quote.currency} if getattr(quote, "currency", None) else {}
            if quote.revision_no:
                facts["revision"] = str(quote.revision_no)
            quote_node = LineageNode(kind="quote", state="linked", id=quote.id, label=quote.quote_number, status=quote.status,
                                     path=f"/sales/quotes/{quote.id}", facts=facts)
            if quote.issued_at is not None:
                event("quote_issued", f"{quote.quote_number} issued", quote.issued_at, ref="quote")
    if sample.challan_id is not None:
        challan_node = _challan_node(uow, sample.challan_id, event)
    product_id = sample.product_id or (custom.promoted_product_id if custom is not None else None)
    if product_id is not None:
        ref = catalogue.product_refs(uow, [product_id]).get(product_id)
        if ref is None:
            product_node = _hidden("product")
        else:
            facts = {"origin": "promoted"} if sample.product_id is None else {}
            product_node = LineageNode(kind="product", state="linked", id=ref.id, label=ref.display_sku,
                                       title=ref.product_name, status=ref.status, path=f"/products/{ref.id}", facts=facts)
        if custom is not None and custom.promoted_product_id is not None and sample.product_id is None:
            promoted_at = uow.session.scalar(select(CustomProductPromotion.executed_at).where(
                CustomProductPromotion.company_id == uow.actor.company_id,
                CustomProductPromotion.custom_product_id == custom.id,
                CustomProductPromotion.executed_product_id == custom.promoted_product_id))
            event("product_promoted", f"{custom.custom_code} promoted to the catalogue", promoted_at, ref="product")

    event("sample_requested", f"{sample.sample_number} requested", sample.created_at, on=sample.requested_on, ref="sample")
    via = f" on {challan_node.label}" if challan_node is not None and challan_node.label else ""
    ref_text = f" ({sample.dispatch_reference})" if sample.dispatch_reference else ""
    event("sample_dispatched", f"Dispatched{via}{ref_text}", sample.dispatched_at, ref="sample")
    event("sample_delivered", "Delivered", sample.delivered_at, ref="sample")
    event("feedback_recorded", "Feedback recorded", sample.feedback_at, ref="sample")
    if sample.status == SampleStatus.CLOSED.value:
        event("sample_closed", "Closed", sample.closed_at, ref="sample")
    events.sort(key=lambda e: (e.on, e.at.timestamp() if e.at is not None else 0.0, _ORDER.index(e.kind)))
    missing = [k for k, v in (("custom_product", sample.custom_product_id), ("quote", sample.quote_id),
                              ("challan", sample.challan_id)) if v is None]
    return SampleLineage(
        sample_id=sample.id, sample_number=sample.sample_number, status=SampleStatus(sample.status),
        custom_product=custom_node, spec_revision=spec_node, quote=quote_node, challan=challan_node, product=product_node,
        related_samples=related, timeline=events, missing=missing,  # type: ignore[arg-type]
    )


def _challan_node(uow: UnitOfWork, challan_id: uuid.UUID, event: Any) -> LineageNode:
    from app.modules.challans.models import Challan

    if not uow.actor.can(CHALLAN_READ):
        return _hidden("challan")
    challan = uow.session.scalars(uow.repo(Challan).select(include_archived=True).where(Challan.id == challan_id)).first()
    if challan is None:
        return _hidden("challan")
    facts = {"challan_type": challan.challan_type, "challan_date": challan.challan_date.isoformat()}
    if challan.issued_at is not None:
        event("challan_issued", f"{challan.challan_number} issued", challan.issued_at, ref="challan")
    return LineageNode(kind="challan", state="linked", id=challan.id, label=challan.challan_number, status=challan.status,
                       path=f"/operations/challans/{challan.id}", facts=facts)


def link_command(uow: UnitOfWork, sample_id: uuid.UUID, data: SampleChallanLink) -> tuple[Any, bool]:
    from app.modules.sales.common import idempotent
    from app.modules.sales.samples import read
    from app.modules.sales.schemas import SampleRead

    uow.repo(Sample).get(sample_id)
    return idempotent(uow, f"sales.link_sample_challan:{sample_id}", data, lambda: read(uow, link_challan(uow, sample_id, data)),
                      SampleRead)

