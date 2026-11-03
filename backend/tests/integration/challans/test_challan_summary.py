"""The summary cards (LM-88, API-58, UI-28): computed server-side over the same filters and scope as the list."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.challans import service as challans
from app.modules.challans.schemas import ChallanFilters, ChallanType
from app.seed.world import keys
from tests.integration.challans.conftest import CHALLANS, as_
from tests.integration.challans.world import ChallanWorld

pytestmark = pytest.mark.db
RAVI, SAHIL, MEERA = keys.USERS.RAVI, keys.USERS.SAHIL, keys.USERS.MEERA


def test_summary_counts_scoped(challan_world: ChallanWorld) -> None:
    w = challan_world
    with w.uow(SAHIL) as uow:  # management: company scope
        s = challans.summary(uow, ChallanFilters())
        assert s.total == 3 and s.issued == 2 and s.this_week == 1 and s.this_month == 3
        assert s.pending_returnable == 2
        assert s.pending_returnable_quantity == {"pcs": Decimal("2"), "sheets": Decimal("12")}  # per unit, never added across units
        assert {b.key: b.count for b in s.by_type}["job_work"] == 1 and {b.key: b.count for b in s.by_type}["sample"] == 1
        assert {b.key: b.count for b in s.by_type}["outward"] == 1 and {b.key: b.count for b in s.by_type}["transfer"] == 0
        assert {b.key: b.count for b in s.by_destination} == {"fabricator": 1, "customer": 2, "warehouse": 0, "vendor": 0, "office": 0, "transporter": 0}
        assert {b.key: b.count for b in s.by_status} == {"draft": 1, "issued": 2, "closed": 0, "cancelled": 0}
        assert [b.label for b in s.by_type][:2] == ["Outward", "Inward"] and s.week_start.isoformat() == "2026-10-12"
        filtered = challans.summary(uow, ChallanFilters(challan_type=[ChallanType.SAMPLE]))
        assert filtered.total == 1 and filtered.pending_returnable == 1 and filtered.pending_returnable_quantity == {"pcs": Decimal("2")}
        assert challans.summary(uow, ChallanFilters(q="JW-0918")).total == 1
    with w.uow(MEERA) as uow:  # sales, own scope: none of Ravi's challans
        s = challans.summary(uow, ChallanFilters())
        assert s.total == 0 and s.pending_returnable == 0 and s.pending_returnable_quantity == {}
        assert all(b.count == 0 for b in s.by_type + s.by_destination + s.by_status)


def test_summary_and_list_agree_over_http(challan_client, challan_world: ChallanWorld) -> None:  # type: ignore[no-untyped-def]
    ravi = as_(RAVI)
    listed = challan_client.get(CHALLANS, params={"limit": 50}, headers=ravi).json()
    summary = challan_client.get(f"{CHALLANS}/summary", headers=ravi).json()
    assert summary["total"] == listed["total"] == 3
    assert summary["pending_returnable_quantity"] == {"pcs": "2", "sheets": "12"}
    assert sum(b["count"] for b in summary["by_status"]) == listed["total"]
    pending = challan_client.get(CHALLANS, params={"pending_returnable": "true"}, headers=ravi).json()
    assert pending["total"] == summary["pending_returnable"]
