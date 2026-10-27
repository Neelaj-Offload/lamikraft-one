"""Sales module manifest: models, policies, sequences (API, tools, document job, readers and seeds are wired in
as they land). Permissions and events come from the frozen catalogues (registered centrally by the
``authz``/``events`` manifests); this module only names them."""

from __future__ import annotations

from app.modules.sales.events import ENQUIRY_SEQUENCE, QUOTE_SEQUENCE
from app.modules.sales.policies import POLICIES
from app.platform.manifest import ModuleManifest

MANIFEST = ModuleManifest(
    name="sales",
    models=("app.modules.sales.models",),
    policies=list(POLICIES),
    sequences=[QUOTE_SEQUENCE, ENQUIRY_SEQUENCE],
)
