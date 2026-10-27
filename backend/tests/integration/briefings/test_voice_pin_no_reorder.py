"""SCN-B3: an active spoken briefing never reorders; ordinals resolve against the pinned version."""

from __future__ import annotations

import uuid

import pytest

from app.modules.briefings import service
from app.modules.briefings.errors import PinEnded
from app.modules.briefings.schemas import PinCreate, PinUpdate
from app.modules.tasks import issue_keys
from app.seed.world import keys
from tests.integration.briefings.test_versions_and_actions import (
    issue,
    new_message,
    today,
)
from tests.integration.briefings.world import FakeWorld, d0

pytestmark = pytest.mark.db


def test_pinned_order_and_ordinal_resolution(world: FakeWorld) -> None:
    """B-05/B-06: pinned order is stable across a new version; approval shows in place; stop ends the pin."""
    v1 = today(world, keys.USERS.MEERA)
    with world.uow(keys.USERS.MEERA) as uow:
        pin = service.create_pin(uow, v1.briefing_id, PinCreate(kind="voice"))  # type: ignore[arg-type]
    second = uuid.UUID(pin.ordinal_map[1]["issue_id"])
    new_message(world, "MSG_MAISON_NEW", "MAISON", d0(9, 10))
    world.at(d0(9, 15))
    proposal_id = world.refs[keys.PROPOSALS.NORDHAUS]
    from app.modules.approvals import service as approvals

    with world.uow(keys.USERS.SAHIL) as uow:
        p = approvals.get(uow, proposal_id)
        approvals.decide(uow, proposal_id, decision="approve", content_hash_seen=p.content_hash, expected_version=p.version)
    world.drain()
    pinned = today(world, keys.USERS.MEERA)
    assert pinned.version == 1 and pinned.pin is not None and pinned.pin.pending_updates >= 1
    assert [i.issue_id for i in pinned.items] == [i.issue_id for i in v1.items]
    nordhaus = next(i for i in pinned.items if i.issue_id == issue(world, issue_keys.message_key(world.refs[keys.MESSAGES.NORDHAUS])))
    assert nordhaus.ordinal == 3 and nordhaus.blocked and nordhaus.state.blocked_now is False  # approved, shown in place
    with world.uow(keys.USERS.MEERA) as uow:
        resolved = service.resolve_pin(uow, pin.id, 2)
        assert resolved.issue_id == second and not resolved.resolved_since
        service.update_pin(uow, pin.id, PinUpdate(state="stopped"))
    after = today(world, keys.USERS.MEERA)
    assert after.pin is None and after.version == after.latest_version and after.version >= 2
    with world.uow(keys.USERS.MEERA) as uow, pytest.raises(PinEnded):
        service.resolve_pin(uow, pin.id, 2)
