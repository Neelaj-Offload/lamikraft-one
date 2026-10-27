"""Quote commands and reads: header, lines with snapshots, persisted totals, numbering, optimistic versions.

Every command is one unit of work: the quote row is locked, lines are changed, the commercial engine runs on the
new content and its result is persisted on the quote and its lines before the transaction commits (BUG-03,
DEBT-03). Prices of catalog lines come from ``pricing.resolve_price``; a different quoted price or a discount
needs ``sales.quote_price.override`` and a reason unless the actor also holds ``sales.quote_price.approve``
(permissions.md §10, ADR-046). Catalogue and price-list changes never alter an existing line: snapshots are
refreshed only explicitly, and reads report ``PRICE_CHANGED_SINCE_SNAPSHOT`` meanwhile.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import ColumnElement, func, or_, select

from app.core.db.base import new_id
from app.core.errors import AppError, Conflict, Forbidden, NotFound
from app.core.http.pagination import MAX_LIMIT, Page
from app.core.money import Money, quantize_money, quantize_quantity, quantize_unit_price
from app.core.text import LIKE_ESCAPE, contains_pattern, tokens
from app.modules.approvals import service as approvals
from app.modules.catalogue import service as catalogue
from app.modules.catalogue.normalise import plain_decimal
from app.modules.catalogue.schemas import ProductDetail
from app.modules.commercial import engine
from app.modules.commercial import service as commercial
from app.modules.commercial.schemas import CalculationResultOut
from app.modules.parties import service as parties
from app.modules.pricing import service as pricing
from app.modules.pricing.schemas import PriceResolution, PriceType
from app.modules.sales import enquiries
from app.modules.sales import events as ev
from app.modules.sales.common import (
    Errors,
    business_date,
    check_member,
    company_zone,
    idempotent,
    party_ref,
    party_refs,
    quote_path,
    user_ref,
    user_refs,
)
from app.modules.sales.models import (
    LINE_NO_CONSTRAINT,
    CustomerMessage,
    Enquiry,
    Quote,
    QuoteLine,
    QuoteRevision,
    QuoteStatusHistory,
)
from app.modules.sales.schemas import (
    CLOSED_STATUSES,
    MANUAL_PRESETS,
    BasisLine,
    Capability,
    CommercialSnapshot,
    LineType,
    MediaSnapshot,
    MinimumRead,
    PackagingSnapshot,
    PartyAddressSnapshot,
    PartySnapshot,
    PreviewLineOut,
    ProductSnapshot,
    QuoteCreate,
    QuoteDetail,
    QuoteFilters,
    QuoteHistoryRead,
    QuoteLineCreate,
    QuoteLineRead,
    QuoteLineUpdate,
    QuoteOrigin,
    QuotePreviewIn,
    QuotePreviewOut,
    QuoteRevisionRead,
    QuoteRevisionSummary,
    QuoteStatus,
    QuoteSummary,
    QuoteTotals,
    QuoteUpdate,
    RecommendationRead,
    RefreshSnapshots,
    ReviewRead,
    RevisionKind,
    TransitionRead,
    UsualOrderOutput,
)
from app.modules.sales.state import transitions_from
from app.platform.service import query
from app.platform.uow import UnitOfWork

READ = "sales.quote.read"
PRICE_CHANGED = "PRICE_CHANGED_SINCE_SNAPSHOT"
OPEN_STATUSES = frozenset({QuoteStatus.DRAFT.value, QuoteStatus.INTERNAL_REVIEW.value})
#: units that only accept whole quantities (conventions.md §6; ``uom.is_integer`` once the org master merges)
INTEGER_UOMS = frozenset({"pcs", "nos", "sheets", "box", "set", "roll", "bundle", "carton"})
DEFAULT_UNIT = "pcs"
TERMS_PLACEHOLDER = "Demo terms: prices exclude taxes; payment and delivery terms as agreed in writing."


def _d(value: Any) -> str | None:
    return None if value is None else format(value, "f")


# =====================================================================================================
# snapshots
# =====================================================================================================
def party_snapshot(uow: UnitOfWork, party_id: uuid.UUID) -> PartySnapshot:
    detail = parties.get_party(uow, party_id)
    primary = [c for c in detail.contacts if c.is_primary] or detail.contacts
    contact = primary[0] if primary else None
    addresses = [
        PartyAddressSnapshot(
            kind=a.kind.value,
            lines=[ln for ln in (a.line1, a.line2, " ".join(p for p in (a.postal_code, a.city) if p), a.region, a.country_code) if ln],
        )
        for a in detail.addresses
        if a.is_default
    ]
    return PartySnapshot(
        party_id=detail.id,
        party_number=detail.party_number,
        display_name=detail.display_name,
        legal_name=detail.legal_name,
        country_code=detail.country_code,
        default_currency=detail.default_currency,
        customer_type=detail.customer_type.value if detail.customer_type else None,
        contact_name=contact.name if contact else None,
        contact_email=contact.email if contact else None,
        addresses=addresses,
        taken_at=uow.now(),
    )


def _size_text(product: ProductDetail) -> str | None:
    s = product.size
    if s.diameter_mm is not None:
        return f"Ø {plain_decimal(s.diameter_mm)} mm"
    if s.length_mm is None or s.width_mm is None:
        return None
    parts = [plain_decimal(s.length_mm), plain_decimal(s.width_mm)]
    if s.height_mm is not None:
        parts.append(plain_decimal(s.height_mm))
    return " × ".join(parts) + " mm"


def product_snapshots(uow: UnitOfWork, product_id: uuid.UUID) -> tuple[ProductSnapshot, PackagingSnapshot, MediaSnapshot, ProductDetail]:
    p = catalogue.get_product(uow, product_id)
    spec = p.specification
    spec_bits = [b for b in (
        f"{plain_decimal(spec.thickness_mm)} mm" if spec and spec.thickness_mm is not None else None,
        spec.material_type if spec else None,
        spec.finish or p.finish if spec else p.finish,
    ) if b]
    product = ProductSnapshot(
        product_id=p.id,
        product_key=p.product_key,
        display_sku=p.display_sku,
        product_name=p.product_name,
        category=p.category.name,
        subcategory=p.subcategory.name if p.subcategory else None,
        unit_of_sale=p.unit_of_sale,
        decor_no=p.decor.decor_no,
        decor_name=p.decor.decor_name,
        finish=p.finish,
        shape=p.shape,
        size_text=_size_text(p),
        thickness_mm=spec.thickness_mm if spec else None,
        specification_summary=" · ".join(spec_bits) or None,
        product_version=p.version,
    )
    pk = p.packaging
    packaging = PackagingSnapshot(
        carton_qty=pk.carton_qty if pk else None,
        inner_qty=pk.inner_qty if pk else None,
        unit_weight_g=pk.unit_weight_g if pk else None,
        packing_type=pk.packing_type if pk else None,
        cbm=pk.cbm if pk else None,
        net_weight_kg=pk.net_weight_kg if pk else None,
        gross_weight_kg=pk.gross_weight_kg if pk else None,
        summary=pk.summary if pk else None,
    )
    media = MediaSnapshot(hint=f"decor:{p.decor.decor_no}" if p.decor.decor_no else None)
    return product, packaging, media, p


def resolve_line_price(
    uow: UnitOfWork, *, product_id: uuid.UUID, party_id: uuid.UUID | None, currency: str, unit_code: str, price_type: str,
    on_date: date | None = None,
) -> PriceResolution:
    return pricing.resolve_price(
        uow, currency=currency, uom=unit_code, product_id=product_id, party_id=party_id,
        on_date=on_date or business_date(uow), price_type=PriceType(price_type),
    )


def commercial_snapshot(resolution: PriceResolution, unit_code: str) -> CommercialSnapshot:
    return CommercialSnapshot(
        price_list_id=resolution.price_list_id,
        price_list_code=resolution.price_list_code,
        item_id=resolution.item_id,
        tier=resolution.tier,
        unit_price=resolution.unit_price,
        currency=resolution.currency or resolution.requested_currency,
        unit_code=unit_code,
        product_moq=resolution.product_moq,
        moq_unit_code=resolution.moq_unit_code,
        resolved_on=resolution.on_date,
        reason_code=resolution.reason_code,
    )


# =====================================================================================================
# engine integration (persisted totals)
# =====================================================================================================
def lines_of(uow: UnitOfWork, quote: Quote) -> list[QuoteLine]:
    return list(
        uow.session.scalars(select(QuoteLine).where(QuoteLine.quote_id == quote.id).order_by(QuoteLine.line_no, QuoteLine.id))
    )


def _line_input(line: QuoteLine) -> engine.LineInput:
    pack = line.packaging_snapshot or {}
    com = line.commercial_snapshot or {}
    carton = pack.get("carton_qty")
    moq = com.get("product_moq")
    moq_unit = com.get("moq_unit_code")
    return engine.LineInput(
        line_key=str(line.line_key),
        line_type=line.line_type,  # type: ignore[arg-type]
        quantity=Decimal(line.quantity),
        unit_price=Decimal(line.unit_price) if line.unit_price is not None else None,
        discount_pct=Decimal(line.discount_pct) if line.discount_pct is not None else None,
        carton_qty=int(carton) if carton is not None and line.unit_code == (line.product_snapshot or {}).get("unit_of_sale", line.unit_code) else None,
        product_moq=Decimal(moq) if moq is not None and moq_unit in (None, line.unit_code) else None,
    )


def content_of(quote: Quote, lines: Sequence[QuoteLine]) -> dict[str, Any]:
    """Stable content (header + lines + totals) that approvals bind to; strings only."""
    return {
        "quote_number": quote.quote_number,
        "party_id": str(quote.party_id),
        "currency": quote.currency,
        "price_type": quote.price_type,
        "incoterm": quote.incoterm,
        "incoterm_place": quote.incoterm_place,
        "payment_terms": quote.payment_terms,
        "validity_days": quote.validity_days,
        "apply_minimum_surcharge": quote.apply_minimum_surcharge,
        "lines": [
            {
                "line_key": str(ln.line_key),
                "line_type": ln.line_type,
                "product_id": str(ln.product_id) if ln.product_id else None,
                "description": ln.description,
                "quantity": _d(ln.quantity),
                "unit_code": ln.unit_code,
                "unit_price": _d(ln.unit_price),
                "default_unit_price": _d(ln.default_unit_price),
                "discount_pct": _d(ln.discount_pct),
            }
            for ln in lines
        ],
        "totals": {
            "gross": _d(quote.gross_subtotal_amount),
            "discount": _d(quote.discount_total_amount),
            "net": _d(quote.net_subtotal_amount),
            "applicable": _d(quote.applicable_subtotal_amount),
            "surcharge": _d(quote.surcharge_amount),
            "grand_total": _d(quote.grand_total_amount),
            "input_hash": quote.calc_input_hash,
        },
    }


def recalculate(uow: UnitOfWork, quote: Quote, lines: Sequence[QuoteLine]) -> engine.CalculationResult:
    """Run the active ``quote_commercial`` rule set over the quote's lines and persist the result."""
    inputs = engine.CalculationInput(
        currency=quote.currency,
        lines=tuple(_line_input(ln) for ln in lines),
        surcharge_requested=bool(quote.apply_minimum_surcharge),
    )
    result = commercial.calculate(uow, inputs)
    by_key = {lr.line_key: lr for lr in result.lines}
    for ln in lines:
        lr = by_key[str(ln.line_key)]
        ln.gross_amount = lr.gross
        ln.discount_amount = lr.discount
        ln.line_total = lr.net
    quote.gross_subtotal_amount = result.gross_subtotal
    quote.discount_total_amount = result.discount_total
    quote.net_subtotal_amount = result.net_subtotal
    quote.applicable_subtotal_amount = result.applicable_subtotal
    quote.surcharge_amount = result.surcharge.amount
    quote.grand_total_amount = result.grand_total
    quote.totals_currency = quote.currency
    quote.line_count = result.line_count
    quote.totals_complete = result.totals_complete
    quote.minimum_status = result.minimum.status
    quote.surcharge_applied = result.surcharge.applied
    quote.surcharge_reason_code = result.surcharge.reason_code
    quote.engine_version = result.engine_version
    quote.rule_set_id = result.rule_set_id
    quote.rule_set_version = result.rule_set_version
    quote.calc_input_hash = result.input_hash
    quote.calculation = result.as_dict()
    quote.has_price_override = any(
        ln.line_type == LineType.CATALOG.value and ln.unit_price is not None and ln.default_unit_price is not None
        and ln.unit_price != ln.default_unit_price
        for ln in lines
    )
    quote.has_discount = any(ln.discount_pct is not None and ln.discount_pct > 0 for ln in lines)
    quote.content_hash = approvals.content_hash(content_of(quote, lines))
    return result


def needs_review(quote: Quote) -> list[str]:
    reasons: list[str] = []
    if quote.has_price_override:
        reasons.append("price_override")
    if quote.has_discount:
        reasons.append("discount")
    if quote.minimum_status == "BELOW":
        reasons.append("below_minimum")
    return reasons


def approval_current(quote: Quote) -> bool:
    return quote.approved_proposal_id is not None and quote.approved_content_hash == quote.content_hash


def touch(uow: UnitOfWork, quote: Quote, *, invalidate: bool = True) -> None:
    """Mark the quote changed (one version bump per command) and invalidate a pending review."""
    quote.updated_at = uow.now()
    if invalidate:
        approvals.invalidate_for_target(uow, "sales.quote", quote.id)
        if quote.review_proposal_id is not None and quote.status == QuoteStatus.DRAFT.value:
            quote.review_proposal_id = None


def emit_updated(uow: UnitOfWork, quote: Quote, changed: Sequence[str], line_kinds: Sequence[str]) -> None:
    uow.emit(
        ev.QUOTE_UPDATED,
        aggregate_id=quote.id,
        aggregate_version=quote.version,
        payload=ev.payload(
            ev.QuoteUpdatedPayload(quote_id=quote.id, version=quote.version, changed_fields=sorted(set(changed)),
                                   line_change_kinds=sorted(set(line_kinds)))
        ),
    )


# =====================================================================================================
# commands
# =====================================================================================================
def _locked_quote(uow: UnitOfWork, quote_id: uuid.UUID, action: str) -> Quote:
    return uow.repo(Quote).get(quote_id, action, for_update=True, include_archived=False)


def _check_quantity(quantity: Decimal, unit_code: str, errors: Errors, loc: str = "quantity") -> Decimal:
    q = quantize_quantity(Decimal(quantity))
    if q <= 0:
        errors.add([loc], "not_positive", "quantity must be positive")
    elif unit_code in INTEGER_UOMS and q != q.to_integral_value():
        errors.add([loc], "not_integer", f"{unit_code} quantities must be whole numbers")
    elif q != q.quantize(Decimal("0.0001")):
        errors.add([loc], "too_many_decimals", "quantities accept at most 4 decimal places")
    return q


def create_quote(
    uow: UnitOfWork, data: QuoteCreate, *, origin: str | None = None, origin_ref: str | None = None
) -> Quote:
    actor = uow.actor
    actor.require("sales.quote.create")
    errors = Errors()
    party = party_ref(uow, data.party_id)
    owner_id = data.owner_user_id or actor.user_id
    if owner_id is None:
        errors.add(["owner_user_id"], "required", "A quote needs an owner")
        errors.raise_if_any()
    assert owner_id is not None
    if owner_id != actor.user_id and not actor.can("sales.quote.assign"):
        raise Forbidden("Assigning a quote to someone else needs sales.quote.assign", code="permission_denied",
                        permission="sales.quote.assign")
    check_member(uow, owner_id, errors, "owner_user_id")
    errors.raise_if_any()
    if data.enquiry_id is not None:
        uow.repo(Enquiry).get(data.enquiry_id, "update")
    if data.origin_message_id is not None:
        uow.repo(CustomerMessage).get(data.origin_message_id)
    currency = data.currency or party.default_currency
    snapshot = party_snapshot(uow, party.id)
    actor_origin = QuoteOrigin.AGENT.value if actor.actor_type == "agent" else QuoteOrigin.USER.value
    quote = Quote(
        id=new_id(),
        company_id=actor.company_id,
        party_id=party.id,
        party_snapshot=snapshot.model_dump(mode="json"),
        party_snapshot_at=snapshot.taken_at,
        party_name=snapshot.display_name,
        party_country=snapshot.country_code,
        owner_user_id=owner_id,
        branch_id=data.branch_id or party.branch_id or (sorted(actor.branch_ids)[0] if actor.branch_ids else None),
        enquiry_id=data.enquiry_id,
        origin_message_id=data.origin_message_id,
        origin=origin or actor_origin,
        origin_ref=origin_ref,
        brand=data.brand,
        price_type=data.price_type.value,
        currency=currency,
        incoterm=data.incoterm.value if data.incoterm else None,
        incoterm_place=data.incoterm_place,
        payment_terms=data.payment_terms,
        validity_days=data.validity_days,
        customer_reference=data.customer_reference,
        remarks=data.remarks,
        apply_minimum_surcharge=data.apply_minimum_surcharge,
        status=QuoteStatus.DRAFT.value,
        revision_no=0,
        totals_currency=currency,
    )
    quote.quote_number = uow.allocate_number(
        ev.QUOTE_SEQUENCE.key,
        document_date=business_date(uow),
        resource_type="sales.quote",
        resource_id=quote.id,
        tokens={"brand": quote.brand},
    )
    recalculate(uow, quote, [])
    uow.add(quote)
    uow.flush()
    if data.enquiry_id is not None:
        enquiries.mark_enquiry_quoted(uow, data.enquiry_id, quote, origin=origin)
    if data.origin_message_id is not None:
        enquiries.link_quote_to_message(uow, data.origin_message_id, quote)
    uow.emit(
        ev.QUOTE_CREATED,
        aggregate_id=quote.id,
        aggregate_version=quote.version,
        payload=ev.payload(
            ev.QuoteCreatedPayload(
                quote_id=quote.id, quote_number=quote.quote_number, owner_user_id=owner_id, branch_id=quote.branch_id,
                party_id=party.id, enquiry_id=quote.enquiry_id, origin_message_id=quote.origin_message_id, origin=origin,
            )
        ),
    )
    uow.audit("sales.quote.created", resource_type="sales.quote", resource_id=quote.id,
              resource_label=f"{quote.quote_number} · {quote.party_name}")
    return quote


def update_quote(uow: UnitOfWork, quote_id: uuid.UUID, data: QuoteUpdate, *, origin: str | None = None) -> Quote:
    quote = _locked_quote(uow, quote_id, "update")
    uow.expect_version(quote, data.expected_version)
    fields = data.model_dump(exclude_unset=True, exclude={"expected_version", "refresh_party_snapshot"})
    changed: set[str] = set()
    for name, value in fields.items():
        if hasattr(value, "value"):
            value = value.value
        if name in ("validity_days",) and value is None:
            continue
        if name == "apply_minimum_surcharge" and value is None:
            continue
        if getattr(quote, name) != value:
            setattr(quote, name, value)
            changed.add(name)
    if data.refresh_party_snapshot:
        snapshot = party_snapshot(uow, quote.party_id)
        quote.party_snapshot = snapshot.model_dump(mode="json")
        quote.party_snapshot_at = snapshot.taken_at
        quote.party_name = snapshot.display_name
        quote.party_country = snapshot.country_code
        changed.add("party_snapshot")
    if not changed:
        return quote
    lines = lines_of(uow, quote)
    recalculate(uow, quote, lines)
    touch(uow, quote)
    uow.flush()
    emit_updated(uow, quote, sorted(changed), [])
    uow.audit("sales.quote.updated", resource_type="sales.quote", resource_id=quote.id, resource_label=quote.quote_number,
              details={"changed_fields": sorted(changed)})
    return quote


def _apply_override(
    uow: UnitOfWork, line: QuoteLine, *, requested_price: Decimal | None, reason: str | None, discount_pct: Decimal | None,
    errors: Errors,
) -> None:
    """Price override rule (ADR-046): a quoted price different from the resolved default, or any discount, needs
    ``sales.quote_price.override`` and a reason unless the actor may approve price overrides."""
    actor = uow.actor
    default = line.default_unit_price
    price = quantize_unit_price(requested_price) if requested_price is not None else default
    overriding = (price is not None and default is not None and price != default) or (default is None and price is not None)
    discounting = discount_pct is not None and discount_pct > 0
    if overriding or discounting:
        if not actor.can("sales.quote_price.override"):
            raise Forbidden("Changing the quoted price needs sales.quote_price.override", code="permission_denied",
                            permission="sales.quote_price.override")
        if not reason and not actor.can("sales.quote_price.approve"):
            errors.add(["override_reason"], "override_reason_required", "A reason is required for a price override or discount")
            errors.raise_if_any()
        line.override_reason = reason
        line.override_by = actor.user_id
        line.override_at = uow.now()
    else:
        line.override_reason = None
        line.override_by = None
        line.override_at = None
    line.unit_price = price
    line.discount_pct = discount_pct


def _catalog_line(uow: UnitOfWork, quote: Quote, data: QuoteLineCreate, errors: Errors) -> QuoteLine:
    product_ref = catalogue.get_product_ref(uow, product_id=data.product_id, product_key=data.product_key)
    if product_ref.archived:
        errors.add(["product_id"], "product_archived", "The product is archived")
        errors.raise_if_any()
    product, packaging, media, _detail = product_snapshots(uow, product_ref.id)
    unit_code = data.unit_code or product.unit_of_sale or DEFAULT_UNIT
    quantity = _check_quantity(data.quantity, unit_code, errors)
    errors.raise_if_any()
    resolution = resolve_line_price(
        uow, product_id=product.product_id, party_id=quote.party_id, currency=quote.currency, unit_code=unit_code,
        price_type=quote.price_type,
    )
    if resolution.status == "ambiguous":
        raise Conflict(resolution.explanation, code="price_ambiguous",
                       candidates=[c.model_dump(mode="json") for c in resolution.candidates])
    default = resolution.unit_price if resolution.status == "found" else None
    if default is None and data.unit_price is None:
        raise Conflict(resolution.explanation, code="price_unavailable", reason_code=resolution.reason_code, hints=resolution.hints)
    line = QuoteLine(
        id=new_id(),
        company_id=uow.actor.company_id,
        quote_id=quote.id,
        line_key=new_id(),
        line_type=LineType.CATALOG.value,
        product_id=product.product_id,
        description=data.description or product.product_name,
        quantity=quantity,
        unit_code=unit_code,
        default_unit_price=quantize_unit_price(default) if default is not None else None,
        currency=quote.currency,
        remarks=data.remarks,
        internal_note=data.internal_note,
        price_list_item_id=resolution.item_id,
        product_snapshot=product.model_dump(mode="json"),
        packaging_snapshot=packaging.model_dump(mode="json"),
        media_snapshot=media.model_dump(mode="json"),
        commercial_snapshot=commercial_snapshot(resolution, unit_code).model_dump(mode="json"),
    )
    _apply_override(uow, line, requested_price=data.unit_price, reason=data.override_reason, discount_pct=data.discount_pct, errors=errors)
    return line


def _manual_line(uow: UnitOfWork, quote: Quote, data: QuoteLineCreate, errors: Errors) -> QuoteLine:
    preset_desc, preset_unit = MANUAL_PRESETS[data.manual_preset] if data.manual_preset else (None, None)
    unit_code = data.unit_code or preset_unit or DEFAULT_UNIT
    quantity = _check_quantity(data.quantity, unit_code, errors)
    errors.raise_if_any()
    assert data.unit_price is not None
    price = quantize_unit_price(data.unit_price)
    line = QuoteLine(
        id=new_id(),
        company_id=uow.actor.company_id,
        quote_id=quote.id,
        line_key=new_id(),
        line_type=LineType.MANUAL.value,
        product_id=None,
        description=data.description or preset_desc or "Manual line",
        manual_preset=data.manual_preset.value if data.manual_preset else None,
        quantity=quantity,
        unit_code=unit_code,
        default_unit_price=price,
        unit_price=price,
        currency=quote.currency,
        discount_pct=None,
        remarks=data.remarks,
        internal_note=data.internal_note,
    )
    if data.discount_pct is not None and data.discount_pct > 0:
        _apply_override(uow, line, requested_price=price, reason=data.override_reason, discount_pct=data.discount_pct, errors=errors)
    return line


def add_line(uow: UnitOfWork, quote_id: uuid.UUID, data: QuoteLineCreate, *, origin: str | None = None) -> tuple[Quote, QuoteLine]:
    quote = _locked_quote(uow, quote_id, "update")
    uow.expect_version(quote, data.expected_version)
    errors = Errors()
    lines = lines_of(uow, quote)
    line = _catalog_line(uow, quote, data, errors) if data.line_type == "catalog" else _manual_line(uow, quote, data, errors)
    line.line_no = (max((ln.line_no for ln in lines), default=0)) + 1
    uow.add(line)
    uow.flush()
    lines.append(line)
    recalculate(uow, quote, lines)
    touch(uow, quote)
    uow.flush()
    emit_updated(uow, quote, ["lines"], ["added"])
    uow.audit("sales.quote.line_added", resource_type="sales.quote", resource_id=quote.id, resource_label=quote.quote_number,
              details={"line_no": line.line_no, "line_type": line.line_type})
    return quote, line


def _line_of(uow: UnitOfWork, quote: Quote, line_id: uuid.UUID) -> QuoteLine:
    line = uow.session.scalars(select(QuoteLine).where(QuoteLine.id == line_id, QuoteLine.quote_id == quote.id)).first()
    if line is None:
        raise NotFound(code="not_found", resource_type="sales.quote_line")
    return line


def update_line(uow: UnitOfWork, quote_id: uuid.UUID, line_id: uuid.UUID, data: QuoteLineUpdate, *, origin: str | None = None) -> tuple[Quote, QuoteLine]:
    quote = _locked_quote(uow, quote_id, "update")
    uow.expect_version(quote, data.expected_version)
    line = _line_of(uow, quote, line_id)
    errors = Errors()
    # attribute access keeps Decimals (model_dump would serialise DecimalStr fields to strings)
    sent = data.model_fields_set - {"expected_version", "clear_override", "clear_discount"}
    changed: set[str] = set()
    if "quantity" in sent and data.quantity is not None:
        q = _check_quantity(data.quantity, line.unit_code, errors)
        errors.raise_if_any()
        if q != line.quantity:
            line.quantity = q
            changed.add("quantity")
    if "description" in sent and data.description and line.line_type == LineType.MANUAL.value and data.description != line.description:
        line.description = data.description
        changed.add("description")
    for name in ("remarks", "internal_note"):
        if name in sent and getattr(data, name) != getattr(line, name):
            setattr(line, name, getattr(data, name))
            changed.add(name)
    reason = data.override_reason if "override_reason" in sent else line.override_reason
    price_touched = "unit_price" in sent or data.clear_override or "discount_pct" in sent or data.clear_discount
    if price_touched:
        before = (line.unit_price, line.discount_pct, line.override_reason)
        if line.line_type == LineType.MANUAL.value:
            if "unit_price" in sent and data.unit_price is not None:
                line.default_unit_price = line.unit_price = quantize_unit_price(data.unit_price)
            discount = None if data.clear_discount else (data.discount_pct if "discount_pct" in sent else line.discount_pct)
            _apply_override(uow, line, requested_price=line.unit_price, reason=reason, discount_pct=discount, errors=errors)
        else:
            requested = None if data.clear_override else (data.unit_price if "unit_price" in sent else line.unit_price)
            discount = None if data.clear_discount else (data.discount_pct if "discount_pct" in sent else line.discount_pct)
            _apply_override(uow, line, requested_price=requested, reason=reason, discount_pct=discount, errors=errors)
        if (line.unit_price, line.discount_pct, line.override_reason) != before:
            changed.add("unit_price")
    elif "override_reason" in sent and line.override_reason is not None and reason != line.override_reason:
        line.override_reason = reason
        changed.add("override_reason")
    if not changed:
        return quote, line
    uow.flush()
    lines = lines_of(uow, quote)
    recalculate(uow, quote, lines)
    touch(uow, quote)
    uow.flush()
    emit_updated(uow, quote, ["lines"], ["changed"])
    uow.audit("sales.quote.line_changed", resource_type="sales.quote", resource_id=quote.id, resource_label=quote.quote_number,
              details={"line_no": line.line_no, "changed_fields": sorted(changed)})
    return quote, line


def remove_line(uow: UnitOfWork, quote_id: uuid.UUID, line_id: uuid.UUID, *, expected_version: int | None, origin: str | None = None) -> Quote:
    """Delete a line and renumber the remaining lines atomically (deferred unique constraint)."""
    quote = _locked_quote(uow, quote_id, "update")
    uow.expect_version(quote, expected_version)
    line = _line_of(uow, quote, line_id)
    removed_no = line.line_no
    uow.session.delete(line)
    uow.flush()
    uow.defer_constraints(LINE_NO_CONSTRAINT)
    remaining = lines_of(uow, quote)
    for position, ln in enumerate(remaining, start=1):
        if ln.line_no != position:
            ln.line_no = position
    uow.flush()
    recalculate(uow, quote, remaining)
    touch(uow, quote)
    uow.flush()
    emit_updated(uow, quote, ["lines"], ["removed"])
    uow.audit("sales.quote.line_removed", resource_type="sales.quote", resource_id=quote.id, resource_label=quote.quote_number,
              details={"line_no": removed_no})
    return quote


def refresh_snapshots(uow: UnitOfWork, quote_id: uuid.UUID, data: RefreshSnapshots, *, origin: str | None = None) -> Quote:
    """Explicitly re-read the catalogue and the current list prices into every catalog line (never implicit)."""
    quote = _locked_quote(uow, quote_id, "update")
    uow.expect_version(quote, data.expected_version)
    lines = lines_of(uow, quote)
    changed = False
    for line in lines:
        if line.line_type != LineType.CATALOG.value or line.product_id is None:
            continue
        product, packaging, media, _detail = product_snapshots(uow, line.product_id)
        resolution = resolve_line_price(
            uow, product_id=line.product_id, party_id=quote.party_id, currency=quote.currency, unit_code=line.unit_code,
            price_type=quote.price_type,
        )
        if resolution.status == "ambiguous":
            raise Conflict(resolution.explanation, code="price_ambiguous")
        new_default = quantize_unit_price(resolution.unit_price) if resolution.status == "found" and resolution.unit_price is not None else None
        was_overridden = line.override_reason is not None or (
            line.unit_price is not None and line.default_unit_price is not None and line.unit_price != line.default_unit_price
        )
        before = (line.product_snapshot, line.packaging_snapshot, line.default_unit_price, line.unit_price)
        line.product_snapshot = product.model_dump(mode="json")
        line.packaging_snapshot = packaging.model_dump(mode="json")
        line.media_snapshot = media.model_dump(mode="json")
        line.commercial_snapshot = commercial_snapshot(resolution, line.unit_code).model_dump(mode="json")
        line.price_list_item_id = resolution.item_id
        if new_default is not None:
            line.default_unit_price = new_default
            if not was_overridden:
                line.unit_price = new_default
        old_name = (before[0] or {}).get("product_name")
        if old_name is not None and line.description == old_name:
            line.description = product.product_name
        if (line.product_snapshot, line.packaging_snapshot, line.default_unit_price, line.unit_price) != before:
            changed = True
    if not changed:
        return quote
    uow.flush()
    recalculate(uow, quote, lines)
    touch(uow, quote)
    uow.flush()
    emit_updated(uow, quote, ["lines"], ["changed"])
    uow.audit("sales.quote.snapshots_refreshed", resource_type="sales.quote", resource_id=quote.id, resource_label=quote.quote_number)
    return quote


def delete_quote(uow: UnitOfWork, quote_id: uuid.UUID, *, expected_version: int | None, origin: str | None = None) -> Quote:
    """Soft-delete a never-issued draft (``sales.quote.delete``); the number is never reused."""
    quote = _locked_quote(uow, quote_id, "delete")
    uow.expect_version(quote, expected_version)
    approvals.invalidate_for_target(uow, "sales.quote", quote.id, reason="target_deleted")
    quote.deleted_at = uow.now()
    quote.deleted_by = uow.actor.user_id
    quote.updated_at = uow.now()
    uow.flush()
    uow.emit(ev.QUOTE_DELETED, aggregate_id=quote.id, aggregate_version=quote.version,
             payload=ev.payload(ev.QuoteDeletedPayload(quote_id=quote.id, origin=origin)))
    uow.audit("sales.quote.deleted", resource_type="sales.quote", resource_id=quote.id, resource_label=quote.quote_number)
    return quote


# =====================================================================================================
# reads
# =====================================================================================================
def _money(amount: Decimal | None, currency: str) -> Money | None:
    """Persisted 4-dp storage shown at the currency's minor unit (the engine already rounded it)."""
    return None if amount is None else Money(amount=quantize_money(Decimal(amount), currency), currency=currency)  # type: ignore[arg-type]


def _minor(amount: Decimal | None, currency: str) -> Decimal | None:
    return None if amount is None else quantize_money(Decimal(amount), currency)


def totals_of(quote: Quote) -> QuoteTotals:
    calc = quote.calculation or {}
    minimum = calc.get("minimum") or {}
    surcharge = calc.get("surcharge") or {}
    note = None
    if quote.minimum_status == "BELOW" and minimum.get("minimum_order_value"):
        note = (
            f"Minimum invoice value: {quote.currency} {Decimal(minimum['minimum_order_value']):,.2f}. "
            f"This quotation is below the minimum order value"
            + (f"; a {surcharge.get('label', 'surcharge').lower()} of {quote.currency} {Decimal(quote.surcharge_amount):,.2f} applies." if quote.surcharge_applied else ".")
        )
    return QuoteTotals(
        currency=quote.currency,
        gross_subtotal=_money(quote.gross_subtotal_amount, quote.currency),  # type: ignore[arg-type]
        discount_total=_money(quote.discount_total_amount, quote.currency),  # type: ignore[arg-type]
        net_subtotal=_money(quote.net_subtotal_amount, quote.currency),  # type: ignore[arg-type]
        applicable_subtotal=_money(quote.applicable_subtotal_amount, quote.currency),  # type: ignore[arg-type]
        surcharge=_money(quote.surcharge_amount, quote.currency),  # type: ignore[arg-type]
        surcharge_applied=quote.surcharge_applied,
        surcharge_reason_code=quote.surcharge_reason_code,
        surcharge_label=str(surcharge.get("label") or "Shipping surcharge"),
        grand_total=_money(quote.grand_total_amount, quote.currency),
        totals_complete=quote.totals_complete,
        line_count=quote.line_count,
        minimum=MinimumRead(
            status=quote.minimum_status,
            minimum_order_value=minimum.get("minimum_order_value"),
            shortfall=minimum.get("shortfall"),
            reason_code=minimum.get("reason_code"),
        ),
        tax_status=str(calc.get("tax_status") or "not_calculated"),
        tax_label=str(calc.get("tax_label") or engine.TAX_LABEL),
        threshold_note=note,
        engine_version=quote.engine_version,
        rule_set_version=quote.rule_set_version,
        input_hash=quote.calc_input_hash,
    )


def _current_prices(uow: UnitOfWork, quote: Quote, lines: Sequence[QuoteLine]) -> dict[uuid.UUID, Decimal | None]:
    """Current list price per catalog line of an open quote (for PRICE_CHANGED_SINCE_SNAPSHOT)."""
    out: dict[uuid.UUID, Decimal | None] = {}
    if quote.status not in OPEN_STATUSES or not uow.actor.can("pricing.price.read"):
        return out
    for line in lines:
        if line.line_type != LineType.CATALOG.value or line.product_id is None:
            continue
        try:
            resolution = resolve_line_price(
                uow, product_id=line.product_id, party_id=quote.party_id, currency=quote.currency, unit_code=line.unit_code,
                price_type=quote.price_type,
            )
        except AppError:
            continue
        out[line.id] = quantize_unit_price(resolution.unit_price) if resolution.status == "found" and resolution.unit_price is not None else None
    return out


def line_reads(uow: UnitOfWork, quote: Quote, lines: Sequence[QuoteLine], *, with_current_prices: bool = True) -> list[QuoteLineRead]:
    calc_lines = {ln["line_key"]: ln for ln in (quote.calculation or {}).get("lines", [])}
    current = _current_prices(uow, quote, lines) if with_current_prices else {}
    out: list[QuoteLineRead] = []
    for line in lines:
        cl = calc_lines.get(str(line.line_key)) or {}
        rec = cl.get("recommendation")
        advisories = list(cl.get("advisories") or [])
        current_price = current.get(line.id)
        if line.id in current and current_price != line.default_unit_price:
            advisories.append(PRICE_CHANGED)
        out.append(
            QuoteLineRead(
                id=line.id,
                line_no=line.line_no,
                line_key=line.line_key,
                line_type=LineType(line.line_type),
                product_id=line.product_id,
                description=line.description,
                manual_preset=line.manual_preset,  # type: ignore[arg-type]
                quantity=line.quantity,
                unit_code=line.unit_code,
                default_unit_price=line.default_unit_price,
                unit_price=line.unit_price,
                currency=line.currency,
                is_overridden=line.override_reason is not None or (
                    line.line_type == LineType.CATALOG.value and line.unit_price is not None and line.unit_price != line.default_unit_price
                ),
                override_reason=line.override_reason,
                discount_pct=line.discount_pct,
                gross_amount=_minor(line.gross_amount, line.currency),
                discount_amount=_minor(line.discount_amount, line.currency),
                line_total=_minor(line.line_total, line.currency),
                remarks=line.remarks,
                internal_note=line.internal_note,
                price_list_item_id=line.price_list_item_id,
                product_snapshot=ProductSnapshot.model_validate(line.product_snapshot) if line.product_snapshot else None,
                packaging_snapshot=PackagingSnapshot.model_validate(line.packaging_snapshot) if line.packaging_snapshot else None,
                media_snapshot=MediaSnapshot.model_validate(line.media_snapshot) if line.media_snapshot else None,
                commercial_snapshot=CommercialSnapshot.model_validate(line.commercial_snapshot) if line.commercial_snapshot else None,
                recommendation=RecommendationRead(**{k: rec[k] for k in ("status", "quantity", "carton_qty", "explanation", "label")}) if rec else None,
                advisories=advisories,
                current_unit_price=current_price,
            )
        )
    return out


def _summary(uow: UnitOfWork, rows: Sequence[Quote]) -> list[QuoteSummary]:
    if not rows:
        return []
    users = user_refs(uow, [q.owner_user_id for q in rows] + [q.created_by for q in rows])
    refs = party_refs(uow, [q.party_id for q in rows], {q.party_id: ((q.party_snapshot or {}).get("party_number", ""), q.party_name, q.party_country) for q in rows})
    return [
        QuoteSummary(
            id=q.id,
            quote_number=q.quote_number,
            revision_no=q.revision_no,
            status=QuoteStatus(q.status),
            party=refs[q.party_id],
            customer_reference=q.customer_reference,
            currency=q.currency,
            line_count=q.line_count,
            grand_total=_money(q.grand_total_amount, q.currency),
            owner=users.get(q.owner_user_id) or user_ref(uow, q.owner_user_id),  # type: ignore[arg-type]
            created_by=users.get(q.created_by) if q.created_by else None,
            branch_id=q.branch_id,
            origin=QuoteOrigin(q.origin),
            valid_until=q.valid_until,
            issued_at=q.issued_at,
            sent_at=q.sent_at,
            created_at=q.created_at,
            updated_at=q.updated_at,
            version=q.version,
            path=quote_path(q.id),
        )
        for q in rows
    ]


def allowed_transitions(uow: UnitOfWork, quote: Quote, lines: Sequence[QuoteLine]) -> list[TransitionRead]:
    repo = uow.repo(Quote)
    if quote.deleted_at is not None:
        return []
    out: list[TransitionRead] = []
    seen: set[str] = set()
    for t in transitions_from(quote.status):
        if t.action in seen:
            continue
        seen.add(t.action)
        if not repo.can(quote, t.permission_action):
            continue
        if t.guard == "lines_present" and not lines:
            continue
        if t.guard == "proposal_pending" and quote.review_proposal_id is None:
            continue
        out.append(TransitionRead(action=t.action, to_status=t.to_status, requires_reason=t.requires_reason))
    return out


def detail(uow: UnitOfWork, quote: Quote, lines: Sequence[QuoteLine] | None = None) -> QuoteDetail:
    lines = list(lines) if lines is not None else lines_of(uow, quote)
    base = _summary(uow, [quote])[0]
    repo = uow.repo(Quote)
    caps = repo.capabilities(quote, ["update", "delete", "export", "issue", "transition"])
    reasons = needs_review(quote)
    current = approval_current(quote)
    if caps["issue"]["allowed"]:
        if not lines:
            caps["issue"] = {"allowed": False, "reason_code": "no_lines"}
        elif not quote.totals_complete:
            caps["issue"] = {"allowed": False, "reason_code": "totals_incomplete"}
        elif reasons and not current:
            caps["issue"] = {"allowed": False, "reason_code": "review_approval_required"}
    caps["add_line"] = dict(caps["update"])
    caps["refresh_snapshots"] = dict(caps["update"])
    return QuoteDetail(
        **base.model_dump(),
        party_snapshot=PartySnapshot.model_validate(quote.party_snapshot),
        enquiry_id=quote.enquiry_id,
        origin_message_id=quote.origin_message_id,
        brand=quote.brand,
        price_type=PriceType(quote.price_type),
        incoterm=quote.incoterm,
        incoterm_place=quote.incoterm_place,
        payment_terms=quote.payment_terms,
        validity_days=quote.validity_days,
        remarks=quote.remarks,
        apply_minimum_surcharge=quote.apply_minimum_surcharge,
        won_at=quote.won_at,
        accepted_revision_id=quote.accepted_revision_id,
        lost_reason_code=quote.lost_reason_code,
        cancelled_reason_code=quote.cancelled_reason_code,
        deleted_at=quote.deleted_at,
        lines=line_reads(uow, quote, lines),
        totals=totals_of(quote),
        calculation=CalculationResultOut.model_validate(quote.calculation) if quote.calculation else None,
        content_hash=quote.content_hash,
        review=ReviewRead(
            requires_approval=bool(reasons),
            reasons=reasons,
            review_proposal_id=quote.review_proposal_id,
            approved_proposal_id=quote.approved_proposal_id,
            approval_current=current,
        ),
        capabilities={k: Capability(**v) for k, v in caps.items()},
        allowed_transitions=allowed_transitions(uow, quote, lines),
    )


def _visible_quote(uow: UnitOfWork, quote_id: uuid.UUID, *, include_deleted: bool = False) -> Quote:
    return uow.repo(Quote).get(quote_id, include_archived=include_deleted)


@query(READ)
def get_quote(uow: UnitOfWork, quote_id: uuid.UUID) -> QuoteDetail:
    return detail(uow, _visible_quote(uow, quote_id))


@query(READ)
def get_quote_by_number(uow: UnitOfWork, quote_number: str) -> QuoteDetail:
    quote = uow.repo(Quote).get_by_key(quote_number.strip().upper())
    if quote.deleted_at is not None:
        raise NotFound(code="not_found", resource_type="sales.quote")
    return detail(uow, quote)


def _conditions(uow: UnitOfWork, f: QuoteFilters) -> list[ColumnElement[bool]]:
    conds: list[ColumnElement[bool]] = []
    if f.q:
        for tok in tokens(f.q):
            conds.append(
                or_(
                    Quote.quote_number.ilike(contains_pattern(tok), escape=LIKE_ESCAPE),
                    Quote.party_name.ilike(contains_pattern(tok), escape=LIKE_ESCAPE),
                    Quote.party_country.ilike(contains_pattern(tok), escape=LIKE_ESCAPE),
                    Quote.customer_reference.ilike(contains_pattern(tok), escape=LIKE_ESCAPE),
                )
            )
    if f.status:
        conds.append(Quote.status.in_([s.value for s in f.status]))
    if f.scope == "mine" and uow.actor.user_id is not None:
        conds.append(Quote.owner_user_id == uow.actor.user_id)
    if f.owner_user_id:
        conds.append(Quote.owner_user_id == f.owner_user_id)
    if f.party_id:
        conds.append(Quote.party_id == f.party_id)
    return conds


@query(READ)
def list_quotes(uow: UnitOfWork, filters: QuoteFilters, *, limit: int = 50, offset: int = 0) -> Page[QuoteSummary]:
    """Scoped list (``scope=all`` is still bounded by the actor's read scope); filters apply before pagination."""
    page = uow.repo(Quote).list(
        *_conditions(uow, filters),
        order_by=[Quote.created_at.desc(), Quote.id.desc()],
        limit=max(1, min(limit, MAX_LIMIT)),
        offset=max(0, offset),
        include_archived=filters.include_deleted,
    )
    return Page[QuoteSummary](items=_summary(uow, page.items), total=page.total, limit=page.limit, offset=page.offset)


@query(READ)
def status_counts(uow: UnitOfWork, filters: QuoteFilters) -> dict[str, int]:
    """Server counts per status tab over the scoped, filtered set (UI-50)."""
    f = filters.model_copy(update={"status": None})
    stmt = uow.repo(Quote).select().where(*_conditions(uow, f)).with_only_columns(Quote.status, func.count(Quote.id)).group_by(Quote.status)
    counts = {s.value: 0 for s in QuoteStatus}
    for status, n in uow.session.execute(stmt).all():
        counts[status] = int(n)
    return counts


@query(READ)
def list_status_history(uow: UnitOfWork, quote_id: uuid.UUID) -> list[QuoteHistoryRead]:
    quote = _visible_quote(uow, quote_id, include_deleted=True)
    rows = list(
        uow.session.scalars(
            select(QuoteStatusHistory).where(QuoteStatusHistory.quote_id == quote.id).order_by(QuoteStatusHistory.occurred_at, QuoteStatusHistory.id)
        )
    )
    users = user_refs(uow, [r.actor_user_id for r in rows])
    return [
        QuoteHistoryRead(
            id=r.id, action=r.action, from_status=r.from_status, to_status=r.to_status,
            actor=users.get(r.actor_user_id) if r.actor_user_id else None, reason_code=r.reason_code, reason=r.reason,
            occurred_at=r.occurred_at, quote_version=r.quote_version,
        )
        for r in rows
    ]


def _revision_summary(uow: UnitOfWork, quote: Quote, rows: Sequence[QuoteRevision]) -> list[QuoteRevisionSummary]:
    users = user_refs(uow, [r.issued_by for r in rows])
    return [
        QuoteRevisionSummary(
            id=r.id, revision_no=r.revision_no, kind=RevisionKind(r.kind), issued_at=r.issued_at,
            issued_by=users.get(r.issued_by) if r.issued_by else None, valid_until=r.valid_until,
            document_sha256=r.document_sha256, content_hash=r.content_hash,
            document_path=f"/api/v1/sales/quotes/{quote.id}/revisions/{r.revision_no}/document.pdf",
        )
        for r in rows
    ]


@query(READ)
def list_revisions(uow: UnitOfWork, quote_id: uuid.UUID) -> list[QuoteRevisionSummary]:
    quote = _visible_quote(uow, quote_id)
    rows = list(uow.session.scalars(select(QuoteRevision).where(QuoteRevision.quote_id == quote.id).order_by(QuoteRevision.revision_no)))
    return _revision_summary(uow, quote, rows)


def revision_row(uow: UnitOfWork, quote: Quote, revision_no: int) -> QuoteRevision:
    row = uow.session.scalars(
        select(QuoteRevision).where(QuoteRevision.quote_id == quote.id, QuoteRevision.revision_no == revision_no)
    ).first()
    if row is None:
        raise NotFound(code="not_found", resource_type="sales.quote_revision")
    return row


@query(READ)
def revision_document(uow: UnitOfWork, quote_id: uuid.UUID, revision_no: int) -> tuple[dict[str, Any], str]:
    """The snapshot and expected sha256 of an issued revision for an actor who may export the quote
    (404 outside read scope, 403 without ``sales.quote.export`` in scope)."""
    quote = uow.repo(Quote).get(quote_id, "export", include_archived=False)
    row = revision_row(uow, quote, revision_no)
    return dict(row.snapshot), row.document_sha256


@query(READ)
def get_revision(uow: UnitOfWork, quote_id: uuid.UUID, revision_no: int) -> QuoteRevisionRead:
    quote = _visible_quote(uow, quote_id)
    row = revision_row(uow, quote, revision_no)
    base = _revision_summary(uow, quote, [row])[0]
    return QuoteRevisionRead(**base.model_dump(), snapshot=row.snapshot)


# =====================================================================================================
# repeat-quote basis and engine preview (tools and the UI)
# =====================================================================================================
@query(READ)
def find_repeat_quote_basis(uow: UnitOfWork, party_id: uuid.UUID) -> UsualOrderOutput:
    """The most recent won quote of the party visible to the actor, with its lines as a basis."""
    party = party_ref(uow, party_id)
    quote = uow.session.scalars(
        uow.repo(Quote).select().where(Quote.party_id == party.id, Quote.status == QuoteStatus.WON.value)
        .order_by(Quote.won_at.desc(), Quote.id.desc()).limit(1)
    ).first()
    if quote is None:
        return UsualOrderOutput(status="none", party_id=party.id, explanation=f"{party.display_name} has no won quotation yet.")
    lines = lines_of(uow, quote)
    return UsualOrderOutput(
        status="found",
        party_id=party.id,
        quote_id=quote.id,
        quote_number=quote.quote_number,
        won_at=quote.won_at,
        currency=quote.currency,
        grand_total=_money(quote.grand_total_amount, quote.currency),
        lines=[
            BasisLine(
                line_no=ln.line_no, line_type=LineType(ln.line_type), product_id=ln.product_id,
                product_key=(ln.product_snapshot or {}).get("product_key"), product_name=ln.description,
                quantity=ln.quantity, unit_code=ln.unit_code, unit_price=ln.unit_price, currency=ln.currency,
            )
            for ln in lines
        ],
        explanation=f"{quote.quote_number} (won) is the most recent won quotation of {party.display_name}.",
    )


@query("pricing.price.read")
def calculate_preview(uow: UnitOfWork, data: QuotePreviewIn) -> QuotePreviewOut:
    """Engine preview over proposed lines (nothing persisted). Catalog prices resolve through pricing."""
    errors = Errors()
    party = party_ref(uow, data.party_id) if data.party_id else None
    day = business_date(uow)
    inputs: list[engine.LineInput] = []
    refs: list[PreviewLineOut] = []
    warnings: list[str] = []
    for i, line in enumerate(data.lines):
        key = line.line_key or f"L{i + 1}"
        if line.line_type == "catalog":
            assert line.product_id is not None
            product, packaging, _media, _detail = product_snapshots(uow, line.product_id)
            unit_code = line.unit_code or product.unit_of_sale or DEFAULT_UNIT
            resolution = resolve_line_price(
                uow, product_id=line.product_id, party_id=party.id if party else None, currency=data.currency,
                unit_code=unit_code, price_type=data.price_type.value, on_date=day,
            )
            if resolution.status == "ambiguous":
                raise Conflict(resolution.explanation, code="price_ambiguous")
            default = quantize_unit_price(resolution.unit_price) if resolution.status == "found" and resolution.unit_price is not None else None
            price = quantize_unit_price(line.unit_price) if line.unit_price is not None else default
            if resolution.reason_code:
                warnings.append(f"line:{key}:{resolution.reason_code}")
            inputs.append(engine.LineInput(
                line_key=key, line_type="catalog", quantity=_check_quantity(line.quantity, unit_code, errors, f"lines.{i}.quantity"),
                unit_price=price, discount_pct=line.discount_pct,
                carton_qty=packaging.carton_qty if unit_code == (product.unit_of_sale or unit_code) else None,
                product_moq=resolution.product_moq if resolution.moq_unit_code in (None, unit_code) else None,
            ))
            refs.append(PreviewLineOut(
                line_key=key, line_type="catalog", product_id=product.product_id, product_key=product.product_key, unit_code=unit_code,
                default_unit_price=default, unit_price=price, price_status="priced" if price is not None else "missing",
                reason_code=resolution.reason_code,
            ))
        else:
            unit_code = line.unit_code or DEFAULT_UNIT
            price = quantize_unit_price(line.unit_price) if line.unit_price is not None else None
            inputs.append(engine.LineInput(
                line_key=key, line_type="manual", quantity=_check_quantity(line.quantity, unit_code, errors, f"lines.{i}.quantity"),
                unit_price=price, discount_pct=line.discount_pct,
            ))
            refs.append(PreviewLineOut(
                line_key=key, line_type="manual", product_id=None, product_key=None, unit_code=unit_code,
                default_unit_price=price, unit_price=price, price_status="priced" if price is not None else "missing", reason_code=None,
            ))
    errors.raise_if_any()
    try:
        calc_input = engine.CalculationInput(currency=data.currency, lines=tuple(inputs), surcharge_requested=data.surcharge_requested)
    except ValueError as exc:
        errors.add(["lines"], "invalid_lines", str(exc))
        errors.raise_if_any()
        raise
    result = commercial.calculate(uow, calc_input)
    return QuotePreviewOut(calculation=CalculationResultOut.model_validate(result.as_dict()), lines=refs, warnings=warnings + list(result.warnings))


# =====================================================================================================
# HTTP command wrappers (optional Idempotency-Key replay)
# =====================================================================================================
def create_quote_command(uow: UnitOfWork, data: QuoteCreate) -> tuple[QuoteDetail, bool]:
    uow.actor.require("sales.quote.create")
    return idempotent(uow, "sales.create_quote", data, lambda: detail(uow, create_quote(uow, data)), QuoteDetail, status=201)


def update_quote_command(uow: UnitOfWork, quote_id: uuid.UUID, data: QuoteUpdate) -> tuple[QuoteDetail, bool]:
    uow.repo(Quote).get(quote_id, "update", include_archived=False)
    return idempotent(uow, f"sales.update_quote:{quote_id}", data, lambda: detail(uow, update_quote(uow, quote_id, data)), QuoteDetail)


def add_line_command(uow: UnitOfWork, quote_id: uuid.UUID, data: QuoteLineCreate) -> tuple[QuoteDetail, bool]:
    uow.repo(Quote).get(quote_id, "update", include_archived=False)
    return idempotent(uow, f"sales.add_line:{quote_id}", data, lambda: detail(uow, add_line(uow, quote_id, data)[0]), QuoteDetail, status=201)


def update_line_command(uow: UnitOfWork, quote_id: uuid.UUID, line_id: uuid.UUID, data: QuoteLineUpdate) -> tuple[QuoteDetail, bool]:
    uow.repo(Quote).get(quote_id, "update", include_archived=False)
    return idempotent(uow, f"sales.update_line:{quote_id}:{line_id}", data, lambda: detail(uow, update_line(uow, quote_id, line_id, data)[0]), QuoteDetail)


def remove_line_command(uow: UnitOfWork, quote_id: uuid.UUID, line_id: uuid.UUID, expected_version: int | None) -> tuple[QuoteDetail, bool]:
    uow.repo(Quote).get(quote_id, "update", include_archived=False)
    return idempotent(
        uow, f"sales.remove_line:{quote_id}:{line_id}", {"expected_version": expected_version},
        lambda: detail(uow, remove_line(uow, quote_id, line_id, expected_version=expected_version)), QuoteDetail,
    )


def refresh_snapshots_command(uow: UnitOfWork, quote_id: uuid.UUID, data: RefreshSnapshots) -> tuple[QuoteDetail, bool]:
    uow.repo(Quote).get(quote_id, "update", include_archived=False)
    return idempotent(uow, f"sales.refresh_snapshots:{quote_id}", data, lambda: detail(uow, refresh_snapshots(uow, quote_id, data)), QuoteDetail)


def delete_quote_command(uow: UnitOfWork, quote_id: uuid.UUID, expected_version: int | None) -> tuple[QuoteDetail, bool]:
    uow.repo(Quote).get(quote_id, "delete", include_archived=False)
    return idempotent(
        uow, f"sales.delete_quote:{quote_id}", {"expected_version": expected_version},
        lambda: detail(uow, delete_quote(uow, quote_id, expected_version=expected_version)), QuoteDetail,
    )


def is_closed(quote: Quote) -> bool:
    return quote.deleted_at is not None or quote.status in {s.value for s in CLOSED_STATUSES}


def zone(uow: UnitOfWork) -> str:
    return company_zone(uow)
