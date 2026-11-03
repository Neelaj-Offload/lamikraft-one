"""Canonical keys the optimiser groups and locks on (pure; reuses the catalogue's identifier rules).

- Decor: trimmed text; leading zeros are kept (``"0120"`` and ``"120"`` are different decors) and the legacy float
  artefact ``"120.0"`` is the decor ``"120"`` (warning ``DECOR_FLOAT_ARTEFACT_NORMALISED``), the same rule the
  catalogue and the imports apply, so a grain lock on ``120`` also locks pieces entered as ``120.0`` (FG-GRN-01).
- Thickness: a canonical millimetre Decimal, so ``0.8`` and ``0.80`` are one group.
- Dimensions: millimetres with at most one decimal place (the packer works in integer deci-millimetres).
"""

from __future__ import annotations

from decimal import Decimal

from app.modules.catalogue.normalise import normalise_identifier, normalise_thickness, plain_decimal

DECOR_MAX = 40


def canonical_decor(value: str | None) -> tuple[str, tuple[str, ...]]:
    """``(decor_key, warnings)``; a blank decor is ``""`` (the packer treats it as grain-locked)."""
    if value is None:
        return "", ()
    result = normalise_identifier(value, float_artefact_rule=True)
    return (result.value or ""), result.warnings


def thickness_key(value: Decimal | str | None) -> str:
    """Normalised thickness text (``"18"``, ``"0.8"``); ``""`` when unknown."""
    if value is None:
        return ""
    mm = normalise_thickness(value)
    return plain_decimal(mm) if mm is not None else ""
