"""Source reader ``orders.sales_order`` for tasks, briefings and the agent: ids, number, party, status, fulfilment
state and dates (no amounts). Visibility follows the resource policy (an invisible order reads as ``None``)."""

from __future__ import annotations

import uuid

from app.core.errors import NotFound
from app.modules.orders.models import SalesOrder
from app.modules.orders.service import READ, order_path
from app.platform.sources import SourceFacts
from app.platform.uow import UnitOfWork

CLOSED = frozenset({"completed", "cancelled"})


def read_order_facts(uow: UnitOfWork, order_id: uuid.UUID) -> SourceFacts | None:
    try:
        o = uow.repo(SalesOrder).get(order_id)
    except NotFound:
        return None
    return SourceFacts(
        source_type="orders.sales_order",
        source_id=o.id,
        version=o.version,
        label=f"{o.order_number} · {o.party_name}",
        status=o.status,
        owner_user_id=o.owner_user_id,
        branch_id=o.branch_id,
        required_permission=READ,
        canonical_path=order_path(o.id),
        is_closed=o.status in CLOSED,
        updated_at=o.updated_at,
        facts={
            "order_number": o.order_number,
            "party_name": o.party_name,
            "quote_number": o.quote_number,
            "fulfilment_state": o.fulfilment_state,
            "order_date": o.order_date.isoformat(),
            "requested_delivery_date": o.requested_delivery_date.isoformat()
            if o.requested_delivery_date
            else None,
        },
    )


READERS = {"orders.sales_order": read_order_facts}
