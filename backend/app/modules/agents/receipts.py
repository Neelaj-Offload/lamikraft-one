"""Draft receipts and Undo (design section 9 "Undo").

A receipt is written by the orchestrator when an agent step changed a draft (``draft_quote`` created one,
``update_line`` changed a quantity). Its ``undo_spec`` is server-built from tool outputs, never from model text.
``POST /api/v1/receipts/{id}/undo`` reverts it within 24 hours while the target is unchanged (same row version):

- ``revert_draft``: soft-deletes the agent-created draft through ``sales.service.delete_quote``;
- ``restore_line``: puts the prior quantities back through ``sales.service.update_line`` (a new version).

Undo is a human action of the receipt's owner (own scope: someone else's receipt is a 404). The services still
authorise (``sales.quote.delete`` / ``sales.quote.update``) and write the audit and outbox rows.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from app.core.errors import Conflict
from app.modules.agents import cards as card_builders
from app.modules.agents import context as ctx_mod
from app.modules.agents.cards import RecordLink, UndoInfo
from app.modules.agents.models import Receipt
from app.modules.agents.providers import provider_label
from app.modules.agents.schemas import ReceiptOut, UndoResult
from app.modules.agents.service import own_receipt
from app.platform.uow import UnitOfWork

SALES_SERVICE = "app.modules.sales.service"
SALES_SCHEMAS = "app.modules.sales.schemas"
UNDO_ORIGIN = "agent_undo"


class UndoNotAvailable(Conflict):
    code, title = "undo_not_available", "This change can no longer be undone"


def _target_version(uow: UnitOfWork, receipt: Receipt) -> int | None:
    """The target's current version, or None when it is gone (deleted, not visible, module absent)."""
    sales = ctx_mod.optional_module(SALES_SERVICE)
    if sales is None or receipt.resource_type != "sales.quote":
        return None
    try:
        return int(sales.get_quote(uow, receipt.resource_id).version)
    except Exception:  # noqa: BLE001 - NotFound/Forbidden: the target cannot be undone any more
        return None


def can_undo(uow: UnitOfWork, receipt: Receipt) -> tuple[bool, str | None]:
    """(allowed, reason): active, inside the window and the target at the version the step left it."""
    if receipt.undo_kind == "none" or receipt.undo_spec is None:
        return False, "not_undoable"
    if receipt.status != "active":
        return False, receipt.status
    if receipt.undo_until is None or uow.now() > receipt.undo_until:
        return False, "expired"
    if _target_version(uow, receipt) != receipt.resource_version:
        return False, "target_changed"
    return True, None


def receipt_out(uow: UnitOfWork, receipt: Receipt) -> ReceiptOut:
    allowed, _ = can_undo(uow, receipt)
    return ReceiptOut(
        id=receipt.id, run_id=receipt.run_id, step_seq=receipt.step_seq, action=receipt.action, summary=receipt.summary,
        resource_type=receipt.resource_type, resource_id=receipt.resource_id, resource_version=receipt.resource_version,
        undo_kind=receipt.undo_kind, undo_until=receipt.undo_until, status=receipt.status, undone_at=receipt.undone_at,
        correlation_id=receipt.correlation_id, created_at=receipt.created_at, can_undo=allowed,
    )


def get_receipt(uow: UnitOfWork, receipt_id: uuid.UUID) -> ReceiptOut:
    return receipt_out(uow, own_receipt(uow, receipt_id))


def _apply(uow: UnitOfWork, receipt: Receipt) -> str:
    sales = ctx_mod.optional_module(SALES_SERVICE)
    schemas = ctx_mod.optional_module(SALES_SCHEMAS)
    if sales is None or schemas is None:
        raise UndoNotAvailable("The sales module is not installed.", reason="module_missing")
    spec: dict[str, Any] = dict(receipt.undo_spec or {})
    quote_id = uuid.UUID(str(spec["quote_id"]))
    if receipt.undo_kind == "revert_draft":
        # a draft is deleted when the member may delete drafts, otherwise cancelled (both keep the number unused)
        if uow.actor.can("sales.quote.delete"):
            sales.delete_quote(uow, quote_id, expected_version=receipt.resource_version, origin=UNDO_ORIGIN)
            return "The draft the assistant created was removed."
        sales.transition_quote(uow, quote_id, schemas.QuoteTransition(
            action="cancel", expected_version=receipt.resource_version, reason="Undone from the assistant's receipt.",
        ), origin=UNDO_ORIGIN)
        return "The draft the assistant created was cancelled."
    version = receipt.resource_version
    for line in spec.get("lines") or []:
        quote, _ = sales.update_line(
            uow, quote_id, uuid.UUID(str(line["line_id"])),
            schemas.QuoteLineUpdate(expected_version=version, quantity=Decimal(str(line["quantity"]))), origin=UNDO_ORIGIN,
        )
        version = quote.version
    return "The previous line quantity was restored."


def undo(uow: UnitOfWork, receipt_id: uuid.UUID) -> UndoResult:
    receipt = own_receipt(uow, receipt_id, for_update=True)
    allowed, reason = can_undo(uow, receipt)
    if not allowed:  # computed on every read; nothing is written on a refused undo
        raise UndoNotAvailable(
            {"expired": "The 24-hour undo window has passed.",
             "target_changed": "The record changed after the assistant's step; undo it from the record instead.",
             "undone": "This change was already undone."}.get(str(reason), "This change cannot be undone."),
            reason=reason,
        )
    message = _apply(uow, receipt)
    receipt.status = "undone"
    receipt.undone_at = uow.now()
    receipt.updated_at = uow.now()
    uow.flush()
    uow.audit("agents.receipt.undone", resource_type=receipt.resource_type, resource_id=receipt.resource_id,
              resource_label=receipt.action)
    card = card_builders.receipt_card(
        f"undo_{receipt.action}", message, uow.now(), provider_label=provider_label(), tainted=False,
        record=RecordLink(label="Quotes", path="/sales/quotes") if receipt.undo_kind == "revert_draft"
        else RecordLink(label="Review", path=f"/sales/quotes/{receipt.resource_id}"),
        undo=UndoInfo(receipt_id=receipt.id, allowed=False, until=receipt.undo_until, kind=receipt.undo_kind),
    )
    return UndoResult(receipt=receipt_out(uow, receipt), card=card)


__all__ = ["UndoNotAvailable", "can_undo", "get_receipt", "receipt_out", "undo"]
