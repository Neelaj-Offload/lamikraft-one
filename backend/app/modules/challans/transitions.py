"""``transition_challan``: every status change through one table (``state.TRANSITIONS``; LM-83, BUG-14).

Each transition locks the challan, checks the actor's scope for the required ``challans.challan.<verb>``, checks the
optimistic version, evaluates the guard, appends a status-history row, emits the catalogued event and audits.
``issue`` freezes the document into an immutable revision (its PDF hash is recorded) and, for a Return challan,
records the document links against the original lines (``challans.return.received``). Slice 4: ``movement.on_issue``
posts the stock movement of the policy matrix exactly once and ``movement.on_cancel_issued`` posts its reversal
(``inventory_effect`` stays ``none`` before inventory go-live).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select

from app.core.errors import Conflict, InvalidTransition, ValidationFailed
from app.modules.challans import documents, movement, service
from app.modules.challans import events as ev
from app.modules.challans.common import idempotent
from app.modules.challans.models import (
    Challan,
    ChallanLine,
    ChallanReturnLink,
    ChallanRevision,
    ChallanStatusHistory,
)
from app.modules.challans.schemas import (
    ChallanDetail,
    ChallanStatus,
    ChallanTransition,
    ChallanType,
    ReturnLinkKind,
    ReturnType,
    TransitionAction,
)
from app.modules.challans.state import TRANSITIONS, Transition
from app.platform.uow import UnitOfWork

RESOURCE = "challans.challan"


def _invalid(uow: UnitOfWork, challan: Challan, action: str) -> InvalidTransition:
    allowed = service.allowed_transitions(uow, challan, service.lines_of(uow, challan))
    return InvalidTransition(
        f"{action} is not allowed while the challan is {challan.status}",
        allowed_transitions=[t.model_dump() for t in allowed],
        current_status=challan.status,
    )


def _history(uow: UnitOfWork, challan: Challan, t: Transition, data: ChallanTransition) -> None:
    uow.add(
        ChallanStatusHistory(
            company_id=uow.actor.company_id,
            challan_id=challan.id,
            action=t.action,
            from_status=t.from_status,
            to_status=t.to_status,
            actor_user_id=uow.actor.user_id,
            reason_code=data.reason_code,
            reason=data.reason,
            occurred_at=uow.now(),
            challan_version=challan.version,
        )
    )


# ---- guards --------------------------------------------------------------------------------------------------
def _guard(uow: UnitOfWork, challan: Challan, lines: list[ChallanLine], t: Transition) -> None:
    if t.guard == "issue_ready":
        blocker = service.issue_blockers(uow, challan, lines)
        if blocker == "no_lines":
            raise Conflict("Add at least one line before issuing the challan", code="no_lines")
        if blocker is not None:
            raise Conflict(f"The challan cannot be issued: {blocker}", code=blocker)
    if t.guard == "no_return_links" and service.has_return_links(uow, challan):
        raise Conflict(
            "Returns have been recorded against this challan; cancel those first", code="has_return_links"
        )


# ---- effects -------------------------------------------------------------------------------------------------
def _record_returns(uow: UnitOfWork, challan: Challan, lines: list[ChallanLine]) -> list[uuid.UUID]:
    """Lock the original lines (sorted), check the outstanding quantities and insert the document links."""
    original_ids = sorted({ln.original_line_id for ln in lines if ln.original_line_id is not None})
    originals = {o.id: o for o in uow.lock(ChallanLine, original_ids)}
    wanted: dict[uuid.UUID, Decimal] = {}
    for ln in lines:
        assert ln.original_line_id is not None
        wanted[ln.original_line_id] = wanted.get(ln.original_line_id, Decimal(0)) + Decimal(ln.quantity)
    errors = []
    for oid, qty in wanted.items():
        original = originals[oid]
        if qty > Decimal(original.quantity) - Decimal(original.returned_qty):
            errors.append(
                {
                    "loc": ["body", "lines"],
                    "msg": f"line {original.line_no} of the original challan has less outstanding than returned",
                    "code": "excess_return",
                }
            )
    if errors:
        raise ValidationFailed(
            "The return exceeds the quantity still out on the original challan", errors=errors
        )
    now = uow.now()
    for ln in lines:
        assert ln.original_line_id is not None
        original = originals[ln.original_line_id]
        original.returned_qty = Decimal(original.returned_qty) + Decimal(ln.quantity)
        uow.add(
            ChallanReturnLink(
                company_id=uow.actor.company_id,
                return_challan_id=challan.id,
                return_line_id=ln.id,
                original_challan_id=original.challan_id,
                original_line_id=original.id,
                quantity=ln.quantity,
                kind=ReturnLinkKind.RETURNED.value,
                created_at=now,
                created_by=uow.actor.user_id,
            )
        )
    uow.flush()
    return original_ids


def _issue(
    uow: UnitOfWork, challan: Challan, lines: list[ChallanLine], data: ChallanTransition
) -> dict[str, object]:
    now = uow.now()
    revision_no = challan.revision_no + 1
    original_line_ids: list[uuid.UUID] = []
    if challan.challan_type == ChallanType.RETURN.value:
        original_line_ids = _record_returns(uow, challan, lines)
    # Slice 4: exactly one stock posting per issue (documents only before inventory go-live)
    movement.on_issue(uow, challan, lines)
    challan.status = ChallanStatus.ISSUED.value
    challan.issued_at = now
    challan.issued_by = uow.actor.user_id
    challan.revision_no = revision_no
    challan.updated_at = now
    snapshot = documents.build_snapshot(uow, challan, lines, revision_no=revision_no, issued_at=now)
    pdf = documents.render_pdf(snapshot)
    revision = ChallanRevision(
        company_id=uow.actor.company_id,
        challan_id=challan.id,
        revision_no=revision_no,
        kind="issued",
        snapshot=snapshot,
        issued_at=now,
        issued_by=uow.actor.user_id,
        document_sha256=documents.sha256_of(pdf),
    )
    uow.add(revision)
    return {"revision": revision, "original_line_ids": original_line_ids}


def _close(
    uow: UnitOfWork, challan: Challan, _lines: list[ChallanLine], data: ChallanTransition
) -> dict[str, object]:
    challan.status = ChallanStatus.CLOSED.value
    challan.closed_at = uow.now()
    challan.closed_by = uow.actor.user_id
    challan.close_reason = data.reason
    challan.updated_at = uow.now()
    return {}


def _cancel(
    uow: UnitOfWork, challan: Challan, lines: list[ChallanLine], data: ChallanTransition
) -> dict[str, object]:
    was_issued = challan.status == ChallanStatus.ISSUED.value
    if was_issued:
        # Slice 4: the auditable correction is a reversal posting (and the SO figures restored)
        movement.on_cancel_issued(uow, challan, lines, reason_code=data.reason_code or "other", reason=data.reason)
    if was_issued and challan.challan_type == ChallanType.RETURN.value:
        # a cancelled Return gives the original lines their outstanding quantity back (document figures only)
        links = list(
            uow.session.scalars(
                select(ChallanReturnLink).where(
                    ChallanReturnLink.return_challan_id == challan.id, ChallanReturnLink.reversed_at.is_(None)
                )
            )
        )
        originals = {o.id: o for o in uow.lock(ChallanLine, [lk.original_line_id for lk in links])}
        for lk in links:
            originals[lk.original_line_id].returned_qty = max(
                Decimal(originals[lk.original_line_id].returned_qty) - Decimal(lk.quantity), Decimal(0)
            )
            lk.reversed_at = uow.now()
    challan.status = ChallanStatus.CANCELLED.value
    challan.cancelled_at = uow.now()
    challan.cancelled_by = uow.actor.user_id
    challan.cancel_reason_code = data.reason_code or "other"
    challan.cancel_reason = data.reason
    challan.updated_at = uow.now()
    return {"was_issued": was_issued}


EFFECTS = {
    TransitionAction.ISSUE.value: _issue,
    TransitionAction.CLOSE.value: _close,
    TransitionAction.CANCEL.value: _cancel,
}


def _emit(uow: UnitOfWork, challan: Challan, t: Transition, effect: dict[str, object]) -> None:
    if t.action == TransitionAction.ISSUE.value:
        uow.emit(
            ev.CHALLAN_ISSUED,
            aggregate_id=challan.id,
            aggregate_version=challan.version,
            payload=ev.payload(
                ev.ChallanIssuedPayload(
                    challan_id=challan.id,
                    challan_number=challan.challan_number,
                    challan_type=challan.challan_type,
                    return_type=challan.return_type,
                    destination_type=challan.destination_type,
                    party_id=challan.party_id,
                    inventory_effect=challan.inventory_effect,
                    posting_id=challan.issue_posting_id,
                    sample_id=None,
                )
            ),
        )
        if challan.challan_type == ChallanType.RETURN.value and challan.original_challan_id is not None:
            uow.emit(
                ev.RETURN_RECEIVED,
                aggregate_id=challan.id,
                aggregate_version=challan.version,
                payload=ev.payload(
                    ev.ReturnReceivedPayload(
                        return_challan_id=challan.id,
                        original_challan_id=challan.original_challan_id,
                        original_line_ids=list(effect.get("original_line_ids") or []),  # type: ignore[arg-type]
                    )
                ),
            )
    elif t.action == TransitionAction.CLOSE.value:
        uow.emit(
            ev.CHALLAN_CLOSED,
            aggregate_id=challan.id,
            aggregate_version=challan.version,
            payload=ev.payload(ev.ChallanClosedPayload(challan_id=challan.id)),
        )
    elif t.action == TransitionAction.CANCEL.value:
        uow.emit(
            ev.CHALLAN_CANCELLED,
            aggregate_id=challan.id,
            aggregate_version=challan.version,
            payload=ev.payload(
                ev.ChallanCancelledPayload(
                    challan_id=challan.id,
                    reason_code=challan.cancel_reason_code or "other",
                    reversal_posting_id=challan.reversal_posting_id,
                )
            ),
        )


def _auto_close_original(uow: UnitOfWork, challan: Challan) -> None:
    """A returnable original whose every line is fully returned closes itself (operations.md §4)."""
    if challan.challan_type != ChallanType.RETURN.value or challan.original_challan_id is None:
        return
    original = uow.session.scalars(
        select(Challan).where(Challan.id == challan.original_challan_id).with_for_update()
    ).first()
    if (
        original is None
        or original.status != ChallanStatus.ISSUED.value
        or original.return_type != ReturnType.RETURNABLE.value
    ):
        return
    lines = service.lines_of(uow, original)
    if not lines or any(Decimal(ln.returned_qty) < Decimal(ln.quantity) for ln in lines):
        return
    original.status = ChallanStatus.CLOSED.value
    original.closed_at = uow.now()
    original.closed_by = uow.actor.user_id
    original.close_reason = f"All lines returned on {challan.challan_number}"
    original.updated_at = uow.now()
    uow.flush()
    uow.add(
        ChallanStatusHistory(
            company_id=uow.actor.company_id,
            challan_id=original.id,
            action=TransitionAction.CLOSE.value,
            from_status=ChallanStatus.ISSUED.value,
            to_status=ChallanStatus.CLOSED.value,
            actor_user_id=uow.actor.user_id,
            reason_code="all_returned",
            reason=original.close_reason,
            occurred_at=uow.now(),
            challan_version=original.version,
        )
    )
    uow.emit(
        ev.CHALLAN_CLOSED,
        aggregate_id=original.id,
        aggregate_version=original.version,
        payload=ev.payload(ev.ChallanClosedPayload(challan_id=original.id)),
    )
    uow.audit(
        "challans.challan.close",
        resource_type=RESOURCE,
        resource_id=original.id,
        resource_label=original.challan_number,
        details={"from_status": "issued", "to_status": "closed", "reason_code": "all_returned"},
    )


def transition_challan(uow: UnitOfWork, challan_id: uuid.UUID, data: ChallanTransition) -> Challan:
    """Apply one state-machine action. 409 ``invalid_transition`` (with ``allowed_transitions``) when the action is not
    in the table for the current status; 403 when the actor lacks the verb in scope; 409 ``version_conflict`` when
    stale; 409 with a guard code when a precondition fails."""
    repo = uow.repo(Challan)
    challan = repo.get(challan_id, for_update=True, include_archived=False)
    t = TRANSITIONS.get((challan.status, data.action))
    if t is None:
        raise _invalid(uow, challan, data.action)
    repo.require_action(challan, t.permission_action)
    uow.expect_version(challan, data.expected_version)
    if t.requires_reason and not (data.reason or data.reason_code):
        raise ValidationFailed(
            f"{t.action} needs a reason",
            errors=[
                {
                    "loc": ["body", "reason"],
                    "msg": "a reason or reason code is required",
                    "code": "reason_required",
                }
            ],
        )
    lines = service.lines_of(uow, challan)
    _guard(uow, challan, lines, t)
    effect = EFFECTS[t.action](uow, challan, lines, data)
    uow.flush()
    _history(uow, challan, t, data)
    _emit(uow, challan, t, effect)
    if t.action == TransitionAction.ISSUE.value:
        _auto_close_original(uow, challan)
    uow.flush()  # the history row and the links are visible to the detail read that answers the command
    uow.audit(
        f"challans.challan.{t.action}",
        resource_type=RESOURCE,
        resource_id=challan.id,
        resource_label=challan.challan_number,
        reason=data.reason,
        details={"from_status": t.from_status, "to_status": t.to_status, "reason_code": data.reason_code},
    )
    return challan


def transition_challan_command(
    uow: UnitOfWork, challan_id: uuid.UUID, data: ChallanTransition
) -> tuple[ChallanDetail, bool]:
    """HTTP entry point: ``Idempotency-Key`` is required for ``issue`` and the cancel of an issued challan."""
    challan = uow.repo(Challan).get(challan_id, include_archived=False)
    t = TRANSITIONS.get((challan.status, data.action))
    if t is not None and t.idempotency_required and not uow.actor.idempotency_key:
        raise ValidationFailed(
            f"{data.action} requires an Idempotency-Key header",
            code="idempotency_key_required",
            errors=[
                {
                    "loc": ["header", "Idempotency-Key"],
                    "msg": "required for this command",
                    "code": "idempotency_key_required",
                }
            ],
        )
    return idempotent(
        uow,
        f"challans.transition:{challan_id}",
        data,
        lambda: service.detail(uow, transition_challan(uow, challan_id, data)),
        ChallanDetail,
    )
