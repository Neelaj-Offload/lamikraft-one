"""Voice/vision lane contracts: database CHECKs mirror the StrEnums, every ``voice_`` / ``vision_`` table has forced
fail-closed RLS, ``file_object`` accepts the ``screen_capture`` purpose, the routes carry catalogued permissions, and
the contributions (setting, jobs, schedules, integrations, readiness check) are registered."""

from __future__ import annotations

import re
from enum import StrEnum

import pytest
from sqlalchemy import text

from app.core.db.base import Base
from app.modules.vision.models import CaptureStatus, RequestKind, RequestStatus
from app.modules.voice.models import UtteranceSource, UtteranceStatus
from app.platform.authz.catalogue_data import PERMISSIONS
from app.platform.authz.context import ActorContext
from app.platform.files.models import FilePurpose
from app.platform.uow import UnitOfWork
from app.registry import get_registry

ENUM_COLUMNS: dict[tuple[str, str], type[StrEnum]] = {
    ("voice_utterance", "status"): UtteranceStatus,
    ("voice_utterance", "source"): UtteranceSource,
    ("vision_capture", "status"): CaptureStatus,
    ("vision_request", "kind"): RequestKind,
    ("vision_request", "status"): RequestStatus,
    ("file_object", "purpose"): FilePurpose,
}
TABLES = {"voice_utterance", "voice_speech", "voice_readback", "vision_capture", "vision_request"}


def _check_values(uow: UnitOfWork, table: str, name: str) -> set[str]:
    definition = uow.session.execute(
        text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = CAST(:t AS regclass) AND conname = :n"),
        {"t": table, "n": name},
    ).scalar_one()
    return set(re.findall(r"'([^']*)'", definition))


@pytest.mark.db
def test_enum_checks_match_the_strenums(db: None) -> None:
    with UnitOfWork(ActorContext.system(None)) as uow:
        for (table, column), enum in ENUM_COLUMNS.items():
            assert _check_values(uow, table, f"ck_{table}_{column}_values") == {e.value for e in enum}, (table, column)


@pytest.mark.db
def test_tables_force_rls_and_requests_are_always_tainted(db: None) -> None:
    mapped = {m.class_.__tablename__ for m in Base.registry.mappers if m.class_.__tablename__.startswith(("voice_", "vision_"))}
    assert mapped == TABLES
    with UnitOfWork(ActorContext.system(None)) as uow:
        policies = set(uow.session.execute(text("SELECT tablename FROM pg_policies WHERE policyname = 'tenant_isolation'")).scalars())
        forced = set(uow.session.execute(text("SELECT relname FROM pg_class WHERE relforcerowsecurity")).scalars())
        tainted = uow.session.execute(text(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'ck_vision_request_always_tainted'"
        )).scalar_one()
    assert TABLES <= policies and TABLES <= forced
    assert "tainted" in tainted


def test_routes_name_catalogued_permissions() -> None:
    from app.main import create_app

    keys = {p["key"] for p in PERMISSIONS}
    paths = create_app().openapi()["paths"]
    ours = {p: ops for p, ops in paths.items() if p.startswith(("/api/v1/voice/", "/api/v1/vision/"))}
    assert len(ours) == 15  # 8 voice paths, 7 vision paths
    for path, ops in ours.items():
        for method, op in ops.items():
            authz = op.get("x-authz") or {}
            assert authz.get("kind") == "permission", (method, path)
            assert set(authz["permissions"]) <= keys, (method, path)
            module = path.split("/")[3]
            assert op["operationId"].startswith(f"{module}_") and op["tags"] == [module]
    assert paths["/api/v1/voice/speech"]["post"]["x-authz"]["permissions"] == ["voice.speech.use"]


def test_lane_contributions_are_registered() -> None:
    from app.platform.org.service import setting_defs
    from app.platform.system.integrations import integration_def
    from app.platform.system.readiness import _CHECKS

    registry = get_registry()
    assert {"voice", "vision"} <= {m.name for m in registry.manifests}
    jobs = {j.kind for m in registry.manifests for j in m.jobs}
    schedules = {s.kind for m in registry.manifests for s in m.schedules}
    assert {"voice.audio.purge", "vision.captures.purge"} <= jobs & schedules
    assert setting_defs()["screen_capture"].owner_module == "vision"
    for key in ("voice.stt", "voice.tts", "ai.gemini"):
        definition = integration_def(key)
        assert definition is not None and definition.verify is not None, key
    assert "voice" in _CHECKS
