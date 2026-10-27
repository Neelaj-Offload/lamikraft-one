"""Settings service: the only reader and writer of ``setting`` / ``setting_revision``.

Reads apply the definition's read permission and the field-guard registry (restricted sub-fields are nulled
and listed in ``redacted_fields``). Writes need the manage permission, every guard key of restricted
sub-fields and a recent authentication when the permission is RA-flagged; they validate the typed value,
check the optimistic version (409 ``version_conflict`` carrying the current redacted setting), append a
revision, write a masked audit entry and emit ``org.setting.updated``.
"""

from __future__ import annotations

import threading
import uuid
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ValidationError
from sqlalchemy import select

from app.core.errors import Forbidden, NotFound, ValidationFailed, VersionConflict
from app.platform.authz.redaction import redact
from app.platform.org.models import Branch, Setting, SettingRevision
from app.platform.org.schemas import Capability, SettingRead, SettingRevisionRead
from app.platform.org.settings import SettingDef, restricted_guards
from app.platform.org.stepup import require_recent_auth
from app.platform.service import command, query

if TYPE_CHECKING:
    from app.platform.uow import UnitOfWork

_defs_lock = threading.Lock()
_defs_cache: tuple[int, dict[str, SettingDef]] | None = None
#: advisory-lock namespace serialising, per company, every setting write whose definition has a ``validate``
#: hook (cross-setting invariants); taken before the per-key lock
VALIDATION_LOCK = "org.setting.validated"


# ---- definitions ------------------------------------------------------------------------------------------
def setting_defs() -> dict[str, SettingDef]:
    """Every registered SettingDef by key (validated once per registry instance)."""
    global _defs_cache
    from app.registry import get_registry

    registry = get_registry()
    with _defs_lock:
        if _defs_cache is not None and _defs_cache[0] == id(registry):
            return _defs_cache[1]
        defs: dict[str, SettingDef] = {}
        problems: list[str] = []
        for definition in registry.settings:
            if not isinstance(definition, SettingDef):
                problems.append(f"settings entry {definition!r} is not a SettingDef")
                continue
            if definition.key in defs:
                problems.append(f"duplicate setting key {definition.key}")
            for key in (definition.read_permission, definition.manage_permission, *definition.guard_keys):
                if key not in registry.permissions:
                    problems.append(f"setting {definition.key} references unknown permission {key}")
            defs[definition.key] = definition
        if problems:
            raise RuntimeError("setting definitions invalid:\n  - " + "\n  - ".join(problems))
        _defs_cache = (id(registry), defs)
        return defs


def setting_def(key: str) -> SettingDef:
    definition = setting_defs().get(key)
    if definition is None:
        raise NotFound(code="not_found", resource_type="org.setting")
    return definition


# ---- storage helpers --------------------------------------------------------------------------------------
def _check_branch(uow: UnitOfWork, definition: SettingDef, branch_id: uuid.UUID | None) -> None:
    if branch_id is None:
        return
    if definition.scope != "branch":
        raise ValidationFailed(
            f"{definition.key} is a company-wide setting.",
            errors=[{"loc": ["branch_id"], "msg": "company-scoped setting", "code": "branch_not_allowed"}],
        )
    exists = uow.session.scalar(
        select(Branch.id).where(Branch.id == branch_id, Branch.company_id == uow.actor.company_id)
    )
    if exists is None:
        raise NotFound(code="not_found", resource_type="org.branch")


def _row(uow: UnitOfWork, key: str, branch_id: uuid.UUID | None, *, for_update: bool = False) -> Setting | None:
    stmt = select(Setting).where(Setting.company_id == uow.actor.company_id, Setting.key == key)
    stmt = stmt.where(Setting.branch_id.is_(None) if branch_id is None else Setting.branch_id == branch_id)
    if for_update:
        stmt = stmt.with_for_update()
    return uow.session.scalars(stmt).first()


def _effective_row(uow: UnitOfWork, definition: SettingDef, branch_id: uuid.UUID | None) -> Setting | None:
    """Branch row, then the company row (branch-scoped definitions fall back to the company value)."""
    if branch_id is not None:
        row = _row(uow, definition.key, branch_id)
        if row is not None:
            return row
    return _row(uow, definition.key, None)


def _typed(definition: SettingDef, raw: dict[str, Any]) -> BaseModel:
    return definition.model.model_validate(raw)


def stored_or_default(uow: UnitOfWork, key: str, branch_id: uuid.UUID | None = None) -> BaseModel:
    """The unredacted typed value (internal to org: cross-setting validation). Modules use ``effective_value``."""
    definition = setting_def(key)
    row = _effective_row(uow, definition, branch_id)
    return _typed(definition, row.value) if row is not None else definition.default_value(uow)


# ---- redaction and reporting ------------------------------------------------------------------------------
def _diff_nulled(original: Any, redacted: Any, path: str, out: list[str]) -> None:
    if isinstance(original, dict) and isinstance(redacted, dict):
        for k, v in original.items():
            _diff_nulled(v, redacted.get(k), f"{path}.{k}" if path else k, out)
    elif isinstance(original, list) and isinstance(redacted, list):
        for i, (a, b) in enumerate(zip(original, redacted, strict=False)):
            _diff_nulled(a, b, f"{path}[{i}]", out)
    elif original is not None and redacted is None:
        out.append(path)


def _redacted(uow: UnitOfWork, value: BaseModel) -> tuple[BaseModel, list[str]]:
    shown = redact(value, uow.actor)
    paths: list[str] = []
    _diff_nulled(value.model_dump(mode="json"), shown.model_dump(mode="json"), "", paths)
    return shown, paths


def _absent(value: Any, path: str, out: list[str]) -> None:
    if isinstance(value, dict):
        for k, v in value.items():
            if k.endswith("_last4"):  # derived companions are configured through their source field
                continue
            _absent(v, f"{path}.{k}" if path else k, out)
    elif value is None or value == "" or value == []:
        out.append(path)


def not_configured_fields(value: BaseModel) -> list[str]:
    out: list[str] = []
    _absent(value.model_dump(mode="json"), "", out)
    return out


def _capabilities(uow: UnitOfWork, definition: SettingDef) -> dict[str, Capability]:
    actor = uow.actor
    if not actor.can(definition.manage_permission):
        return {"update": Capability(allowed=False, reason_code="permission_denied")}
    if any(not actor.can(g) for g in definition.guard_keys):
        return {"update": Capability(allowed=False, reason_code="restricted_fields_not_readable")}
    return {"update": Capability(allowed=True)}


def _audit_sensitive_read(uow: UnitOfWork, definition: SettingDef, value: BaseModel, redacted: list[str]) -> None:
    """Sensitive guard keys (S flag) are audited on use: a user who sees unmasked restricted values."""
    actor = uow.actor
    if actor.is_system or not definition.guard_keys:
        return
    dump = value.model_dump(mode="json")
    shown = [p for p in restricted_guards(definition.model) if _extract(dump, p) and p]
    if shown and not redacted:
        uow.audit(
            "org.setting.restricted_read",
            resource_type="org.setting",
            resource_label=definition.key,
            restricted_fields=sorted(shown),
            details={"guards": sorted(definition.guard_keys)},
        )


def _read(uow: UnitOfWork, definition: SettingDef, branch_id: uuid.UUID | None) -> SettingRead:
    row = _effective_row(uow, definition, branch_id)
    value = _typed(definition, row.value) if row is not None else definition.default_value(uow)
    shown, redacted = _redacted(uow, value)
    _audit_sensitive_read(uow, definition, value, redacted)
    return SettingRead(
        key=definition.key,
        description=definition.description,
        scope=definition.scope,
        branch_id=row.branch_id if row is not None else None,
        value=shown.model_dump(mode="json"),
        version=row.version if row is not None else 0,
        configured=row is not None,
        not_configured_fields=not_configured_fields(value),
        redacted_fields=redacted,
        updated_at=row.updated_at if row is not None else None,
        updated_by=row.updated_by if row is not None else None,
        capabilities=_capabilities(uow, definition),
    )


def _extract(dump: Any, path: str) -> list[Any]:
    """Values at a ``restricted_guards`` path (``[]`` expands list items); empty values are dropped."""
    current: list[Any] = [dump]
    for part in path.split("."):
        is_list = part.endswith("[]")
        name = part[:-2] if is_list else part
        nxt: list[Any] = []
        for item in current:
            if isinstance(item, dict):
                v = item.get(name)
                if is_list and isinstance(v, list):
                    nxt.extend(v)
                elif v is not None:
                    nxt.append(v)
        current = nxt
    return [v for v in current if v not in (None, "", [])]


# ---- public API -------------------------------------------------------------------------------------------
@query()
def list_settings(uow: UnitOfWork, *, branch_id: uuid.UUID | None = None) -> list[SettingRead]:
    """Every setting the actor may read (definitions the actor cannot read are omitted)."""
    uow.actor.require("org.settings.read")
    out: list[SettingRead] = []
    for key in sorted(setting_defs()):
        definition = setting_defs()[key]
        if not uow.actor.can(definition.read_permission):
            continue
        effective_branch = branch_id if definition.scope == "branch" else None
        if effective_branch is not None:
            _check_branch(uow, definition, effective_branch)
        out.append(_read(uow, definition, effective_branch))
    return out


@query()
def get_setting(uow: UnitOfWork, key: str, *, branch_id: uuid.UUID | None = None) -> SettingRead:
    definition = setting_def(key)
    uow.actor.require(definition.read_permission)
    _check_branch(uow, definition, branch_id)
    return _read(uow, definition, branch_id)


@query()
def effective_value(uow: UnitOfWork, key: str, *, branch_id: uuid.UUID | None = None) -> BaseModel:
    """The typed value as the actor may see it (restricted fields nulled). For documents and other modules."""
    definition = setting_def(key)
    uow.actor.require(definition.read_permission)
    value = stored_or_default(uow, key, branch_id)
    return redact(value, uow.actor)  # type: ignore[no-any-return]


@query()
def list_setting_revisions(
    uow: UnitOfWork, key: str, *, branch_id: uuid.UUID | None = None, limit: int = 50
) -> list[SettingRevisionRead]:
    definition = setting_def(key)
    uow.actor.require(definition.read_permission)
    _check_branch(uow, definition, branch_id)
    row = _row(uow, key, branch_id)
    if row is None:
        return []
    revisions = uow.session.scalars(
        select(SettingRevision)
        .where(SettingRevision.company_id == uow.actor.company_id, SettingRevision.setting_id == row.id)
        .order_by(SettingRevision.version.desc())
        .limit(max(1, min(limit, 200)))
    ).all()
    out: list[SettingRevisionRead] = []
    for rev in revisions:
        shown, redacted = _redacted(uow, _typed(definition, rev.value))
        out.append(
            SettingRevisionRead(
                version=rev.version,
                value=shown.model_dump(mode="json"),
                redacted_fields=redacted,
                changed_at=rev.changed_at,
                changed_by=rev.changed_by,
                change_reason=rev.change_reason,
            )
        )
    return out


def _validate_value(definition: SettingDef, raw: dict[str, Any]) -> BaseModel:
    try:
        return definition.model.model_validate(raw)
    except ValidationError as exc:
        errors = [
            {"loc": ["body", "value", *[str(p) for p in err.get("loc", ())]], "msg": err.get("msg"), "code": err.get("type")}
            for err in exc.errors(include_input=False, include_context=False, include_url=False)
        ]
        raise ValidationFailed("Some values are not valid.", errors=errors) from None


def _authorize_write(uow: UnitOfWork, definition: SettingDef) -> None:
    """Read right (404 otherwise), manage right, every restricted-field guard key and recent authentication."""
    actor = uow.actor
    if not actor.can(definition.read_permission):
        raise NotFound(code="not_found", resource_type="org.setting")
    actor.require(definition.manage_permission)
    for guard in sorted(definition.guard_keys):
        if not actor.can(guard):
            raise Forbidden(
                "Restricted values in this setting can only be changed by people who can read them.",
                code="permission_denied",
                permission=guard,
            )
    require_recent_auth(uow, definition.manage_permission)


@command()
def update_setting(
    uow: UnitOfWork,
    key: str,
    *,
    value: dict[str, Any],
    expected_version: int,
    branch_id: uuid.UUID | None = None,
    change_reason: str | None = None,
    origin: str | None = None,
) -> SettingRead:
    """Replace a setting value. Authorisation runs before the idempotent part, so a replayed
    ``Idempotency-Key`` is answered only while the actor still holds the rights (api-conventions §6)."""
    definition = setting_def(key)
    _authorize_write(uow, definition)
    result = _write_setting(
        uow,
        key,
        value=value,
        expected_version=expected_version,
        branch_id=branch_id,
        change_reason=change_reason,
        origin=origin,
    )
    return result if isinstance(result, SettingRead) else SettingRead.model_validate(result)


@command(idempotent=True)
def _write_setting(
    uow: UnitOfWork,
    key: str,
    *,
    value: dict[str, Any],
    expected_version: int,
    branch_id: uuid.UUID | None,
    change_reason: str | None,
    origin: str | None,
) -> SettingRead:
    definition = setting_def(key)
    actor = uow.actor
    _check_branch(uow, definition, branch_id)
    typed = _validate_value(definition, value)

    # Locks, always in this order (no deadlocks): the company's validation lock, then the per-key lock.
    # Cross-setting checks read other settings (brands <-> quote_defaults), so every write that has a
    # check is serialised per company and validated only once the lock is held. Under READ COMMITTED the
    # check then sees the other writer's committed value, which closes the write skew where two checks
    # pass on stale data and both commit.
    if definition.validate is not None:
        uow.advisory_xact_lock(VALIDATION_LOCK, str(actor.company_id))
    uow.advisory_xact_lock("org.setting", f"{actor.company_id}:{branch_id}:{key}")
    row = _row(uow, key, branch_id, for_update=True)
    current_version = row.version if row is not None else 0
    if expected_version != current_version:
        current = _read(uow, definition, branch_id).model_dump(mode="json")
        raise VersionConflict(
            "This setting changed since you opened it.",
            current_version=current_version,
            current=current,
            changed_by=str(row.updated_by) if row is not None and row.updated_by else None,
            changed_at=row.updated_at.isoformat() if row is not None else None,
        )
    if definition.validate is not None:
        definition.validate(uow, typed)

    new_dump = typed.model_dump(mode="json")
    old_typed = _typed(definition, row.value) if row is not None else None
    old_dump = old_typed.model_dump(mode="json") if old_typed is not None else {}
    if row is not None and old_dump == new_dump:
        return _read(uow, definition, branch_id)  # no change: no new version, revision or event

    if row is None:
        row = uow.add(
            Setting(
                company_id=actor.company_id,
                branch_id=branch_id,
                key=key,
                value=new_dump,
                schema_version=definition.schema_version,
            )
        )
    else:
        row.value = new_dump
        row.schema_version = definition.schema_version
    uow.flush()

    uow.add(
        SettingRevision(
            company_id=actor.company_id,
            setting_id=row.id,
            key=key,
            branch_id=branch_id,
            version=row.version,
            value=new_dump,
            schema_version=definition.schema_version,
            changed_by=actor.user_id,
            changed_at=uow.now(),
            change_reason=change_reason,
        )
    )
    changed = sorted(k for k in set(old_dump) | set(new_dump) if old_dump.get(k) != new_dump.get(k))
    restricted_changed = sorted(
        p for p in restricted_guards(definition.model) if _extract(old_dump, p) != _extract(new_dump, p)
    )
    uow.audit(
        "org.setting.updated",
        resource_type="org.setting",
        resource_id=row.id,
        resource_label=key,
        reason=change_reason,
        changes={"changed_fields": changed},
        restricted_fields=restricted_changed or None,
        details={"version": row.version, "branch_id": str(branch_id) if branch_id else None},
    )
    payload: dict[str, Any] = {
        "setting_key": key,
        "branch_id": str(branch_id) if branch_id else None,
        "version": row.version,
    }
    if origin:
        payload["origin"] = origin
    uow.emit("org.setting.updated", aggregate_id=row.id, aggregate_version=row.version, payload=payload)
    return _read(uow, definition, branch_id)
