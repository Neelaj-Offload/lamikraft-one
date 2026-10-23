"""Files: streamed uploads with limits and sniffing, dedupe, parent-authorised downloads and their headers."""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.core.errors import ValidationFailed
from app.platform.authz.context import ActorContext
from app.platform.authz.permissions import Scope
from app.platform.files import service as files
from app.platform.files.access import register_file_access, unregister_file_access
from app.platform.files.models import FileObject, FilePurpose
from app.platform.files.storage import LocalFsStorage
from app.platform.org import service as settings_service
from app.platform.uow import UnitOfWork
from app.seed.world import keys
from tests.integration.org.platform_lane import ApiClient, audit_rows, member, problem
from tests.unit.files.test_sniff import PDF, image_bytes, xlsx_bytes

pytestmark = pytest.mark.db

PNG = image_bytes("PNG")


@pytest.fixture
def people(company):  # type: ignore[no-untyped-def]
    company_id, _ = company
    return {
        "priya": member(company_id, keys.PEOPLE["PRIYA"].name, "admin"),
        "meera": member(company_id, keys.PEOPLE["MEERA"].name, "sales"),
        "neha": member(company_id, keys.PEOPLE["NEHA"].name, "sales"),
    }


def upload(api: ApiClient, data: bytes, name: str, purpose: str = "image", ctype: str = "application/octet-stream"):  # type: ignore[no-untyped-def]
    return api.post(f"/api/v1/files?purpose={purpose}", files={"file": (name, data, ctype)})


def _count(company_id: uuid.UUID) -> int:
    with UnitOfWork(ActorContext.system(company_id)) as uow:
        return int(uow.session.scalar(select(func.count()).select_from(FileObject)) or 0)


# ---- upload ----------------------------------------------------------------------------------------------------
def test_upload_stores_sniffed_metadata_under_a_random_key(api: ApiClient, people, company, storage: LocalFsStorage) -> None:  # type: ignore[no-untyped-def]
    company_id, _ = company
    r = upload(api.as_(people["meera"].actor()), PNG, "Oak Tray (front).png", ctype="text/plain")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["kind"] == "png" and body["content_type"] == "image/png"  # the bytes decide, not the header
    assert body["sha256"] == hashlib.sha256(PNG).hexdigest() and body["size_bytes"] == len(PNG)
    assert body["original_name"] == "Oak Tray (front).png" and body["deduplicated"] is False
    assert body["content_url"] == f"/api/v1/files/{body['id']}/content"
    with UnitOfWork(ActorContext.system(company_id)) as uow:
        row = uow.session.get(FileObject, uuid.UUID(body["id"]))
        assert row is not None
        assert row.declared_content_type == "text/plain"
        assert row.created_by == people["meera"].user_id
        assert "oak" not in row.storage_key.lower() and row.storage_key.startswith(f"{company_id}/")
        assert storage.exists(row.storage_key)
    staging = Path(storage.root) / "_staging"
    assert list(staging.iterdir()) == []  # spooled upload moved into storage


def test_same_bytes_are_deduplicated_per_company(api: ApiClient, people, company) -> None:  # type: ignore[no-untyped-def]
    company_id, _ = company
    api.as_(people["meera"].actor())
    first = upload(api, PNG, "a.png").json()
    second = upload(api, PNG, "b.png").json()
    assert second["id"] == first["id"] and second["deduplicated"] is True
    assert second["original_name"] == "b.png"
    assert _count(company_id) == 1
    from tests.support import create_company

    other_company, _ = create_company()
    other = member(other_company, "Elsewhere", "employee")
    third = upload(api.as_(other.actor()), PNG, "a.png").json()
    assert third["id"] != first["id"] and third["deduplicated"] is False


@pytest.mark.parametrize(
    ("data", "name", "purpose", "reason"),
    [
        (b'<svg xmlns="http://www.w3.org/2000/svg"/>', "logo.svg", "image", "svg_not_allowed"),
        (b"<html><body>hi</body></html>", "page.html", "document", "html_not_allowed"),
        (PNG, "logo.jpg", "image", "extension_mismatch"),
        (PDF, "quote.pdf", "image", "type_not_allowed_for_purpose"),
        (PNG, "logo.png", "import", "type_not_allowed_for_purpose"),
    ],
)
def test_rejected_uploads_are_415_and_leave_nothing_behind(  # type: ignore[no-untyped-def]
    api: ApiClient, people, company, storage, data, name, purpose, reason
) -> None:
    company_id, _ = company
    r = upload(api.as_(people["meera"].actor()), data, name, purpose)
    assert r.status_code == 415
    body = problem(r)
    assert body["code"] == "unsupported_media_type" and body["reason"] == reason
    assert _count(company_id) == 0
    assert [p for p in Path(storage.root).rglob("*") if p.is_file()] == []


def test_documents_and_imports_accept_their_kinds(api: ApiClient, people) -> None:  # type: ignore[no-untyped-def]
    api.as_(people["meera"].actor())
    assert upload(api, PDF, "spec.pdf", "document").json()["kind"] == "pdf"
    assert upload(api, xlsx_bytes(), "products.xlsx", "import").json()["kind"] == "xlsx"
    assert upload(api, b"product_key\nLK-OT-0450\n", "keys.csv", "import").json()["kind"] == "csv"


def test_per_purpose_size_limit_is_413(api: ApiClient, people, company, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    company_id, _ = company
    monkeypatch.setitem(files.PURPOSE_LIMITS, FilePurpose.IMAGE, 64)
    r = upload(api.as_(people["meera"].actor()), PNG, "logo.png")
    assert r.status_code == 413
    body = problem(r)
    assert body["code"] == "payload_too_large" and body["limit_bytes"] == 64
    assert _count(company_id) == 0


def test_declared_content_length_over_the_limit_is_refused_before_reading(api: ApiClient, people, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setitem(files.PURPOSE_LIMITS, FilePurpose.IMAGE, 10)
    big = b"x" * (200 * 1024)
    r = upload(api.as_(people["meera"].actor()), big, "big.png")
    assert r.status_code == 413


def test_purpose_limits_follow_the_contract() -> None:
    mib = 1024 * 1024
    assert files.limit_for("image") == 15 * mib
    assert files.limit_for("document") == 25 * mib
    assert files.limit_for("import") == 50 * mib


def test_malformed_requests(api: ApiClient, people) -> None:  # type: ignore[no-untyped-def]
    api.as_(people["meera"].actor())
    r = api.post("/api/v1/files?purpose=image", content=b"raw", headers={"Content-Type": "image/png"})
    assert r.status_code == 415 and problem(r)["reason"] == "multipart_required"
    r = api.post("/api/v1/files?purpose=image", data={"note": "no file"}, files={"other": ("a.png", PNG)})
    assert r.status_code == 422
    r = api.post(
        "/api/v1/files?purpose=image",
        files=[("file", ("a.png", PNG, "image/png")), ("file", ("b.png", image_bytes("PNG", (9, 9)), "image/png"))],
    )
    assert r.status_code == 422 and problem(r)["errors"][0]["code"] == "one_file_required"
    r = upload(api, PNG, "a.png", purpose="export")  # exports are created by services, never uploaded
    assert r.status_code == 422


def test_upload_needs_the_create_permission(api: ApiClient, company) -> None:  # type: ignore[no-untyped-def]
    company_id, _ = company
    nobody = member(company_id, "No Files", extra={"search.global.use": Scope.COMPANY})
    r = upload(api.as_(nobody.actor()), PNG, "a.png")
    assert r.status_code == 403 and problem(r)["code"] == "permission_denied"
    assert upload(api.as_(None), PNG, "a.png").status_code == 401


# ---- download -----------------------------------------------------------------------------------------------------
def test_download_headers(api: ApiClient, people) -> None:  # type: ignore[no-untyped-def]
    api.as_(people["meera"].actor())
    file_id = upload(api, PNG, "Résumé front.png").json()["id"]
    r = api.get(f"/api/v1/files/{file_id}/content")
    assert r.status_code == 200 and r.content == PNG
    assert r.headers["content-type"] == "image/png"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["content-security-policy"] == "sandbox"
    assert r.headers["content-disposition"] == (
        "inline; filename=\"Resume front.png\"; filename*=UTF-8''R%C3%A9sum%C3%A9%20front.png"
    )
    etag = r.headers["etag"]
    assert etag == f'"{hashlib.sha256(PNG).hexdigest()}"'
    assert r.headers.get_list("cache-control")[0] == "private, no-cache"
    assert r.headers["content-length"] == str(len(PNG))
    again = api.get(f"/api/v1/files/{file_id}/content", headers={"If-None-Match": etag})
    assert again.status_code == 304 and again.content == b""


def test_only_images_and_pdfs_are_inline(api: ApiClient, people) -> None:  # type: ignore[no-untyped-def]
    api.as_(people["meera"].actor())
    pdf_id = upload(api, PDF, "spec.pdf", "document").json()["id"]
    csv_id = upload(api, b"a,b\n1,2\n", "rates.csv", "document").json()["id"]
    xlsx_id = upload(api, xlsx_bytes(), "list.xlsx", "import").json()["id"]
    assert api.get(f"/api/v1/files/{pdf_id}/content").headers["content-disposition"].startswith("inline;")
    csv = api.get(f"/api/v1/files/{csv_id}/content")
    assert csv.headers["content-disposition"].startswith("attachment;")
    assert csv.headers["content-type"] == "text/csv; charset=utf-8"
    assert api.get(f"/api/v1/files/{xlsx_id}/content").headers["content-disposition"].startswith("attachment;")


def test_unreferenced_upload_is_visible_only_to_its_uploader(api: ApiClient, people) -> None:  # type: ignore[no-untyped-def]
    file_id = upload(api.as_(people["meera"].actor()), PNG, "draft.png").json()["id"]
    r = api.as_(people["neha"].actor()).get(f"/api/v1/files/{file_id}/content")
    assert r.status_code == 404 and problem(r)["code"] == "not_found"
    assert api.as_(people["priya"].actor()).get(f"/api/v1/files/{file_id}/content").status_code == 404
    assert api.get(f"/api/v1/files/{uuid.uuid7()}/content").status_code == 404


def test_files_never_cross_tenants(api: ApiClient, people) -> None:  # type: ignore[no-untyped-def]
    from tests.support import create_company

    file_id = upload(api.as_(people["meera"].actor()), PNG, "a.png").json()["id"]
    other_company, _ = create_company()
    stranger = member(other_company, "Stranger", "admin").actor()
    assert api.as_(stranger).get(f"/api/v1/files/{file_id}/content").status_code == 404


def test_access_is_decided_by_the_attaching_parent(api: ApiClient, people, company) -> None:  # type: ignore[no-untyped-def]
    company_id, _ = company
    file_id = upload(api.as_(people["meera"].actor()), PNG, "tray.png").json()["id"]

    def parent_check(uow: UnitOfWork, obj: FileObject) -> bool | None:
        if str(obj.id) != file_id:
            return None
        return uow.actor.can("sales.quote.read", Scope.COMPANY)

    register_file_access("test.quote_photo", parent_check)
    try:
        assert api.as_(people["priya"].actor()).get(f"/api/v1/files/{file_id}/content").status_code == 200
        # referenced but the parent is not readable: even the uploader is refused
        r = api.as_(people["neha"].actor()).get(f"/api/v1/files/{file_id}/content")
        assert r.status_code == 404
        assert api.as_(people["meera"].actor()).get(f"/api/v1/files/{file_id}/content").status_code == 404
    finally:
        unregister_file_access("test.quote_photo")


def test_exports_are_creator_only_and_restricted_ones_are_never_cached(api: ApiClient, people, company) -> None:  # type: ignore[no-untyped-def]
    company_id, _ = company
    meera = people["meera"].actor()
    export = files.store_generated(meera, b"quote_number,total\nLK-QT-2026-0008,5760.00\n", filename="quotes.csv",
                                   restricted=True)
    assert export.purpose == "export" and export.restricted is True
    r = api.as_(meera).get(export.content_url)
    assert r.status_code == 200
    assert r.headers.get_list("cache-control")[0] == "no-store"
    assert r.headers["content-disposition"].startswith("attachment;")
    assert api.get(export.content_url, headers={"If-None-Match": r.headers["etag"]}).status_code == 200
    assert api.as_(people["priya"].actor()).get(export.content_url).status_code == 404
    downloads = audit_rows(company_id, "files.file.downloaded")
    assert downloads and downloads[-1].actor_user_id == people["meera"].user_id
    assert downloads[-1].details == {"purpose": "export", "restricted": True}


def test_generated_files_are_sniffed_too(people) -> None:  # type: ignore[no-untyped-def]
    from app.platform.files.errors import UnsupportedMediaType

    with pytest.raises(UnsupportedMediaType):
        files.store_generated(people["meera"].actor(), b"<html></html>", filename="report.pdf")


def test_company_logo_is_branding_every_member_can_load(api: ApiClient, people) -> None:  # type: ignore[no-untyped-def]
    priya = people["priya"].actor()
    logo = upload(api.as_(priya), PNG, "logo.png").json()
    gif = upload(api, image_bytes("GIF"), "logo.gif").json()
    r = api.put("/api/v1/org/settings/company_identity",
                json={"value": {"logo_file_id": gif["id"]}, "expected_version": 0})
    assert r.status_code == 422 and problem(r)["errors"][0]["code"] == "logo_not_image"
    r = api.put("/api/v1/org/settings/company_identity",
                json={"value": {"logo_file_id": logo["id"]}, "expected_version": 0})
    assert r.status_code == 200, r.text
    assert api.as_(people["neha"].actor()).get(logo["content_url"]).status_code == 200
    # another member cannot point the logo at a file they cannot read
    meera_file = upload(api.as_(people["meera"].actor()), image_bytes("PNG", (3, 3)), "mine.png").json()
    with pytest.raises(ValidationFailed) as exc:
        settings_service.update_setting(priya, "company_identity", value={"logo_file_id": meera_file["id"]},
                                        expected_version=1)
    assert exc.value.extra["errors"][0]["code"] == "file_not_found"
