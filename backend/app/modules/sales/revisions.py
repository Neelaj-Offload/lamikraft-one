"""Revision compare and restore (LM-54, FG-QRV-03, LP-06.10).

An issued revision is immutable (append-only table). It carries the printed document input plus a ``working_copy``
section (every priced line field and the editable header) so a revision can be restored into the working copy
without losing provenance. Restoring never rewrites history: a sent quote is revised first, the restore is a
history row, and the next issue creates a new revision. Internal notes are never part of a revision; on restore a
line keeps the internal note of the working-copy line with the same ``line_key``.

Compare works between two issued revisions or between a revision and the working copy: header fields, lines by
``line_key`` (added, removed, changed, moved) and the persisted totals.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.core.db.base import new_id
from app.core.errors import Conflict
from app.core.money import quantize_money
from app.modules.sales import documents, quotes
from app.modules.sales import events as ev
from app.modules.sales.common import idempotent
from app.modules.sales.models import LINE_NO_CONSTRAINT, Quote, QuoteLine, QuoteRevision
from app.modules.sales.schemas import (
    FieldChange,
    LineDiff,
    QuoteDetail,
    QuoteStatus,
    RestoreRevision,
    RevisionCompare,
    TotalDiff,
    TransitionAction,
)
from app.platform.service import query
from app.platform.uow import UnitOfWork

#: editable header fields restored from a revision (party and owner never change on restore)
HEADER_FIELDS = (
    "currency", "price_type", "incoterm", "incoterm_place", "payment_terms", "validity_days", "customer_reference",
    "remarks", "apply_minimum_surcharge",
)
LINE_FIELDS = (
    "line_type", "product_id", "custom_product_id", "description", "manual_preset", "quantity", "unit_code",
    "default_unit_price", "unit_price", "currency", "override_reason", "override_by", "override_at", "discount_pct",
    "remarks", "price_list_item_id", "product_snapshot", "packaging_snapshot", "media_snapshot", "commercial_snapshot",
    "source_currency", "source_unit_price", "fx_rate_id", "fx_rate",
)
COMPARED_LINE_FIELDS = ("product_key", "description", "quantity", "unit_code", "unit_price", "discount_pct", "line_total")
TOTAL_FIELDS = ("gross_subtotal", "discount_total", "net_subtotal", "surcharge", "grand_total")
_DECIMALS = {"quantity", "default_unit_price", "unit_price", "discount_pct", "source_unit_price", "fx_rate"}
_UUIDS = {"product_id", "custom_product_id", "override_by", "price_list_item_id", "fx_rate_id"}


def _json(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def working_copy_of(quote: Quote, lines: list[QuoteLine]) -> dict[str, Any]:
    """The restorable content of a quote (stored on every issued revision; no internal notes)."""
    return {
        "header": {name: _json(getattr(quote, name)) for name in HEADER_FIELDS},
        "lines": [
            {"line_no": ln.line_no, "line_key": str(ln.line_key), **{name: _json(getattr(ln, name)) for name in LINE_FIELDS}}
            for ln in lines
        ],
    }


def _from_json(name: str, value: Any) -> Any:
    if value is None:
        return None
    if name in _DECIMALS:
        return Decimal(str(value))
    if name in _UUIDS:
        return uuid.UUID(str(value))
    if name == "override_at":
        return datetime.fromisoformat(str(value))
    return value


def _fallback_lines(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Revisions issued before ``working_copy`` existed: rebuild the priced fields from the document lines."""
    out: list[dict[str, Any]] = []
    for ln in snapshot.get("lines", []):
        out.append({
            "line_no": ln["line_no"], "line_key": ln["line_key"], "line_type": ln["line_type"], "product_id": ln.get("product_id"),
            "custom_product_id": None, "description": ln["description"], "manual_preset": None, "quantity": ln["quantity"],
            "unit_code": ln["unit_code"], "default_unit_price": ln.get("default_unit_price"), "unit_price": ln.get("unit_price"),
            "currency": snapshot["header"]["currency"], "discount_pct": ln.get("discount_pct"), "remarks": ln.get("remarks"),
        })
    return out


def load_working_copy(uow: UnitOfWork, quote: Quote, revision: QuoteRevision) -> list[QuoteLine]:
    """Replace the quote's lines (new ids, same ``line_key``) and editable header with the revision's content."""
    snapshot = revision.snapshot
    working = snapshot.get("working_copy") or {"header": {k: snapshot["header"].get(k) for k in HEADER_FIELDS},
                                               "lines": _fallback_lines(snapshot)}
    current = quotes.lines_of(uow, quote)
    notes = {str(ln.line_key): ln.internal_note for ln in current}
    for ln in current:
        uow.session.delete(ln)
    uow.flush()
    uow.defer_constraints(LINE_NO_CONSTRAINT)
    header = working["header"]
    for name in HEADER_FIELDS:
        value = header.get(name)
        if name == "currency" and value:
            quote.currency = value
            quote.totals_currency = value
        elif name == "validity_days":
            quote.validity_days = int(value or quote.validity_days)
        elif name == "apply_minimum_surcharge":
            quote.apply_minimum_surcharge = bool(value)
        elif name != "currency":
            setattr(quote, name, value)
    restored: list[QuoteLine] = []
    for position, data in enumerate(sorted(working["lines"], key=lambda d: d["line_no"]), start=1):
        line = QuoteLine(
            id=new_id(),
            company_id=uow.actor.company_id,
            quote_id=quote.id,
            line_no=position,
            line_key=uuid.UUID(str(data["line_key"])),
            internal_note=notes.get(str(data["line_key"])),
            restored_from_revision_no=revision.revision_no,
            **{name: _from_json(name, data.get(name)) for name in LINE_FIELDS if name in data},
        )
        if line.currency is None:
            line.currency = quote.currency
        uow.add(line)
        restored.append(line)
    uow.flush()
    quotes.recalculate(uow, quote, restored)
    return restored


# =====================================================================================================
# restore
# =====================================================================================================
def restore_revision(
    uow: UnitOfWork, quote_id: uuid.UUID, revision_no: int, data: RestoreRevision, *, origin: str | None = None
) -> Quote:
    """Copy issued revision ``revision_no`` into the working copy. From ``sent`` the quote is revised first (the
    restore never touches issued revisions); from ``draft``/``revised`` the working copy is replaced."""
    from app.modules.sales.transitions import emit_status_changed, write_history

    repo = uow.repo(Quote)
    quote = repo.get(quote_id, for_update=True, include_archived=False)
    uow.expect_version(quote, data.expected_version)
    revision = quotes.revision_row(uow, quote, revision_no)
    if quote.status == QuoteStatus.SENT.value:
        repo.require_action(quote, "transition")
        quote.status = QuoteStatus.REVISED.value
        quote.updated_at = uow.now()
        uow.flush()
        write_history(uow, quote, action=TransitionAction.REVISE.value, from_status=QuoteStatus.SENT.value,
                      to_status=quote.status, reason=data.reason)
        uow.emit(ev.QUOTE_REVISED, aggregate_id=quote.id, aggregate_version=quote.version,
                 payload=ev.payload(ev.QuoteRevisedPayload(quote_id=quote.id, revision_no=quote.revision_no + 1, origin=origin)))
        emit_status_changed(uow, quote, TransitionAction.REVISE.value, QuoteStatus.SENT.value, quote.status, origin=origin)
    elif quote.status in (QuoteStatus.DRAFT.value, QuoteStatus.REVISED.value):
        repo.require_action(quote, "update")
    else:
        raise Conflict(f"A {quote.status} quote cannot be restored; correct its status first", code="quote_not_restorable")
    before_total = quote.grand_total_amount
    load_working_copy(uow, quote, revision)
    quote.restored_from_revision_no = revision.revision_no
    quotes.touch(uow, quote)
    uow.flush()
    write_history(uow, quote, action=TransitionAction.RESTORE.value, from_status=quote.status, to_status=quote.status,
                  reason_code=f"revision_{revision.revision_no}", reason=data.reason)
    uow.emit(ev.QUOTE_RESTORED, aggregate_id=quote.id, aggregate_version=quote.version,
             payload=ev.payload(ev.QuoteRestoredPayload(quote_id=quote.id, from_revision_no=revision.revision_no, origin=origin)))
    quotes.emit_updated(uow, quote, ["lines", "header"], ["restored"])
    uow.audit("sales.quote.restored", resource_type="sales.quote", resource_id=quote.id, resource_label=quote.quote_number,
              reason=data.reason, details={"from_revision_no": revision.revision_no,
                                           "grand_total_before": _json(before_total), "grand_total_after": _json(quote.grand_total_amount)})
    return quote


def restore_revision_command(uow: UnitOfWork, quote_id: uuid.UUID, revision_no: int, data: RestoreRevision) -> tuple[QuoteDetail, bool]:
    uow.repo(Quote).get(quote_id, include_archived=False)
    return idempotent(
        uow, f"sales.restore_revision:{quote_id}:{revision_no}", data,
        lambda: quotes.detail(uow, restore_revision(uow, quote_id, revision_no, data)), QuoteDetail,
    )


# =====================================================================================================
# compare
# =====================================================================================================
def _norm(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (Decimal, int, float)) and not isinstance(value, bool):
        return format(Decimal(str(value)).normalize(), "f")
    if isinstance(value, str):
        try:
            if value.strip() and value.replace(".", "", 1).replace("-", "", 1).isdigit():
                return format(Decimal(value).normalize(), "f")
        except ArithmeticError:
            return value
    return value


def _side(uow: UnitOfWork, quote: Quote, revision: QuoteRevision | None) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    if revision is not None:
        snap = revision.snapshot
        return snap["header"], snap.get("lines", []), snap.get("totals", {})
    lines = quotes.lines_of(uow, quote)
    header = {name: _json(getattr(quote, name)) for name in HEADER_FIELDS}
    totals = {
        "gross_subtotal": _json(quote.gross_subtotal_amount), "discount_total": _json(quote.discount_total_amount),
        "net_subtotal": _json(quote.net_subtotal_amount), "surcharge": _json(quote.surcharge_amount),
        "grand_total": _json(quote.grand_total_amount),
    }
    return header, [documents.line_snapshot(ln) for ln in lines], totals


@query("sales.quote.read")
def compare_revisions(uow: UnitOfWork, quote_id: uuid.UUID, from_revision_no: int, to_revision_no: int | None = None) -> RevisionCompare:
    """Compare revision ``from_revision_no`` with ``to_revision_no`` (or the working copy when omitted)."""
    quote = uow.repo(Quote).get(quote_id, include_archived=False)
    before_rev = quotes.revision_row(uow, quote, from_revision_no)
    after_rev = quotes.revision_row(uow, quote, to_revision_no) if to_revision_no is not None else None
    h1, l1, t1 = _side(uow, quote, before_rev)
    h2, l2, t2 = _side(uow, quote, after_rev)
    header = [
        FieldChange(field=name, before=h1.get(name), after=h2.get(name))
        for name in HEADER_FIELDS
        if _norm(h1.get(name)) != _norm(h2.get(name))
    ]
    before_lines = {str(ln["line_key"]): ln for ln in l1}
    after_lines = {str(ln["line_key"]): ln for ln in l2}
    diffs: list[LineDiff] = []
    for key in [*before_lines, *[k for k in after_lines if k not in before_lines]]:
        b, a = before_lines.get(key), after_lines.get(key)
        if b is None and a is not None:
            diffs.append(LineDiff(line_key=key, change="added", line_no_before=None, line_no_after=a["line_no"],
                                  description=a["description"], changes=[]))
            continue
        if a is None and b is not None:
            diffs.append(LineDiff(line_key=key, change="removed", line_no_before=b["line_no"], line_no_after=None,
                                  description=b["description"], changes=[]))
            continue
        assert a is not None and b is not None
        changes = [FieldChange(field=f, before=b.get(f), after=a.get(f)) for f in COMPARED_LINE_FIELDS if _norm(b.get(f)) != _norm(a.get(f))]
        kind = "changed" if changes else ("moved" if b["line_no"] != a["line_no"] else "unchanged")
        diffs.append(LineDiff(line_key=key, change=kind, line_no_before=b["line_no"], line_no_after=a["line_no"],  # type: ignore[arg-type]
                              description=a["description"], changes=changes))
    currency_before = str(h1.get("currency") or quote.currency)
    currency_after = str(h2.get("currency") or quote.currency)
    totals: list[TotalDiff] = []
    for name in TOTAL_FIELDS:
        b_val = Decimal(str(t1[name])) if t1.get(name) is not None else None
        a_val = Decimal(str(t2[name])) if t2.get(name) is not None else None
        delta = (a_val - b_val) if a_val is not None and b_val is not None and currency_before == currency_after else None
        totals.append(TotalDiff(
            field=name,
            before=quantize_money(b_val, currency_before) if b_val is not None else None,
            after=quantize_money(a_val, currency_after) if a_val is not None else None,
            delta=quantize_money(delta, currency_after) if delta is not None else None,
        ))
    counts = {k: sum(1 for d in diffs if d.change == k) for k in ("added", "removed", "changed", "moved")}
    parts = [f"{n} line{'s' if n != 1 else ''} {k}" for k, n in counts.items() if n]
    if header:
        parts.append(f"{len(header)} header field{'s' if len(header) != 1 else ''} changed")
    grand = next(t for t in totals if t.field == "grand_total")
    if grand.delta is not None and grand.delta != 0:
        sign = "+" if grand.delta > 0 else ""
        parts.append(f"grand total {sign}{format(grand.delta, 'f')} {currency_after}")
    elif currency_before != currency_after:
        parts.append(f"currency {currency_before} → {currency_after}")
    return RevisionCompare(
        quote_id=quote.id,
        currency_before=currency_before,
        currency_after=currency_after,
        from_revision_no=from_revision_no,
        to_revision_no=to_revision_no,
        header=header,
        lines=diffs,
        totals=totals,
        summary="; ".join(parts) if parts else "No differences",
    )


__all__ = ["compare_revisions", "load_working_copy", "restore_revision", "restore_revision_command", "working_copy_of"]

