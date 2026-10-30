"""Server-built cards (ai-routing.md section 5): Pydantic models with a ``kind`` discriminator, built from tool
outputs, never from model text. Every card carries the provider label ("Demo") and the run's taint marker.

Builders read the sales module's ``QuoteDetail`` (``draft_quote`` output: ``id``, ``quote_number``, ``status``,
``party{id, display_name}``, ``currency``, ``version``, ``lines[QuoteLineRead]``, ``totals``, ``calculation``) and
stay tolerant of the older documented aliases (``quote_id``, ``party_id``, ``line_id``, ``uom``); anything missing
is left as ``None`` rather than inventing a figure.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from app.core.money import DecimalStr

QUOTE_REVIEW_PATH = "/sales/quotes/{quote_id}"


class CardBase(BaseModel):
    provider_label: str = "Demo"
    tainted: bool = False


class RecordLink(BaseModel):
    resource_type: str | None = None
    resource_id: uuid.UUID | None = None
    label: str
    path: str


class Capability(BaseModel):
    allowed: bool
    reason_code: str | None = None


class QuoteLineCard(BaseModel):
    line_id: uuid.UUID | None = None
    line_no: int | None = None
    product_id: uuid.UUID | None = None
    product_key: str | None = None
    product_name: str | None = None
    quantity: DecimalStr | None = None
    uom: str | None = None
    unit_price: DecimalStr | None = None
    line_total: DecimalStr | None = None
    price_list_item_id: uuid.UUID | None = None
    price_list_code: str | None = None


class QuoteTotalsCard(BaseModel):
    currency: str
    gross_subtotal: DecimalStr | None = None
    discount_total: DecimalStr | None = None
    applicable_subtotal: DecimalStr | None = None
    surcharge: DecimalStr | None = None
    surcharge_applied: bool = False
    grand_total: DecimalStr | None = None
    minimum_status: str | None = None
    recommended_quantity: int | None = None
    notes: list[str] = Field(default_factory=list)


class QuoteDraftCard(CardBase):
    kind: Literal["quote_draft"] = "quote_draft"
    quote_id: uuid.UUID | None
    quote_number: str | None
    status: str
    #: the quote's row version when the card was built (``expected_version`` for a follow-up line update)
    version: int | None = None
    party_id: uuid.UUID | None
    party_label: str | None
    currency: str
    lines: list[QuoteLineCard]
    totals: QuoteTotalsCard | None
    capabilities: dict[str, Capability] = Field(default_factory=dict)
    review: RecordLink | None = None
    #: true when the figures come from a calculation preview and no draft was written
    preview_only: bool = False
    #: tainted runs require an explicit human confirmation before anything leaves the system
    requires_confirmation: bool = False


class OptionAction(BaseModel):
    """What the client posts as the next turn when the user picks this option (``TurnCreate.selected_option``)."""

    kind: Literal["select_option"] = "select_option"
    slot: str
    value: str
    label: str
    data: dict[str, Any] = Field(default_factory=dict)


class ClarificationOption(BaseModel):
    ref: str
    label: str
    detail: str | None = None
    action: OptionAction


class ClarificationCard(CardBase):
    kind: Literal["clarification"] = "clarification"
    slot: str
    question: str
    options: list[ClarificationOption]


class ErrorCard(CardBase):
    kind: Literal["error"] = "error"
    code: str
    message: str
    recoverable_draft: RecordLink | None = None
    direct_controls: list[RecordLink] = Field(default_factory=list)


class RecordLinkCard(CardBase):
    kind: Literal["record_link"] = "record_link"
    resource_type: str | None = None
    resource_id: uuid.UUID | None = None
    label: str
    path: str
    ordinal: int | None = None


class ReceiptCard(CardBase):
    kind: Literal["receipt"] = "receipt"
    action: str
    summary: str
    record: RecordLink | None = None
    at: datetime


Card = Annotated[
    QuoteDraftCard | ClarificationCard | ErrorCard | RecordLinkCard | ReceiptCard, Field(discriminator="kind")
]


def _uuid(value: Any) -> uuid.UUID | None:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value)) if value else None
    except ValueError:
        return None


def _dec(value: Any) -> str | None:
    """A decimal string from a plain value, a ``Money`` ({amount, currency}) or a ``Quantity`` ({value, uom})."""
    if value is None:
        return None
    if isinstance(value, Mapping):
        inner = value.get("amount", value.get("value"))
        return None if inner is None else str(inner)
    return str(value)


def _int(value: Any) -> int | None:
    text = _dec(value)
    return None if text is None else int(Decimal(text))


def _uom(value: Any, default: Any = None) -> str | None:
    if isinstance(value, Mapping) and value.get("uom"):
        return str(value["uom"])
    return None if default is None else str(default)


def _totals_from_calculation(calc: Mapping[str, Any]) -> QuoteTotalsCard:
    """Totals from the commercial engine's ``CalculationResultOut`` (``calculate_quote`` output)."""
    minimum = calc.get("minimum") or {}
    surcharge = calc.get("surcharge") or {}
    recommended = None
    for line in calc.get("lines") or []:
        rec = (line.get("recommendation") or {}).get("quantity")
        if rec is not None:
            recommended = _int(rec)
            break
    notes = list(calc.get("warnings") or [])
    if minimum.get("status") == "BELOW":
        notes.append("below the EUR minimum order value")
    return QuoteTotalsCard(
        currency=str(calc.get("currency") or ""),
        gross_subtotal=_dec(calc.get("gross_subtotal")),
        discount_total=_dec(calc.get("discount_total")),
        applicable_subtotal=_dec(calc.get("applicable_subtotal")),
        surcharge=_dec(surcharge.get("amount")),
        surcharge_applied=bool(surcharge.get("applied") or calc.get("surcharge_applied")),
        grand_total=_dec(calc.get("grand_total")),
        minimum_status=minimum.get("status"),
        recommended_quantity=recommended,
        notes=notes,
    )


def _totals_from_persisted(totals: Mapping[str, Any], currency: str) -> QuoteTotalsCard:
    """Totals as the sales module persists them on the quote header."""
    if "calculation" in totals and isinstance(totals["calculation"], Mapping):
        return _totals_from_calculation(totals["calculation"])
    if "gross_subtotal" in totals and "minimum" in totals:
        return _totals_from_calculation(totals)
    recommended = totals.get("recommended_quantity")
    return QuoteTotalsCard(
        currency=str(totals.get("currency") or currency),
        gross_subtotal=_dec(totals.get("gross_subtotal") or totals.get("gross")),
        discount_total=_dec(totals.get("discount_total") or totals.get("discount")),
        applicable_subtotal=_dec(totals.get("applicable_subtotal") or totals.get("applicable")),
        surcharge=_dec(totals.get("surcharge") if not isinstance(totals.get("surcharge"), Mapping) else totals["surcharge"].get("amount")),
        surcharge_applied=bool(totals.get("surcharge_applied") or (isinstance(totals.get("surcharge"), Mapping) and totals["surcharge"].get("applied"))),
        grand_total=_dec(totals.get("grand_total")),
        minimum_status=(totals.get("minimum") or {}).get("status") if isinstance(totals.get("minimum"), Mapping) else totals.get("minimum_status"),
        recommended_quantity=_int(recommended),
        notes=list(totals.get("notes") or totals.get("warnings") or []),
    )


def _line(raw: Mapping[str, Any]) -> QuoteLineCard:
    product: Mapping[str, Any] = {}
    for key in ("product", "product_snapshot"):  # QuoteLineRead carries the frozen product_snapshot
        if isinstance(raw.get(key), Mapping):
            product = raw[key]
            break
    return QuoteLineCard(
        line_id=_uuid(raw.get("line_id") or raw.get("id")),
        line_no=raw.get("line_no"),
        product_id=_uuid(raw.get("product_id") or product.get("product_id") or product.get("id")),
        product_key=raw.get("product_key") or product.get("product_key"),
        product_name=raw.get("product_name") or product.get("product_name") or product.get("name") or raw.get("description"),
        quantity=_dec(raw.get("quantity")),
        uom=_uom(raw.get("quantity"), raw.get("uom") or raw.get("unit_code")),
        unit_price=_dec(raw.get("unit_price")),
        line_total=_dec(raw.get("line_total") or raw.get("net")),
        price_list_item_id=_uuid(raw.get("price_list_item_id") or raw.get("item_id")),
        price_list_code=raw.get("price_list_code"),
    )


def quote_draft_card(
    output: Mapping[str, Any], *, provider_label: str, tainted: bool, party_label: str | None = None
) -> QuoteDraftCard:
    """QuoteDraftCard from a ``draft_quote`` output or a sales ``QuoteDetail`` (persisted totals, never recomputed)."""
    quote_id = _uuid(output.get("quote_id") or output.get("id"))
    currency = str(output.get("currency") or (output.get("totals") or {}).get("currency") or "")
    party = output.get("party") if isinstance(output.get("party"), Mapping) else {}
    calculation = output.get("calculation")
    totals_raw = output.get("totals")
    if isinstance(calculation, Mapping):  # the persisted engine result: totals, minimum and the recommendation
        totals = _totals_from_calculation(calculation)
    elif isinstance(totals_raw, Mapping):
        totals = _totals_from_persisted(totals_raw, currency)
    else:
        totals = None
    capabilities = {
        k: Capability(**v) if isinstance(v, Mapping) else Capability(allowed=bool(v))
        for k, v in (output.get("capabilities") or {}).items()
    }
    return QuoteDraftCard(
        provider_label=provider_label,
        tainted=tainted,
        quote_id=quote_id,
        quote_number=output.get("quote_number"),
        status=str(output.get("status") or "draft"),
        version=output.get("version") if isinstance(output.get("version"), int) else None,
        party_id=_uuid(output.get("party_id") or party.get("id")),
        party_label=output.get("party_name") or output.get("party_label") or party.get("display_name") or party_label,
        currency=currency,
        lines=[_line(line) for line in output.get("lines") or []],
        totals=totals,
        capabilities=capabilities,
        review=RecordLink(
            resource_type="sales.quote", resource_id=quote_id, label=f"Review {output.get('quote_number') or 'draft'}",
            path=QUOTE_REVIEW_PATH.format(quote_id=quote_id),
        ) if quote_id else None,
        requires_confirmation=tainted,
    )


def quote_preview_card(
    calculation_output: Mapping[str, Any],
    *,
    provider_label: str,
    tainted: bool,
    base: QuoteDraftCard | None,
    quantity: str,
) -> QuoteDraftCard:
    """QuoteDraftCard from a ``calculate_quote`` preview over an existing draft (the update is applied separately)."""
    calc = calculation_output.get("calculation") or {}
    refs = {r.get("line_key"): r for r in calculation_output.get("lines") or []}
    lines: list[QuoteLineCard] = []
    for result in calc.get("lines") or []:
        ref = refs.get(result.get("line_key")) or {}
        lines.append(QuoteLineCard(
            line_id=_uuid(result.get("line_key")),
            product_id=_uuid(ref.get("product_id")),
            product_key=ref.get("product_key"),
            quantity=_dec(result.get("quantity")),
            uom=_uom(result.get("quantity"), ref.get("unit_code")),
            unit_price=_dec(result.get("unit_price")),
            line_total=_dec(result.get("net")),
            price_list_item_id=_uuid(ref.get("price_list_item_id")),
            price_list_code=ref.get("price_list_code"),
        ))
    return QuoteDraftCard(
        provider_label=provider_label,
        tainted=tainted,
        quote_id=base.quote_id if base else None,
        quote_number=base.quote_number if base else None,
        status=base.status if base else "preview",
        version=base.version if base else None,
        party_id=base.party_id if base else None,
        party_label=base.party_label if base else None,
        currency=str(calc.get("currency") or (base.currency if base else "")),
        lines=lines,
        totals=_totals_from_calculation(calc),
        review=base.review if base else None,
        preview_only=True,
        requires_confirmation=tainted,
    )


def clarification_card(
    slot: str, question: str, options: list[ClarificationOption], *, provider_label: str, tainted: bool
) -> ClarificationCard:
    return ClarificationCard(provider_label=provider_label, tainted=tainted, slot=slot, question=question, options=options)


def party_options(candidates: list[Mapping[str, Any]]) -> list[ClarificationOption]:
    """Exactly the candidates of an ambiguous ``resolve_party`` result, each carrying its select action."""
    options: list[ClarificationOption] = []
    for i, c in enumerate(candidates, start=1):
        label = str(c.get("display_name") or c.get("legal_name") or c.get("party_number"))
        detail = " · ".join(str(x) for x in (c.get("party_number"), c.get("country_code"), c.get("default_currency")) if x)
        options.append(ClarificationOption(
            ref=f"o{i}", label=label, detail=detail or None,
            action=OptionAction(slot="party", value=str(c["party_id"]), label=label,
                                data={"default_currency": c.get("default_currency"), "party_number": c.get("party_number")}),
        ))
    return options


def product_options(candidates: list[Mapping[str, Any]]) -> list[ClarificationOption]:
    options: list[ClarificationOption] = []
    for i, c in enumerate(candidates, start=1):
        label = f"{c.get('product_key')} · {c.get('product_name')}"
        options.append(ClarificationOption(
            ref=f"o{i}", label=label, detail=c.get("decor_no"),
            action=OptionAction(slot="product", value=str(c["product_id"]), label=label, data={"product_key": c.get("product_key")}),
        ))
    return options


def line_options(lines: list[Mapping[str, Any]]) -> list[ClarificationOption]:
    options: list[ClarificationOption] = []
    for i, line in enumerate(lines, start=1):
        label = f"{line.get('product_key') or line.get('product_name') or 'line'} × {line.get('quantity')} {line.get('uom') or ''}".strip()
        value = str(line.get("line_id") or line.get("product_id") or i)
        options.append(ClarificationOption(
            ref=f"o{i}", label=label, detail=None,
            action=OptionAction(slot="line", value=value, label=label, data={"product_id": str(line.get("product_id"))}),
        ))
    return options


def error_card(
    code: str, message: str, *, provider_label: str, tainted: bool, recoverable_draft: RecordLink | None = None,
    direct_controls: list[RecordLink] | None = None,
) -> ErrorCard:
    return ErrorCard(
        provider_label=provider_label, tainted=tainted, code=code, message=message,
        recoverable_draft=recoverable_draft, direct_controls=direct_controls or [],
    )


def record_link_card(
    label: str, path: str, *, provider_label: str, tainted: bool, resource_type: str | None = None,
    resource_id: uuid.UUID | None = None, ordinal: int | None = None,
) -> RecordLinkCard:
    return RecordLinkCard(
        provider_label=provider_label, tainted=tainted, label=label, path=path, resource_type=resource_type,
        resource_id=resource_id, ordinal=ordinal,
    )


def receipt_card(action: str, summary: str, at: datetime, *, provider_label: str, tainted: bool, record: RecordLink | None) -> ReceiptCard:
    return ReceiptCard(provider_label=provider_label, tainted=tainted, action=action, summary=summary, record=record, at=at)


def dump_cards(cards: list[Any]) -> list[dict[str, Any]]:
    return [c.model_dump(mode="json") for c in cards]


def uuids_in_cards(cards: list[Mapping[str, Any]]) -> set[uuid.UUID]:
    from app.modules.agents.grounding import uuids_in

    return uuids_in(cards)
