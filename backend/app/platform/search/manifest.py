from app.platform.manifest import ModuleManifest
from app.platform.search.people import PEOPLE_PROVIDER


def _router():  # type: ignore[no-untyped-def]
    from app.platform.search.router import router

    return router


def _on_load() -> None:
    from app.platform.search.service import read_recent_search_facts
    from app.platform.sources import register_reader

    register_reader("search.recent", read_recent_search_facts)


MANIFEST = ModuleManifest(
    name="search",
    models=("app.platform.search.models",),
    routers=[_router],
    search_providers=[PEOPLE_PROVIDER],
    on_load=_on_load,
)
