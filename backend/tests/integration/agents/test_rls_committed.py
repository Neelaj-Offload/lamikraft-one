"""Row-level security on the agents tables with real commits: a second tenant's GUC sees nothing of the first, no
GUC sees nothing, and the append-only triggers reject updates on run steps and the AI call log."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import text

from app.modules.agents import service
from app.modules.agents.cards import RecordLinkCard
from app.modules.agents.models import Run
from app.modules.agents.schemas import ConversationCreate, TurnCreate
from app.platform.authz.context import ActorContext
from app.platform.uow import UnitOfWork
from app.seed.world import keys
from tests.integration.catalogue.world import World, build_personas, member_actors  # noqa: F401
from tests.support import create_company

pytestmark = [pytest.mark.db, pytest.mark.committed]


@pytest.fixture
def committed_world(committed_db: str, member_actors: None) -> Iterator[World]:  # noqa: F811
    yield build_personas()


def _count(uow: UnitOfWork, table: str) -> int:
    return int(uow.session.execute(text(f"SELECT count(*) FROM {table}")).scalar() or 0)


def test_agents_tables_are_tenant_isolated_and_append_only(committed_world: World) -> None:
    meera = committed_world.actor(keys.USERS.MEERA)
    with UnitOfWork(meera) as uow:
        conversation = service.create_conversation(uow, ConversationCreate())
        accepted = service.create_turn(uow, conversation.id, TurnCreate(text="go to quotes"))
    with UnitOfWork(meera) as uow:
        run = uow.session.get(Run, accepted.run_id)
        assert run is not None
        service.append_step(uow, run, kind="route", name="grammar", output={"kind": "navigate"}, model_route="grammar")
        service.log_call(uow, run, step_seq=1, response=None, task_class="orchestration", model="demo")
        service.finish_run(uow, run, status="succeeded", text="Demo: opening quotes.",
                           cards=[RecordLinkCard(label="Quotes", path="/sales/quotes")])
    other_company, _ = create_company()
    tables = ("agents_conversation", "agents_turn", "agents_run", "agents_run_step", "agents_ai_call_log")
    with UnitOfWork(ActorContext.system(committed_world.company_id)) as uow:
        assert [_count(uow, t) for t in tables] == [1, 2, 1, 1, 1]
    with UnitOfWork(ActorContext.system(other_company)) as uow:
        assert [_count(uow, t) for t in tables] == [0, 0, 0, 0, 0]
    with UnitOfWork(ActorContext.system(None)) as uow:
        assert [_count(uow, t) for t in tables] == [0, 0, 0, 0, 0], "no tenant GUC: fail closed"
    for table in ("agents_run_step", "agents_ai_call_log"):
        with pytest.raises(Exception, match="append-only|permission denied"):
            with UnitOfWork(ActorContext.system(committed_world.company_id)) as uow:
                uow.session.execute(text(f"UPDATE {table} SET created_at = created_at"))
    with UnitOfWork(ActorContext.system(committed_world.company_id)) as uow:
        assert uow.session.execute(text("SELECT count(*) FROM domain_event WHERE event_type = 'agents.run.completed'")).scalar() == 1


def test_cross_tenant_read_through_the_service_is_404(committed_world: World) -> None:
    meera = committed_world.actor(keys.USERS.MEERA)
    with UnitOfWork(meera) as uow:
        conversation_id = service.create_conversation(uow, ConversationCreate()).id
    stranger = ActorContext(actor_type="user", company_id=create_company()[0], user_id=uuid.uuid7(),
                            permissions=meera.permissions, channel="test")
    from app.core.errors import NotFound

    with pytest.raises(NotFound):
        with UnitOfWork(stranger) as uow:
            service.own_conversation(uow, conversation_id)
