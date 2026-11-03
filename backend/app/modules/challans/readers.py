"""Source reader ``challans.challan`` for tasks, briefings and the agent (``app.platform.sources``).

Exposes ids, the number, type, destination, status, dates and quantities as display facts; never the internal
note. Visibility follows the resource policy (an invisible challan reads as ``None``). The ``expected_return``
deadline (end of the expected return day in the company zone) is what the ``ops.returnables`` rule family keys on.
"""

from __future__ import annotations

import uuid
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.core.errors import NotFound
from app.modules.challans import service
from app.modules.challans.common import challan_path, company_zone
from app.modules.challans.models import Challan
from app.modules.challans.schemas import (
    DESTINATION_LABELS,
    TYPE_LABELS,
    ChallanStatus,
    ChallanType,
    DestinationType,
)
from app.platform.sources import SourceFacts
from app.platform.uow import UnitOfWork

UTC = ZoneInfo("UTC")
CLOSED = frozenset({ChallanStatus.CLOSED.value, ChallanStatus.CANCELLED.value})


def read_challan_facts(uow: UnitOfWork, challan_id: uuid.UUID) -> SourceFacts | None:
    try:
        c = uow.repo(Challan).get(challan_id, include_archived=True)
    except NotFound:
        return None
    if c.deleted_at is not None:
        return None
    zone = company_zone(uow)
    lines = service.lines_of(uow, c)
    deadlines: dict[str, datetime] = {}
    if c.status == ChallanStatus.ISSUED.value and c.expected_return_date is not None:
        deadlines["expected_return"] = datetime.combine(
            c.expected_return_date + timedelta(days=1), time(0, 0), tzinfo=ZoneInfo(zone)
        ).astimezone(UTC)
    outstanding = service.outstanding_by_unit(c, lines)
    return SourceFacts(
        source_type="challans.challan",
        source_id=c.id,
        version=c.version,
        label=f"{c.challan_number} · {c.destination_party}",
        status=c.status,
        owner_user_id=c.owner_user_id,
        branch_id=c.branch_id,
        required_permission=service.READ,
        canonical_path=challan_path(c.id),
        is_closed=c.status in CLOSED,
        updated_at=c.updated_at,
        deadlines=deadlines,
        facts={
            "challan_number": c.challan_number,
            "challan_type": TYPE_LABELS[ChallanType(c.challan_type)],
            "return_type": c.return_type,
            "destination_type": DESTINATION_LABELS[DestinationType(c.destination_type)],
            "destination_party": c.destination_party,
            "party_id": str(c.party_id) if c.party_id else None,
            "challan_date": c.challan_date.isoformat(),
            "expected_return_date": c.expected_return_date.isoformat() if c.expected_return_date else None,
            "line_count": str(c.line_count),
            "quantity_by_unit": {u: format(q, "f") for u, q in service.quantity_by_unit(lines).items()},
            "outstanding_by_unit": {u: format(q, "f") for u, q in outstanding.items()},
            "inventory_effect": c.inventory_effect,
        },
    )


READERS = {"challans.challan": read_challan_facts}
