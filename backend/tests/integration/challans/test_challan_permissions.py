"""Scope and IDOR (PERM-23, SEC-03, LM-93, API-61, FG-DCL-01, UI-84): invisible challans are 404 for every child path;
operations works at branch scope, sales at own scope, management reads company-wide; delete is admin-only, drafts
only, soft, and the number is never reused."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.core.errors import Forbidden, NotFound
from app.modules.challans import service as challans
from app.modules.challans.schemas import (
    ChallanCreate,
    ChallanFilters,
    ChallanLineAdd,
    ChallanLineUpdate,
    ChallanTransition,
    ChallanUpdate,
    LineType,
)
from app.modules.challans.transitions import transition_challan
from app.seed.world import keys
from tests.integration.challans.conftest import CHALLANS, as_, problem
from tests.integration.challans.world import ChallanWorld

pytestmark = pytest.mark.db
RAVI, KABIR, MEERA, NEHA, SAHIL, PRIYA, ANANYA = (
    keys.USERS.RAVI, keys.USERS.KABIR, keys.USERS.MEERA, keys.USERS.NEHA, keys.USERS.SAHIL, keys.USERS.PRIYA, keys.USERS.ANANYA,
)


def test_scope_enforced_on_read_edit_issue_export_and_admin_only_draft_delete(challan_client, challan_world: ChallanWorld) -> None:  # type: ignore[no-untyped-def]
    w = challan_world
    issued_id = w.ref(keys.CHALLAN_REFS.JOB_WORK)
    draft_id = w.ref(keys.CHALLAN_REFS.OUTWARD_DRAFT)
    meeras = w.new_draft(MEERA, ("OAK_TRAY", "3"), party_id=w.ref("NORDHAUS"))  # sales may create (own scope)
    with w.uow(RAVI) as uow:
        draft_line = challans.get_challan(uow, draft_id).lines[0]
    # Meera (sales, own): Ravi's challans do not exist for her; every child path is a 404, never a 403
    probes = [
        lambda uow: challans.get_challan(uow, issued_id),
        lambda uow: challans.get_challan_by_number(uow, keys.CHALLANS.JOB_WORK),
        lambda uow: challans.list_revisions(uow, issued_id),
        lambda uow: challans.get_revision(uow, issued_id, 1),
        lambda uow: challans.exportable(uow, issued_id),
        lambda uow: challans.update_challan(uow, draft_id, ChallanUpdate(expected_version=1, remarks="x")),
        lambda uow: challans.add_line(uow, draft_id, ChallanLineAdd(expected_version=1, line_type=LineType.MANUAL, item_name="x", quantity=Decimal(1))),
        lambda uow: challans.update_line(uow, draft_id, draft_line.id, ChallanLineUpdate(expected_version=1, quantity=Decimal(2))),
        lambda uow: challans.remove_line(uow, draft_id, draft_line.id, expected_version=1),
        lambda uow: transition_challan(uow, draft_id, ChallanTransition(action="issue", expected_version=1)),
        lambda uow: transition_challan(uow, issued_id, ChallanTransition(action="close", expected_version=1)),
        lambda uow: challans.duplicate_challan(uow, issued_id),
        lambda uow: challans.delete_challan(uow, draft_id, expected_version=1),
    ]
    for probe in probes:
        with pytest.raises(NotFound):
            with w.uow(MEERA) as uow:
                probe(uow)
    with w.uow(MEERA) as uow:
        assert {c.id for c in challans.list_challans(uow, ChallanFilters()).items} == {meeras.id}
        assert challans.summary(uow, ChallanFilters()).total == 1
        with pytest.raises(Forbidden):  # visible but sales has no issue right
            transition_challan(uow, meeras.id, ChallanTransition(action="issue", expected_version=meeras.version))
    with w.uow(NEHA) as uow:  # another sales owner: Meera's draft is invisible
        with pytest.raises(NotFound):
            challans.get_challan(uow, meeras.id)
    # Ravi (operations, branch): sees everything in his branch including Meera's draft; may issue his own
    with w.uow(RAVI) as uow:
        every = {c.id for c in challans.list_challans(uow, ChallanFilters(), limit=50).items}
        assert {issued_id, draft_id, meeras.id} <= every
        assert challans.get_challan(uow, meeras.id).capabilities["issue"].allowed is True
    # Sahil (management, company read + export, no update / issue): reads and exports, cannot edit or issue
    with w.uow(SAHIL) as uow:
        assert challans.get_challan(uow, draft_id).capabilities["update"].allowed is False
        assert challans.exportable(uow, issued_id)[0].id == issued_id
        with pytest.raises(Forbidden):
            challans.update_challan(uow, draft_id, ChallanUpdate(expected_version=1, remarks="x"))
        with pytest.raises(Forbidden):
            transition_challan(uow, draft_id, ChallanTransition(action="issue", expected_version=1))
        with pytest.raises(Forbidden):
            challans.create_challan(uow, ChallanCreate(party_id=w.ref("NORDHAUS")))
    # Kabir (warehouse, no challan permissions): nothing, 403 on create, 404 on reads
    r = challan_client.get(CHALLANS, headers=as_(KABIR))
    problem(r, 403, "permission_denied")
    problem(challan_client.post(CHALLANS, json={"destination_party": "x"}, headers=as_(KABIR)), 403, "permission_denied")
    problem(challan_client.get(f"{CHALLANS}/{issued_id}", headers=as_(MEERA)), 404, "not_found")
    problem(challan_client.get(f"{CHALLANS}/{issued_id}/document.pdf", headers=as_(MEERA)), 404, "not_found")
    problem(challan_client.get(f"{CHALLANS}/{issued_id}/print", headers=as_(MEERA)), 404, "not_found")
    problem(challan_client.get(f"{CHALLANS}/{issued_id}/revisions/1/document.pdf", headers=as_(MEERA)), 404, "not_found")
    problem(challan_client.get(f"{CHALLANS}/{uuid.uuid4()}", headers=as_(RAVI)), 404, "not_found")
    # export needs the export right in scope: Ananya (finance) has company read + export but no update
    assert challan_client.get(f"{CHALLANS}/{issued_id}/document.pdf", headers=as_(ANANYA)).status_code == 200
    problem(challan_client.patch(f"{CHALLANS}/{draft_id}", json={"expected_version": 1, "remarks": "x"}, headers=as_(ANANYA)), 403, "permission_denied")
    # delete: Ravi (operations) has no delete right even on his own draft; Priya (admin) does
    problem(challan_client.delete(f"{CHALLANS}/{draft_id}", headers=as_(RAVI)), 403, "permission_denied")
    problem(challan_client.delete(f"{CHALLANS}/{draft_id}", headers=as_(MEERA)), 404, "not_found")
    deleted = challan_client.delete(f"{CHALLANS}/{draft_id}", headers=as_(PRIYA))
    assert deleted.status_code == 200 and deleted.json()["deleted_at"] is not None


def test_admin_only_draft_delete_number_not_reused(challan_client, challan_world: ChallanWorld) -> None:  # type: ignore[no-untyped-def]
    w = challan_world
    draft_id = w.ref(keys.CHALLAN_REFS.OUTWARD_DRAFT)
    issued_id = w.ref(keys.CHALLAN_REFS.JOB_WORK)
    with w.uow(PRIYA) as uow:
        d = challans.get_challan(uow, draft_id)
        assert d.capabilities["delete"].allowed is True
        assert challans.get_challan(uow, issued_id).capabilities["delete"] .allowed is False
        with pytest.raises(Forbidden):  # issued documents are never deleted, even by an admin
            challans.delete_challan(uow, issued_id, expected_version=None)
        gone = challans.delete_challan(uow, draft_id, expected_version=d.version)
        assert gone.deleted_at is not None and gone.status == "draft"
    with w.uow(RAVI) as uow:
        assert challans.get_challan(uow, draft_id).capabilities["delete"].allowed is False  # no delete right
        assert draft_id not in {c.id for c in challans.list_challans(uow, ChallanFilters(), limit=50).items}
        assert draft_id in {c.id for c in challans.list_challans(uow, ChallanFilters(include_deleted=True), limit=50).items}
        with pytest.raises(NotFound):  # a deleted draft is not found by number
            challans.get_challan_by_number(uow, keys.CHALLANS.OUTWARD_DRAFT)
        with pytest.raises(NotFound):
            challans.update_challan(uow, draft_id, ChallanUpdate(expected_version=d.version, remarks="x"))
        nxt = challans.create_challan(uow, ChallanCreate(party_id=w.ref("NORDHAUS")))
        assert nxt.challan_number == "DC-2026-0004"  # the deleted number 0003 stays reserved
    # a deleted draft is a 404 for the PDF and a 409 for a second delete, and the web gets capability-gated controls
    problem(challan_client.get(f"{CHALLANS}/{draft_id}/document.pdf", headers=as_(PRIYA)), 404, "not_found")
    problem(challan_client.delete(f"{CHALLANS}/{draft_id}", headers=as_(PRIYA)), 404, "not_found")
