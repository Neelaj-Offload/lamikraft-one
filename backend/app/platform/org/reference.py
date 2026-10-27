"""Reference data: the global currency list and the per-company unit-of-measure master (conventions §6).

``convert`` only uses conversions that exist: a product-specific row for the pair, then a generic row, in
either direction (the reverse divides by the factor). Anything else is a 422 ``uom_conversion_missing`` —
conversions are never guessed or chained. Integer units (pcs, nos, sheets, box, set, roll, bundle, carton)
accept whole numbers only; other units accept at most 4 decimal places at entry.
"""

from __future__ import annotations

import unicodedata
import uuid
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Context, Decimal
from typing import TYPE_CHECKING

from sqlalchemy import and_, or_, select

from app.core.errors import NotFound, ValidationFailed
from app.core.money import QUANTITY_STORAGE_PLACES
from app.platform.org.models import (
    Currency,
    Uom,
    UomAlias,
    UomConversion,
    UomConversionProvenance,
    UomDimension,
)
from app.platform.org.schemas import CurrencyRead, UomConversionRead, UomRead
from app.platform.service import command, query

if TYPE_CHECKING:
    from app.platform.uow import UnitOfWork

MAX_ENTRY_DECIMALS = 4
_DIVISION = Context(prec=40, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class UomSeed:
    code: str
    name: str
    dimension: UomDimension
    is_integer: bool
    aliases: tuple[str, ...]


#: the seeded unit master (conventions §6) with common spellings from legacy data, imports and voice
DEFAULT_UOMS: tuple[UomSeed, ...] = (
    UomSeed("pcs", "Pieces", UomDimension.COUNT, True, ("pc", "piece", "pieces", "pce", "pcs.")),
    UomSeed("nos", "Numbers", UomDimension.COUNT, True, ("no", "no.", "nos.", "number", "numbers")),
    UomSeed("sheets", "Sheets", UomDimension.COUNT, True, ("sheet", "sht", "shts")),
    UomSeed("kg", "Kilograms", UomDimension.MASS, False, ("kgs", "kilogram", "kilograms", "kilo", "kg.")),
    UomSeed("g", "Grams", UomDimension.MASS, False, ("gm", "gms", "gram", "grams", "gr", "grm")),
    UomSeed("m", "Metres", UomDimension.LENGTH, False, ("mtr", "mtrs", "meter", "meters", "metre", "metres")),
    UomSeed("mm", "Millimetres", UomDimension.LENGTH, False, ("millimeter", "millimeters", "millimetre", "millimetres")),
    UomSeed("cm", "Centimetres", UomDimension.LENGTH, False, ("cms", "centimeter", "centimeters", "centimetre", "centimetres")),
    UomSeed("sqm", "Square metres", UomDimension.AREA, False, ("sq m", "sq.m", "sq. m", "m2", "m²", "square meter", "square metre", "square meters", "square metres")),
    UomSeed("sqft", "Square feet", UomDimension.AREA, False, ("sq ft", "sq.ft", "sq. ft", "ft2", "ft²", "square foot", "square feet")),
    UomSeed("box", "Boxes", UomDimension.PACK, True, ("boxes", "bx")),
    UomSeed("set", "Sets", UomDimension.PACK, True, ("sets",)),
    UomSeed("roll", "Rolls", UomDimension.PACK, True, ("rolls",)),
    UomSeed("bundle", "Bundles", UomDimension.PACK, True, ("bundles", "bdl", "bdls")),
    UomSeed("carton", "Cartons", UomDimension.PACK, True, ("cartons", "ctn", "ctns")),
)

#: exact, product-independent conversions (1 from = factor to); pack units convert only per product
DEFAULT_CONVERSIONS: tuple[tuple[str, str, str], ...] = (
    ("kg", "g", "1000"),
    ("m", "mm", "1000"),
    ("m", "cm", "100"),
    ("cm", "mm", "10"),
    ("sqft", "sqm", "0.09290304"),  # exact by definition (0.3048 m)²
    ("pcs", "nos", "1"),  # both are counts of single items
)


def normalize_unit_text(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text).casefold().strip()
    return " ".join(folded.split())


# ---- currencies -------------------------------------------------------------------------------------------
@query()
def list_currencies(uow: UnitOfWork) -> list[CurrencyRead]:
    rows = uow.session.scalars(select(Currency).where(Currency.enabled.is_(True)).order_by(Currency.sort_order, Currency.code))
    return [CurrencyRead(code=c.code, name=c.name, symbol=c.symbol, exponent=c.exponent) for c in rows]


# ---- unit master ------------------------------------------------------------------------------------------
def ensure_default_uoms(uow: UnitOfWork) -> int:
    """Create the seeded units, aliases and standard conversions for the actor's company (idempotent)."""
    company_id = uow.actor.company_id
    if company_id is None:
        raise ValueError("a company context is required")
    existing = set(uow.session.scalars(select(Uom.code).where(Uom.company_id == company_id)))
    created = 0
    for order, seed in enumerate(DEFAULT_UOMS, start=1):
        if seed.code not in existing:
            uow.add(
                Uom(
                    company_id=company_id,
                    code=seed.code,
                    name=seed.name,
                    dimension=seed.dimension.value,
                    is_integer=seed.is_integer,
                    sort_order=order,
                )
            )
            created += 1
    uow.flush()
    aliases = set(uow.session.scalars(select(UomAlias.alias).where(UomAlias.company_id == company_id)))
    for seed in DEFAULT_UOMS:
        for alias in seed.aliases:
            text = normalize_unit_text(alias)
            if text not in aliases and text != seed.code:
                uow.add(UomAlias(company_id=company_id, alias=text, uom_code=seed.code))
                aliases.add(text)
    pairs = {
        (row.from_code, row.to_code)
        for row in uow.session.execute(
            select(UomConversion.from_code, UomConversion.to_code).where(
                UomConversion.company_id == company_id, UomConversion.product_id.is_(None)
            )
        )
    }
    for from_code, to_code, factor in DEFAULT_CONVERSIONS:
        if (from_code, to_code) not in pairs and (to_code, from_code) not in pairs:
            uow.add(
                UomConversion(
                    company_id=company_id,
                    from_code=from_code,
                    to_code=to_code,
                    factor=Decimal(factor),
                    provenance=UomConversionProvenance.STANDARD.value,
                )
            )
    uow.flush()
    return created


def _uom_by_code(uow: UnitOfWork) -> dict[str, Uom]:
    rows = uow.session.scalars(select(Uom).where(Uom.company_id == uow.actor.company_id, Uom.active.is_(True)))
    return {u.code: u for u in rows}


def resolve_uom_code(uow: UnitOfWork, text: str) -> str | None:
    """The canonical code for an active unit's code or alias (case/space-insensitive); None when unknown or
    when the unit is inactive (its aliases stop resolving with it)."""
    normalized = normalize_unit_text(text)
    if not normalized:
        return None
    company_id = uow.actor.company_id
    code = uow.session.scalar(
        select(Uom.code).where(Uom.company_id == company_id, Uom.code == normalized, Uom.active.is_(True))
    )
    if code is not None:
        return code
    return uow.session.scalar(
        select(UomAlias.uom_code)
        .join(Uom, and_(Uom.company_id == UomAlias.company_id, Uom.code == UomAlias.uom_code))
        .where(UomAlias.company_id == company_id, UomAlias.alias == normalized, Uom.active.is_(True))
    )


@query()
def list_uoms(uow: UnitOfWork) -> list[UomRead]:
    company_id = uow.actor.company_id
    units = list(
        uow.session.scalars(
            select(Uom).where(Uom.company_id == company_id, Uom.active.is_(True)).order_by(Uom.sort_order, Uom.code)
        )
    )
    alias_rows = uow.session.execute(
        select(UomAlias.uom_code, UomAlias.alias).where(UomAlias.company_id == company_id).order_by(UomAlias.alias)
    ).all()
    aliases: dict[str, list[str]] = {}
    for code, alias in alias_rows:
        aliases.setdefault(code, []).append(alias)
    conversions: dict[str, list[UomConversionRead]] = {}
    for conv in uow.session.scalars(
        select(UomConversion)
        .where(UomConversion.company_id == company_id, UomConversion.product_id.is_(None))
        .order_by(UomConversion.from_code, UomConversion.to_code)
    ):
        conversions.setdefault(conv.from_code, []).append(
            UomConversionRead(from_code=conv.from_code, to_code=conv.to_code, factor=conv.factor, provenance=conv.provenance)
        )
    return [
        UomRead(
            code=u.code,
            name=u.name,
            dimension=u.dimension,
            is_integer=u.is_integer,
            max_decimal_places=0 if u.is_integer else MAX_ENTRY_DECIMALS,
            aliases=aliases.get(u.code, []),
            conversions=conversions.get(u.code, []),
        )
        for u in units
    ]


def _missing(from_uom: str, to_uom: str, product_id: uuid.UUID | None, unknown: list[str]) -> ValidationFailed:
    return ValidationFailed(
        f"No conversion from {from_uom} to {to_uom} is defined.",
        code="uom_conversion_missing",
        from_uom=from_uom,
        to_uom=to_uom,
        product_id=str(product_id) if product_id else None,
        unknown_uoms=unknown,
    )


def _factor(uow: UnitOfWork, from_code: str, to_code: str, product_id: uuid.UUID | None) -> Decimal | None:
    """Factor such that ``qty_from * factor = qty_to``: product row first, then generic; direct, then reverse."""
    company_id = uow.actor.company_id
    scopes: list[uuid.UUID | None] = [product_id, None] if product_id is not None else [None]
    for scope in scopes:
        product_filter = UomConversion.product_id.is_(None) if scope is None else UomConversion.product_id == scope
        direct = uow.session.scalar(
            select(UomConversion.factor).where(
                UomConversion.company_id == company_id,
                UomConversion.from_code == from_code,
                UomConversion.to_code == to_code,
                product_filter,
            )
        )
        if direct is not None:
            return Decimal(direct)
        reverse = uow.session.scalar(
            select(UomConversion.factor).where(
                UomConversion.company_id == company_id,
                UomConversion.from_code == to_code,
                UomConversion.to_code == from_code,
                product_filter,
            )
        )
        if reverse is not None:
            return _DIVISION.divide(Decimal(1), Decimal(reverse))
    return None


@query()
def convert(
    uow: UnitOfWork, qty: Decimal, from_uom: str, to_uom: str, product_id: uuid.UUID | None = None
) -> Decimal:
    """Convert ``qty`` between units, quantized to the storage precision (6 dp, HALF_UP). Never guesses."""
    if isinstance(qty, float) or not isinstance(qty, Decimal | int):
        raise TypeError("quantities must be Decimal (floats are rejected)")
    qty = Decimal(qty)
    from_code = resolve_uom_code(uow, from_uom)
    to_code = resolve_uom_code(uow, to_uom)
    unknown = [text for text, code in ((from_uom, from_code), (to_uom, to_code)) if code is None]
    if from_code is None or to_code is None:
        raise _missing(from_uom, to_uom, product_id, unknown)
    if from_code == to_code:
        return qty.quantize(QUANTITY_STORAGE_PLACES, rounding=ROUND_HALF_UP)
    factor = _factor(uow, from_code, to_code, product_id)
    if factor is None:
        raise _missing(from_code, to_code, product_id, [])
    return _DIVISION.multiply(qty, factor).quantize(QUANTITY_STORAGE_PLACES, rounding=ROUND_HALF_UP)


def validate_quantity(uow: UnitOfWork, value: Decimal, uom: str, *, allow_zero: bool = False) -> tuple[Decimal, str]:
    """Entry rule per unit: integers only for integer units, otherwise at most 4 decimal places; > 0."""
    if isinstance(value, float) or not isinstance(value, Decimal | int):
        raise TypeError("quantities must be Decimal (floats are rejected)")
    value = Decimal(value)
    code = resolve_uom_code(uow, uom)
    unit = _uom_by_code(uow).get(code) if code is not None else None
    if unit is None:
        raise ValidationFailed(
            f"Unknown unit {uom!r}.",
            errors=[{"loc": ["uom"], "msg": "unknown unit of measure", "code": "uom_unknown"}],
        )
    exponent = value.normalize().as_tuple().exponent
    places = -exponent if isinstance(exponent, int) and exponent < 0 else 0
    if unit.is_integer and places > 0:
        raise ValidationFailed(
            f"{unit.name} are counted in whole numbers.",
            errors=[{"loc": ["quantity"], "msg": "whole numbers only for this unit", "code": "not_integer"}],
        )
    if places > MAX_ENTRY_DECIMALS:
        raise ValidationFailed(
            "Use at most 4 decimal places.",
            errors=[{"loc": ["quantity"], "msg": "at most 4 decimal places", "code": "too_many_decimals"}],
        )
    if value < 0 or (value == 0 and not allow_zero):
        raise ValidationFailed(
            "Quantities must be greater than zero.",
            errors=[{"loc": ["quantity"], "msg": "must be greater than zero", "code": "not_positive"}],
        )
    return value, code


@command("org.uom.manage")
def define_conversion(
    uow: UnitOfWork,
    from_uom: str,
    to_uom: str,
    factor: Decimal,
    *,
    product_id: uuid.UUID | None = None,
    provenance: UomConversionProvenance = UomConversionProvenance.MANUAL,
) -> UomConversionRead:
    """Create or replace the conversion between two units (product packaging conversions come from the catalogue).

    A unit pair has one conversion per product scope, stored in one direction. Defining ``b -> a`` when
    ``a -> b`` exists replaces that row (direction and factor as given now, so the stated factor stays exact)
    instead of adding a second row that could disagree with it; the database enforces the same rule.
    """
    if isinstance(factor, float) or not isinstance(factor, Decimal):
        raise TypeError("factors must be Decimal (floats are rejected)")
    if factor <= 0:
        raise ValidationFailed(errors=[{"loc": ["factor"], "msg": "must be greater than zero", "code": "not_positive"}])
    from_code, to_code = resolve_uom_code(uow, from_uom), resolve_uom_code(uow, to_uom)
    if from_code is None or to_code is None:
        raise NotFound(code="not_found", resource_type="org.uom")
    if from_code == to_code:
        raise ValidationFailed(errors=[{"loc": ["to_uom"], "msg": "units must differ", "code": "same_unit"}])
    low, high = sorted((from_code, to_code))
    uow.advisory_xact_lock("org.uom_conversion", f"{uow.actor.company_id}:{low}:{high}:{product_id}")
    product_filter = UomConversion.product_id.is_(None) if product_id is None else UomConversion.product_id == product_id
    row = uow.session.scalars(
        select(UomConversion)
        .where(
            UomConversion.company_id == uow.actor.company_id,
            or_(
                and_(UomConversion.from_code == from_code, UomConversion.to_code == to_code),
                and_(UomConversion.from_code == to_code, UomConversion.to_code == from_code),
            ),
            product_filter,
        )
        .with_for_update()
    ).first()
    if row is None:
        row = uow.add(
            UomConversion(
                company_id=uow.actor.company_id,
                from_code=from_code,
                to_code=to_code,
                factor=factor,
                product_id=product_id,
                provenance=provenance.value,
            )
        )
    else:
        row.from_code = from_code
        row.to_code = to_code
        row.factor = factor
        row.provenance = provenance.value
    uow.flush()
    uow.audit(
        "org.uom_conversion.defined",
        resource_type="org.uom_conversion",
        resource_id=row.id,
        resource_label=f"{from_code}->{to_code}",
        details={"product_id": str(product_id) if product_id else None, "provenance": provenance.value},
    )
    return UomConversionRead(from_code=from_code, to_code=to_code, factor=row.factor, provenance=row.provenance)
