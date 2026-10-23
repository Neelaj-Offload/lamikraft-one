from app.platform.manifest import ModuleManifest

MANIFEST = ModuleManifest(
    name="org", models=("app.platform.org.models", "app.platform.org.workcal", "app.platform.org.teams")
)
