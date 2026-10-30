"""Grounding: ID provenance, numeric provenance, the price guard, the numeric-claim checker and taint detection
(docs/architecture/ai-routing.md section 6).

Everything here is pure (no database): the tools runtime feeds it the facts of the run — ids the user has seen
(re-read screen context, object context, earlier tool outputs, card actions), the user's turn text and the
numeric values that appeared in tool outputs — and it answers before any service is called.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal

from app.modules.agents import numbers

QuantitySource = Literal["user_turn", "record", "clarification"]
QUANTITY_SOURCES: tuple[str, ...] = ("user_turn", "record", "clarification")
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
_DECIMAL = re.compile(r"^-?\d{1,14}(\.\d{1,6})?$")
#: input field names that carry quantities (provenance required)
_QUANTITY_NAMES = re.compile(r"^(quantity|qty|.*_quantity|.*_qty)$")
#: input field names that would carry a price or amount (never a model input); identifiers, codes, types,
#: statuses and flags that merely mention "price" (``price_list_item_id``, ``price_type``) are not prices
_PRICE_NAMES = re.compile(r"^(?!.*(?:_id|_code|_type|_key|_status|_source|_requested|_list|_basis)$)(?!price_list)"
                          r"(.*price.*|.*amount.*|.*total.*|rate|.*_rate|.*subtotal.*|surcharge)$")
PRICE_OVERRIDE_FIELD = "price_override"
SEE_CARD = "see card"


class GroundingError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ---- walking values ---------------------------------------------------------------------------------------------
def _walk(value: Any) -> Iterator[tuple[str, Any]]:
    """Yield (key, leaf) pairs for every leaf in a nested mapping/sequence (key = the nearest mapping key)."""
    stack: list[tuple[str, Any]] = [("", value)]
    while stack:
        key, current = stack.pop()
        if isinstance(current, Mapping):
            stack.extend((str(k), v) for k, v in current.items())
        elif isinstance(current, (list, tuple, set, frozenset)):
            stack.extend((key, v) for v in current)
        else:
            yield key, current


def uuids_in(value: Any) -> set[uuid.UUID]:
    """Every UUID found anywhere in a nested value (uuid objects or canonical strings)."""
    found: set[uuid.UUID] = set()
    for _, leaf in _walk(value):
        if isinstance(leaf, uuid.UUID):
            found.add(leaf)
        elif isinstance(leaf, str) and _UUID.match(leaf):
            found.add(uuid.UUID(leaf))
    return found


def decimals_in(value: Any) -> set[Decimal]:
    """Every numeric value found anywhere in a nested value (ints, Decimals, decimal strings)."""
    found: set[Decimal] = set()
    for _, leaf in _walk(value):
        if isinstance(leaf, bool):
            continue
        if isinstance(leaf, (int, Decimal)):
            found.add(Decimal(leaf))
        elif isinstance(leaf, str) and _DECIMAL.match(leaf.strip()):
            found.add(Decimal(leaf.strip()))
    return found


def is_untrusted(value: Any) -> bool:
    """True when a tool output carries external text (``{"untrusted": true, ...}`` anywhere)."""
    stack: list[Any] = [value]
    while stack:
        current = stack.pop()
        if isinstance(current, Mapping):
            if current.get("untrusted") is True:
                return True
            stack.extend(current.values())
        elif isinstance(current, (list, tuple)):
            stack.extend(current)
    return False


# ---- provenance ----------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Provenance:
    """What this run may legitimately reference."""

    known_ids: frozenset[uuid.UUID]
    user_text: str
    record_values: frozenset[Decimal] = frozenset()
    clarification_values: frozenset[Decimal] = frozenset()
    can_override_price: bool = False

    def with_ids(self, ids: Iterable[uuid.UUID]) -> Provenance:
        return Provenance(
            known_ids=self.known_ids | frozenset(ids), user_text=self.user_text, record_values=self.record_values,
            clarification_values=self.clarification_values, can_override_price=self.can_override_price,
        )

    def with_values(self, values: Iterable[Decimal]) -> Provenance:
        return Provenance(
            known_ids=self.known_ids, user_text=self.user_text, record_values=self.record_values | frozenset(values),
            clarification_values=self.clarification_values, can_override_price=self.can_override_price,
        )


@dataclass
class GroundedInput:
    """A tool input with its provenance sidecars removed (``<field>_source``) and checked."""

    data: dict[str, Any]
    quantity_sources: dict[str, str] = field(default_factory=dict)
    price_override: dict[str, Any] | None = None


def check_ids(data: Any, provenance: Provenance) -> None:
    """Every uuid in a tool input must be one the run has seen (ai-routing.md section 6, ID provenance)."""
    unknown = uuids_in(data) - provenance.known_ids
    if unknown:
        shown = ", ".join(sorted(str(u) for u in unknown)[:3])
        raise GroundingError(
            "id_provenance",
            f"The id(s) {shown} did not come from the screen context, the object context, an earlier tool output of "
            "this run or a card action; the call was rejected before any service was reached.",
        )


def _check_quantity(path: str, value: Any, source: Any, provenance: Provenance) -> None:
    if source not in QUANTITY_SOURCES:
        raise GroundingError(
            "quantity_provenance",
            f"{path} needs a quantity_source of user_turn, record or clarification (got {source!r}).",
        )
    literal = numbers.parse_decimal(str(value)) if value is not None else None
    if literal is None:
        raise GroundingError("quantity_provenance", f"{path} is not a decimal quantity: {value!r}.")
    if source == "user_turn" and not numbers.mentions(provenance.user_text, literal):
        raise GroundingError(
            "quantity_provenance", f"{path}={value} is marked as said by the user but does not occur in the user's turn."
        )
    if source == "record" and literal not in provenance.record_values:
        raise GroundingError(
            "quantity_provenance", f"{path}={value} is marked as a record value but no record read in this run holds it."
        )
    if source == "clarification" and literal not in provenance.clarification_values:
        raise GroundingError(
            "quantity_provenance", f"{path}={value} is marked as a clarification answer but no option carried it."
        )


def _check_override(path: str, value: Any, provenance: Provenance) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) - {"value", "reason", "source"} or value.get("source") != "user_turn":
        raise GroundingError(
            "price_not_model_input",
            f"{path} must be an explicit override {{value, reason, source: user_turn}}; prices never come from the model.",
        )
    if not provenance.can_override_price:
        raise GroundingError("permission_denied", "Overriding a price needs sales.quote_price.override.")
    literal = numbers.parse_decimal(str(value.get("value")))
    if literal is None or not numbers.mentions(provenance.user_text, literal):
        raise GroundingError("price_not_model_input", f"{path}.value must be a figure the user stated in this turn.")
    if not str(value.get("reason") or "").strip():
        raise GroundingError("price_not_model_input", f"{path}.reason is required.")
    return {"value": str(literal), "reason": str(value["reason"]).strip(), "source": "user_turn"}


def ground_input(raw: Mapping[str, Any], provenance: Provenance) -> GroundedInput:
    """Strip and verify provenance sidecars, reject model-supplied prices, verify every id."""
    grounded = GroundedInput(data={})
    grounded.data = _ground_mapping(raw, provenance, grounded, path="")
    check_ids(grounded.data, provenance)
    return grounded


def _ground_mapping(mapping: Mapping[str, Any], provenance: Provenance, out: GroundedInput, *, path: str) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in mapping.items():
        here = f"{path}.{key}" if path else key
        if key == PRICE_OVERRIDE_FIELD:
            out.price_override = _check_override(here, value, provenance)
            cleaned[key] = out.price_override
            continue
        if key.endswith("_source") and key[:-7] in mapping:
            continue  # sidecar, consumed below with its base field
        if _QUANTITY_NAMES.match(key) and not isinstance(value, (Mapping, list)):
            source = mapping.get(f"{key}_source")
            _check_quantity(here, value, source, provenance)
            out.quantity_sources[here] = str(source)
        elif _PRICE_NAMES.match(key) and not isinstance(value, (Mapping, list, bool)) and value is not None:
            raise GroundingError(
                "price_not_model_input",
                f"{here} looks like a price or amount; prices are resolved by services, never supplied by the model.",
            )
        if isinstance(value, Mapping):
            cleaned[key] = _ground_mapping(value, provenance, out, path=here)
        elif isinstance(value, list):
            cleaned[key] = [
                _ground_mapping(item, provenance, out, path=f"{here}[{i}]") if isinstance(item, Mapping) else item
                for i, item in enumerate(value)
            ]
        else:
            cleaned[key] = value
    return cleaned


# ---- numeric-claim checker ------------------------------------------------------------------------------------
_CLAIM = re.compile(
    r"(?<![\w.\-/#])(?:(?P<prefix>(?:EUR|GBP|USD|INR|Rs\.?|€|₹|£|\$)\s?)?)"
    r"(?P<number>\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?P<suffix>\s?(?:pcs|pieces|units|nos|sets|cartons?|kg|%)?)(?![\w.\-/]|,\d)",
    re.I,
)


def check_claims(text: str, allowed: Iterable[Decimal]) -> tuple[str, int]:
    """Replace every money or quantity figure in ``text`` that is not in ``allowed`` with "see card".

    Figures attached to identifiers (``LK-QT-2026-0009``, ``P-00001``), dates and ordinals are not claims.
    Returns the rewritten text and the number of replacements.
    """
    allowed_set = {Decimal(v) for v in allowed}
    count = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal count
        value = numbers.parse_decimal(match.group("number"))
        if value is not None and value in allowed_set:
            return match.group(0)
        count += 1
        return SEE_CARD

    return _CLAIM.sub(replace, text), count
