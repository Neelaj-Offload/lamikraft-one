from app.platform.manifest import ModuleManifest
from app.platform.org.settings import BUILTIN_SETTINGS
from app.seed.context import SeedContext, SeedDef


def _router():  # type: ignore[no-untyped-def]
    from app.platform.org.router import build_router

    return build_router()


def _seed_org(ctx: SeedContext) -> None:
    from app.seed.world.org import seed_org

    seed_org(ctx)


def _on_load() -> None:
    from app.platform.files.access import register_file_access
    from app.platform.org.files_access import company_logo_access

    register_file_access("org.setting", company_logo_access)


MANIFEST = ModuleManifest(
    name="org",
    models=("app.platform.org.models", "app.platform.org.workcal"),
    settings=list(BUILTIN_SETTINGS),
    routers=[_router],
    seeds=[SeedDef(name="org.reference_calendar_settings", order=12, run=_seed_org)],
    on_load=_on_load,
)
