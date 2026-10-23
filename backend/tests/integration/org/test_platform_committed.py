"""Committed-mode checks for the platform lane: RLS isolation of the new tenant tables and concurrent writers."""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import create_engine, text

from app.core.config import get_settings
from app.core.errors import VersionConflict
from app.platform.authz.context import ActorContext
from app.platform.files import service as files
from app.platform.files.storage import LocalFsStorage, set_storage
from app.platform.org import service as settings_service
from app.platform.search import service as search
from app.platform.uow import UnitOfWork
from tests.integration.org.platform_lane import member
from tests.support import create_company

pytestmark = [pytest.mark.db, pytest.mark.committed]

TABLES = ("setting", "setting_revision", "file_object", "search_recent", "note", "uom")


def _race(*calls: Callable[[], Any]) -> list[Any]:
    """Run calls in threads released together by a barrier; returns results or raised exceptions in order."""
    barrier = threading.Barrier(len(calls))
    results: list[Any] = [None] * len(calls)

    def run(i: int, call: Callable[[], Any]) -> None:
        barrier.wait()
        try:
            results[i] = call()
        except Exception as exc:  # noqa: BLE001 - collected for assertions
            results[i] = exc

    threads = [threading.Thread(target=run, args=(i, c)) for i, c in enumerate(calls)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    return results


def test_new_tenant_tables_are_isolated_by_rls(committed_db: str, tmp_path) -> None:  # type: ignore[no-untyped-def]
    set_storage(LocalFsStorage(tmp_path))
    try:
        ids = []
        for name in ("Alpha", "Beta"):
            company_id, _ = create_company()
            admin = member(company_id, f"{name} Admin", "admin")
            settings_service.update_setting(admin.actor(), "document_terms", value={"quote": name}, expected_version=0)
            files.store_generated(admin.actor(), f"{name},1\n".encode(), filename="x.csv")
            search.record_recent(admin.actor(), name)
            from app.platform.org.reference import ensure_default_uoms

            with UnitOfWork(ActorContext.system(company_id)) as uow:
                ensure_default_uoms(uow)
            ids.append(company_id)
    finally:
        set_storage(None)
    engine = create_engine(get_settings().app_database_url)
    try:
        with engine.connect() as conn:
            for table in TABLES:
                assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar() == 0, table  # fail closed
            conn.execute(text("SELECT set_config('app.company_id', :c, false)"), {"c": str(ids[0])})
            for table in TABLES:
                companies = set(conn.execute(text(f"SELECT DISTINCT company_id FROM {table}")).scalars())
                assert companies <= {ids[0]}, table
            assert conn.execute(text("SELECT value->>'quote' FROM setting")).scalar() == "Alpha"
    finally:
        engine.dispose()


def test_concurrent_first_writes_of_a_setting_yield_one_version(committed_db: str) -> None:
    company_id, _ = create_company()
    a = member(company_id, "Admin A", "admin").actor()
    b = member(company_id, "Admin B", "admin").actor()
    results = _race(
        lambda: settings_service.update_setting(a, "document_terms", value={"quote": "A"}, expected_version=0),
        lambda: settings_service.update_setting(b, "document_terms", value={"quote": "B"}, expected_version=0),
    )
    winners = [r for r in results if not isinstance(r, Exception)]
    losers = [r for r in results if isinstance(r, Exception)]
    assert len(winners) == 1 and winners[0].version == 1
    assert len(losers) == 1 and isinstance(losers[0], VersionConflict)
    assert losers[0].extra["current"]["value"]["quote"] == winners[0].value["quote"]


def test_concurrent_uploads_of_the_same_bytes_store_one_file(committed_db: str, tmp_path) -> None:  # type: ignore[no-untyped-def]
    storage = LocalFsStorage(tmp_path)
    set_storage(storage)
    try:
        company_id, _ = create_company()
        a = member(company_id, "Uploader A", "employee").actor()
        b = member(company_id, "Uploader B", "employee").actor()
        data = b"product_key,qty\nLK-OT-0450,240\n" + uuid.uuid4().hex.encode()
        results = _race(
            lambda: files.store_generated(a, data, filename="a.csv", purpose="document"),
            lambda: files.store_generated(b, data, filename="b.csv", purpose="document"),
        )
    finally:
        set_storage(None)
    assert not any(isinstance(r, Exception) for r in results), results
    assert results[0].id == results[1].id
    assert sorted(r.deduplicated for r in results) == [False, True]
    with UnitOfWork(ActorContext.system(company_id)) as uow:
        count = uow.session.execute(text("SELECT count(*) FROM file_object")).scalar()
    assert count == 1
    stored = [p for p in tmp_path.rglob("*") if p.is_file() and "_staging" not in p.parts]
    assert len(stored) == 1  # the losing copy was removed from storage
