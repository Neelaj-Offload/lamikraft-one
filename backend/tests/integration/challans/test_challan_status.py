"""Transitions (API-60, LM-83, FG-DC-12): validated through the table, issued challans immutable except the note."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.core.errors import Conflict, InvalidTransition, ValidationFailed
from app.modules.challans import service as challans
from app.modules.challans.schemas import (
    ChallanLineAdd,
    ChallanLineUpdate,
    ChallanTransition,
    ChallanUpdate,
    LineType,
)
from app.modules.challans.transitions import transition_challan, transition_challan_command
from app.platform.collab import service as notes
from app.seed.world import keys
from tests.integration.challans.conftest import CHALLANS, as_, problem
from tests.integration.challans.world import ChallanWorld

pytestmark = pytest.mark.db
RAVI = keys.USERS.RAVI


def test_transitions_validated_and_issued_immutable(challan_world: ChallanWorld) -> None:
    w = challan_world
    draft = w.new_draft(RAVI, ("OAK_TRAY", "10"), party_id=w.ref("NORDHAUS"))
    assert [t.action for t in draft.allowed_transitions] == ["issue", "cancel"]
    with w.uow(RAVI) as uow:
        # the legacy "any status string" is gone: unknown or out-of-table actions are 409 with the allowed list
        for action in ("close", "reopen", "issued"):
            with pytest.raises(InvalidTransition) as exc:
                transition_challan(uow, draft.id, ChallanTransition(action=action, expected_version=draft.version))
            assert {t["action"] for t in exc.value.extra["allowed_transitions"]} == {"issue", "cancel"}
            assert exc.value.extra["current_status"] == "draft"
        with pytest.raises(ValidationFailed):  # cancel needs a reason
            transition_challan(uow, draft.id, ChallanTransition(action="cancel", expected_version=draft.version))
        with pytest.raises(ValidationFailed):  # issue over HTTP semantics: the command requires an Idempotency-Key
            transition_challan_command(uow, draft.id, ChallanTransition(action="issue", expected_version=draft.version))
    issued = w.transition(RAVI, draft.id, "issue")
    assert issued.status == "issued" and issued.revision_no == 1 and issued.issued_at is not None and issued.issued_by
    assert [t.action for t in issued.allowed_transitions] == ["close", "cancel"]
    assert issued.capabilities["update"].allowed is False and issued.capabilities["update"].reason_code == "challan_not_editable"
    assert issued.capabilities["add_line"].allowed is False and issued.capabilities["note"].allowed is True
    assert issued.capabilities["export"].allowed and issued.inventory_effect == "none"
    assert [h.action for h in issued.history] == ["issue"]
    with w.uow(RAVI) as uow:  # immutable: header, lines (add / edit / remove) all 409 challan_not_editable
        with pytest.raises(Conflict) as exc:
            challans.update_challan(uow, issued.id, ChallanUpdate(expected_version=issued.version, remarks="late edit"))
        assert exc.value.code == "challan_not_editable"
        with pytest.raises(Conflict):
            challans.add_line(uow, issued.id, ChallanLineAdd(expected_version=issued.version, line_type=LineType.MANUAL, item_name="x", quantity=Decimal(1)))
        with pytest.raises(Conflict):
            challans.update_line(uow, issued.id, issued.lines[0].id, ChallanLineUpdate(expected_version=issued.version, quantity=Decimal(2)))
        with pytest.raises(Conflict):
            challans.remove_line(uow, issued.id, issued.lines[0].id, expected_version=issued.version)
        with pytest.raises(InvalidTransition):  # issue twice
            transition_challan(uow, issued.id, ChallanTransition(action="issue", expected_version=issued.version))
        # the internal note stays editable after issue (FG-DC-11): it lives in collab, authorised through the challan
        note = notes.save_note(uow, "challans.challan", issued.id, body="Driver to call before 9", expected_version=0)
        assert note.version == 1 and notes.get_note(uow, "challans.challan", issued.id).body == "Driver to call before 9"
    closed = w.transition(RAVI, issued.id, "close", reason="Received at site")
    assert closed.status == "closed" and closed.closed_at is not None and closed.close_reason == "Received at site"
    assert closed.allowed_transitions == [] and [h.action for h in closed.history] == ["issue", "close"]
    with w.uow(RAVI) as uow:
        with pytest.raises(InvalidTransition):  # terminal
            transition_challan(uow, closed.id, ChallanTransition(action="cancel", expected_version=closed.version, reason="x"))
    # cancel from draft (with a reason), terminal afterwards
    other = w.new_draft(RAVI, ("OAK_TRAY", "1"), party_id=w.ref("NORDHAUS"))
    cancelled = w.transition(RAVI, other.id, "cancel", reason_code="duplicate_entry", reason="Raised twice")
    assert cancelled.status == "cancelled" and cancelled.cancel_reason_code == "duplicate_entry" and cancelled.allowed_transitions == []


def test_transition_over_http_is_replay_safe_and_conflicts_are_problems(challan_client, challan_world: ChallanWorld) -> None:  # type: ignore[no-untyped-def]
    w = challan_world
    draft = w.new_draft(RAVI, ("OAK_TRAY", "5"), party_id=w.ref("NORDHAUS"))
    url = f"{CHALLANS}/{draft.id}/transitions"
    no_key = challan_client.post(url, json={"action": "issue", "expected_version": draft.version}, headers=as_(RAVI))
    problem(no_key, 422, "idempotency_key_required")
    key = str(uuid.uuid7())
    first = challan_client.post(url, json={"action": "issue", "expected_version": draft.version}, headers=as_(RAVI, **{"Idempotency-Key": key}))
    assert first.status_code == 200 and first.json()["status"] == "issued", first.text
    again = challan_client.post(url, json={"action": "issue", "expected_version": draft.version}, headers=as_(RAVI, **{"Idempotency-Key": key}))
    assert again.status_code == 200 and again.headers.get("Idempotent-Replayed") == "true" and again.json()["revision_no"] == 1
    revisions = challan_client.get(f"{CHALLANS}/{draft.id}/revisions", headers=as_(RAVI)).json()
    assert len(revisions) == 1  # the replay did not issue a second revision
    stale = challan_client.post(url, json={"action": "close", "expected_version": draft.version}, headers=as_(RAVI))
    problem(stale, 409, "version_conflict")
    bad = challan_client.post(url, json={"action": "issue", "expected_version": first.json()["version"]}, headers=as_(RAVI, **{"Idempotency-Key": str(uuid.uuid7())}))
    body = problem(bad, 409, "invalid_transition")
    assert {t["action"] for t in body["allowed_transitions"]} == {"close", "cancel"}
    edit = challan_client.patch(f"{CHALLANS}/{draft.id}", json={"expected_version": first.json()["version"], "remarks": "x"}, headers=as_(RAVI))
    problem(edit, 409, "challan_not_editable")
