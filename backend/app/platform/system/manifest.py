from app.platform.manifest import ModuleManifest


def _router():  # type: ignore[no-untyped-def]
    from app.platform.system.router import router

    return router


MANIFEST = ModuleManifest(name="system", routers=[_router])
