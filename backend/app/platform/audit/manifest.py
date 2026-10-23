from app.platform.manifest import ModuleManifest


def _router():  # type: ignore[no-untyped-def]
    from app.platform.audit.router import router

    return router


MANIFEST = ModuleManifest(name="audit", models=("app.platform.audit.models",), routers=[_router])
