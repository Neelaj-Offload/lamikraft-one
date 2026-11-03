"""Agent tool of the challans module: ``draft_challan`` (a thin descriptor over the same service the UI uses).

Inputs never carry identity: the actor comes from the server-built context, the draft is owned by the user and
nothing is issued or moved. ``resolve_party`` and ``resolve_product`` (parties, catalogue) are reused for lookups.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel

from app.modules.catalogue import service as catalogue
from app.modules.challans import service
from app.modules.challans.common import idempotent
from app.modules.challans.schemas import (
    ChallanCreate,
    ChallanDetail,
    ChallanLineCreate,
    DraftChallanInput,
    LineType,
)
from app.platform.tools import ToolDef
from app.platform.uow import UnitOfWork


def draft_challan(
    uow: UnitOfWork, data: DraftChallanInput, *, origin: str | None = None, origin_ref: str | None = None
) -> ChallanDetail:
    """Create a draft owned by the actor; catalog lines take code, name, HSN/SAC and unit from the product."""
    lines: list[ChallanLineCreate] = []
    for ln in data.lines:
        product_id = ln.product_id
        if product_id is None and ln.product_key:
            product_id = catalogue.get_product_ref(uow, product_key=ln.product_key).id
        lines.append(
            ChallanLineCreate(
                line_type=LineType.CATALOG if product_id is not None else LineType.MANUAL,
                product_id=product_id,
                item_name=ln.item_name,
                quantity=Decimal(ln.quantity),
                unit=ln.unit,
                remarks=ln.remarks,
            )
        )
    challan = service.create_challan(
        uow,
        ChallanCreate(
            challan_type=data.challan_type,
            return_type=data.return_type,
            destination_type=data.destination_type,
            party_id=data.party_id,
            destination_party=data.destination_party,
            reference_no=data.reference_no,
            remarks=data.remarks,
            expected_return_date=data.expected_return_date,
            lines=lines,
        ),
        origin=origin,
        origin_ref=origin_ref,
    )
    return service.detail(uow, challan)


def _draft_challan(uow: UnitOfWork, data: BaseModel) -> ChallanDetail:
    """The tool runtime passes a per-step ``Idempotency-Key``: a retried step replays the first draft."""
    assert isinstance(data, DraftChallanInput)
    detail, _replayed = idempotent(
        uow, "challans.draft_challan", data, lambda: draft_challan(uow, data), ChallanDetail, status=201
    )
    return detail


DRAFT_CHALLAN = ToolDef(
    name="draft_challan",
    group="Warehouse",
    description=(
        "Create a draft delivery challan (Outward, Inward, Return, Job Work, Transfer or Sample; returnable or not) to a "
        "customer, fabricator, vendor, transporter, warehouse or office, with catalog or free-text lines. The draft is "
        "owned by the user, is not issued, moves no stock, and shows in their challan list for review."
    ),
    input_model=DraftChallanInput,
    output_model=ChallanDetail,
    handler=_draft_challan,
    effect="draft",
    permission="challans.challan.create",
    requires_idempotency=True,
)

TOOLS = [DRAFT_CHALLAN]
