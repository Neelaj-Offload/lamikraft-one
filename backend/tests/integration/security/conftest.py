"""Fixtures for cross-cutting security tests: the sales world (personas, catalogue, pricing, sales seeds)."""

from tests.integration.catalogue.world import member_actors, personas  # noqa: F401
from tests.integration.sales.world import sales_world, world  # noqa: F401
