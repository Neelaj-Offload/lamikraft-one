"""The posting engine: the only code that writes the ledger and the balance/summary projections (ADR-021).

``post_movement(uow, PostingRequest)``:
1. Serialise on the source (advisory lock on ``source_type:source_id:purpose``), then look the source up: an existing
   posting with the same payload hash is returned (replays, double clicks, re-delivered events); a different hash is
   409 ``posting_conflict``. The database backs this with UNIQUE(company, source_type, source_id, purpose).
2. Validate: products are stock-tracked with a stock unit, lots belong to the product and are present when tracked,
   locations belong to the company, each (from type -> to type) pair is allowed, and the entered quantity follows the
   unit's entry rule and converts to the stock unit through master-data conversions (422 otherwise).
3. Lock in the documented order: summaries (product, warehouse) -> balances (key) -> reservations (id); missing
   projection rows are created first with ``INSERT ... ON CONFLICT DO NOTHING``.
4. Apply from -= q and to += q. A stock-bearing balance below zero raises 409 ``negative_stock`` (rolled back; negative
   stock is never silent). Reservation-linked lines consume their reservation. An outbound move that does not
   consume a reservation must leave ``available_on_hand >= reserved`` (409 ``reserved_stock_conflict``), except for an
   approved loss/count posting, which then emits ``inventory.reservation.shortfall_detected``.
5. Insert the posting and its movements, bump the summary versions, emit ``inventory.stock.posted``.

``reverse_posting``: a new posting with from/to swapped (same lots and owners), ``reverses_posting_id`` set and its own
source; UNIQUE(reverses_posting_id) means a posting is reversed at most once. Reservations are not recreated.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from sqlalchemy import and_, func, select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.errors import Conflict, ValidationFailed
from app.modules.catalogue.models import Product
from app.modules.inventory import events as ev
from app.modules.inventory.enums import LocationType, LotKind, ReservationStatus
from app.modules.inventory.locations import locations_by_id
from app.modules.inventory.models import (
    Location,
    Lot,
    Reservation,
    StockBalance,
    StockMovement,
    StockPosting,
    StockSummary,
)
from app.platform.org.reference import convert, validate_quantity
from app.platform.uow import UnitOfWork

L = LocationType
#: allowed (from type -> to type) pairs; a reversal posts the swapped pair of an allowed one
TRANSITION_MATRIX: frozenset[tuple[LocationType, LocationType]] = frozenset(
    {
        (L.OPENING, L.INTERNAL),
        (L.SUPPLIER, L.QC_HOLD),
        (L.SUPPLIER, L.INTERNAL),
        (L.CUSTOMER, L.QC_HOLD),
        (L.CUSTOMER, L.INTERNAL),
        (L.QC_HOLD, L.INTERNAL),
        (L.QC_HOLD, L.REJECTED),
        (L.QC_HOLD, L.SUPPLIER),
        (L.REJECTED, L.SUPPLIER),
        (L.REJECTED, L.SCRAP),
        (L.REJECTED, L.INTERNAL),
        (L.INTERNAL, L.INTERNAL),
        (L.INTERNAL, L.CUSTOMER),
        (L.INTERNAL, L.SUPPLIER),
        (L.INTERNAL, L.EXTERNAL_HOLDING),
        (L.INTERNAL, L.SAMPLE_CONSUMPTION),
        (L.INTERNAL, L.OFFICE),
        (L.INTERNAL, L.IN_TRANSIT),
        (L.INTERNAL, L.QC_HOLD),
        (L.INTERNAL, L.REJECTED),
        (L.INTERNAL, L.SCRAP),
        (L.INTERNAL, L.PRODUCTION),
        (L.INTERNAL, L.WIP),
        (L.WIP, L.INTERNAL),
        (L.WIP, L.PRODUCTION),
        (L.PRODUCTION, L.INTERNAL),
        (L.PRODUCTION, L.QC_HOLD),
        (L.IN_TRANSIT, L.INTERNAL),
        (L.EXTERNAL_HOLDING, L.QC_HOLD),
        (L.EXTERNAL_HOLDING, L.INTERNAL),
        (L.EXTERNAL_HOLDING, L.CUSTOMER),
        (L.EXTERNAL_HOLDING, L.PRODUCTION),
        (L.OFFICE, L.INTERNAL),
        (L.OFFICE, L.QC_HOLD),
        (L.OFFICE, L.SAMPLE_CONSUMPTION),
        (L.OFFICE, L.EXTERNAL_HOLDING),
        # a consumed sample that comes back
        (L.SAMPLE_CONSUMPTION, L.QC_HOLD),
        (L.SAMPLE_CONSUMPTION, L.INTERNAL),
        # counts, adjustments and write-offs go through the adjustment location
        *(
            (L.ADJUSTMENT, t)
            for t in (L.INTERNAL, L.QC_HOLD, L.REJECTED, L.EXTERNAL_HOLDING, L.OFFICE, L.IN_TRANSIT)
        ),
        *(
            (t, L.ADJUSTMENT)
            for t in (L.INTERNAL, L.QC_HOLD, L.REJECTED, L.EXTERNAL_HOLDING, L.OFFICE, L.IN_TRANSIT)
        ),
    }
)
ZERO = Decimal(0)


class NegativeStockError(Conflict):
    code, title = "negative_stock", "Not enough stock"


class ReservedStockConflict(Conflict):
    code, title = "reserved_stock_conflict", "That stock is reserved for other demand"


class PostingConflict(Conflict):
    code, title = "posting_conflict", "This source was already posted with different content"


@dataclass(frozen=True)
class PostingLine:
    product_id: uuid.UUID
    #: the quantity as entered, in ``uom_code`` (converted to the product's stock unit)
    quantity: Decimal
    uom_code: str
    from_location_id: uuid.UUID
    to_location_id: uuid.UUID
    lot_id: uuid.UUID | None = None
    owner_party_id: uuid.UUID | None = None
    counterparty_party_id: uuid.UUID | None = None
    reservation_id: uuid.UUID | None = None
    source_line_type: str | None = None
    source_line_id: uuid.UUID | None = None


@dataclass(frozen=True)
class PostingRequest:
    source_type: str
    source_id: uuid.UUID
    purpose: str
    lines: tuple[PostingLine, ...]
    source_label: str | None = None
    reason_code: str | None = None
    reason: str | None = None
    reverses_posting_id: uuid.UUID | None = None
    #: approved loss / count postings may eat into reservations (a shortfall is then emitted, never silent)
    allow_reserved_shortfall: bool = False
    idempotency_key: str | None = None
    effective_at: datetime | None = None
    #: reversals post the swapped pair of an allowed transition
    is_reversal: bool = False


@dataclass
class _Line:
    req: PostingLine
    base_qty: Decimal
    stock_uom: str
    from_loc: Location
    to_loc: Location
    lot_kind: str | None


@dataclass
class PostingReceipt:
    posting: StockPosting
    replayed: bool
    shortfalls: list[tuple[uuid.UUID, uuid.UUID]] = field(default_factory=list)


def _source_key(req: PostingRequest) -> str:
    return f"{req.source_type}:{req.source_id}:{req.purpose}"


def payload_hash(req: PostingRequest) -> str:
    body = {
        "source": _source_key(req),
        "reverses": str(req.reverses_posting_id) if req.reverses_posting_id else None,
        "lines": [
            {
                "product": str(ln.product_id),
                "qty": format(Decimal(ln.quantity).normalize(), "f"),
                "uom": ln.uom_code,
                "from": str(ln.from_location_id),
                "to": str(ln.to_location_id),
                "lot": str(ln.lot_id) if ln.lot_id else None,
                "owner": str(ln.owner_party_id) if ln.owner_party_id else None,
                "reservation": str(ln.reservation_id) if ln.reservation_id else None,
                "source_line": str(ln.source_line_id) if ln.source_line_id else None,
            }
            for ln in req.lines
        ],
    }
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def find_posting(
    uow: UnitOfWork, source_type: str, source_id: uuid.UUID, purpose: str
) -> StockPosting | None:
    return uow.session.scalars(
        select(StockPosting).where(
            StockPosting.company_id == uow.actor.company_id,
            StockPosting.source_type == source_type,
            StockPosting.source_id == source_id,
            StockPosting.purpose == purpose,
        )
    ).first()


def _problem(
    errors: list[dict[str, object]], detail: str = "Some stock movement lines are not valid"
) -> None:
    if errors:
        raise ValidationFailed(detail, errors=errors)


def _validate(uow: UnitOfWork, req: PostingRequest) -> list[_Line]:
    if not req.lines:
        raise ValidationFailed(
            "A posting needs at least one line",
            errors=[{"loc": ["body", "lines"], "msg": "no lines", "code": "no_lines"}],
        )
    products = {
        p.id: p
        for p in uow.session.scalars(
            select(Product).where(
                Product.company_id == uow.actor.company_id,
                Product.id.in_({ln.product_id for ln in req.lines}),
            )
        )
    }
    locs = locations_by_id(uow, [x for ln in req.lines for x in (ln.from_location_id, ln.to_location_id)])
    lot_ids = {ln.lot_id for ln in req.lines if ln.lot_id}
    lots = (
        {
            lot.id: lot
            for lot in uow.session.scalars(
                select(Lot).where(Lot.company_id == uow.actor.company_id, Lot.id.in_(lot_ids))
            )
        }
        if lot_ids
        else {}
    )
    errors: list[dict[str, object]] = []
    out: list[_Line] = []
    for i, ln in enumerate(req.lines):
        loc = ["body", "lines", i]
        product = products.get(ln.product_id)
        if product is None:
            errors.append(
                {"loc": [*loc, "product_id"], "msg": "unknown product", "code": "product_not_found"}
            )
            continue
        if not product.is_stock_tracked:
            errors.append(
                {
                    "loc": [*loc, "product_id"],
                    "msg": f"{product.product_key} is not stock-tracked",
                    "code": "product_not_stock_tracked",
                }
            )
            continue
        if not product.stock_uom_code:
            errors.append({"loc": [*loc, "product_id"], "msg": "no stock unit", "code": "stock_uom_missing"})
            continue
        lot = lots.get(ln.lot_id) if ln.lot_id else None
        if ln.lot_id and (lot is None or lot.product_id != product.id):
            errors.append(
                {"loc": [*loc, "lot_id"], "msg": "the lot belongs to another product", "code": "lot_mismatch"}
            )
            continue
        if product.track_lots and lot is None:
            errors.append(
                {
                    "loc": [*loc, "lot_id"],
                    "msg": f"{product.product_key} is lot-tracked",
                    "code": "lot_required",
                }
            )
            continue
        src, dst = locs.get(ln.from_location_id), locs.get(ln.to_location_id)
        if src is None or dst is None:
            errors.append(
                {"loc": [*loc, "location_id"], "msg": "unknown location", "code": "location_not_found"}
            )
            continue
        if src.id == dst.id:
            errors.append(
                {"loc": [*loc, "to_location_id"], "msg": "from and to are the same", "code": "same_location"}
            )
            continue
        pair = (LocationType(src.location_type), LocationType(dst.location_type))
        allowed = (pair[1], pair[0]) in TRANSITION_MATRIX if req.is_reversal else pair in TRANSITION_MATRIX
        if not allowed:
            errors.append(
                {
                    "loc": [*loc, "to_location_id"],
                    "msg": f"stock cannot move from {pair[0].value} to {pair[1].value}",
                    "code": "transition_not_allowed",
                }
            )
            continue
        try:
            entered, entered_uom = validate_quantity(uow, Decimal(ln.quantity), ln.uom_code)
            base = convert(uow, entered, entered_uom, product.stock_uom_code, product.id)
        except ValidationFailed as exc:
            for item in exc.extra.get("errors") or [{"msg": exc.detail, "code": exc.code}]:
                errors.append(
                    {
                        "loc": [*loc, "quantity"],
                        "msg": item.get("msg", ""),
                        "code": item.get("code", "invalid"),
                    }
                )
            continue
        if base <= 0:
            errors.append({"loc": [*loc, "quantity"], "msg": "converts to zero", "code": "not_positive"})
            continue
        out.append(_Line(ln, base, product.stock_uom_code, src, dst, lot.lot_kind if lot else None))
    _problem(errors)
    return out


def _counts_available(loc: Location, owner: uuid.UUID | None, lot_kind: str | None) -> bool:
    return bool(
        loc.counts_available
        and loc.warehouse_id is not None
        and owner is None
        and lot_kind != LotKind.OFFCUT.value
    )


def lock_summaries(
    uow: UnitOfWork, keys: set[tuple[uuid.UUID, uuid.UUID]]
) -> dict[tuple[uuid.UUID, uuid.UUID], StockSummary]:
    """Create missing (product, warehouse) summaries, then lock them in key order (lock-order step 3)."""
    if not keys:
        return {}
    company = uow.actor.company_id
    now = uow.now()
    uow.session.execute(
        pg_insert(StockSummary)
        .values(
            [
                {
                    "id": uuid.uuid7(),
                    "company_id": company,
                    "product_id": p,
                    "warehouse_id": w,
                    "available_on_hand": ZERO,
                    "reserved": ZERO,
                    "version": 0,
                    "updated_at": now,
                }
                for p, w in sorted(keys)
            ]
        )
        .on_conflict_do_nothing()
    )
    rows = uow.session.scalars(
        select(StockSummary)
        .where(
            StockSummary.company_id == company,
            tuple_(StockSummary.product_id, StockSummary.warehouse_id).in_(sorted(keys)),
        )
        .order_by(StockSummary.product_id, StockSummary.warehouse_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return {(s.product_id, s.warehouse_id): s for s in rows}


BalanceKey = tuple[uuid.UUID, uuid.UUID, uuid.UUID | None, uuid.UUID | None]


def _lock_balances(uow: UnitOfWork, keys: dict[BalanceKey, Location]) -> dict[BalanceKey, StockBalance]:
    company = uow.actor.company_id
    uow.session.execute(
        pg_insert(StockBalance)
        .values(
            [
                {
                    "id": uuid.uuid7(),
                    "company_id": company,
                    "product_id": k[0],
                    "location_id": k[1],
                    "lot_id": k[2],
                    "owner_party_id": k[3],
                    "warehouse_id": loc.warehouse_id,
                    "quantity": ZERO,
                    "enforce_non_negative": loc.is_stock_bearing,
                }
                for k, loc in sorted(keys.items(), key=lambda kv: tuple(str(x) for x in kv[0]))
            ]
        )
        .on_conflict_do_nothing()
    )
    conds = [
        and_(
            StockBalance.product_id == k[0],
            StockBalance.location_id == k[1],
            StockBalance.lot_id.is_(None) if k[2] is None else StockBalance.lot_id == k[2],
            StockBalance.owner_party_id.is_(None) if k[3] is None else StockBalance.owner_party_id == k[3],
        )
        for k in keys
    ]
    from sqlalchemy import or_

    rows = uow.session.scalars(
        select(StockBalance)
        .where(StockBalance.company_id == company, or_(*conds))
        .order_by(
            StockBalance.product_id,
            StockBalance.location_id,
            StockBalance.lot_id.nulls_first(),
            StockBalance.owner_party_id.nulls_first(),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return {(b.product_id, b.location_id, b.lot_id, b.owner_party_id): b for b in rows}


def post_movement(uow: UnitOfWork, req: PostingRequest) -> PostingReceipt:
    """Post ``req`` exactly once (see the module docstring). Returns the receipt; ``replayed`` when it already existed."""
    uow.advisory_xact_lock("inventory.posting", _source_key(req))
    digest = payload_hash(req)
    existing = find_posting(uow, req.source_type, req.source_id, req.purpose)
    if existing is not None:
        if existing.payload_hash != digest:
            raise PostingConflict(
                "This document was already posted with different lines", posting_id=str(existing.id)
            )
        return PostingReceipt(existing, replayed=True)
    key = req.idempotency_key or _source_key(req)
    if req.idempotency_key:
        other = uow.session.scalars(
            select(StockPosting).where(
                StockPosting.company_id == uow.actor.company_id, StockPosting.idempotency_key == key
            )
        ).first()
        if other is not None:
            if other.payload_hash != digest:
                raise PostingConflict(
                    "The idempotency key was used for another posting", posting_id=str(other.id)
                )
            return PostingReceipt(other, replayed=True)
    lines = _validate(uow, req)

    # ---- deltas ------------------------------------------------------------------------------------------
    balance_delta: dict[BalanceKey, Decimal] = defaultdict(lambda: ZERO)
    balance_loc: dict[BalanceKey, Location] = {}
    summary_delta: dict[tuple[uuid.UUID, uuid.UUID], Decimal] = defaultdict(lambda: ZERO)
    summary_unreserved_out: dict[tuple[uuid.UUID, uuid.UUID], Decimal] = defaultdict(lambda: ZERO)
    for ln in lines:
        r = ln.req
        for loc, sign in ((ln.from_loc, -1), (ln.to_loc, 1)):
            k: BalanceKey = (r.product_id, loc.id, r.lot_id, r.owner_party_id)
            balance_delta[k] += sign * ln.base_qty
            balance_loc[k] = loc
            if _counts_available(loc, r.owner_party_id, ln.lot_kind):
                assert loc.warehouse_id is not None
                summary_delta[(r.product_id, loc.warehouse_id)] += sign * ln.base_qty
                if sign < 0 and r.reservation_id is None:
                    summary_unreserved_out[(r.product_id, loc.warehouse_id)] += ln.base_qty
    # every touched (product, warehouse) is locked, even when only non-available locations move (serialises counts)
    summary_keys = set(summary_delta)
    for ln in lines:
        for loc in (ln.from_loc, ln.to_loc):
            if loc.warehouse_id is not None:
                summary_keys.add((ln.req.product_id, loc.warehouse_id))

    # ---- locks in the documented order -------------------------------------------------------------------
    summaries = lock_summaries(uow, summary_keys)
    balances = _lock_balances(uow, balance_loc)
    reservation_ids = sorted({ln.req.reservation_id for ln in lines if ln.req.reservation_id})
    reservations = {r.id: r for r in uow.lock(Reservation, reservation_ids)}
    for r in reservations.values():
        uow.session.refresh(r)  # the identity map may hold a copy read before the lock

    # ---- balances --------------------------------------------------------------------------------------
    now = uow.now()
    for k, delta in balance_delta.items():
        bal = balances[k]
        new_qty = Decimal(bal.quantity) + delta
        if bal.enforce_non_negative and new_qty < 0:
            loc = balance_loc[k]
            raise NegativeStockError(
                f"Only {format(Decimal(bal.quantity).normalize(), 'f')} on hand at {loc.code}",
                product_id=str(k[0]),
                location_id=str(k[1]),
                lot_id=str(k[2]) if k[2] else None,
                shortfall=format((-new_qty).normalize(), "f"),
            )
        bal.quantity = new_qty
        bal.last_movement_at = now

    # ---- reservations consumed by this posting ------------------------------------------------------------
    consumed: dict[tuple[uuid.UUID, uuid.UUID], Decimal] = defaultdict(lambda: ZERO)
    for ln in lines:
        rid = ln.req.reservation_id
        if rid is None:
            continue
        res = reservations.get(rid)
        if res is None or res.status != ReservationStatus.ACTIVE.value:
            raise Conflict(
                "The reservation is no longer active", code="reservation_not_active", reservation_id=str(rid)
            )
        if res.product_id != ln.req.product_id or ln.from_loc.warehouse_id != res.warehouse_id:
            raise Conflict("The reservation is for another product or warehouse", code="reservation_mismatch")
        remaining = Decimal(res.quantity) - Decimal(res.consumed_qty) - Decimal(res.released_qty)
        if ln.base_qty > remaining:
            raise Conflict(
                "The movement exceeds what is reserved", code="reservation_exceeded", reservation_id=str(rid)
            )
        res.consumed_qty = Decimal(res.consumed_qty) + ln.base_qty
        if Decimal(res.consumed_qty) + Decimal(res.released_qty) >= Decimal(res.quantity):
            res.status = ReservationStatus.FULFILLED.value
        consumed[(res.product_id, res.warehouse_id)] += ln.base_qty

    # ---- summaries -----------------------------------------------------------------------------------------
    shortfalls: list[tuple[uuid.UUID, uuid.UUID]] = []
    for sk, summary in summaries.items():
        summary.available_on_hand = Decimal(summary.available_on_hand) + summary_delta.get(sk, ZERO)
        summary.reserved = Decimal(summary.reserved) - consumed.get(sk, ZERO)
        if summary_unreserved_out.get(sk, ZERO) > 0 and summary.available_on_hand < summary.reserved:
            if not req.allow_reserved_shortfall:
                raise ReservedStockConflict(
                    "The movement would use stock reserved for other demand",
                    product_id=str(sk[0]),
                    warehouse_id=str(sk[1]),
                )
            shortfalls.append(sk)
        summary.version = int(summary.version) + 1
        summary.updated_at = now

    # ---- the posting and its movements ------------------------------------------------------------------------
    posting = StockPosting(
        id=uuid.uuid7(),
        company_id=uow.actor.company_id,
        source_type=req.source_type,
        source_id=req.source_id,
        purpose=req.purpose,
        source_label=req.source_label,
        idempotency_key=key,
        payload_hash=digest,
        effective_at=req.effective_at or now,
        posted_at=now,
        posted_by=uow.actor.user_id,
        reason_code=req.reason_code,
        reason=req.reason,
        reverses_posting_id=req.reverses_posting_id,
        movement_count=len(lines),
    )
    uow.add(posting)
    uow.flush()
    for i, ln in enumerate(lines, start=1):
        r = ln.req
        uow.add(
            StockMovement(
                id=uuid.uuid7(),
                company_id=uow.actor.company_id,
                posting_id=posting.id,
                line_no=i,
                product_id=r.product_id,
                lot_id=r.lot_id,
                owner_party_id=r.owner_party_id,
                from_location_id=ln.from_loc.id,
                to_location_id=ln.to_loc.id,
                from_warehouse_id=ln.from_loc.warehouse_id,
                to_warehouse_id=ln.to_loc.warehouse_id,
                quantity=ln.base_qty,
                uom_code=ln.stock_uom,
                entered_qty=Decimal(r.quantity),
                entered_uom=r.uom_code,
                counterparty_party_id=r.counterparty_party_id,
                reservation_id=r.reservation_id,
                source_line_type=r.source_line_type,
                source_line_id=r.source_line_id,
                created_at=now,
            )
        )
    uow.flush()
    product_ids = sorted({str(ln.req.product_id) for ln in lines})
    warehouse_ids = sorted({str(w) for (_p, w) in summary_keys})
    uow.emit(
        ev.STOCK_POSTED,
        aggregate_id=posting.id,
        aggregate_version=1,
        payload={
            "posting_id": str(posting.id),
            "source_type": req.source_type,
            "source_id": str(req.source_id),
            "purpose": req.purpose,
            "product_ids": product_ids,
            "warehouse_ids": warehouse_ids,
        },
    )
    for product_id, warehouse_id in shortfalls:
        from app.modules.inventory.reservations import emit_shortfall_for_holders

        emit_shortfall_for_holders(uow, product_id, warehouse_id)
    return PostingReceipt(posting, replayed=False, shortfalls=shortfalls)


def movements_of(uow: UnitOfWork, posting_id: uuid.UUID) -> list[StockMovement]:
    return list(
        uow.session.scalars(
            select(StockMovement)
            .where(StockMovement.company_id == uow.actor.company_id, StockMovement.posting_id == posting_id)
            .order_by(StockMovement.line_no)
        )
    )


def reverse_posting(
    uow: UnitOfWork,
    posting_id: uuid.UUID,
    *,
    reason_code: str,
    reason: str | None = None,
    source: tuple[str, uuid.UUID, str] | None = None,
    source_label: str | None = None,
) -> PostingReceipt:
    """A compensating posting (from/to swapped) for ``posting_id``; replay-safe and at most once per posting."""
    original = uow.session.scalars(
        select(StockPosting).where(
            StockPosting.company_id == uow.actor.company_id, StockPosting.id == posting_id
        )
    ).first()
    if original is None:
        from app.core.errors import NotFound

        raise NotFound("posting not found", code="posting_not_found")
    if original.reverses_posting_id is not None:
        raise Conflict("A reversal cannot itself be reversed", code="reversal_of_reversal")
    source_type, source_id, purpose = source or ("reversal", original.id, "reverse")
    already = uow.session.scalars(
        select(StockPosting).where(
            StockPosting.company_id == uow.actor.company_id, StockPosting.reverses_posting_id == original.id
        )
    ).first()
    if already is not None:
        if (already.source_type, already.source_id, already.purpose) == (source_type, source_id, purpose):
            return PostingReceipt(already, replayed=True)
        raise Conflict(
            "This posting was already reversed", code="already_reversed", reversal_posting_id=str(already.id)
        )
    lines = tuple(
        PostingLine(
            product_id=m.product_id,
            quantity=Decimal(m.quantity),
            uom_code=m.uom_code,
            from_location_id=m.to_location_id,
            to_location_id=m.from_location_id,
            lot_id=m.lot_id,
            owner_party_id=m.owner_party_id,
            counterparty_party_id=m.counterparty_party_id,
            source_line_type=m.source_line_type,
            source_line_id=m.source_line_id,
        )
        for m in movements_of(uow, original.id)
    )
    receipt = post_movement(
        uow,
        PostingRequest(
            source_type=source_type,
            source_id=source_id,
            purpose=purpose,
            lines=lines,
            source_label=source_label or original.source_label,
            reason_code=reason_code,
            reason=reason,
            reverses_posting_id=original.id,
            idempotency_key=f"reversal:{original.id}",
            is_reversal=True,
        ),
    )
    if not receipt.replayed:
        uow.emit(
            ev.POSTING_REVERSED,
            aggregate_id=original.id,
            aggregate_version=1,
            payload={"posting_id": str(original.id), "reversal_posting_id": str(receipt.posting.id)},
        )
    return receipt


def high_water_seq(uow: UnitOfWork) -> int:
    return int(
        uow.session.scalar(
            select(func.coalesce(func.max(StockMovement.seq), 0)).where(
                StockMovement.company_id == uow.actor.company_id
            )
        )
        or 0
    )
