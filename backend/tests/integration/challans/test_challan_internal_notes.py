"""LM-95, FG-DC-11: the internal note of a challan is a collab note on ``challans.challan``, authorised through the
challan, editable after issue, and never part of any printed or exported output (PDF, print view, CSV, snapshot)."""

from __future__ import annotations

import csv
import io

import pytest
from pypdf import PdfReader

from app.core.errors import NotFound
from app.modules.challans import service as challans
from app.platform.collab import service as notes
from app.seed.world import keys
from tests.integration.catalogue.world import member_actors, personas  # noqa: F401
from tests.integration.challans.conftest import CHALLANS, as_, challan_client  # noqa: F401
from tests.integration.challans.world import ChallanWorld, challan_world, world  # noqa: F401
from tests.integration.sales.http import api_app  # noqa: F401

pytestmark = pytest.mark.db
RAVI, MEERA, SAHIL = keys.USERS.RAVI, keys.USERS.MEERA, keys.USERS.SAHIL
NOTE = "INTERNAL: customer disputes the last invoice — ask Sahil before releasing the next lot"
URL = "/api/v1/collab/notes"


def test_notes_never_printed(challan_client, challan_world: ChallanWorld) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    w = challan_world
    cid = w.ref(keys.CHALLAN_REFS.JOB_WORK)
    params = {"resource_type": "challans.challan", "resource_id": str(cid)}
    saved = challan_client.put(URL, params=params, json={"body": NOTE, "expected_version": 0}, headers=as_(RAVI))
    assert saved.status_code == 200 and saved.json()["version"] == 1, saved.text
    assert challan_client.get(URL, params=params, headers=as_(RAVI)).json()["body"] == NOTE
    # the note is nowhere in the outputs
    detail = challan_client.get(f"{CHALLANS}/{cid}", headers=as_(RAVI)).json()
    pdf = challan_client.get(f"{CHALLANS}/{cid}/document.pdf", headers=as_(RAVI)).content
    pdf_text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(pdf)).pages)
    view = challan_client.get(f"{CHALLANS}/{cid}/print", headers=as_(RAVI)).json()
    csv_body = challan_client.get(f"{CHALLANS}/export.csv", headers=as_(RAVI)).content.decode("utf-8")
    revision = challan_client.get(f"{CHALLANS}/{cid}/revisions/1", headers=as_(RAVI)).json()
    for channel, text in (("detail", str(detail)), ("pdf", pdf_text), ("print", str(view)), ("csv", csv_body), ("snapshot", str(revision["snapshot"]))):
        assert "INTERNAL" not in text and "disputes" not in text, channel
    assert all(not row or "INTERNAL" not in "".join(row) for row in csv.reader(io.StringIO(csv_body.lstrip("﻿"))))
    # authorised through the challan: Meera (invisible) is 404; Sahil (read, no update) reads but cannot write
    assert challan_client.get(URL, params=params, headers=as_(MEERA)).status_code == 404
    sahil = challan_client.get(URL, params=params, headers=as_(SAHIL))
    assert sahil.status_code == 200 and sahil.json()["capabilities"]["update"]["allowed"] is False
    assert challan_client.put(URL, params=params, json={"body": "x", "expected_version": 1}, headers=as_(SAHIL)).status_code == 403
    with w.uow(MEERA) as uow:
        with pytest.raises(NotFound):
            notes.get_note(uow, "challans.challan", cid)
    with w.uow(RAVI) as uow:  # the challan itself knows nothing of the note (it is not a column)
        assert not hasattr(challans.get_challan(uow, cid), "internal_notes")
