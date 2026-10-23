from app.platform.manifest import ModuleManifest
from app.platform.search.people import PEOPLE_PROVIDER


def _router():  # type: ignore[no-untyped-def]
    from app.platform.search.router import router

    return router


MANIFEST = ModuleManifest(
    name="search",
    models=("app.platform.search.models",),
    routers=[_router],
    search_providers=[PEOPLE_PROVIDER],
)
