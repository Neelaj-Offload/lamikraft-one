"""Shared read-model types for what the caller may do next (api-conventions: capabilities and transitions).

Detail responses carry ``capabilities: {action: Capability}`` (server-decided, so the UI never renders a dead
control) and ``allowed_transitions: [TransitionRead]`` for status machines. One definition for every module, so
the OpenAPI document has a single ``Capability`` and ``TransitionRead`` schema.
"""

from __future__ import annotations

from pydantic import BaseModel


class Capability(BaseModel):
    allowed: bool
    #: why not, when ``allowed`` is false (e.g. ``permission_denied``, ``archived``, ``not_owner``)
    reason_code: str | None = None


class TransitionRead(BaseModel):
    action: str
    to_status: str
    requires_reason: bool
