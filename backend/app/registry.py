"""Installed modules and startup cross-validation.

Integrator-owned: lanes add exactly one line per new module to ``INSTALLED_MODULES``.
Validation failures stop the application from starting (fail fast, never at runtime).
"""

from __future__ import annotations

import importlib
import importlib.util
import threading
from dataclasses import dataclass, field
from typing import Any

from app.platform.authz.permissions import PermissionDef, Scope
from app.platform.authz.policy import ResourcePolicy, register_policy
from app.platform.events.defs import EventDef, Subscription
from app.platform.jobs.defs import JobDef, ScheduleDef
from app.platform.manifest import ModuleManifest
from app.platform.numbering.defs import SequenceDef

PLATFORM_MODULES: tuple[str, ...] = (
    "app.platform.org",
    "app.platform.identity",
    "app.platform.events",
    "app.platform.jobs",
    "app.platform.numbering",
    "app.platform.idempotency",
    "app.platform.audit",
    "app.platform.system",
)


def discover_domain_modules() -> tuple[str, ...]:
    """Every package under app/modules with a manifest.py is a domain module (sorted, stable).

    ``LK_DOMAIN_MODULES`` (comma list, dev/test only) restricts discovery so parallel lanes can test
    their own modules while another lane's work is mid-edit.
    """
    import os
    import pkgutil

    import app.modules as modules_pkg

    found = sorted(
        f"app.modules.{m.name}"
        for m in pkgutil.iter_modules(modules_pkg.__path__)
        if m.ispkg and importlib.util.find_spec(f"app.modules.{m.name}.manifest") is not None
    )
    only = os.environ.get("LK_DOMAIN_MODULES")
    if only:
        wanted = {f"app.modules.{n.strip()}" for n in only.split(",") if n.strip()}
        found = [m for m in found if m in wanted]
    return tuple(found)


def installed_modules() -> tuple[str, ...]:
    return PLATFORM_MODULES + discover_domain_modules()


INSTALLED_MODULES = PLATFORM_MODULES  # kept for import compatibility; use installed_modules()


class RegistryError(RuntimeError):
    pass


@dataclass
class Registry:
    manifests: list[ModuleManifest] = field(default_factory=list)
    permissions: dict[str, PermissionDef] = field(default_factory=dict)
    template_grants: dict[str, dict[str, Scope]] = field(default_factory=dict)
    events: dict[str, EventDef] = field(default_factory=dict)
    subscriptions: dict[str, list[Subscription]] = field(default_factory=dict)
    handlers: dict[str, Subscription] = field(default_factory=dict)
    jobs: dict[str, JobDef] = field(default_factory=dict)
    schedules: dict[str, ScheduleDef] = field(default_factory=dict)
    sequences: dict[str, SequenceDef] = field(default_factory=dict)
    policies: dict[str, ResourcePolicy] = field(default_factory=dict)
    tools: list[Any] = field(default_factory=list)
    settings: list[Any] = field(default_factory=list)
    search_providers: list[Any] = field(default_factory=list)

    def routers(self) -> list[Any]:
        out: list[Any] = []
        for manifest in self.manifests:
            for factory in manifest.routers:
                out.append(factory())
        return out

    def legacy_alias_map(self) -> dict[str, list[str]]:
        mapping: dict[str, list[str]] = {}
        for perm in self.permissions.values():
            for alias in perm.legacy_aliases:
                mapping.setdefault(alias, []).append(perm.key)
        return {k: sorted(v) for k, v in sorted(mapping.items())}


_lock = threading.Lock()
_registry: Registry | None = None


def _load_manifest(module_path: str) -> ModuleManifest:
    mod = importlib.import_module(f"{module_path}.manifest")
    manifest = getattr(mod, "MANIFEST", None)
    if not isinstance(manifest, ModuleManifest):
        raise RegistryError(f"{module_path}.manifest must define MANIFEST: ModuleManifest")
    for models_path in manifest.models:
        importlib.import_module(models_path)
    return manifest


def build_registry(modules: tuple[str, ...] | None = None) -> Registry:
    modules = modules or installed_modules()
    reg = Registry()
    errors: list[str] = []
    for path in modules:
        manifest = _load_manifest(path)
        reg.manifests.append(manifest)
        for perm in manifest.permissions:
            if perm.key in reg.permissions:
                errors.append(f"duplicate permission {perm.key} ({manifest.name})")
            reg.permissions[perm.key] = perm
        for template, grants in manifest.template_grants.items():
            reg.template_grants.setdefault(template, {})
            for key, scope in grants.items():
                current = reg.template_grants[template].get(key)
                reg.template_grants[template][key] = max(scope, current) if current else scope
        for event in manifest.events:
            if event.name in reg.events:
                errors.append(f"duplicate event {event.name} ({manifest.name})")
            reg.events[event.name] = event
        for sub in manifest.subscriptions:
            if sub.handler_key in reg.handlers:
                errors.append(f"duplicate handler key {sub.handler_key}")
            reg.handlers[sub.handler_key] = sub
            reg.subscriptions.setdefault(sub.event, []).append(sub)
        for job in manifest.jobs:
            if job.kind in reg.jobs:
                errors.append(f"duplicate job kind {job.kind}")
            reg.jobs[job.kind] = job
        for sched in manifest.schedules:
            if sched.schedule_key in reg.schedules:
                errors.append(f"duplicate schedule {sched.schedule_key}")
            reg.schedules[sched.schedule_key] = sched
        for seq in manifest.sequences:
            if seq.key in reg.sequences:
                errors.append(f"duplicate sequence {seq.key}")
            reg.sequences[seq.key] = seq
        for policy in manifest.policies:
            if policy.resource_type in reg.policies:
                errors.append(f"duplicate resource policy {policy.resource_type}")
            reg.policies[policy.resource_type] = policy
        reg.tools.extend(manifest.tools)
        reg.settings.extend(manifest.settings)
        reg.search_providers.extend(manifest.search_providers)

    # ---- cross validation ------------------------------------------------------------------
    for template, grants in reg.template_grants.items():
        for key, scope in grants.items():
            perm = reg.permissions.get(key)
            if perm is None:
                errors.append(f"template {template} grants unknown permission {key}")
            elif scope not in perm.scopes:
                errors.append(f"template {template} grants {key} at {scope.label}, allowed {[s.label for s in perm.scopes]}")
    for event_name in reg.subscriptions:
        if event_name not in reg.events:
            errors.append(f"subscription to unregistered event {event_name}")
    for sched in reg.schedules.values():
        if sched.kind not in reg.jobs:
            errors.append(f"schedule {sched.schedule_key} references unknown job kind {sched.kind}")
    for policy in reg.policies.values():
        if policy.parent and policy.parent.resource_type not in reg.policies:
            errors.append(f"policy {policy.resource_type} has unknown parent {policy.parent.resource_type}")
        if not policy.parent:
            for action in ("read",):
                key = policy.permission(action)
                if key not in reg.permissions:
                    errors.append(f"policy {policy.resource_type} needs permission {key}")
    if "event.handle" not in reg.jobs:
        errors.append("platform job kind event.handle must be registered")
    if errors:
        raise RegistryError("registry validation failed:\n  - " + "\n  - ".join(errors))

    for policy in reg.policies.values():
        register_policy(policy)
    for manifest in reg.manifests:
        if manifest.on_load:
            manifest.on_load()
    return reg


def get_registry() -> Registry:
    global _registry
    with _lock:
        if _registry is None:
            _registry = build_registry()
        return _registry


def reset_registry() -> None:
    global _registry
    with _lock:
        _registry = None
