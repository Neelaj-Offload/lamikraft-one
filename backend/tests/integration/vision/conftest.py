"""Vision tests reuse the voice/agents fixtures (world, client, Meera, a throw-away storage root)."""

from __future__ import annotations

from tests.integration.agents.conftest import app, client, meera, sales_tools  # noqa: F401
from tests.integration.catalogue.world import media_storage, member_actors, personas, world  # noqa: F401
