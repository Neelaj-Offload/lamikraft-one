"""SCN-B4 (Slice-1 part): a snooze is per user and server-side, so it survives a reload and a channel switch
(web, then the WhatsApp channel actor); the WhatsApp summary itself is Slice 3."""

from __future__ import annotations

import pytest

from app.modules.briefings import service
from app.modules.briefings.schemas import ItemActionRequest
from app.platform.uow import UnitOfWork
from app.seed.world import keys
from tests.integration.briefings.world import FakeWorld, d0

pytestmark = pytest.mark.db


def test_snooze_reload_and_whatsapp_sync(world: FakeWorld) -> None:
    with UnitOfWork(world.actor(keys.USERS.MEERA, channel="web")) as uow:
        view = service.get_today(uow)
        target = next(i for i in view.items if any(a.action == "snooze" for a in i.allowed_actions))
        service.run_item_action(uow, target.issue_id, ItemActionRequest(action="snooze", until=d0(11, 0)))
    for channel in ("web", "whatsapp"):  # a reload on the web, then the same person on another channel
        with UnitOfWork(world.actor(keys.USERS.MEERA, channel=channel)) as uow:
            again = service.get_today(uow)
        assert target.issue_id not in {i.issue_id for i in again.items}
        (snoozed,) = [i for i in again.snoozed if i.issue_id == target.issue_id]
        assert snoozed.state.snoozed_until == d0(11, 0)
    with UnitOfWork(world.actor(keys.USERS.NEHA)) as uow:  # per user: nobody else's view changes
        assert all(i.issue_id != target.issue_id for i in service.get_today(uow).snoozed)
