"""Subscriptions of the tasks module (events come from the frozen catalogue; tasks.* defs are registered
by the platform events catalogue). Handler keys are unique per subscription: ``tasks.rules:<event>``.
"""

from __future__ import annotations

from app.modules.tasks.rules.consumer import TRIGGERS
from app.platform.events.defs import Subscription
from app.platform.events.models import DomainEvent
from app.platform.uow import UnitOfWork

RULES_HANDLER = "tasks.rules"
VISIBILITY_HANDLER = "tasks.visibility"
VISIBILITY_EVENTS = ("identity.membership.access_changed", "identity.permission_override.changed")


def _rules(uow: UnitOfWork, event: DomainEvent) -> None:
    from app.modules.tasks.rules.consumer import handle

    handle(uow, event)


def _visibility(uow: UnitOfWork, event: DomainEvent) -> None:
    """Access changed: re-check approval eligibility and scope attributes in a consistency job."""
    uow.enqueue(
        "tasks.visibility_consistency",
        {"cause_event_id": str(event.id)},
        dedupe_key=f"tasks.visibility:{event.id}",
        resource_type="identity.membership",
        resource_id=event.aggregate_id,
    )


SUBSCRIPTIONS: list[Subscription] = [
    Subscription(event=name, handler_key=f"{RULES_HANDLER}:{name}", handler=_rules) for name in sorted(TRIGGERS)
] + [
    Subscription(event=name, handler_key=f"{VISIBILITY_HANDLER}:{name}", handler=_visibility) for name in VISIBILITY_EVENTS
]
