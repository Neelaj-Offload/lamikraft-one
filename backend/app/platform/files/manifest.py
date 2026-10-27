from app.platform.manifest import ModuleManifest


def _router():  # type: ignore[no-untyped-def]
    from app.platform.files.router import router

    return router


MANIFEST = ModuleManifest(name="files", models=("app.platform.files.models",), routers=[_router])
