"""Load suggestion (operations.md §8), pure and deterministic: first-fit decreasing by carton CBM.

Lines are sorted by carton CBM (descending), then carton weight, then line number. Each line's cartons are placed whole
into the first container with room by both volume (``internal volume x fill factor``) and payload; a new container is
opened when none has room. The result names the containers, what each holds, utilisation and the binding constraint.
It is a **suggestion**: a volume / weight check only; no 3D stowage, stacking or carrier acceptance is verified, and
fragile lines are flagged for manual planning. Lines without CBM or weight cannot be planned and are listed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal

LABEL = "Suggestion: volume and weight check only; no 3D stowage, stacking or carrier acceptance verified."
ZERO = Decimal(0)


@dataclass(frozen=True)
class CartonLine:
    line_no: int
    ref: str
    cartons: int
    carton_cbm: Decimal | None
    carton_kg: Decimal | None
    is_fragile: bool = False


@dataclass(frozen=True)
class Container:
    volume_m3: Decimal
    max_payload_kg: Decimal
    fill_factor: Decimal

    @property
    def usable_cbm(self) -> Decimal:
        return self.volume_m3 * self.fill_factor


@dataclass
class Allocation:
    line_no: int
    ref: str
    cartons: int


@dataclass
class Load:
    index: int
    cbm: Decimal = ZERO
    kg: Decimal = ZERO
    allocations: list[Allocation] = field(default_factory=list)


@dataclass(frozen=True)
class LoadResult:
    loads: list[Load]
    unplanned: list[tuple[int, str]]
    manual_review: list[int]
    label: str = LABEL

    def utilisation(self, c: Container, load: Load) -> tuple[Decimal, Decimal, str]:
        """(volume %, payload %, binding constraint) to one decimal place, HALF_UP."""
        vol = (load.cbm / c.usable_cbm * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        kg = (load.kg / c.max_payload_kg * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        return vol, kg, "volume" if vol >= kg else "weight"


def plan(lines: list[CartonLine], c: Container) -> LoadResult:
    if c.volume_m3 <= 0 or c.max_payload_kg <= 0 or not (ZERO < c.fill_factor <= 1):
        raise ValueError("container capacity, payload and fill factor must be positive (fill factor <= 1)")
    unplanned: list[tuple[int, str]] = []
    plannable: list[CartonLine] = []
    for ln in lines:
        if ln.cartons <= 0:
            continue
        if ln.carton_cbm is None or ln.carton_kg is None or ln.carton_cbm <= 0 or ln.carton_kg < 0:
            unplanned.append((ln.line_no, "missing_dimensions_or_weight"))
        elif ln.carton_cbm > c.usable_cbm or ln.carton_kg > c.max_payload_kg:
            unplanned.append((ln.line_no, "carton_exceeds_container"))
        else:
            plannable.append(ln)
    plannable.sort(key=lambda x: (-x.carton_cbm, -x.carton_kg, x.line_no))  # type: ignore[operator]
    loads: list[Load] = []
    for ln in plannable:
        remaining = ln.cartons
        assert ln.carton_cbm is not None and ln.carton_kg is not None
        while remaining > 0:
            target = None
            fit = 0
            for load in loads:
                fit = _fits(load, ln, c, remaining)
                if fit > 0:
                    target = load
                    break
            if target is None:
                target = Load(index=len(loads) + 1)
                loads.append(target)
                fit = _fits(target, ln, c, remaining)
            target.allocations.append(Allocation(ln.line_no, ln.ref, fit))
            target.cbm += fit * ln.carton_cbm
            target.kg += fit * ln.carton_kg
            remaining -= fit
    manual = sorted({ln.line_no for ln in lines if ln.is_fragile})
    return LoadResult(loads=loads, unplanned=unplanned, manual_review=manual)


def _fits(load: Load, ln: CartonLine, c: Container, wanted: int) -> int:
    assert ln.carton_cbm is not None and ln.carton_kg is not None
    by_cbm = ((c.usable_cbm - load.cbm) / ln.carton_cbm).to_integral_value(rounding=ROUND_FLOOR)
    by_kg = (
        ((c.max_payload_kg - load.kg) / ln.carton_kg).to_integral_value(rounding=ROUND_FLOOR)
        if ln.carton_kg > 0
        else Decimal(wanted)
    )
    return max(0, min(wanted, int(by_cbm), int(by_kg)))
