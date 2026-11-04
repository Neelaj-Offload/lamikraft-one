"""Source reader ``quality.inspection`` for tasks and briefings: number, subject, product, warehouse and status
(quantities as display strings in the inspected unit; no costs)."""

from __future__ import annotations

import uuid

from app.core.errors import NotFound
from app.modules.quality.models import Inspection
from app.platform.sources import SourceFacts
from app.platform.uow import UnitOfWork


def read_inspection_facts(uow: UnitOfWork, inspection_id: uuid.UUID) -> SourceFacts | None:
    try:
        insp = uow.repo(Inspection).get(inspection_id)
    except NotFound:
        return None
    from app.modules.inventory.reads import product_refs, warehouse_refs
    from app.modules.procurement.common import plain

    p = product_refs(uow, [insp.product_id])[insp.product_id]
    w = warehouse_refs(uow, [insp.warehouse_id])[insp.warehouse_id]
    return SourceFacts(
        source_type="quality.inspection",
        source_id=insp.id,
        version=insp.version,
        label=f"{insp.inspection_number} · {p.product_key}",
        status=insp.status,
        owner_user_id=None,
        branch_id=insp.branch_id,
        required_permission="quality.inspection.read",
        canonical_path=f"/operations/quality/{insp.id}",
        is_closed=insp.status != "pending",
        updated_at=insp.updated_at,
        facts={
            "inspection_number": insp.inspection_number,
            "subject_label": insp.subject_label,
            "subject_type": insp.subject_type,
            "product_key": p.product_key,
            "warehouse_code": w.code,
            "quantity": f"{plain(insp.quantity)} {insp.uom_code}",
        },
    )


READERS = {"quality.inspection": read_inspection_facts}
