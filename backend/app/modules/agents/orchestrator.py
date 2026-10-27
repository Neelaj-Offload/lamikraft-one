"""The run pipeline (ai-routing.md sections 3 and 5): grammar match → router → provider loop over typed tools →
server-built cards → receipt. Runs as the member (``actor_for_member``), never as system.

Every step commits in its own unit of work so polling clients see progress and no transaction is held across a
provider call. Budget: ``STEP_BUDGET`` tool calls / ``TIME_BUDGET_SECONDS``; over budget ends the run as
``budget_exceeded`` with an ErrorCard and the recoverable draft reference. The deterministic grammar path never
touches the provider, so it keeps working when the provider raises.
"""

from __future__ import annotations

import importlib
import importlib.util
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.core.errors import NotConfigured
from app.core.logging import get_logger
from app.modules.agents import cards as card_builders
from app.modules.agents import context as ctx_mod
from app.modules.agents import service
from app.modules.agents.cards import Card, QuoteDraftCard, RecordLink
from app.modules.agents.context import ContextRef
from app.modules.agents.grounding import Provenance, check_claims, decimals_in, uuids_in
from app.modules.agents.models import Run, Turn
from app.modules.agents.providers import get_provider
from app.modules.agents.providers.base import (
    Message,
    ModelRequest,
    ModelResponse,
    Stopwatch,
    TextBlock,
    ToolResultBlock,
    ToolSpec,
    ToolUseBlock,
)
from app.modules.agents.providers.demo import ASK_CLARIFICATION, PROVIDER_LABEL, parse_request
from app.modules.agents.providers.demo_intents import HELP_TEXT, Command, parse_command
from app.modules.agents.schemas import ScreenContext
from app.modules.agents.tools_runtime import (
    PRICE_OVERRIDE_PERMISSION,
    ToolContext,
    ToolOutcome,
    advertised_tools,
    execute_tool,
)
from app.platform.authz.context import ActorContext
from app.platform.uow import UnitOfWork

log = get_logger("lk.agents.run")

STEP_BUDGET = service.STEP_BUDGET
TIME_BUDGET_SECONDS = service.TIME_BUDGET_SECONDS
MAX_PROVIDER_ROUNDS = 12
SYSTEM_PROMPT_VERSION = "system.v1"
SYSTEM_PROMPT = (
    "You are the Lamikraft One assistant. Facts come from tools; you never compute money or quantities, never "
    "guess ids, never supply prices. Ask one clarifying question when a customer or product is ambiguous."
)
DRAFT_TOOLS = ("draft_quote", "revise_draft_line")
BRIEFINGS_SERVICE = "app.modules.briefings.service"
SALES_SERVICE = "app.modules.sales.service"
TODAY_PATH = "/today"


@dataclass
class RunState:
    run_id: uuid.UUID
    conversation_id: uuid.UUID
    actor: ActorContext
    user_text: str
    selected_option: dict[str, Any] | None
    screen: ScreenContext | None
    refs: list[ContextRef]
    last_cards: list[dict[str, Any]]
    provenance: Provenance
    messages: list[Message] = field(default_factory=list)
    outcomes: list[ToolOutcome] = field(default_factory=list)
    text_parts: list[str] = field(default_factory=list)
    tainted: bool = False
    tool_calls: int = 0
    clarification: tuple[str, str] | None = None
    budget_exceeded: bool = False
    cancelled: bool = False
    provider_label: str = PROVIDER_LABEL
    clock: Stopwatch = field(default_factory=Stopwatch)

    @property
    def last_quote_card(self) -> dict[str, Any] | None:
        for card in reversed(self.last_cards):
            if card.get("kind") == "quote_draft":
                return card
        return None

    def last_ok(self, name: str) -> ToolOutcome | None:
        for outcome in reversed(self.outcomes):
            if outcome.name == name and not outcome.is_error:
                return outcome
        return None

    @property
    def last_outcome(self) -> ToolOutcome | None:
        return self.outcomes[-1] if self.outcomes else None

    @property
    def allowed_figures(self) -> set[Decimal]:
        values: set[Decimal] = set()
        for outcome in self.outcomes:
            if outcome.output_for_user is not None:
                values |= decimals_in(outcome.output_for_user)
        return values


# ---- transaction helper ---------------------------------------------------------------------------------------
def _tx[T](actor: ActorContext, run_id: uuid.UUID, fn: Callable[[UnitOfWork, Run], T]) -> T:
    with UnitOfWork(actor) as uow:
        run = uow.session.get(Run, run_id)
        if run is None:
            raise RuntimeError(f"run {run_id} vanished")
        return fn(uow, run)


def _cancel_requested(actor: ActorContext, run_id: uuid.UUID) -> bool:
    return _tx(actor, run_id, lambda uow, run: run.cancel_requested_at is not None)


# ---- state ---------------------------------------------------------------------------------------------------
def _build_state(actor: ActorContext, run_id: uuid.UUID) -> RunState:
    def build(uow: UnitOfWork, run: Run) -> RunState:
        run.status = "running"
        run.started_at = uow.now()
        turn = uow.session.get(Turn, run.turn_id)
        assert turn is not None
        screen = ScreenContext.model_validate(turn.screen_context) if turn.screen_context else None
        previous = service.last_assistant_turn(uow, run.conversation_id)
        last_cards = list(previous.cards) if previous is not None else []
        refs = ctx_mod.ground_screen_context(uow, screen) + ctx_mod.refs_from_cards(last_cards)
        service.add_object_context(uow, run, refs)
        known = {r.resource_id for r in refs} | uuids_in(last_cards)
        clarification_values: set[Decimal] = set()
        if turn.selected_option:
            known |= uuids_in(turn.selected_option)
            clarification_values |= decimals_in(turn.selected_option)
        history = [t for t in service.turns_of(uow, run.conversation_id, limit=service.HISTORY_TURNS + 1) if t.id != turn.id]
        messages = [Message(role=t.role, content=(TextBlock(t.text),)) for t in history if t.text]  # type: ignore[arg-type]
        messages.append(Message(role="user", content=(TextBlock(turn.text),)))
        return RunState(
            run_id=run.id, conversation_id=run.conversation_id, actor=actor, user_text=turn.text,
            selected_option=turn.selected_option, screen=screen, refs=refs, last_cards=last_cards,
            provenance=Provenance(
                known_ids=frozenset(known), user_text=turn.text, clarification_values=frozenset(clarification_values),
                can_override_price=actor.can(PRICE_OVERRIDE_PERMISSION),
            ),
            messages=messages,
        )

    return _tx(actor, run_id, build)


# ---- steps ---------------------------------------------------------------------------------------------------
def _route_step(state: RunState, name: str, output: Mapping[str, Any], model_route: str, request_type: str) -> None:
    def write(uow: UnitOfWork, run: Run) -> None:
        run.request_type = request_type
        service.append_step(uow, run, kind="route", name=name, output=output, model_route=model_route)

    _tx(state.actor, state.run_id, write)


def _tool_step(state: RunState, block: ToolUseBlock, model_route: str) -> ToolOutcome:
    """Record the call, execute it as the member (own transaction), record the result and update provenance."""

    def next_seq(uow: UnitOfWork, run: Run) -> int:
        step = service.append_step(
            uow, run, kind="tool_call", name=block.name, input=dict(block.input), model_route=model_route,
        )
        return step.seq

    seq = _tx(state.actor, state.run_id, next_seq)
    tool_ctx = ToolContext(
        actor=state.actor, run_id=state.run_id, conversation_id=state.conversation_id, step_seq=seq,
        provenance=state.provenance, tainted=state.tainted,
    )
    outcome = execute_tool(tool_ctx, block.name, block.input)
    state.tool_calls += 1
    state.outcomes.append(outcome)
    if not outcome.is_error:
        state.provenance = state.provenance.with_ids(outcome.new_ids).with_values(outcome.new_values)
        if outcome.untrusted:
            state.tainted = True

    def record(uow: UnitOfWork, run: Run) -> None:
        if outcome.untrusted:
            run.tainted = True
        service.append_step(
            uow, run, kind="tool_result", name=block.name,
            output=outcome.result_content, is_error=outcome.is_error, error_code=outcome.error_code,
            model_route=model_route, duration_ms=outcome.duration_ms,
        )
        if outcome.output_for_model is not None:
            service.add_object_context(uow, run, ctx_mod.typed_refs_from_output(outcome.output_for_model))

    _tx(state.actor, state.run_id, record)
    return outcome


def _log_call(state: RunState, response: ModelResponse | None, error: Exception | None, provider: Any) -> None:
    def write(uow: UnitOfWork, run: Run) -> None:
        service.log_call(
            uow, run, step_seq=run.step_count, response=response, task_class="orchestration", error=error,
            provider=getattr(provider, "name", "demo"), model=getattr(provider, "model", ""),
        )

    _tx(state.actor, state.run_id, write)


# ---- cards ---------------------------------------------------------------------------------------------------
def _party_label(state: RunState) -> str | None:
    if state.selected_option and state.selected_option.get("slot") == "party":
        return state.selected_option.get("label")
    party = state.last_ok("resolve_party")
    if party and party.output_for_user and party.output_for_user.get("status") == "unique":
        return party.output_for_user["candidates"][0].get("display_name")
    return None


def _draft_link(state: RunState) -> RecordLink | None:
    for name in DRAFT_TOOLS:
        outcome = state.last_ok(name)
        if outcome and outcome.output_for_user and outcome.output_for_user.get("quote_id"):
            card = card_builders.quote_draft_card(outcome.output_for_user, provider_label=state.provider_label, tainted=state.tainted)
            return card.review
    last = state.last_quote_card
    if last and last.get("quote_id"):
        return RecordLink(resource_type="sales.quote", resource_id=uuid.UUID(str(last["quote_id"])),
                          label=f"Review {last.get('quote_number') or 'draft'}", path=card_builders.QUOTE_REVIEW_PATH.format(quote_id=last["quote_id"]))
    return None


def _clarification_options(state: RunState, slot: str) -> list[card_builders.ClarificationOption]:
    if slot == "party":
        party = state.last_ok("resolve_party")
        if party and party.output_for_user and party.output_for_user.get("status") == "ambiguous":
            return card_builders.party_options(party.output_for_user.get("candidates") or [])
    if slot == "product":
        product = state.last_ok("resolve_product")
        if product and product.output_for_user and product.output_for_user.get("status") == "ambiguous":
            return card_builders.product_options(product.output_for_user.get("candidates") or [])
    if slot == "line":
        usual = state.last_ok("find_usual_order")
        if usual and usual.output_for_user and usual.output_for_user.get("lines"):
            return card_builders.line_options(usual.output_for_user["lines"])
        last = state.last_quote_card
        if last and last.get("lines"):
            return card_builders.line_options(last["lines"])
    return []


def _build_cards(state: RunState) -> tuple[list[Card], str | None, str | None]:
    """Cards from tool outputs. Returns (cards, error_code, error_message) where error_code marks a failed run."""
    label, tainted = state.provider_label, state.tainted
    cards: list[Card] = []
    if state.budget_exceeded:
        cards.append(card_builders.error_card(
            "budget_exceeded", f"The run exceeded its budget ({STEP_BUDGET} steps / {TIME_BUDGET_SECONDS} s). "
            "Any draft created so far is kept.", provider_label=label, tainted=tainted, recoverable_draft=_draft_link(state),
        ))
        return cards, "budget_exceeded", "run budget exceeded"
    if state.cancelled:
        cards.append(card_builders.error_card("cancelled", "The run was cancelled.", provider_label=label, tainted=tainted,
                                              recoverable_draft=_draft_link(state)))
        return cards, "cancelled", "cancelled by the user"
    if state.clarification is not None:
        slot, question = state.clarification
        options = _clarification_options(state, slot)
        if not options:
            cards.append(card_builders.error_card(
                "clarification_without_options", "The assistant needed a choice but no options were available.",
                provider_label=label, tainted=tainted,
            ))
            return cards, "clarification_without_options", "no options for clarification"
        cards.append(card_builders.clarification_card(slot, question, options, provider_label=label, tainted=tainted))
        return cards, None, None
    last = state.last_outcome
    if last is not None and last.is_error:
        cards.append(card_builders.error_card(
            last.error_code or "tool_failed", last.message or "The step failed.", provider_label=label, tainted=tainted,
            recoverable_draft=_draft_link(state),
        ))
        return cards, last.error_code or "tool_failed", last.message
    for name in DRAFT_TOOLS:
        draft = state.last_ok(name)
        if draft and draft.output_for_user:
            cards.append(card_builders.quote_draft_card(
                draft.output_for_user, provider_label=label, tainted=tainted, party_label=_party_label(state),
            ))
            if name == "revise_draft_line":
                cards.append(card_builders.receipt_card(
                    "revise_draft_line", "Line quantity updated on the draft.", state_now(state),
                    provider_label=label, tainted=tainted, record=cards[-1].review if isinstance(cards[-1], QuoteDraftCard) else None,
                ))
            return cards, None, None
    calc = state.last_ok("calculate_quote")
    if calc and calc.output_for_user and state.last_quote_card is not None:
        base = QuoteDraftCard.model_validate(state.last_quote_card)
        quantity = str((calc.input.get("lines") or [{}])[0].get("quantity", ""))
        cards.append(card_builders.quote_preview_card(
            calc.output_for_user, provider_label=label, tainted=tainted, base=base, quantity=quantity,
        ))
        applied = _apply_line_update(state, base, calc.input)
        if applied is not None:
            cards.append(applied)
        return cards, None, None
    if last is not None and last.output_for_user is not None:
        status = str(last.output_for_user.get("status") or "")
        if status in ("not_found", "unavailable", "ambiguous") and last.name.startswith("resolve_"):
            cards.append(card_builders.error_card(
                f"{last.name}_{status}", last.output_for_user.get("explanation") or f"{last.name} returned {status}.",
                provider_label=label, tainted=tainted, recoverable_draft=_draft_link(state),
            ))
            return cards, None, None
        if last.name == "find_usual_order" and not last.output_for_user.get("quote_id"):
            cards.append(card_builders.error_card(
                "no_usual_order", "No previous won quote exists for this customer.", provider_label=label, tainted=tainted,
            ))
            return cards, None, None
    return cards, None, None


def state_now(state: RunState) -> Any:
    return _tx(state.actor, state.run_id, lambda uow, run: uow.now())


def _apply_line_update(state: RunState, base: QuoteDraftCard, calc_input: Mapping[str, Any]) -> Card | None:
    """Seam: apply the recalculated quantity to the draft through ``sales.service.update_line`` when installed."""
    if importlib.util.find_spec(SALES_SERVICE) is None:
        return None
    sales = importlib.import_module(SALES_SERVICE)
    update_line = getattr(sales, "update_line", None)
    if update_line is None or not base.quote_id or not base.lines:
        return None
    line = (calc_input.get("lines") or [{}])[0]
    line_id = line.get("line_key")
    try:
        with UnitOfWork(state.actor.with_(agent_run_id=state.run_id, idempotency_key=f"agent:{state.run_id}:apply")) as uow:
            update_line(uow, base.quote_id, uuid.UUID(str(line_id)), quantity=Decimal(str(line.get("quantity"))))
            at = uow.now()
    except Exception as exc:  # the preview stands; the user applies the change in the workspace
        log.warning("agents.apply_line_update_failed", run_id=str(state.run_id), error=str(exc)[:200])
        return None
    return card_builders.receipt_card(
        "update_line", "Line quantity applied to the draft through the sales service.", at,
        provider_label=state.provider_label, tainted=state.tainted, record=base.review,
    )


# ---- finish ----------------------------------------------------------------------------------------------------
def _finish(state: RunState, *, status: str, text: str, cards: list[Card], error_code: str | None, error_message: str | None) -> None:
    checked, replaced = check_claims(text, state.allowed_figures)

    def write(uow: UnitOfWork, run: Run) -> None:
        for card in cards:
            service.append_step(uow, run, kind="card", name=card.kind, output=card.model_dump(mode="json"), model_route=run.model_route)
        service.append_step(uow, run, kind="text", name="final_text", output={"text": checked, "replaced_figures": replaced},
                            model_route=run.model_route)
        run.tainted = run.tainted or state.tainted
        service.finish_run(
            uow, run, status=status, text=checked, cards=cards, error_code=error_code, error_message=error_message,
            elapsed_ms=state.clock.elapsed_ms,
        )

    _tx(state.actor, state.run_id, write)


def _finish_from_state(state: RunState) -> str:
    cards, error_code, error_message = _build_cards(state)
    if state.budget_exceeded:
        status = "budget_exceeded"
    elif state.cancelled:
        status = "cancelled"
    elif error_code:
        status = "failed"
    else:
        status = "succeeded"
    text = "\n".join(p for p in state.text_parts if p.strip()).strip()
    if not text:
        text = {"budget_exceeded": "Demo: the run stopped at its budget; see the card.",
                "cancelled": "Demo: cancelled.", "failed": "Demo: that did not work; see the card."}.get(status, "Demo: done; see the card.")
    _finish(state, status=status, text=text, cards=cards, error_code=error_code, error_message=error_message)
    return status


# ---- deterministic commands (grammar) -----------------------------------------------------------------------------
def _briefings(attr: str) -> Any | None:
    if importlib.util.find_spec(BRIEFINGS_SERVICE) is None:
        return None
    return getattr(importlib.import_module(BRIEFINGS_SERVICE), attr, None)


def _run_command(state: RunState, command: Command) -> str:
    label, tainted = state.provider_label, state.tainted
    cards: list[Card] = []
    text = ""
    error_code: str | None = None
    if command.kind == "open_item":
        def resolve(uow: UnitOfWork, run: Run) -> ctx_mod.OrdinalResolution:
            last_list = next((c.get("options") or [] for c in reversed(state.last_cards) if c.get("kind") == "clarification"), [])
            return ctx_mod.resolve_ordinal(uow, state.screen, state.refs, command.ordinal or 1, last_list=last_list)

        resolution = _tx(state.actor, state.run_id, resolve)
        if resolution.status == "resolved" and resolution.ref is not None:
            ref = resolution.ref
            cards.append(card_builders.record_link_card(
                ref.label or ref.resource_type, ref.path or "", provider_label=label, tainted=tainted,
                resource_type=ref.resource_type, resource_id=ref.resource_id, ordinal=resolution.ref.ordinal,
            ))
            text = f"Demo: opening item {command.ordinal} — {ref.label or ref.resource_type}."
        elif resolution.status == "stale":
            options = [
                card_builders.ClarificationOption(
                    ref=r.ref_key or f"o{i}", label=r.label or r.resource_type, detail=None,
                    action=card_builders.OptionAction(slot="item", value=str(r.resource_id), label=r.label or r.resource_type),
                )
                for i, r in enumerate(state.refs, start=1) if r.origin == "screen" and r.list_key == resolution.list_key
            ]
            cards.append(card_builders.clarification_card(
                "item", "That list changed since you saw it. Which item do you mean?", options, provider_label=label, tainted=tainted,
            ))
            text = "Demo: the list changed since you saw it; please pick the item."
        else:
            error_code = "no_list_in_context"
            cards.append(card_builders.error_card(
                error_code, "There is no list on screen or in the conversation to pick an item from.", provider_label=label, tainted=tainted,
            ))
            text = "Demo: I do not see a list to pick from."
    elif command.kind == "snooze":
        snooze = _briefings("snooze_item")
        if snooze is None:
            error_code = "capability_not_installed"
            cards.append(card_builders.error_card(
                error_code, "Snoozing needs the briefings module, which is not installed here.", provider_label=label, tainted=tainted,
                direct_controls=[RecordLink(label="Today", path=TODAY_PATH)],
            ))
            text = "Demo: snoozing is not available yet."
        else:
            text = "Demo: snoozed."
    elif command.kind == "navigate":
        cards.append(card_builders.record_link_card(command.target or "page", command.path or "/", provider_label=label, tainted=tainted))
        text = f"Demo: opening {command.target}."
    elif command.kind == "stop":
        text = "Demo: stopped."
    elif command.kind == "today_overview":
        cards.append(card_builders.record_link_card("Today", TODAY_PATH, provider_label=label, tainted=tainted))
        text = "Demo: your briefing is on the Today page."
    else:
        text = HELP_TEXT
    status = "failed" if error_code else "succeeded"
    _finish(state, status=status, text=text, cards=cards, error_code=error_code, error_message=None)
    return status


# ---- the provider loop ------------------------------------------------------------------------------------------
def _request(state: RunState, tools: list[Any]) -> ModelRequest:
    focus = next(({"type": r.resource_type, "id": str(r.resource_id)} for r in state.refs if r.role == "focus"), None)
    return ModelRequest(
        task_class="orchestration",
        system=f"{SYSTEM_PROMPT_VERSION}\n{SYSTEM_PROMPT}",
        messages=tuple(state.messages),
        tools=tuple(ToolSpec(name=t.name, description=t.description, input_schema=t.json_schema(), effect=t.effect) for t in tools),
        max_tokens=8192,
        context={
            "selected_option": state.selected_option,
            "focus": focus,
            "last_quote_card": state.last_quote_card,
            "object_context": [{"type": r.resource_type, "id": str(r.resource_id), "label": r.label} for r in state.refs],
            "tools": [t.name for t in tools],
            "tainted": state.tainted,
        },
    )


def _over_budget(state: RunState) -> bool:
    return state.tool_calls >= STEP_BUDGET or state.clock.elapsed_ms > TIME_BUDGET_SECONDS * 1000


def _orchestrate(state: RunState, request_type: str) -> str:
    try:
        provider = get_provider()
    except NotConfigured as exc:
        _finish(state, status="failed", text="Demo: the assistant is not configured.", cards=[card_builders.error_card(
            "not_configured", exc.detail, provider_label=state.provider_label, tainted=state.tainted)],
            error_code="not_configured", error_message=exc.detail)
        return "failed"
    state.provider_label = getattr(provider, "label", PROVIDER_LABEL)
    model_route = getattr(provider, "model", "unknown")
    for _ in range(MAX_PROVIDER_ROUNDS):
        if _cancel_requested(state.actor, state.run_id):
            state.cancelled = True
            return _finish_from_state(state)
        if _over_budget(state):
            state.budget_exceeded = True
            return _finish_from_state(state)
        tools = advertised_tools(state.actor, tainted=state.tainted)
        try:
            response = provider.generate(_request(state, tools))
        except Exception as exc:  # provider outage: degrade with an ErrorCard and direct controls
            log.warning("agents.provider_failed", run_id=str(state.run_id), error_type=type(exc).__name__)
            _log_call(state, None, exc, provider)
            _finish(state, status="failed", text="Demo: the assistant is unavailable; use the direct controls.", cards=[
                card_builders.error_card(
                    getattr(exc, "code", "provider_unavailable"), "Assistant unavailable — use direct controls.",
                    provider_label=state.provider_label, tainted=state.tainted, recoverable_draft=_draft_link(state),
                    direct_controls=[RecordLink(label="Quotes", path="/sales/quotes"), RecordLink(label="Today", path=TODAY_PATH)],
                )], error_code=getattr(exc, "code", "provider_unavailable"), error_message=str(exc)[:500])
            return "failed"
        _log_call(state, response, None, provider)
        tool_blocks: list[ToolUseBlock] = []
        for block in response.iter_blocks():  # by type, never content[0]
            if isinstance(block, TextBlock):
                state.text_parts.append(block.text)
            elif isinstance(block, ToolUseBlock):
                tool_blocks.append(block)
        if response.stop_reason == "refusal":
            state.text_parts.append("The assistant declined; use the direct controls.")
        if not tool_blocks:
            return _finish_from_state(state)
        state.messages.append(Message(role="assistant", content=tuple(response.content)))
        results: list[ToolResultBlock] = []
        for block in tool_blocks:
            if block.name == ASK_CLARIFICATION:
                slot = str(block.input.get("slot") or "unknown")
                question = str(block.input.get("question") or "Which one do you mean?")
                state.clarification = (slot, question)
                _tx(state.actor, state.run_id, lambda uow, run, b=block: service.append_step(
                    uow, run, kind="tool_call", name=ASK_CLARIFICATION, input=dict(b.input), model_route=model_route))
                return _finish_from_state(state)
            if _cancel_requested(state.actor, state.run_id):
                state.cancelled = True
                return _finish_from_state(state)
            if _over_budget(state):
                state.budget_exceeded = True
                return _finish_from_state(state)
            outcome = _tool_step(state, block, model_route)
            results.append(ToolResultBlock(tool_use_id=block.id, name=block.name, content=outcome.result_content, is_error=outcome.is_error))
        state.messages.append(Message(role="user", content=tuple(results)))
    state.budget_exceeded = True
    return _finish_from_state(state)


# ---- entry point ---------------------------------------------------------------------------------------------
def classify(text: str, *, selected_option: Mapping[str, Any] | None) -> tuple[str, str]:
    """Deterministic router (Haiku in live mode, Slice 3): (request_type, detail)."""
    if selected_option:
        return "data_or_action", "clarification_answer"
    intent = parse_request(text)
    if intent is None:
        return "out_of_scope", "unrecognised"
    if intent.kind == "screen_question":
        return "screen_question", intent.kind
    return "data_or_action", intent.kind


def run_agent(actor: ActorContext, run_id: uuid.UUID) -> str:
    """Execute one run as the member. Returns the final run status; never raises for business failures."""
    state = _build_state(actor, run_id)
    command = parse_command(state.user_text) if not state.selected_option else None
    if command is not None:
        _route_step(state, "grammar", {"request_type": "command", "kind": command.kind, "pattern": command.pattern,
                                       "language": command.language}, "grammar", "command")
        return _run_command(state, command)
    request_type, detail = classify(state.user_text, selected_option=state.selected_option)
    _route_step(state, "router", {"request_type": request_type, "detail": detail}, "demo-router", request_type)
    if request_type == "out_of_scope":
        _finish(state, status="succeeded", text=HELP_TEXT, cards=[], error_code=None, error_message=None)
        return "succeeded"
    return _orchestrate(state, request_type)
