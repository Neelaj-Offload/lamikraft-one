"""Packing arithmetic (operations.md §8): cartons, inner packs, CBM and weights in Decimal, HALF_UP to the minor unit
(CBM 0.000001 m3, weights 0.001 kg), with incomplete / estimate flags. The OAK tray figures are the fixture
packaging of LK-OT-0450 (carton 24, inner 6, 450 g, 48 x 33 x 30 cm, CBM 0.047520, net 10.8 kg, gross 11.6 kg)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.logistics.packing import Overrides, PackagingSnapshot, compute_line, totals

D = Decimal
OAK = PackagingSnapshot(carton_qty=24, inner_qty=6, carton_length_cm=D("48"), carton_width_cm=D("33"),
                        carton_height_cm=D("30"), stated_carton_cbm=D("0.047520"), unit_weight_kg=D("0.450"),
                        carton_net_kg=D("10.8"), carton_gross_kg=D("11.6"))


def test_cartons_cbm_weights_and_incomplete_flags() -> None:
    full = compute_line(D(240), OAK)
    assert (full.full_cartons, full.loose_qty, full.cartons, full.inner_packs) == (10, 0, 10, 40)
    assert (full.cbm, full.net_kg, full.gross_kg) == (D("0.475200"), D("108.000"), D("116.000"))
    assert full.is_complete and not full.is_estimate and not full.is_part_carton
    part = compute_line(D(250), OAK)  # 10 full cartons + 10 loose: a part carton
    assert (part.full_cartons, part.loose_qty, part.cartons, part.inner_packs) == (10, 10, 11, 42)
    assert part.cbm == D("0.522720")  # 11 x 0.047520: the part carton occupies a whole carton
    assert part.net_kg == D("112.500") and part.gross_kg == D("120.500")  # 10 x 11.6 + 10 x 0.45
    assert part.is_part_carton and part.is_estimate and part.is_complete  # tare of the part carton unknown
    # dimensions only: 48 x 33 x 30 / 1e6
    dims = compute_line(D(24), PackagingSnapshot(carton_qty=24, carton_length_cm=D("48"), carton_width_cm=D("33"),
                                                 carton_height_cm=D("30"), carton_gross_kg=D("11.6"),
                                                 carton_net_kg=D("10.8")))
    assert dims.carton_cbm == D("0.047520") and dims.cbm == D("0.047520")
    # stated vs dimension CBM over 2 % apart: incomplete
    conflict = compute_line(D(24), PackagingSnapshot(**{**OAK.__dict__, "stated_carton_cbm": D("0.050000")}))
    assert conflict.incomplete_reasons == ("cbm_conflict",) and conflict.cbm is None
    within = compute_line(D(24), PackagingSnapshot(**{**OAK.__dict__, "stated_carton_cbm": D("0.048000")}))
    assert within.is_complete and within.cbm == D("0.048000")  # 1 % apart: the stated value wins
    # nothing known (pallet goods): every reason listed, totals partial
    bare = compute_line(D(40), PackagingSnapshot())
    assert set(bare.incomplete_reasons) == {"missing_carton_qty", "missing_cbm", "missing_net_weight",
                                            "missing_gross_weight"}
    t = totals([full, bare])
    assert (t.cartons, t.cbm, t.gross_kg, t.is_partial) == (10, D("0.475200"), D("116.000"), True)
    # entered values (with a reason, stored by the service) clear the reasons
    fixed = compute_line(D(40), PackagingSnapshot(), Overrides(cbm=D("1.25"), net_kg=D("410"), gross_kg=D("432.5")))
    assert fixed.incomplete_reasons == ("missing_carton_qty",) and fixed.cbm == D("1.250000")


def test_half_up_to_the_minor_unit() -> None:
    s = PackagingSnapshot(carton_qty=7, carton_length_cm=D("10.15"), carton_width_cm=D("10.15"),
                          carton_height_cm=D("10.15"), unit_weight_kg=D("0.0015"), carton_net_kg=D("0.0105"),
                          carton_gross_kg=D("0.0115"))
    r = compute_line(D(7), s)
    assert r.carton_cbm == D("0.001046")  # 1045.678375 cm3 -> 0.001046 m3 (HALF_UP)
    assert r.net_kg == D("0.011") and r.gross_kg == D("0.012")  # 0.0105 -> 0.011, 0.0115 -> 0.012
    with pytest.raises(TypeError):
        compute_line(1.5, OAK)  # type: ignore[arg-type]


@settings(max_examples=150, derandomize=True)
@given(qty=st.integers(min_value=1, max_value=50_000), carton=st.integers(min_value=1, max_value=500))
def test_carton_identity(qty: int, carton: int) -> None:
    r = compute_line(D(qty), PackagingSnapshot(carton_qty=carton, stated_carton_cbm=D("0.01"), unit_weight_kg=D("0.2"),
                                               carton_net_kg=D("0.2") * carton, carton_gross_kg=D("0.25") * carton))
    assert r.full_cartons * carton + r.loose_qty == qty  # type: ignore[operator]
    assert 0 <= r.loose_qty < carton  # type: ignore[operator]
    assert r.cartons == r.full_cartons + (1 if r.loose_qty else 0)  # type: ignore[operator]
    assert r.net_kg == (D("0.2") * qty).quantize(D("0.001"))
    assert r.gross_kg >= r.net_kg  # type: ignore[operator]
