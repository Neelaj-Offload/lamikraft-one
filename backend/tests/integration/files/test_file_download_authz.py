"""PARITY API-27 (legacy ``GET /files/{id}/download`` accepted ``?auth=``): downloads are cookie-authenticated, never
take a token from the query string, are authorised by the parent record of the attachment, and carry safe headers;
image variants follow the same rule."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from app.platform.authz.permissions import Scope
from app.seed.world import keys
from tests.integration.collab.conftest import PARENT_TYPE, make_parent, parent_table  # noqa: F401
from tests.integration.org.platform_lane import ApiClient, member

pytestmark = pytest.mark.db


def _jpeg() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (600, 400), (120, 90, 60)).save(out, format="JPEG")
    return out.getvalue()


def test_download_requires_parent_read_and_headers(api: ApiClient, company, parent_table) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    company_id, _ = company
    meera = member(company_id, keys.PEOPLE["MEERA"].name, "sales")
    neha = member(company_id, keys.PEOPLE["NEHA"].name, "sales")
    ravi = member(company_id, keys.PEOPLE["RAVI"].name, "employee", extra={"sales.quote.read": Scope.COMPANY})
    parent = make_parent(company_id, meera.user_id)

    api.as_(meera.actor())
    up = api.post("/api/v1/files?purpose=image", files={"file": ("Zürich tray.jpg", _jpeg(), "image/jpeg")})
    assert up.status_code == 201, up.text
    file_id = up.json()["id"]
    att = api.post("/api/v1/collab/attachments", json={"resource_type": PARENT_TYPE, "resource_id": str(parent), "file_id": file_id})
    assert att.status_code == 201, att.text

    # a reader of the parent downloads with safe headers (RFC 6266 filename*, sandbox CSP, nosniff, private cache)
    api.as_(ravi.actor())
    r = api.get(f"/api/v1/files/{file_id}/content")
    assert r.status_code == 200
    assert r.headers["content-security-policy"] == "sandbox"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "filename*=UTF-8''Z%C3%BCrich%20tray.jpg" in r.headers["content-disposition"]
    assert r.headers["content-disposition"].startswith("inline")
    assert api.get(f"/api/v1/files/{file_id}/content?variant=thumb").status_code == 200

    # someone who cannot read the parent gets 404 for the file and its variants
    api.as_(neha.actor())
    assert api.get(f"/api/v1/files/{file_id}/content").status_code == 404
    assert api.get(f"/api/v1/files/{file_id}/content?variant=thumb").status_code == 404

    # no session: a token in the query string is never accepted
    api.as_(None)
    for query in ("auth=abc", "token=abc", "t=abc"):
        assert api.get(f"/api/v1/files/{file_id}/content?{query}").status_code == 401
