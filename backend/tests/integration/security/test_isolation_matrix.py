"""Isolation matrix (PARITY SEC-03, LP-01.4, SCN-A3 platform part; platform-2 brief item 7).

A sentinel is planted in another owner's quote (fields, internal note, attachment title and file) and in its party.
A restricted warehouse user (Kabir) and a peer sales user (Neha, own scope) then call global search, the activity
feed and timeline, notes, attachments, the planted file and every GET route on this branch: the sentinel never
appears in any response body, and the collaboration children of the invisible quote answer 404 (never 403, which
would confirm the record exists).
"""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.routing import APIRoute, iter_route_contexts
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.platform.authz.context import ActorContext
from app.platform.collab.models import Attachment, Note
from app.platform.files import service as files
from app.platform.files.storage import LocalFsStorage, set_storage, staging_dir
from app.platform.identity.actors import actor_for
from app.platform.uow import UnitOfWork
from tests.integration.identity.fixtures import origin_headers

pytestmark = pytest.mark.db

SENTINEL = "ZQSENTINEL" + uuid.uuid4().hex[:8].upper()


@pytest.fixture(autouse=True)
def storage(tmp_path: Path) -> Iterator[LocalFsStorage]:
    backend = LocalFsStorage(tmp_path / "storage")
    set_storage(backend)
    yield backend
    set_storage(None)


def _sign_in(app, key: str) -> TestClient:  # type: ignore[no-untyped-def]
    c = TestClient(app, base_url="http://testserver")
    r = c.post("/api/v1/_test/sign-in", json={"user_key": key}, headers=origin_headers())
    assert r.status_code == 200, r.text
    return c


def _staged(data: bytes) -> Path:
    fd, name = tempfile.mkstemp(dir=staging_dir())
    with open(fd, "wb") as fh:
        fh.write(data)
    return Path(name)


def _plant(world) -> tuple[uuid.UUID, uuid.UUID]:  # type: ignore[no-untyped-def]
    company_id = world.company_id
    quote_id = world.ref("Q_NORDHAUS_DRAFT")
    with UnitOfWork(ActorContext.system(company_id, reason="test-plant")) as uow:
        owner = uow.session.execute(text("SELECT owner_user_id FROM sales_quote WHERE id = :q"), {"q": quote_id}).scalar_one()
        uow.session.execute(text("UPDATE sales_quote SET customer_reference = :s, remarks = :r WHERE id = :q"), {"s": SENTINEL, "r": SENTINEL, "q": quote_id})
        uow.session.execute(
            text("UPDATE parties_party SET display_name = :s WHERE id = (SELECT party_id FROM sales_quote WHERE id = :q)"),
            {"s": f"{SENTINEL} Interiors", "q": quote_id},
        )
    owner_actor = actor_for(company_id, owner)
    assert owner_actor is not None
    # the quote is in internal review (not editable), so the note and attachment rows are planted directly; the
    # read paths under test are the same whoever wrote them
    with UnitOfWork(owner_actor) as uow:
        uow.add(Note(company_id=company_id, resource_type="sales.quote", resource_id=quote_id, body=f"internal {SENTINEL}"))
    pdf = b"%PDF-1.4\n%" + SENTINEL.encode() + b"\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
    with UnitOfWork(owner_actor) as uow:
        stored = files._store(
            uow,
            path=_staged(pdf),
            size=len(pdf),
            sha256=hashlib.sha256(pdf).hexdigest(),
            head=pdf[:64],
            filename=f"{SENTINEL}.pdf",
            declared_content_type="application/pdf",
            purpose=files.FilePurpose.DOCUMENT,
            restricted=False,
        )
    with UnitOfWork(owner_actor) as uow:
        uow.add(
            Attachment(
                id=uuid.uuid7(), company_id=company_id, resource_type="sales.quote", resource_id=quote_id, file_id=stored.id,
                role="document", title=f"{SENTINEL} drawing",
            )
        )
        uow.emit(
            "collab.attachment.added",
            aggregate_id=None,
            payload={"resource_type": "sales.quote", "resource_id": str(quote_id), "attachment_id": str(uuid.uuid7()), "file_id": str(stored.id), "role": "document"},
        )
    return quote_id, stored.id


def _get_routes(app) -> list[str]:  # type: ignore[no-untyped-def]
    out = set()
    for ctx in iter_route_contexts(app.routes):
        path = str(ctx.path)
        if not isinstance(ctx.original_route, APIRoute) or "GET" not in (ctx.methods or ()) or not path.startswith("/api/v1/"):
            continue
        if path.startswith(("/api/v1/_test", "/api/v1/health")):
            continue
        out.add(path)
    return sorted(out)


def _without_echo(response) -> str:  # type: ignore[no-untyped-def]
    """The body minus the caller's own search text echoed back (``query`` / ``terms`` of a search response)."""
    try:
        body = response.json()
    except ValueError:
        return response.text
    if isinstance(body, dict):
        body = {k: v for k, v in body.items() if k not in ("query", "terms", "q")}
    return json.dumps(body)


def _probe(c: TestClient, path: str, ids: dict[str, uuid.UUID]) -> list[tuple[str, int, str]]:
    """GET a route with path parameters filled from the planted ids where the name fits (others skipped), with no
    query, with the sentinel as a search query, and with the planted record as the polymorphic parent."""
    concrete = path
    for name in re.findall(r"{([^}]+)}", path):
        value = next((v for k, v in ids.items() if k in name), None)
        if value is None:
            return []
        concrete = concrete.replace("{" + name + "}", str(value))
    out = []
    for query in ({}, {"q": SENTINEL}, {"q": SENTINEL[:6].lower()}, {"resource_type": "sales.quote", "resource_id": str(ids["quote"])}):
        r = c.get(concrete, params=query)
        out.append((f"{concrete} {query}", r.status_code, _without_echo(r)))
    return out


@pytest.mark.parametrize("persona", ["KABIR", "NEHA"])
def test_restricted_user_sees_no_sentinel_anywhere(client: TestClient, world, persona: str) -> None:  # type: ignore[no-untyped-def]
    quote_id, file_id = _plant(world)
    c = _sign_in(client.app, persona)

    for url, params in (
        ("/api/v1/collab/notes", {"resource_type": "sales.quote", "resource_id": str(quote_id)}),
        ("/api/v1/collab/attachments", {"resource_type": "sales.quote", "resource_id": str(quote_id)}),
        ("/api/v1/collab/activity", {"resource_type": "sales.quote", "resource_id": str(quote_id)}),
        (f"/api/v1/files/{file_id}/content", {}),
    ):
        r = c.get(url, params=params)
        assert r.status_code == 404, (url, r.status_code, r.text)
        assert SENTINEL.lower() not in r.text.lower()
    detail = c.get(f"/api/v1/sales/quotes/{quote_id}")
    assert detail.status_code in (403, 404) and SENTINEL not in detail.text

    put = c.put(
        "/api/v1/collab/notes",
        params={"resource_type": "sales.quote", "resource_id": str(quote_id)},
        json={"body": "overwrite", "expected_version": 1},
        headers={**origin_headers(), "X-CSRF-Token": c.cookies.get("lk_csrf") or ""},
    )
    assert put.status_code == 404

    leaks: list[str] = []
    errors: list[str] = []
    probed = 0
    for path in _get_routes(client.app):
        for where, status, body in _probe(c, path, {"quote": quote_id, "file": file_id}):
            probed += 1
            if status >= 500:
                errors.append(f"{where}: {status}")
            if SENTINEL.lower() in body.lower():
                leaks.append(where)
    assert leaks == []
    assert errors == []
    assert probed > 100

    # the owner does see it, so the probe is meaningful
    meera = _sign_in(client.app, "MEERA")
    params = {"resource_type": "sales.quote", "resource_id": str(quote_id)}
    assert SENTINEL in meera.get("/api/v1/collab/attachments", params=params).text
    assert SENTINEL in meera.get("/api/v1/collab/notes", params=params).text
