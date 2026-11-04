"""Load suggestion: deterministic first-fit decreasing by carton CBM, whole cartons, respecting
``volume x fill factor`` and payload, labelled as a suggestion (no 3D stowage)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.logistics.load_planner import LABEL, CartonLine, Container, plan

D = Decimal
C20 = Container(volume_m3=D("33.2"), max_payload_kg=D("28200"), fill_factor=D("0.85"))


def test_respects_capacity_and_payload_and_labels_estimate() -> None:
    # usable 33.2 x 0.85 = 28.22 m3 holds 593 tray cartons (0.04752 m3, 11.6 kg): one container, volume-bound
    one = plan([CartonLine(1, "LK-OT-0450", 593, D("0.04752"), D("11.6"))], C20)
    assert len(one.loads) == 1 and one.loads[0].allocations[0].cartons == 593
    vol, kg, binding = one.utilisation(C20, one.loads[0])
    assert (vol, kg, binding) == (D("99.9"), D("24.4"), "volume")
    assert one.label == LABEL and "no 3D stowage" in LABEL
    # 600 cartons overflow by 7: whole cartons split into a second container
    two = plan([CartonLine(1, "LK-OT-0450", 600, D("0.04752"), D("11.6"))], C20)
    assert [a.cartons for load in two.loads for a in load.allocations] == [593, 7] or \
        sum(a.cartons for load in two.loads for a in load.allocations) == 600
    assert all(load.cbm <= C20.usable_cbm and load.kg <= C20.max_payload_kg for load in two.loads)
    # heavy boards: payload binds before volume
    heavy = plan([CartonLine(1, "LK-WB-1800", 40, D("0.20"), D("900"))], C20)
    assert [sum(a.cartons for a in load.allocations) for load in heavy.loads] == [31, 9]
    assert heavy.utilisation(C20, heavy.loads[0])[2] == "weight"


def test_deterministic_unplanned_and_fragile_flags() -> None:
    lines = [
        CartonLine(1, "SMALL", 10, D("0.01"), D("1")),
        CartonLine(2, "BIG", 5, D("0.50"), D("20"), is_fragile=True),
        CartonLine(3, "NODIMS", 3, None, D("2")),
        CartonLine(4, "HUGE", 1, D("40"), D("5")),
    ]
    a, b = plan(lines, C20), plan(list(reversed(lines)), C20)
    assert [(x.line_no, x.cartons) for x in a.loads[0].allocations] == [(2, 5), (1, 10)]  # decreasing CBM
    assert [(x.line_no, x.cartons) for x in b.loads[0].allocations] == [(2, 5), (1, 10)]
    assert a.unplanned == [(3, "missing_dimensions_or_weight"), (4, "carton_exceeds_container")]
    assert a.manual_review == [2]
    with pytest.raises(ValueError):
        plan(lines, Container(volume_m3=D("1"), max_payload_kg=D("1"), fill_factor=D("1.2")))
