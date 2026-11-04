"""Opening balances: an authorised stock count staged as its own batch, approved by a second person, posted by the
inventory module.

Legacy challans never create stock (they are documents only); stock starts from an approved opening batch. This lane
builds the staging and reconciliation side: ``stage_batch`` stores the dry run's accepted lines (and the quarantined
ones, marked) with totals by unit; ``approve_batch`` records the approval (``migration.apply.execute``, never the
person who staged it); ``post_batch`` hands the approved lines to the poster the inventory module registers with
``register_opening_poster`` (Slice 4). Until then posting is refused with ``inventory_module_unavailable``.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Callable, Sequence
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.core.errors import Conflict, NotFound, ServiceUnavailable, VersionConflict
from app.modules.migration.analysis import Analysis, field_text
from app.modules.migration.documents import money
from app.modules.migration.models import OpeningBatch, OpeningLine, OpeningLineStatus, OpeningStatus
from app.platform.authz.context import ActorContext
from app.platform.authz.permissions import Scope
from app.platform.service import command
from app.platform.uow import UnitOfWork

APPLY = "migration.apply.execute"

#: (uow, batch, valid lines) -> posting reference; registered by the inventory module
OpeningPoster = Callable[[UnitOfWork, OpeningBatch, Sequence[OpeningLine]], str]
_poster: OpeningPoster | None = None


def register_opening_poster(poster: OpeningPoster | None) -> None:
    global _poster
    _poster = poster


def poster_available() -> bool:
    return _poster is not None


def stage_batch(actor: ActorContext, an: Analysis, run_id: uuid.UUID) -> uuid.UUID | None:
    """Store the dry run's opening-balance rows as a staged batch (None when the export has none)."""
    from app.modules.catalogue.models import Product

    rows = an.source.rows("opening_balances")
    if not rows:
        return None
    with UnitOfWork(actor) as uow:
        uow.actor.require(APPLY, Scope.COMPANY)
        ids = {k: i for k, i in uow.session.execute(select(Product.product_key, Product.id))}
        accepted = {acc.row.row_number for acc in an.accepted["opening_balances"].values()}
        quarantined_codes = {f.row_number: f.code for f in an.findings
                             if f.entity == "opening_balances" and f.severity == "quarantine"}
        rejected = {f.row_number for f in an.findings if f.entity == "opening_balances" and f.severity == "error"}
        batch = uow.add(OpeningBatch(run_id=run_id, status=OpeningStatus.STAGED.value, source_digest=an.source.digest))
        uow.flush()
        totals: dict[str, Decimal] = defaultdict(Decimal)
        valid = quarantined = 0
        for row in rows:
            qty = money(row.values, "quantity", [])
            pk = field_text(row.values, "product_key")
            loc = field_text(row.values, "location_code", "location", "warehouse")
            uom = (field_text(row.values, "uom", "uom_code", "unit") or "").upper()
            if row.row_number in rejected or qty is None or not pk or not loc or not uom:
                continue  # rejected rows stay in the quarantine report only
            ok = row.row_number in accepted
            uow.add(OpeningLine(
                batch_id=batch.id, row_number=row.row_number, product_key=pk[:200], product_id=ids.get(pk),
                location_code=loc[:80], quantity=qty, uom_code=uom[:20], unit_cost=money(row.values, "unit_cost", []),
                cost_currency=(field_text(row.values, "cost_currency") or None),
                status=OpeningLineStatus.VALID.value if ok else OpeningLineStatus.QUARANTINED.value,
                issue_code=None if ok else quarantined_codes.get(row.row_number),
            ))
            if ok:
                valid += 1
                totals[uom] += qty
            else:
                quarantined += 1
        batch.line_count = valid
        batch.quarantined_count = quarantined
        batch.totals = {k: format(v.normalize(), "f") for k, v in sorted(totals.items())}
        uow.audit("migration.opening_batch.staged", resource_type="migration.opening_batch", resource_id=batch.id,
                  details={"lines": valid, "quarantined": quarantined})
        return batch.id


def _batch(uow: UnitOfWork, batch_id: uuid.UUID, expected_version: int) -> OpeningBatch:
    batch = uow.session.get(OpeningBatch, batch_id, with_for_update=True)
    if batch is None:
        raise NotFound(code="opening_batch_not_found", resource_type="migration.opening_batch")
    if batch.version != expected_version:
        raise VersionConflict(current_version=batch.version)
    return batch


@command(APPLY, at_least=Scope.COMPANY)
def approve_batch(uow: UnitOfWork, batch_id: uuid.UUID, expected_version: int) -> dict[str, Any]:
    batch = _batch(uow, batch_id, expected_version)
    if batch.status != OpeningStatus.STAGED.value:
        raise Conflict(f"The batch is {batch.status}", code="opening_batch_not_staged")
    if uow.actor.user_id is None:
        raise Conflict("An opening batch is approved by a named person (run with --as)", code="approver_required")
    if batch.created_by is not None and batch.created_by == uow.actor.user_id:
        raise Conflict("The person who staged the batch cannot approve it", code="approver_is_stager")
    batch.status = OpeningStatus.APPROVED.value
    batch.approved_by = uow.actor.user_id
    batch.approved_at = uow.now()
    uow.flush()
    uow.audit("migration.opening_batch.approved", resource_type="migration.opening_batch", resource_id=batch.id,
              details={"lines": batch.line_count})
    return {"id": str(batch.id), "status": batch.status, "version": batch.version}


@command(APPLY, at_least=Scope.COMPANY)
def post_batch(uow: UnitOfWork, batch_id: uuid.UUID, expected_version: int) -> dict[str, Any]:
    batch = _batch(uow, batch_id, expected_version)
    if batch.status != OpeningStatus.APPROVED.value:
        raise Conflict(f"The batch is {batch.status}; approve it first", code="opening_batch_not_approved")
    if _poster is None:
        raise ServiceUnavailable("Opening stock is posted by the inventory module, which is not installed yet",
                                 code="inventory_module_unavailable")
    lines = list(uow.session.scalars(select(OpeningLine).where(
        OpeningLine.batch_id == batch.id, OpeningLine.status == OpeningLineStatus.VALID.value)))
    batch.posting_ref = _poster(uow, batch, lines)[:120]
    batch.status = OpeningStatus.POSTED.value
    batch.posted_at = uow.now()
    uow.flush()
    uow.audit("migration.opening_batch.posted", resource_type="migration.opening_batch", resource_id=batch.id,
              details={"posting_ref": batch.posting_ref})
    return {"id": str(batch.id), "status": batch.status, "posting_ref": batch.posting_ref}


__all__ = ["approve_batch", "post_batch", "poster_available", "register_opening_poster", "stage_batch"]
