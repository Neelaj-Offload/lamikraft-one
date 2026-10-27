"""SCN-B2: replayed events and immaterial changes create no version."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.modules.tasks.models import ChangeLog
from app.platform.events.models import DomainEvent
from app.seed.world import keys
from tests.integration.briefings.test_versions_and_actions import (
    current_version,
    today,
)
from tests.integration.briefings.world import FakeWorld

pytestmark = pytest.mark.db


def test_replay_and_immaterial_change_create_no_version(world: FakeWorld) -> None:
    v1 = today(world, keys.USERS.MEERA)
    with world.uow() as uow:
        changes_before = uow.session.scalar(select(func.count()).select_from(ChangeLog))
        received = uow.session.scalars(select(DomainEvent).where(
            DomainEvent.event_type == "sales.customer_message.received", DomainEvent.aggregate_id == world.refs[keys.MESSAGES.BERG])).one()
        uow.enqueue("event.handle", {"event_id": str(received.id), "handler": "tasks.rules:sales.customer_message.received"},
                    dedupe_key=f"replay:{received.id}")
    world.drain()
    world.change_quote("Q_BERG_EXPIRING")  # an internal-notes edit: new version, same material facts
    world.emit_quote(keys.USERS.MEERA, "sales.quote.updated", "Q_BERG_EXPIRING",
                     version=world.quotes["Q_BERG_EXPIRING"].version, changed_fields=["notes"], line_change_kinds=[])
    world.drain()
    assert current_version(world, v1.briefing_id) == 1  # type: ignore[arg-type]
    with world.uow() as uow:
        assert uow.session.scalar(select(func.count()).select_from(ChangeLog)) == changes_before
