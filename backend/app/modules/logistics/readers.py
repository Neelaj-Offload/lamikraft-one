"""Source readers ``logistics.shipment`` (number, party, status, the cutoff as a deadline and its company-local label)
and ``logistics.packing_list`` for tasks and briefings (no quantities beyond display strings)."""

from __future__ import annotations

import uuid

from app.core.errors import NotFound
from app.modules.logistics.models import PackingList, Shipment
from app.platform.sources import SourceFacts
from app.platform.uow import UnitOfWork

OPEN = frozenset({"planned", "booked", "dispatched", "in_transit", "exception"})


def read_shipment_facts(uow: UnitOfWork, shipment_id: uuid.UUID) -> SourceFacts | None:
    try:
        sh = uow.repo(Shipment).get(shipment_id)
    except NotFound:
        return None
    from app.modules.logistics.shipments import _cutoff_local

    return SourceFacts(
        source_type="logistics.shipment",
        source_id=sh.id,
        version=sh.version,
        label=f"{sh.shipment_number} · {sh.party_name}",
        status=sh.status,
        owner_user_id=sh.owner_user_id,
        branch_id=sh.branch_id,
        required_permission="logistics.shipment.read",
        canonical_path=f"/operations/dispatch/shipments/{sh.id}",
        is_closed=sh.status not in OPEN,
        updated_at=sh.updated_at,
        deadlines={"cutoff_at": sh.cutoff_at} if sh.cutoff_at else {},
        facts={
            "shipment_number": sh.shipment_number,
            "party_name": sh.party_name,
            "mode": sh.mode,
            "cutoff_local": _cutoff_local(uow, sh.cutoff_at),
            "exception_code": sh.exception_code,
        },
    )


def read_packing_list_facts(uow: UnitOfWork, pl_id: uuid.UUID) -> SourceFacts | None:
    try:
        pl = uow.repo(PackingList).get(pl_id)
    except NotFound:
        return None
    return SourceFacts(
        source_type="logistics.packing_list",
        source_id=pl.id,
        version=pl.version,
        label=f"{pl.packing_list_number} · {pl.party_name}",
        status=pl.status,
        owner_user_id=pl.owner_user_id,
        branch_id=pl.branch_id,
        required_permission="logistics.packing_list.read",
        canonical_path=f"/operations/dispatch/packing-lists/{pl.id}",
        is_closed=pl.status != "draft",
        updated_at=pl.updated_at,
        facts={
            "packing_list_number": pl.packing_list_number,
            "is_stale": pl.is_stale,
            "totals_partial": pl.totals_partial,
        },
    )


READERS = {"logistics.shipment": read_shipment_facts, "logistics.packing_list": read_packing_list_facts}
