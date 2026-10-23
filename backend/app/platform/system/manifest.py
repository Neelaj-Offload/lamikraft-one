from app.platform.manifest import ModuleManifest


def _router():  # type: ignore[no-untyped-def]
    from app.platform.system.router import router

    return router


def _integrations_router():  # type: ignore[no-untyped-def]
    from app.platform.system.integrations_router import router

    return router


def _on_load() -> None:
    from app.platform.bootstrap import UiSection, register_ui_section
    from app.platform.system.service import ui_section

    register_ui_section(UiSection(key="integrations", build=ui_section, in_poll=False))


MANIFEST = ModuleManifest(
    name="system",
    models=("app.platform.system.models",),
    routers=[_router, _integrations_router],
    on_load=_on_load,
)
