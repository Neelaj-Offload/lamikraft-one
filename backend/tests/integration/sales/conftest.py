"""Fixtures for the sales lane's tests: personas, the catalogue world, the full sales world at D0 and the HTTP client."""

from tests.integration.catalogue.world import member_actors, personas  # noqa: F401
from tests.integration.sales.http import api_app, sales_client  # noqa: F401
from tests.integration.sales.world import sales_world, world  # noqa: F401
