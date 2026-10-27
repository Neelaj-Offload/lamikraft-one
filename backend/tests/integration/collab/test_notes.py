"""Internal notes: one note per record, authorised strictly through the parent (404 vs 403), optimistic saves."""

from __future__ import annotations

import uuid

import pytest

from app.core.errors import Forbidden, NotFound, VersionConflict
from app.platform.authz.permissions import Scope
from app.platform.collab import service as notes
from app.platform.collab.models import NOTE_MAX_CHARS
from app.seed.world import keys
from tests.integration.collab.conftest import PARENT_TYPE, make_parent
from tests.integration.org.platform_lane import ApiClient, events, grants, member, problem, without

pytestmark = pytest.mark.db

URL = "/api/v1/collab/notes"


@pytest.fixture
def world(company, parent_table):  # type: ignore[no-untyped-def]
    company_id, _ = company
    meera = member(company_id, keys.PEOPLE["MEERA"].name, "sales")
    neha = member(company_id, keys.PEOPLE["NEHA"].name, "sales")
    ravi = member(company_id, keys.PEOPLE["RAVI"].name, "employee", extra={"sales.quote.read": Scope.COMPANY})
    sahil = member(
        company_id,
        keys.PEOPLE["SAHIL"].name,
        "employee",
        extra={"sales.quote.read": Scope.COMPANY, "sales.quote.update": Scope.COMPANY},
    )
    parent = make_parent(company_id, meera.user_id)
    return {"company_id": company_id, "meera": meera, "neha": neha, "ravi": ravi, "sahil": sahil, "parent": parent}


def _params(parent: uuid.UUID, resource_type: str = PARENT_TYPE) -> dict[str, str]:
    return {"resource_type": resource_type, "resource_id": str(parent)}


def _save(api: ApiClient, parent: uuid.UUID, body: str, version: int, **kwargs):  # type: ignore[no-untyped-def]
    return api.put(URL, params=_params(parent), json={"body": body, "expected_version": version}, **kwargs)


def test_owner_reads_an_empty_note_then_saves_it(api: ApiClient, world) -> None:  # type: ignore[no-untyped-def]
    api.as_(world["meera"].actor())
    empty = api.get(URL, params=_params(world["parent"]))
    assert empty.status_code == 200, empty.text
    assert empty.json() | {"capabilities": None} == {
        "resource_type": PARENT_TYPE,
        "resource_id": str(world["parent"]),
        "note_id": None,
        "body": "",
        "version": 0,
        "updated_at": None,
        "updated_by": None,
        "updated_by_name": None,
        "capabilities": None,
    }
    assert empty.json()["capabilities"]["update"] == {"allowed": True, "reason_code": None}

    saved = _save(api, world["parent"], "Call Maison about finish preferences", 0)
    assert saved.status_code == 200, saved.text
    note = saved.json()
    assert note["version"] == 1 and note["body"] == "Call Maison about finish preferences"
    assert note["updated_by"] == str(world["meera"].user_id)
    assert note["updated_by_name"] == keys.PEOPLE["MEERA"].name
    assert note["updated_at"] == keys.CLOCK_D0.strftime("%Y-%m-%dT%H:%M:%SZ")
    emitted = events(world["company_id"], "collab.note.updated")
    assert [e.payload for e in emitted] == [
        {
            "resource_type": PARENT_TYPE,
            "resource_id": str(world["parent"]),
            "note_id": note["note_id"],
            "version": 1,
            "origin": "user",
        }
    ]
    assert emitted[0].aggregate_id == uuid.UUID(note["note_id"]) and emitted[0].aggregate_version == 1
    assert "Maison" not in str(emitted[0].payload)  # note text never travels in events


def test_parent_not_visible_is_404_for_read_and_write(api: ApiClient, world) -> None:  # type: ignore[no-untyped-def]
    api.as_(world["neha"].actor())  # sales, own scope: Meera's record is invisible to her
    r = api.get(URL, params=_params(world["parent"]))
    assert r.status_code == 404 and problem(r)["code"] == "not_found"
    r = _save(api, world["parent"], "overwrite", 0)
    assert r.status_code == 404
    with pytest.raises(NotFound):
        notes.save_note(world["neha"].actor(), PARENT_TYPE, world["parent"], body="x", expected_version=0)


def test_visible_parent_without_update_right_is_403(api: ApiClient, world) -> None:  # type: ignore[no-untyped-def]
    api.as_(world["ravi"].actor())  # may read every quote, may not edit any
    r = api.get(URL, params=_params(world["parent"]))
    assert r.status_code == 200
    assert r.json()["capabilities"]["update"] == {"allowed": False, "reason_code": "permission_denied"}
    r = _save(api, world["parent"], "overwrite", 0)
    assert r.status_code == 403 and problem(r)["code"] == "permission_denied"
    with pytest.raises(Forbidden):
        notes.save_note(world["ravi"].actor(), PARENT_TYPE, world["parent"], body="x", expected_version=0)


def test_unknown_parent_type_or_record_is_404(api: ApiClient, world) -> None:  # type: ignore[no-untyped-def]
    api.as_(world["meera"].actor())
    assert api.get(URL, params=_params(world["parent"], "sales.unknown_thing")).status_code == 404
    assert api.get(URL, params=_params(uuid.uuid7())).status_code == 404
    bad = api.get(URL, params={"resource_type": "DROP TABLE", "resource_id": str(world["parent"])})
    assert bad.status_code == 422


def test_other_tenants_cannot_reach_the_note(api: ApiClient, world) -> None:  # type: ignore[no-untyped-def]
    from tests.support import create_company

    other, _ = create_company()
    admin = member(other, "Other Admin", "admin").actor()
    assert api.as_(admin).get(URL, params=_params(world["parent"])).status_code == 404


def test_stale_version_is_409_with_the_current_note(api: ApiClient, world) -> None:  # type: ignore[no-untyped-def]
    parent = world["parent"]
    assert _save(api.as_(world["meera"].actor()), parent, "Mine v1", 0).status_code == 200
    theirs = _save(api.as_(world["sahil"].actor()), parent, "Sahil: price agreed", 1)
    assert theirs.status_code == 200 and theirs.json()["version"] == 2
    conflict = _save(api.as_(world["meera"].actor()), parent, "Mine v2", 1)
    assert conflict.status_code == 409
    body = problem(conflict)
    assert body["code"] == "version_conflict"
    assert body["current_version"] == 2
    assert body["current"]["body"] == "Sahil: price agreed"
    assert body["current"]["updated_by_name"] == keys.PEOPLE["SAHIL"].name
    assert body["changed_by"] == str(world["sahil"].user_id)
    # keep mine: re-save against the new version
    assert _save(api, parent, "Mine v2", 2).json()["version"] == 3


def test_first_save_conflicts_when_someone_created_the_note(world) -> None:  # type: ignore[no-untyped-def]
    notes.save_note(world["sahil"].actor(), PARENT_TYPE, world["parent"], body="first", expected_version=0)
    with pytest.raises(VersionConflict) as exc:
        notes.save_note(world["meera"].actor(), PARENT_TYPE, world["parent"], body="also first", expected_version=0)
    assert exc.value.extra["current"]["body"] == "first"


def test_unchanged_body_does_not_bump_the_version(world) -> None:  # type: ignore[no-untyped-def]
    actor = world["meera"].actor()
    first = notes.save_note(actor, PARENT_TYPE, world["parent"], body="same", expected_version=0)
    again = notes.save_note(actor, PARENT_TYPE, world["parent"], body="same", expected_version=1)
    assert first.version == again.version == 1
    assert len(events(world["company_id"], "collab.note.updated")) == 1


def test_body_length_is_limited(api: ApiClient, world) -> None:  # type: ignore[no-untyped-def]
    r = _save(api.as_(world["meera"].actor()), world["parent"], "x" * (NOTE_MAX_CHARS + 1), 0)
    assert r.status_code == 422
    assert "x" * 50 not in r.text  # validation errors never echo input


def test_idempotency_key_replays_the_save(api: ApiClient, world) -> None:  # type: ignore[no-untyped-def]
    key = str(uuid.uuid7())
    api.as_(world["meera"].actor())
    first = _save(api, world["parent"], "retry me", 0, headers={"Idempotency-Key": key})
    replay = _save(api, world["parent"], "retry me", 0, headers={"Idempotency-Key": key})
    assert first.status_code == replay.status_code == 200
    assert replay.json()["version"] == 1 and replay.json()["note_id"] == first.json()["note_id"]
    assert len(events(world["company_id"], "collab.note.updated")) == 1
    # a replay is only answered while the parent is still editable by the caller
    demoted = world["meera"].actor(permissions=without(grants("sales"), "sales.quote.update"))
    lost = _save(api.as_(demoted), world["parent"], "retry me", 0, headers={"Idempotency-Key": key})
    assert lost.status_code == 403
