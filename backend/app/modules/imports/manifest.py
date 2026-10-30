"""Imports module manifest."""

from __future__ import annotations

from app.platform.manifest import ModuleManifest

MANIFEST = ModuleManifest(name="imports", models=("app.modules.imports.models",))
