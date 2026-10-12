from app.platform.authz.catalogue import permission_defs, template_grants
from app.platform.manifest import ModuleManifest

MANIFEST = ModuleManifest(name="authz", permissions=permission_defs(), template_grants=template_grants())
