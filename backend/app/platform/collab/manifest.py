from app.platform.manifest import ModuleManifest


def _router():  # type: ignore[no-untyped-def]
    from app.platform.collab.router import router

    return router


MANIFEST = ModuleManifest(name="collab", models=("app.platform.collab.models",), routers=[_router])
