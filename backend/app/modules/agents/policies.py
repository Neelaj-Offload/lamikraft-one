"""Conversation scope: own only (owner = user). Turns, runs, steps, object context and call-log rows are children.

The frozen permission catalogue has no ``agents.conversation.*`` keys: the API is gated by ``agents.assistant.use``
(company scope for every employee). Because that key has no ``own`` scope, the generic scope clause cannot
express "own conversations only"; :class:`OwnOnlyPolicy` maps every action to ``agents.assistant.use`` so the
registry and ``uow.repo`` accept the models, and the service additionally filters every read by the owner
(``service.own_conversation``), which is what produces the 404 for another user's conversation or run.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.modules.agents.models import AiCallLog, Conversation, ObjectContext, Run, RunStep, Turn
from app.platform.authz.policy import ParentRef, ResourcePolicy

ASSISTANT_USE = "agents.assistant.use"


@dataclass(frozen=True)
class OwnOnlyPolicy(ResourcePolicy):
    """Every action needs the one catalogued key; the owner filter is applied by the service."""

    def permission(self, action: str) -> str:  # noqa: ARG002 - the key does not vary by action
        return ASSISTANT_USE


CONVERSATION_POLICY = OwnOnlyPolicy(
    resource_type="agents.conversation",
    model=Conversation,
    permission_prefix="agents.assistant",
    owner_columns=("user_id",),
    label=lambda c: c.title or "Conversation",
    canonical_path=lambda c: f"/assistant/conversations/{c.id}",
    archived_column=None,
)

TURN_POLICY = ResourcePolicy(
    resource_type="agents.turn",
    model=Turn,
    permission_prefix="agents.assistant",
    parent=ParentRef("agents.conversation", "conversation_id"),
    archived_column=None,
)
RUN_POLICY = ResourcePolicy(
    resource_type="agents.run",
    model=Run,
    permission_prefix="agents.assistant",
    parent=ParentRef("agents.conversation", "conversation_id"),
    archived_column=None,
)
RUN_STEP_POLICY = ResourcePolicy(
    resource_type="agents.run_step",
    model=RunStep,
    permission_prefix="agents.assistant",
    parent=ParentRef("agents.run", "run_id"),
    archived_column=None,
)
OBJECT_CONTEXT_POLICY = ResourcePolicy(
    resource_type="agents.object_context",
    model=ObjectContext,
    permission_prefix="agents.assistant",
    parent=ParentRef("agents.run", "run_id"),
    archived_column=None,
)
AI_CALL_LOG_POLICY = ResourcePolicy(
    resource_type="agents.ai_call_log",
    model=AiCallLog,
    permission_prefix="agents.assistant",
    parent=ParentRef("agents.run", "run_id"),
    archived_column=None,
)

POLICIES = [
    CONVERSATION_POLICY,
    TURN_POLICY,
    RUN_POLICY,
    RUN_STEP_POLICY,
    OBJECT_CONTEXT_POLICY,
    AI_CALL_LOG_POLICY,
]
