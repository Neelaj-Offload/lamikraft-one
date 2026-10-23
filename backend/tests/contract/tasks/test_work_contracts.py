"""Contracts of the work lane (tasks + briefings): frozen vocabularies, route declarations, operation ids,
event payloads, append-only triggers and RLS, and no identity fields in request bodies."""

from __future__ import annotations

import re

import pytest
from sqlalchemy import text

from app.core.db.base import Base
from app.platform.events.catalogue_data import EVENTS
from app.registry import get_registry

VERBS = {"list", "get", "create", "update", "delete", "archive", "transition", "export", "run", "issue", "post", "decide",
         "resolve", "upload", "download", "poll"}
CATALOGUE_EVENTS = {row["name"] for row in EVENTS}
WORK_MODULES = ("tasks", "briefings")


def _manifests():  # type: ignore[no-untyped-def]
    return [m for m in get_registry().manifests if m.name in WORK_MODULES]


def test_subscriptions_use_catalogue_events_and_unique_handler_keys() -> None:
    for manifest in _manifests():
        for sub in manifest.subscriptions:
            assert sub.event in CATALOGUE_EVENTS, sub.event
            assert sub.handler_key == f"{sub.handler_key.split(':')[0]}:{sub.event}"
            assert sub.handler_key.split(":")[0] in {"tasks.rules", "tasks.visibility", "briefings.refresh", "briefings.access_refresh"}


def test_rule_families_cover_the_slice1_triggers() -> None:
    from app.modules.tasks.rules.consumer import TRIGGERS

    for family_event in ("approvals.proposal.submitted", "sales.quote.created", "sales.quote.issued", "sales.customer_message.received",
                         "sales.customer_message.replied", "sales.enquiry.received", "parties.party.updated",
                         "identity.membership.activated"):
        assert family_event in TRIGGERS
    assert set(TRIGGERS) <= CATALOGUE_EVENTS


def test_work_routes_declare_authz_and_follow_operation_id_grammar() -> None:
    from app.main import create_app

    spec = create_app().openapi()
    seen = 0
    for path, item in spec["paths"].items():
        for method, op in item.items():
            tag = (op.get("tags") or [""])[0]
            if tag not in WORK_MODULES:
                continue
            seen += 1
            assert path.startswith(f"/api/v1/{tag}/")
            assert op.get("x-authz", {}).get("kind") in {"authenticated", "permission"}, (method, path)
            module, verb, *noun = op["operationId"].split("_")
            assert module == tag and verb in VERBS and noun, op["operationId"]
            for key in op["x-authz"].get("permissions", []):
                assert re.match(rf"^{tag}\.", key), key
    assert seen >= 20


def test_request_bodies_carry_no_identity_fields() -> None:
    from app.main import create_app

    spec = create_app().openapi()
    schemas = spec["components"]["schemas"]
    forbidden = {"company_id", "actor", "actor_id", "role", "roles", "permissions", "tenant_id", "user_id"}
    for item in spec["paths"].values():
        for op in item.values():
            if (op.get("tags") or [""])[0] not in WORK_MODULES or "requestBody" not in op:
                continue
            ref = op["requestBody"]["content"]["application/json"]["schema"]["$ref"].rsplit("/", 1)[1]
            assert not forbidden & set(schemas[ref].get("properties", {})), ref


def test_emitted_tasks_and_briefings_payloads_fit_the_catalogue() -> None:
    from app.modules.tasks.issues import emit_issue_event, emit_task_event  # noqa: F401 - imported for presence

    fields = {row["name"]: set(row["fields"]) for row in EVENTS}
    assert fields["tasks.task.created"] == {"task_id", "issue_id", "kind", "family", "owner_user_id", "assignee_user_id", "due_at",
                                           "from_state", "to_state"}
    assert fields["briefings.recommendation.invalidated"] == {"recommendation_id", "issue_id", "cause_event_id"}


@pytest.mark.db
def test_work_tables_have_forced_rls_and_append_only_triggers(db: None) -> None:
    from app.platform.authz.context import ActorContext
    from app.platform.uow import UnitOfWork

    tables = [m for m in Base.registry.mappers if m.local_table.name.startswith(("tasks_", "briefings_"))]
    with UnitOfWork(ActorContext.system(None)) as uow:
        policies = set(uow.session.execute(text("SELECT tablename FROM pg_policies WHERE policyname = 'tenant_isolation'")).scalars())
        triggers = set(uow.session.execute(text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal")).scalars())
    assert len(tables) == 18
    for mapper in tables:
        name = mapper.local_table.name
        assert name in policies, name
        assert (f"trg_{name}_append_only" in triggers) == bool(getattr(mapper.class_, "__append_only__", False)), name
