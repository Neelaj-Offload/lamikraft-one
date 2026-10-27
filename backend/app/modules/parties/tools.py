"""Agent tools for parties (thin descriptors over the same services the UI uses)."""

from __future__ import annotations

from pydantic import BaseModel

from app.modules.parties import service
from app.modules.parties.schemas import PartyResolution, ResolvePartyInput
from app.platform.tools import ToolDef
from app.platform.uow import UnitOfWork


def _resolve_party(uow: UnitOfWork, data: BaseModel) -> PartyResolution:
    assert isinstance(data, ResolvePartyInput)
    return service.resolve_party(uow, data.query, role=data.party_role, country_code=data.country_code)


RESOLVE_PARTY = ToolDef(
    name="resolve_party",
    group="Sales",
    description=(
        "Find the customer, vendor or other party the user means, within the user's own access. Returns "
        "status unique (one party), ambiguous (ask the user to choose; never pick) or not_found."
    ),
    input_model=ResolvePartyInput,
    output_model=PartyResolution,
    handler=_resolve_party,
    effect="read",
    permission="parties.party.read",
)

TOOLS = [RESOLVE_PARTY]
