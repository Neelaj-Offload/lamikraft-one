"""Imports module manifest: the import workbench and the catalogue price bridge."""

from __future__ import annotations

from app.platform.manifest import ModuleManifest


def _on_load() -> None:
    from app.modules.catalogue.service import register_price_presence
    from app.modules.imports.bridges import price_presence

    register_price_presence(price_presence)


MANIFEST = ModuleManifest(name="imports", models=("app.modules.imports.models",), on_load=_on_load)
