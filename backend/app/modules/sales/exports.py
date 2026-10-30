"""Quote CSV exports (LM-57, API-38, BUG-04, SEC-02).

Rows are bounded by the actor's ``sales.quote.export`` scope (a sales user exports only their own quotes, never "all
quotes" like the legacy endpoint) and by the same filters as the list. Line counts and totals come from the persisted
engine result, creator and owner names from the users table, and every cell goes through ``core.csv_safe`` (formula
escaping, UTF-8 BOM). Internal notes and override reasons are never exported.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import and_, exists, select

from app.core.csv_safe import write_csv
from app.core.errors import Forbidden
from app.core.money import quantize_money
from app.modules.sales import quotes
from app.modules.sales.common import user_refs
from app.modules.sales.models import Quote
from app.modules.sales.schemas import QuoteFilters
from app.platform.service import query
from app.platform.uow import UnitOfWork

QUOTE_COLUMNS = (
    "Quote number", "Revision", "Status", "Created", "Issued", "Valid until", "Customer", "Country", "Customer reference",
    "Customer type", "Owner", "Created by", "Currency", "Total lines", "Gross subtotal", "Discount total", "Net subtotal",
    "Surcharge", "Tax", "Grand total",
)
LINE_COLUMNS = (
    "Line", "Type", "Product key", "SKU", "Description", "Decor", "Size", "Quantity", "Unit", "Unit price", "Discount %",
    "Line total", "Currency", "Remarks",
)
MAX_EXPORT_ROWS = 10_000


def _money(amount: Decimal | None, currency: str) -> Decimal | None:
    return None if amount is None else quantize_money(Decimal(amount), currency)


@query("sales.quote.export")
def export_quotes_csv(uow: UnitOfWork, filters: QuoteFilters) -> bytes:
    """The quote list as CSV: rows within the actor's export scope after the list filters (no paging, capped)."""
    repo = uow.repo(Quote)
    stmt = repo.select("export", include_archived=filters.include_deleted).where(*quotes._conditions(uow, filters))
    rows = list(uow.session.scalars(stmt.order_by(Quote.created_at.desc(), Quote.id.desc()).limit(MAX_EXPORT_ROWS)))
    users = user_refs(uow, [q.owner_user_id for q in rows] + [q.created_by for q in rows])

    def name(user_id: uuid.UUID | None) -> str | None:
        return users[user_id].display_name if user_id in users else None

    data = []
    for q in rows:
        calc = q.calculation or {}
        data.append([
            q.quote_number, q.revision_no, q.status, q.created_at.date(), q.issued_at.date() if q.issued_at else None, q.valid_until,
            q.party_name, q.party_country, q.customer_reference, (q.party_snapshot or {}).get("customer_type"),
            name(q.owner_user_id), name(q.created_by), q.currency, q.line_count,
            _money(q.gross_subtotal_amount, q.currency), _money(q.discount_total_amount, q.currency),
            _money(q.net_subtotal_amount, q.currency), _money(q.surcharge_amount, q.currency),
            calc.get("tax_label") or "Excludes taxes", _money(q.grand_total_amount, q.currency),
        ])
    uow.audit("sales.quote.exported", resource_type="sales.quote", details={"rows": len(data), "format": "csv"})
    return write_csv(QUOTE_COLUMNS, data)


def can_export(uow: UnitOfWork, quote: Quote) -> bool:
    """The quote is within the actor's ``sales.quote.export`` scope (list exports ignore the issued-only document rule)."""
    clause = uow.repo(Quote).clause("export")
    return bool(uow.session.scalar(select(exists().where(and_(Quote.id == quote.id, clause)))))


@query("sales.quote.read")
def export_quote_lines_csv(uow: UnitOfWork, quote_id: uuid.UUID) -> tuple[str, bytes]:
    """One quote's lines as CSV (404 outside read scope, 403 outside export scope)."""
    quote = uow.repo(Quote).get(quote_id, include_archived=False)
    if not can_export(uow, quote):
        raise Forbidden(code="permission_denied", permission="sales.quote.export")
    lines = quotes.lines_of(uow, quote)
    data = []
    for ln in lines:
        snap = ln.product_snapshot or {}
        data.append([
            ln.line_no, ln.line_type, snap.get("product_key"), snap.get("display_sku"), ln.description,
            " ".join(p for p in (snap.get("decor_no"), snap.get("decor_name")) if p) or None, snap.get("size_text"),
            Decimal(ln.quantity).normalize(), ln.unit_code, ln.unit_price, ln.discount_pct,
            _money(ln.line_total, ln.currency), ln.currency, ln.remarks,
        ])
    data.append([])
    data.append(["", "", "", "", "Grand total", "", "", "", "", "", "", _money(quote.grand_total_amount, quote.currency), quote.currency, ""])
    uow.audit("sales.quote.lines_exported", resource_type="sales.quote", resource_id=quote.id, resource_label=quote.quote_number)
    return f"{quote.quote_number}-lines.csv", write_csv(LINE_COLUMNS, data)
