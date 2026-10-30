"""Platform collaboration: internal notes (Slice 1), attachments and activity (Slice 2)."""
from app.platform.manifest import ModuleManifest


def _router():  # type: ignore[no-untyped-def]
    from app.platform.collab.router import router

    return router


def _on_load() -> None:
    from app.platform.collab.attachments import attachment_file_access
    from app.platform.files.access import register_file_access

    register_file_access("collab.attachment", attachment_file_access)


MANIFEST = ModuleManifest(name="collab", models=("app.platform.collab.models",), routers=[_router], on_load=_on_load)
