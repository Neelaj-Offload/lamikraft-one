"""Duplicate a quote (LM-55, BUG-02, LP-06.7) and change its owner.

A duplicate is a new draft with a new number whose totals are computed by the engine in the same transaction (never
0), ``customer_reference`` cleared, no review/outcome/dispatch state, and no internal notes. The owner follows the
``quote_defaults.duplicate_copies_assignee`` policy: the source owner is kept when the policy is on and the actor
may assign quotes to that person (management), otherwise the actor owns the copy. ``price_mode=refresh`` re-resolves
catalog prices (a line that no longer resolves keeps its source price and is reported).
"""

from __future__ import annotations

import uuid

from app.core.db.base import new_id
from app.core.errors import Forbidden
from app.core.money import quantize_unit_price
from app.modules.sales import events as ev
from app.modules.sales import quotes
from app.modules.sales.common import Errors, check_member, idempotent
from app.modules.sales.models import Quote, QuoteLine
from app.modules.sales.revisions import LINE_FIELDS, _from_json
from app.modules.sales.schemas import (
    ChangeOwner,
    DuplicateQuote,
    LineType,
    PriceMode,
    QuoteCreate,
    QuoteDetail,
    TransitionAction,
)
from app.platform.uow import UnitOfWork


def _copy_owner(uow: UnitOfWork, source: Quote) -> uuid.UUID:
    from app.platform.org.service import effective_value

    actor = uow.actor
    assert actor.user_id is not None
    defaults = effective_value(uow, "quote_defaults")
    keep = bool(getattr(defaults, "duplicate_copies_assignee", True))
    if keep and source.owner_user_id != actor.user_id and actor.can("sales.quote.assign"):
        return source.owner_user_id
    return actor.user_id


def _source_lines(uow: UnitOfWork, source: Quote, from_revision_no: int | None) -> list[dict[str, object]]:
    if from_revision_no is None:
        return [
            {"line_no": ln.line_no, **{name: getattr(ln, name) for name in LINE_FIELDS}} for ln in quotes.lines_of(uow, source)
        ]
    revision = quotes.revision_row(uow, source, from_revision_no)
    working = revision.snapshot.get("working_copy")
    if not working:
        from app.modules.sales.revisions import _fallback_lines

        rows = _fallback_lines(revision.snapshot)
    else:
        rows = working["lines"]
    return [{"line_no": r["line_no"], **{name: _from_json(name, r.get(name)) for name in LINE_FIELDS if name in r}} for r in rows]


def duplicate_quote(uow: UnitOfWork, quote_id: uuid.UUID, data: DuplicateQuote, *, origin: str | None = None) -> tuple[Quote, list[str]]:
    """Returns the new draft and per-line warnings (``line:<n>:PRICE_NOT_REFRESHED``)."""
    uow.actor.require("sales.quote.create")
    source = uow.repo(Quote).get(quote_id, include_archived=False)  # 404 outside read scope
    header_src: dict[str, object] = {
        "price_type": source.price_type, "currency": source.currency, "incoterm": source.incoterm,
        "incoterm_place": source.incoterm_place, "payment_terms": source.payment_terms, "validity_days": source.validity_days,
        "remarks": source.remarks, "apply_minimum_surcharge": source.apply_minimum_surcharge,
    }
    if data.from_revision_no is not None:
        revision = quotes.revision_row(uow, source, data.from_revision_no)
        header_src.update({k: v for k, v in (revision.snapshot.get("working_copy") or {}).get("header", {}).items()
                           if k in header_src and v is not None})
    owner = _copy_owner(uow, source)
    copy = quotes.create_quote(
        uow,
        QuoteCreate(
            party_id=data.party_id or source.party_id,
            owner_user_id=owner,
            branch_id=source.branch_id,
            brand=source.brand,
            price_type=header_src["price_type"],  # type: ignore[arg-type]
            currency=header_src["currency"],  # type: ignore[arg-type]
            incoterm=header_src["incoterm"],  # type: ignore[arg-type]
            incoterm_place=header_src["incoterm_place"],  # type: ignore[arg-type]
            payment_terms=header_src["payment_terms"],  # type: ignore[arg-type]
            validity_days=int(header_src["validity_days"]),  # type: ignore[arg-type]
            customer_reference=None,  # legacy parity: the customer's reference belongs to the original request
            remarks=header_src["remarks"],  # type: ignore[arg-type]
            apply_minimum_surcharge=bool(header_src["apply_minimum_surcharge"]),
        ),
        origin=origin,
    )
    copy.duplicated_from_quote_id = source.id
    warnings: list[str] = []
    new_lines: list[QuoteLine] = []
    for position, row in enumerate(sorted(_source_lines(uow, source, data.from_revision_no), key=lambda r: int(r["line_no"])), start=1):  # type: ignore[arg-type]
        values = {name: row.get(name) for name in LINE_FIELDS}
        values["currency"] = copy.currency
        line = QuoteLine(id=new_id(), company_id=uow.actor.company_id, quote_id=copy.id, line_no=position, line_key=new_id(),
                         internal_note=None, **values)
        if values.get("override_reason"):
            line.override_by = uow.actor.user_id
            line.override_at = uow.now()
        refresh = data.price_mode == PriceMode.REFRESH or data.party_id not in (None, source.party_id)
        if refresh and line.line_type == LineType.CATALOG.value and line.product_id is not None:
            resolution = quotes.resolve_line_price(
                uow, product_id=line.product_id, party_id=copy.party_id, currency=copy.currency, unit_code=line.unit_code,
                price_type=copy.price_type,
            )
            if resolution.status == "found" and resolution.unit_price is not None:
                new_default = quantize_unit_price(resolution.unit_price.amount)
                was_overridden = line.unit_price is not None and line.default_unit_price is not None and line.unit_price != line.default_unit_price
                line.default_unit_price = new_default
                if not was_overridden:
                    line.unit_price = new_default
                line.price_list_item_id = resolution.item_id
                line.commercial_snapshot = quotes.commercial_snapshot(resolution, line.unit_code).model_dump(mode="json")
                quotes.apply_provenance(line, resolution)
            else:
                warnings.append(f"line:{position}:PRICE_NOT_REFRESHED")
        uow.add(line)
        new_lines.append(line)
    uow.flush()
    quotes.recalculate(uow, copy, new_lines)
    copy.updated_at = uow.now()
    uow.flush()
    uow.emit(ev.QUOTE_DUPLICATED, aggregate_id=copy.id, aggregate_version=copy.version,
             payload=ev.payload(ev.QuoteDuplicatedPayload(quote_id=copy.id, source_quote_id=source.id, origin=origin)))
    uow.audit("sales.quote.duplicated", resource_type="sales.quote", resource_id=copy.id, resource_label=copy.quote_number,
              details={"source_quote_number": source.quote_number, "price_mode": data.price_mode.value,
                       "from_revision_no": data.from_revision_no, "warnings": warnings})
    return copy, warnings


def duplicate_quote_command(uow: UnitOfWork, quote_id: uuid.UUID, data: DuplicateQuote) -> tuple[QuoteDetail, bool]:
    uow.actor.require("sales.quote.create")
    uow.repo(Quote).get(quote_id, include_archived=False)
    return idempotent(
        uow, f"sales.duplicate_quote:{quote_id}", data, lambda: quotes.detail(uow, duplicate_quote(uow, quote_id, data)[0]),
        QuoteDetail, status=201,
    )


def change_owner(uow: UnitOfWork, quote_id: uuid.UUID, data: ChangeOwner, *, origin: str | None = None) -> Quote:
    """Reassign a quote (``sales.quote.assign`` over the quote); the previous owner may lose visibility."""
    from app.modules.sales.transitions import write_history

    repo = uow.repo(Quote)
    quote = repo.get(quote_id, for_update=True, include_archived=False)
    try:
        repo.require_action(quote, "assign")
    except Forbidden:
        raise Forbidden("Reassigning a quote needs sales.quote.assign", code="permission_denied", permission="sales.quote.assign") from None
    uow.expect_version(quote, data.expected_version)
    errors = Errors()
    check_member(uow, data.owner_user_id, errors, "owner_user_id")
    errors.raise_if_any()
    previous = quote.owner_user_id
    if previous == data.owner_user_id:
        return quote
    quote.owner_user_id = data.owner_user_id
    quote.updated_at = uow.now()
    uow.flush()
    write_history(uow, quote, action=TransitionAction.CHANGE_OWNER.value, from_status=quote.status, to_status=quote.status,
                  reason=data.reason)
    uow.emit(ev.QUOTE_OWNER_CHANGED, aggregate_id=quote.id, aggregate_version=quote.version,
             payload=ev.payload(ev.QuoteOwnerChangedPayload(quote_id=quote.id, from_user_id=previous, to_user_id=data.owner_user_id,
                                                            origin=origin)))
    uow.audit("sales.quote.owner_changed", resource_type="sales.quote", resource_id=quote.id, resource_label=quote.quote_number,
              reason=data.reason, details={"from_user_id": str(previous), "to_user_id": str(data.owner_user_id)})
    return quote


def change_owner_command(uow: UnitOfWork, quote_id: uuid.UUID, data: ChangeOwner) -> tuple[QuoteDetail, bool]:
    uow.repo(Quote).get(quote_id, include_archived=False)
    return idempotent(uow, f"sales.change_owner:{quote_id}", data, lambda: quotes.detail(uow, change_owner(uow, quote_id, data)), QuoteDetail)
