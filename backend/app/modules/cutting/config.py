"""Cutting configuration: company settings (legacy constants become defaults), machine profiles and grain locks.

Reads need any ``cutting.`` permission (the optimiser explains rotation and board sizes to everyone who uses it);
writes need ``cutting.settings.manage`` or ``cutting.grain_lock.manage`` (legacy: admin only). Grain locks are keyed
on the canonical decor and every change is audited with its before/after.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed, VersionConflict
from app.modules.cutting.canonical import canonical_decor
from app.modules.cutting.models import CuttingSettings, GrainLock, MachineProfile
from app.modules.cutting.schemas import (
    GrainLockIn,
    GrainLockList,
    GrainLockRead,
    GrainLockReplace,
    MachineProfileCreate,
    MachineProfileRead,
    MachineProfileUpdate,
    SettingsRead,
    SettingsUpdate,
    UserRef,
)
from app.platform.identity.models import AppUser
from app.platform.uow import UnitOfWork

SETTINGS_MANAGE = "cutting.settings.manage"
GRAIN_LOCK_MANAGE = "cutting.grain_lock.manage"
#: plans with more pieces than this calculate as a background job; above ``MAX_PIECES`` the input is rejected
SYNC_PIECE_LIMIT = 300
MAX_PIECES = 5000


@dataclass(frozen=True)
class Defaults:
    """Legacy constants (spec §6 "Sheet"), now company-overridable defaults (LM-72, BR-11)."""

    board_length_mm: Decimal = Decimal("2440")
    board_width_mm: Decimal = Decimal("1220")
    margin_mm: Decimal = Decimal("5")
    gap_mm: Decimal = Decimal("6")
    oversize_mm: Decimal = Decimal("10")
    default_mode: str = "nested"
    max_extra_qty: int = 0
    max_extra_pct: Decimal = Decimal("0")
    min_offcut_mm: Decimal = Decimal("300")
    max_boards_per_group: int = 500


DEFAULTS = Defaults()


def plain(value: Decimal | None) -> Decimal | None:
    """A stored NUMERIC as its plain value (``2440.000`` -> ``2440``, ``0.800`` -> ``0.8``)."""
    if value is None:
        return None
    normal = value.normalize()
    return normal.quantize(Decimal(1)) if normal == normal.to_integral_value() else normal


def require_reader(uow: UnitOfWork) -> None:
    if not uow.actor.has_any("cutting."):
        raise Forbidden(code="permission_denied", permission="cutting.plan.read")


def _settings_row(uow: UnitOfWork) -> CuttingSettings | None:
    return uow.session.scalars(
        select(CuttingSettings).where(CuttingSettings.company_id == uow.actor.company_id)
    ).first()


@dataclass(frozen=True)
class EffectiveSettings:
    board_length_mm: Decimal
    board_width_mm: Decimal
    margin_mm: Decimal
    gap_mm: Decimal
    oversize_mm: Decimal
    default_mode: str
    default_machine_profile_id: uuid.UUID | None
    max_extra_qty: int
    max_extra_pct: Decimal
    min_offcut_mm: Decimal
    max_boards_per_group: int
    version: int
    customised: bool


def effective_settings(uow: UnitOfWork) -> EffectiveSettings:
    row = _settings_row(uow)
    if row is None:
        d = DEFAULTS
        return EffectiveSettings(
            d.board_length_mm, d.board_width_mm, d.margin_mm, d.gap_mm, d.oversize_mm, d.default_mode, None,
            d.max_extra_qty, d.max_extra_pct, d.min_offcut_mm, d.max_boards_per_group, 0, False,
        )
    return EffectiveSettings(
        plain(row.board_length_mm), plain(row.board_width_mm), plain(row.margin_mm), plain(row.gap_mm),  # type: ignore[arg-type]
        plain(row.oversize_mm), row.default_mode, row.default_machine_profile_id, row.max_extra_qty,  # type: ignore[arg-type]
        plain(row.max_extra_pct), plain(row.min_offcut_mm), row.max_boards_per_group, row.version, True,  # type: ignore[arg-type]
    )


def _settings_read(s: EffectiveSettings) -> SettingsRead:
    return SettingsRead(
        board_length_mm=s.board_length_mm,
        board_width_mm=s.board_width_mm,
        margin_mm=s.margin_mm,
        gap_mm=s.gap_mm,
        oversize_mm=s.oversize_mm,
        default_mode=s.default_mode,  # type: ignore[arg-type]
        default_machine_profile_id=s.default_machine_profile_id,
        max_extra_qty=s.max_extra_qty,
        max_extra_pct=s.max_extra_pct,
        min_offcut_mm=s.min_offcut_mm,
        max_boards_per_group=s.max_boards_per_group,
        sync_piece_limit=SYNC_PIECE_LIMIT,
        max_pieces=MAX_PIECES,
        version=s.version,
        customised=s.customised,
    )


def get_settings(uow: UnitOfWork) -> SettingsRead:
    require_reader(uow)
    return _settings_read(effective_settings(uow))


def update_settings(uow: UnitOfWork, data: SettingsUpdate) -> SettingsRead:
    uow.actor.require(SETTINGS_MANAGE)
    row = _settings_row(uow)
    current = effective_settings(uow)
    if row is None:
        if data.expected_version not in (None, 0):
            raise VersionConflict(current_version=0)
        d = DEFAULTS
        row = CuttingSettings(
            board_length_mm=d.board_length_mm, board_width_mm=d.board_width_mm, margin_mm=d.margin_mm,
            gap_mm=d.gap_mm, oversize_mm=d.oversize_mm, default_mode=d.default_mode, max_extra_qty=d.max_extra_qty,
            max_extra_pct=d.max_extra_pct, min_offcut_mm=d.min_offcut_mm, max_boards_per_group=d.max_boards_per_group,
        )
        uow.add(row)
    else:
        uow.expect_version(row, data.expected_version)
    changes: dict[str, Any] = {}
    for field in data.model_fields_set - {"expected_version"}:
        value = getattr(data, field)
        if value is None and field != "default_machine_profile_id":
            continue
        if field == "default_machine_profile_id" and value is not None:
            _profile(uow, value)
        before = getattr(current, field)
        if before != value:
            changes[field] = {"before": _jsonable(before), "after": _jsonable(value)}
        setattr(row, field, value)
    length = row.board_length_mm
    width = row.board_width_mm
    if 2 * Decimal(row.margin_mm) >= min(Decimal(length), Decimal(width)):
        raise ValidationFailed(
            "The margins leave no usable area",
            errors=[{"loc": ["body", "margin_mm"], "msg": "margins leave no usable area", "code": "margin_too_large"}],
        )
    uow.flush()
    uow.audit("cutting.settings.updated", resource_type="cutting.settings", resource_id=row.id, changes=changes or None)
    return _settings_read(effective_settings(uow))


# ---- machine profiles ----------------------------------------------------------------------------------
def _profile_read(p: MachineProfile) -> MachineProfileRead:
    return MachineProfileRead(
        id=p.id, code=p.code, name=p.name, mode=p.mode, gap_mm=plain(p.gap_mm), notes=p.notes,  # type: ignore[arg-type]
        archived=p.archived_at is not None, version=p.version,
    )


def _profile(uow: UnitOfWork, profile_id: uuid.UUID) -> MachineProfile:
    p = uow.session.scalars(
        select(MachineProfile).where(MachineProfile.company_id == uow.actor.company_id, MachineProfile.id == profile_id)
    ).first()
    if p is None:
        raise NotFound(code="not_found", resource_type="cutting.machine_profile")
    return p


def machine_profile(uow: UnitOfWork, profile_id: uuid.UUID) -> MachineProfile:
    """A company machine profile (404 when absent); used by plans for their mode and kerf."""
    return _profile(uow, profile_id)


def list_machine_profiles(uow: UnitOfWork, *, include_archived: bool = False) -> list[MachineProfileRead]:
    require_reader(uow)
    stmt = select(MachineProfile).where(MachineProfile.company_id == uow.actor.company_id)
    if not include_archived:
        stmt = stmt.where(MachineProfile.archived_at.is_(None))
    return [_profile_read(p) for p in uow.session.scalars(stmt.order_by(MachineProfile.code))]


def create_machine_profile(uow: UnitOfWork, data: MachineProfileCreate) -> MachineProfileRead:
    uow.actor.require(SETTINGS_MANAGE)
    exists = uow.session.scalar(
        select(MachineProfile.id).where(MachineProfile.company_id == uow.actor.company_id, MachineProfile.code == data.code)
    )
    if exists is not None:
        raise Conflict("A machine profile with this code exists", code="machine_profile_exists")
    p = MachineProfile(code=data.code, name=data.name, mode=data.mode, gap_mm=data.gap_mm, notes=data.notes)
    uow.add(p)
    uow.flush()
    uow.audit("cutting.machine_profile.created", resource_type="cutting.machine_profile", resource_id=p.id,
              resource_label=p.code, changes={"mode": p.mode, "gap_mm": _jsonable(data.gap_mm)})
    return _profile_read(p)


def update_machine_profile(uow: UnitOfWork, profile_id: uuid.UUID, data: MachineProfileUpdate) -> MachineProfileRead:
    uow.actor.require(SETTINGS_MANAGE)
    p = _profile(uow, profile_id)
    uow.expect_version(p, data.expected_version)
    changes: dict[str, Any] = {}
    for field in data.model_fields_set - {"expected_version", "archived"}:
        value = getattr(data, field)
        if value is None and field in {"name", "mode"}:
            continue
        before = getattr(p, field)
        if (plain(before) if isinstance(before, Decimal) else before) != value:
            changes[field] = {"before": _jsonable(before), "after": _jsonable(value)}
        setattr(p, field, value)
    if data.archived is not None and (p.archived_at is not None) != data.archived:
        p.archived_at = uow.now() if data.archived else None
        p.archived_by = uow.actor.user_id if data.archived else None
        changes["archived"] = data.archived
    uow.flush()
    uow.audit("cutting.machine_profile.updated", resource_type="cutting.machine_profile", resource_id=p.id,
              resource_label=p.code, changes=changes or None)
    return _profile_read(p)


# ---- grain locks -----------------------------------------------------------------------------------
def _user_refs(uow: UnitOfWork, ids: set[uuid.UUID]) -> dict[uuid.UUID, UserRef]:
    if not ids:
        return {}
    rows = uow.session.execute(select(AppUser.id, AppUser.display_name).where(AppUser.id.in_(ids))).all()
    return {r[0]: UserRef(id=r[0], display_name=r[1]) for r in rows}


def _locks(uow: UnitOfWork) -> list[GrainLock]:
    return list(
        uow.session.scalars(
            select(GrainLock).where(GrainLock.company_id == uow.actor.company_id).order_by(GrainLock.decor_key)
        )
    )


def locked_decor_keys(uow: UnitOfWork) -> frozenset[str]:
    """Canonical decors whose pieces may not rotate (no permission check: used inside authorised commands)."""
    return frozenset(
        uow.session.scalars(select(GrainLock.decor_key).where(GrainLock.company_id == uow.actor.company_id))
    )


def _lock_list(uow: UnitOfWork, warnings: list[str] | None = None) -> GrainLockList:
    locks = _locks(uow)
    users = _user_refs(uow, {lock.updated_by for lock in locks if lock.updated_by})
    return GrainLockList(
        items=[
            GrainLockRead(
                id=lock.id, decor_key=lock.decor_key, decor_source=lock.decor_source, label=lock.label,
                updated_at=lock.updated_at, updated_by=users.get(lock.updated_by) if lock.updated_by else None,
            )
            for lock in locks
        ],
        can_manage=uow.actor.can(GRAIN_LOCK_MANAGE),
        warnings=warnings or [],
    )


def list_grain_locks(uow: UnitOfWork) -> GrainLockList:
    require_reader(uow)
    return _lock_list(uow)


def _canonical(data: GrainLockIn, index: int | None = None) -> tuple[str, str | None, list[str]]:
    key, warns = canonical_decor(data.decor)
    loc: list[str | int] = ["body", "decor"] if index is None else ["body", "locks", index, "decor"]
    if not key or len(key) > 40:
        raise ValidationFailed(
            "A grain lock needs a decor of 1 to 40 characters",
            errors=[{"loc": loc, "msg": "decor must be 1 to 40 characters", "code": "invalid_decor"}],
        )
    source = data.decor.strip() if data.decor.strip() != key else None
    notes = [f"{data.decor.strip()} was stored as {key}"] if warns else []
    return key, source, notes


def add_grain_lock(uow: UnitOfWork, data: GrainLockIn) -> GrainLockList:
    uow.actor.require(GRAIN_LOCK_MANAGE)
    key, source, notes = _canonical(data)
    uow.advisory_xact_lock("cutting.grain_lock", str(uow.actor.company_id))
    existing = uow.session.scalars(
        select(GrainLock).where(GrainLock.company_id == uow.actor.company_id, GrainLock.decor_key == key)
    ).first()
    if existing is not None:
        raise Conflict(f"Decor {key} is already grain-locked", code="grain_lock_exists", decor_key=key)
    lock = GrainLock(decor_key=key, decor_source=source, label=data.label or None)
    uow.add(lock)
    uow.flush()
    uow.audit("cutting.grain_lock.added", resource_type="cutting.grain_lock", resource_id=lock.id, resource_label=key,
              changes={"decor": {"before": None, "after": key}, "label": {"before": None, "after": lock.label}})
    return _lock_list(uow, notes)


def remove_grain_lock(uow: UnitOfWork, decor: str) -> GrainLockList:
    uow.actor.require(GRAIN_LOCK_MANAGE)
    key, _warns = canonical_decor(decor)
    lock = uow.session.scalars(
        select(GrainLock).where(GrainLock.company_id == uow.actor.company_id, GrainLock.decor_key == key)
    ).first()
    if lock is None:
        raise NotFound(code="not_found", resource_type="cutting.grain_lock")
    uow.audit("cutting.grain_lock.removed", resource_type="cutting.grain_lock", resource_id=lock.id, resource_label=key,
              changes={"decor": {"before": key, "after": None}, "label": {"before": lock.label, "after": None}})
    uow.session.delete(lock)
    uow.flush()
    return _lock_list(uow)


def replace_grain_locks(uow: UnitOfWork, data: GrainLockReplace) -> GrainLockList:
    """The list becomes exactly ``data.locks`` (keys canonicalised; duplicates after canonicalisation are a 422)."""
    uow.actor.require(GRAIN_LOCK_MANAGE)
    wanted: dict[str, tuple[str | None, str | None]] = {}
    notes: list[str] = []
    errors: list[dict[str, Any]] = []
    for index, entry in enumerate(data.locks):
        key, source, warn = _canonical(entry, index)
        if key in wanted:
            errors.append({"loc": ["body", "locks", index, "decor"], "msg": f"{key} is listed twice", "code": "duplicate_decor"})
            continue
        wanted[key] = (source, entry.label or None)
        notes += warn
    if errors:
        raise ValidationFailed("Some grain locks are not valid", errors=errors)
    uow.advisory_xact_lock("cutting.grain_lock", str(uow.actor.company_id))
    current = {lock.decor_key: lock for lock in _locks(uow)}
    added = sorted(set(wanted) - set(current))
    removed = sorted(set(current) - set(wanted))
    relabelled: list[str] = []
    for key in removed:
        uow.session.delete(current[key])
    for key, lock in current.items():
        if key in wanted and lock.label != wanted[key][1]:
            relabelled.append(key)
            lock.label = wanted[key][1]
    for key in added:
        uow.add(GrainLock(decor_key=key, decor_source=wanted[key][0], label=wanted[key][1]))
    uow.flush()
    uow.audit(
        "cutting.grain_lock.replaced",
        resource_type="cutting.grain_lock",
        changes={"added": added, "removed": removed, "relabelled": relabelled},
    )
    return _lock_list(uow, notes)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(plain(value), "f")
    if isinstance(value, uuid.UUID):
        return str(value)
    return value
