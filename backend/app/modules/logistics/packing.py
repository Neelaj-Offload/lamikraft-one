"""Packing arithmetic (operations.md §8), pure and Decimal throughout.

For a quantity ``q`` of a product with a packaging snapshot:
- ``full = floor(q / carton_qty)``, ``loose = q - full x carton_qty``, ``cartons = full + (1 if loose > 0)``; a loose
  remainder is a *part carton*;
- inner packs: ``ceil(q / inner_qty)`` when the inner quantity is known;
- carton CBM: the stated CBM, else L x W x H / 1,000,000 from the carton dimensions in cm; when both exist and differ by
  more than 2 % the line is incomplete (``cbm_conflict``);
- ``cbm = cartons x carton_cbm`` (a part carton occupies a whole carton);
- net weight: ``full x carton_net + loose x unit_weight`` (or ``q x unit_weight`` when the carton net is unknown);
- gross weight: ``full x carton_gross + loose x unit_weight``; the part carton's tare is unknown, so a line with a
  loose remainder is flagged an *estimate*;
- results are rounded HALF_UP to the minor unit: CBM to 0.000001 m3 (1 cm3), weights to 0.001 kg (1 g).
Missing data marks the line incomplete with reasons (``missing_carton_qty``, ``missing_cbm``, ``missing_gross_weight``,
``missing_net_weight``); totals over incomplete lines are labelled partial. An entered override (with a reason)
replaces a missing or conflicting value and clears the corresponding reason.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal

CBM_PLACES = Decimal("0.000001")
KG_PLACES = Decimal("0.001")
CONFLICT_TOLERANCE = Decimal("0.02")
ZERO = Decimal(0)


@dataclass(frozen=True)
class PackagingSnapshot:
    carton_qty: int | None = None
    inner_qty: int | None = None
    carton_length_cm: Decimal | None = None
    carton_width_cm: Decimal | None = None
    carton_height_cm: Decimal | None = None
    stated_carton_cbm: Decimal | None = None
    #: kg per unit (from the catalogue's grams)
    unit_weight_kg: Decimal | None = None
    carton_net_kg: Decimal | None = None
    carton_gross_kg: Decimal | None = None
    is_fragile: bool = False


@dataclass(frozen=True)
class Overrides:
    cbm: Decimal | None = None
    net_kg: Decimal | None = None
    gross_kg: Decimal | None = None


@dataclass(frozen=True)
class LineResult:
    full_cartons: int | None
    loose_qty: Decimal | None
    cartons: int | None
    inner_packs: int | None
    is_part_carton: bool
    carton_cbm: Decimal | None
    cbm: Decimal | None
    net_kg: Decimal | None
    gross_kg: Decimal | None
    is_estimate: bool
    incomplete_reasons: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_complete(self) -> bool:
        return not self.incomplete_reasons


def _q(value: Decimal, places: Decimal) -> Decimal:
    return value.quantize(places, rounding=ROUND_HALF_UP)


def dimension_cbm(s: PackagingSnapshot) -> Decimal | None:
    if s.carton_length_cm and s.carton_width_cm and s.carton_height_cm:
        return (
            Decimal(s.carton_length_cm)
            * Decimal(s.carton_width_cm)
            * Decimal(s.carton_height_cm)
            / Decimal(1_000_000)
        )
    return None


def compute_line(quantity: Decimal, s: PackagingSnapshot, overrides: Overrides | None = None) -> LineResult:
    if isinstance(quantity, float):
        raise TypeError("quantities must be Decimal")
    q = Decimal(quantity)
    o = overrides or Overrides()
    reasons: list[str] = []
    full: int | None = None
    loose: Decimal | None = None
    cartons: int | None = None
    if s.carton_qty:
        cq = Decimal(s.carton_qty)
        full = int((q / cq).to_integral_value(rounding=ROUND_FLOOR))
        loose = q - full * cq
        cartons = full + (1 if loose > 0 else 0)
    else:
        reasons.append("missing_carton_qty")
    inner = int((q / Decimal(s.inner_qty)).to_integral_value(rounding=ROUND_CEILING)) if s.inner_qty else None
    part = bool(loose and loose > 0)

    # carton CBM: stated, else from dimensions; a stated-vs-dimension conflict over 2 % is incomplete
    stated = Decimal(s.stated_carton_cbm) if s.stated_carton_cbm is not None else None
    from_dims = dimension_cbm(s)
    carton_cbm = stated if stated is not None else from_dims
    conflict = (
        stated is not None
        and from_dims is not None
        and stated > 0
        and abs(stated - from_dims) / stated > CONFLICT_TOLERANCE
    )
    cbm: Decimal | None = None
    if o.cbm is not None:
        cbm = _q(Decimal(o.cbm), CBM_PLACES)
    elif conflict:
        reasons.append("cbm_conflict")
    elif carton_cbm is None:
        reasons.append("missing_cbm")
    elif cartons is not None:
        cbm = _q(cartons * carton_cbm, CBM_PLACES)

    unit = Decimal(s.unit_weight_kg) if s.unit_weight_kg is not None else None
    net: Decimal | None = None
    if o.net_kg is not None:
        net = _q(Decimal(o.net_kg), KG_PLACES)
    elif (
        s.carton_net_kg is not None
        and full is not None
        and loose is not None
        and (loose == 0 or unit is not None)
    ):
        net = _q(full * Decimal(s.carton_net_kg) + loose * (unit or ZERO), KG_PLACES)
    elif unit is not None:
        net = _q(q * unit, KG_PLACES)
    else:
        reasons.append("missing_net_weight")

    gross: Decimal | None = None
    estimate = False
    if o.gross_kg is not None:
        gross = _q(Decimal(o.gross_kg), KG_PLACES)
    elif (
        s.carton_gross_kg is not None
        and full is not None
        and loose is not None
        and (loose == 0 or unit is not None)
    ):
        gross = _q(full * Decimal(s.carton_gross_kg) + loose * (unit or ZERO), KG_PLACES)
        estimate = loose > 0
    else:
        reasons.append("missing_gross_weight")

    return LineResult(
        full_cartons=full,
        loose_qty=loose,
        cartons=cartons,
        inner_packs=inner,
        is_part_carton=part,
        carton_cbm=_q(carton_cbm, CBM_PLACES) if carton_cbm is not None else None,
        cbm=cbm,
        net_kg=net,
        gross_kg=gross,
        is_estimate=estimate,
        incomplete_reasons=tuple(reasons),
    )


@dataclass(frozen=True)
class Totals:
    cartons: int
    cbm: Decimal
    net_kg: Decimal
    gross_kg: Decimal
    is_partial: bool
    has_estimates: bool


def totals(results: list[LineResult]) -> Totals:
    return Totals(
        cartons=sum(r.cartons or 0 for r in results),
        cbm=sum((r.cbm or ZERO for r in results), ZERO),
        net_kg=sum((r.net_kg or ZERO for r in results), ZERO),
        gross_kg=sum((r.gross_kg or ZERO for r in results), ZERO),
        is_partial=any(not r.is_complete for r in results),
        has_estimates=any(r.is_estimate for r in results),
    )
