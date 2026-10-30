"""Attachments and activity on any record (platform-2 item 4; PARITY LM-98, UI-29 backend, SEC-03, API-68, API-27):
parent read to see, parent update to change, downloads follow the parent, activity filtered by parent visibility."""

from __future__ import annotations

import io
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from PIL import Image

from app.platform.authz.permissions import Scope
from app.platform.files.storage import LocalFsStorage, set_storage
from app.seed.world import keys
from tests.integration.collab.conftest import PARENT_TYPE, make_parent
from tests.integration.org.platform_lane import ApiClient, member

pytestmark = pytest.mark.db

ATT = "/api/v1/collab/attachments"
ACT = "/api/v1/collab/activity"


@pytest.fixture(autouse=True)
def storage(tmp_path: Path) -> Iterator[LocalFsStorage]:
    backend = LocalFsStorage(tmp_path / "storage")
    set_storage(backend)
    yield backend
    set_storage(None)


def photo(size: tuple[int, int] = (1600, 900)) -> bytes:
    img = Image.new("RGB", size, (180, 140, 90))
    exif = Image.Exif()
    exif[0x010F] = "SecretCamera"  # Make
    out = io.BytesIO()
    img.save(out, format="JPEG", exif=exif.tobytes())
    return out.getvalue()


@pytest.fixture
def world(company, parent_table):  # type: ignore[no-untyped-def]
    company_id, _ = company
    meera = member(company_id, keys.PEOPLE["MEERA"].name, "sales")
    neha = member(company_id, keys.PEOPLE["NEHA"].name, "sales")
    ravi = member(company_id, keys.PEOPLE["RAVI"].name, "employee", extra={"sales.quote.read": Scope.COMPANY})
    return {
        "company_id": company_id,
        "meera": meera,
        "neha": neha,
        "ravi": ravi,
        "mine": make_parent(company_id, meera.user_id),
        "nehas": make_parent(company_id, neha.user_id),
    }


def _upload(api: ApiClient, data: bytes, name: str = "tray.jpg", purpose: str = "image") -> str:
    r = api.post(f"/api/v1/files?purpose={purpose}", files={"file": (name, data, "image/jpeg" if name.endswith("jpg") else "application/pdf")})
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


def _attach(api: ApiClient, parent: uuid.UUID, file_id: str, title: str | None = None):  # type: ignore[no-untyped-def]
    return api.post(ATT, json={"resource_type": PARENT_TYPE, "resource_id": str(parent), "file_id": file_id, "title": title})


def test_attachments_need_parent_rights_and_downloads_follow_the_parent(api: ApiClient, world) -> None:  # type: ignore[no-untyped-def]
    api.as_(world["meera"].actor())
    file_id = _upload(api, photo())
    added = _attach(api, world["mine"], file_id, "Packed tray")
    assert added.status_code == 201, added.text
    att = added.json()
    assert att["role"] == "image" and att["title"] == "Packed tray" and att["thumbnail_url"].endswith("?variant=thumb")
    assert _attach(api, world["mine"], file_id).json()["code"] == "already_attached"

    listed = api.get(ATT, params={"resource_type": PARENT_TYPE, "resource_id": str(world["mine"])}).json()
    assert [a["id"] for a in listed["items"]] == [att["id"]] and listed["capabilities"]["add"]["allowed"] is True

    # the thumbnail is small and carries no EXIF; the original is unchanged
    thumb = api.get(att["thumbnail_url"])
    assert thumb.status_code == 200 and thumb.headers["content-type"] == "image/jpeg"
    with Image.open(io.BytesIO(thumb.content)) as img:
        assert max(img.size) == 256 and not img.getexif()
    medium = api.get(f"/api/v1/files/{file_id}/content?variant=medium")
    with Image.open(io.BytesIO(medium.content)) as img:
        assert max(img.size) == 1024
    assert api.get(f"/api/v1/files/{file_id}/content?variant=huge").status_code == 422

    # Neha (own scope) cannot see Meera's record: 404 for the list, the file and its variants
    api.as_(world["neha"].actor())
    assert api.get(ATT, params={"resource_type": PARENT_TYPE, "resource_id": str(world["mine"])}).status_code == 404
    assert api.get(f"/api/v1/files/{file_id}/content").status_code == 404
    assert api.get(att["thumbnail_url"]).status_code == 404
    neha_file = _upload(api, photo((40, 40)), "other.jpg")
    assert _attach(api, world["mine"], neha_file).status_code == 404
    assert api.request("DELETE", f"{ATT}/{att['id']}").status_code == 404

    # Ravi reads every quote (company) but cannot update: sees and downloads, cannot add or remove
    api.as_(world["ravi"].actor())
    ravi_view = api.get(ATT, params={"resource_type": PARENT_TYPE, "resource_id": str(world["mine"])}).json()
    assert ravi_view["capabilities"]["add"]["allowed"] is False and ravi_view["items"][0]["capabilities"]["update"]["allowed"] is False
    assert api.get(f"/api/v1/files/{file_id}/content").status_code == 200
    ravi_file = _upload(api, photo((30, 30)), "r.jpg")
    assert _attach(api, world["mine"], ravi_file).status_code == 403
    assert api.request("DELETE", f"{ATT}/{att['id']}").status_code == 403
    # a file the actor cannot read can never be attached (Neha's upload, by Meera)
    api.as_(world["meera"].actor())
    assert _attach(api, world["mine"], neha_file).json()["errors"][0]["code"] == "file_not_found"

    # rename (optimistic) and remove
    renamed = api.request("PATCH", f"{ATT}/{att['id']}", json={"title": "Tray, packed", "expected_version": att["version"]})
    assert renamed.status_code == 200 and renamed.json()["title"] == "Tray, packed"
    stale = api.request("PATCH", f"{ATT}/{att['id']}", json={"title": "x", "expected_version": att["version"]})
    assert stale.status_code == 409
    assert api.request("DELETE", f"{ATT}/{att['id']}").status_code == 204
    assert api.get(ATT, params={"resource_type": PARENT_TYPE, "resource_id": str(world["mine"])}).json()["items"] == []
    # unknown resource types are 404, never an existence leak
    assert api.get(ATT, params={"resource_type": "nope.thing", "resource_id": str(uuid.uuid7())}).status_code == 404


def test_feed_filtered_by_parent_visibility(api: ApiClient, world) -> None:  # type: ignore[no-untyped-def]
    api.as_(world["meera"].actor())
    _attach(api, world["mine"], _upload(api, photo((50, 50)), "a.jpg"))
    api.put("/api/v1/collab/notes", params={"resource_type": PARENT_TYPE, "resource_id": str(world["mine"])}, json={"body": "CANARY-MEERA", "expected_version": 0})
    api.as_(world["neha"].actor())
    api.put("/api/v1/collab/notes", params={"resource_type": PARENT_TYPE, "resource_id": str(world["nehas"])}, json={"body": "hello", "expected_version": 0})

    # Meera's timeline: her record's note and attachment, newest first
    api.as_(world["meera"].actor())
    timeline = api.get(ACT, params={"resource_type": PARENT_TYPE, "resource_id": str(world["mine"])})
    assert timeline.status_code == 200, timeline.text
    assert [i["event_type"] for i in timeline.json()["items"]] == ["collab.note.updated", "collab.attachment.added"]
    assert timeline.json()["items"][0]["summary"] == "Note updated" and "CANARY" not in timeline.text

    # Neha's feed never contains Meera's record; Meera's never contains Neha's; Ravi (company read) sees both
    api.as_(world["neha"].actor())
    neha_feed = api.get(ACT).json()["items"]
    assert {i["resource_id"] for i in neha_feed} == {str(world["nehas"])}
    assert api.get(ACT, params={"resource_type": PARENT_TYPE, "resource_id": str(world["mine"])}).status_code == 404
    api.as_(world["ravi"].actor())
    assert {i["resource_id"] for i in api.get(ACT).json()["items"]} == {str(world["mine"]), str(world["nehas"])}

    # keyset paging never repeats or skips
    first = api.get(ACT, params={"limit": 2}).json()
    rest = api.get(ACT, params={"limit": 2, "before": first["next_cursor"]}).json()
    assert len(first["items"]) == 2 and first["next_cursor"] and len(rest["items"]) == 1 and rest["next_cursor"] is None
    assert not {i["id"] for i in first["items"]} & {i["id"] for i in rest["items"]}
    assert api.get(ACT, params={"before": "%%%"}).status_code == 422
    # without collab.activity.read: 403
    api.as_(world["ravi"].actor().with_(permissions={"sales.quote.read": Scope.COMPANY}))
    assert api.get(ACT).status_code == 403
