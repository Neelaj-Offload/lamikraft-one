# Lane report: agents-demo (Slice 1, wave 2)

Branch `lane/s1w2-agents`, worktree `D:\lk-wt\agents`, env slot 7 (API 8070, databases `lk_wt7` / `lk_wt7_test`).
Branched from `lane/s1w1-catalogue` (catalogue, parties, pricing, commercial and their `tools.py`). Scope: the
`agents` domain module (Demo orchestrator, durable runs, polling API, server-built cards, grounding, screen context,
AI usage log). Status: **implemented and green**; the only failing gate step is the expected `api:check` (new routes,
so `backend/openapi.json` and `apps/web/src/lib/api/schema.d.ts` need regenerating at merge).

Out of scope by the brief (Slice 3, seams named, no pretend stubs): live Anthropic/Gemini adapters, memory,
automations, action_refs UI, the trace view, vision answers to screen questions.

## 1. What is implemented

### Tables and migration (`backend/app/modules/agents/models.py`, `migrations/versions/0008_agents_slice1.py`)
- `0008` with `down_revision = "0005"` (reparent at merge). Six tenant tables, forced fail-closed RLS through
  `helpers.enable_tenant_rls`; `agents_run_step` and `agents_ai_call_log` are append-only (`helpers.append_only`).
- `agents_conversation` (owner `user_id`, channel web/voice/whatsapp, title, `last_activity_at`, status),
  `agents_turn` (seq, role, text, `screen_context` JSONB validated by `schemas.ScreenContext`, `selected_option`,
  cards of the assistant turn, `run_id`), `agents_run` (status queued/running/succeeded/failed/budget_exceeded/
  cancelled, trigger, request type, model route, started/finished, error code, step/tool-call counters and budgets,
  `tainted`, cancel flag), `agents_run_step` (seq, kind route/tool_call/tool_result/card/text/handoff, name, redacted
  input/output, `is_error`, error code, duration), `agents_object_context` (resource type/id/version, origin
  screen/tool/card), `agents_ai_call_log` (provider demo/anthropic/gemini, model, task class, input/output/cache
  tokens, latency, outcome, error type, request id; cost is computed at report time).
- Policy `agents.conversation`: own scope (owner = user); runs, turns and steps are children. All routes require
  `agents.assistant.use`.

### API (`router.py`, `service.py`)
- `POST /api/v1/agents/conversations` (201, `agents_create_conversation`), `GET /conversations/{id}`
  (`agents_get_conversation`), `POST /conversations/{id}/turns` (202 `{run_id, status, replayed}` + `Location`,
  `agents_create_turn`), `GET /runs/{run_id}?after_seq=N` (`agents_get_run`: run, steps with `seq > N`, cards, text,
  `done`, `last_seq`), `POST /runs/{run_id}/cancel` (`agents_cancel_run`).
- Turn validation: `text` ≤ 4,000 chars, `context` ≤ 16 KB and ≤ 50 visible items (422 otherwise); a
  `selected_option` must be one the previous ClarificationCard offered (422 `option_not_offered`); a repeated
  `client_utterance_id` replays the same run. `LK_AI_MODE=live` without a key → 409 `not_configured`.
- Invisible conversation/run → 404 (own scope, no existence leak).

### Run job and orchestrator (`run_job.py`, `orchestrator.py`)
- Job kind `agent.run` (`max_attempts=1`) runs as the member through `actor_for_member(company_id, user_id,
  channel=...)`, never as system. Each step commits in its own unit of work so polling sees progress.
- Pipeline: grammar match (`demo_intents.parse_command`, no provider) → deterministic router (request type) →
  provider loop over the registered ToolDefs → server-built cards → numeric-claim check on the final text →
  `agents.run.completed` / `agents.run.failed`. Budget 8 tool steps / 45 s → `budget_exceeded` + ErrorCard with the
  recoverable draft link. Cancel is checked before every provider round and tool call.
- Provider outage → ErrorCard "Assistant unavailable — use direct controls" with links; the grammar path keeps
  working. One `agents_ai_call_log` row per provider call (Demo: provider `demo`, zero tokens, latency measured).

### Providers (`providers/base.py`, `providers/demo.py`, `providers/demo_intents.py`)
- Provider-neutral `generate(ModelRequest) -> ModelResponse` with text/tool_use content blocks and a `tool_result`
  turn type, usage and request id; `providers.get_provider()` picks Demo in `demo` mode and raises
  `NotConfigured` in `live` mode without a key (the Anthropic adapter is the Slice-3 seam).
- Demo orchestrator ("Demo" on every card; the run detail reports `provider_label: Demo` and `mode: demo`; the
  kernel has no `integration_status` registry yet, so nothing is registered there — see §5): intent grammar + slot extraction
  (customer, product words, quantity with `quantity_source`, currency, usual/repeat) in English and Hinglish, and a
  stateless plan over the registered tools by name (`resolve_party`, `find_usual_order`, `resolve_product`,
  `resolve_price`, `calculate_quote`, `draft_quote`, optional `revise_draft_line`). An absent tool is a step error
  `capability_not_installed` with an ErrorCard.
- Command grammar: open the Nth item, snooze, navigate, stop, help, "what should I handle today", English + Hinglish
  fixtures (`tests/fixtures/demo_intents/*.json`).

### Tools runtime and grounding (`tools_runtime.py`, `grounding.py`, `numbers.py`, `context.py`)
- Order per call: registered and not hidden by taint → provenance sidecars stripped and verified → every uuid seen
  in this run (screen context re-read, object context, earlier tool output, card action) → input validated against
  the ToolDef model (`extra="forbid"`) → permission as the member (403 inside the step) → handler in its own unit of
  work with actor type `agent` (the member's permissions; writes carry origin `agent`) and, for draft/propose tools,
  idempotency key `agent:{run_id}:{step_seq}` → outputs redacted for the model (`model_exposure="deny"` removed).
- Numeric provenance: quantities need `quantity_source` (`user_turn`: the literal occurs in the turn as digits,
  Indian grouping or English number words; `record`: equals a value from this run's tool outputs or the previous
  turn's cards; `clarification`: from the chosen option). Prices are never inputs except an explicit permitted
  override `{value, reason, source: user_turn}`.
- Screen context (`schemas.ScreenContext`, ai-routing §4.1): every referenced record is re-read through the owning
  source reader; unknown or unauthorised refs are dropped silently, visible ones go to `agents_object_context`.
  Ordinals resolve against the active briefing pin first (`briefings.service.resolve_pin` seam), then the visible
  list, then the last presented list; a changed list asks instead of guessing.
- Taint: an `untrusted` tool output marks the run `tainted`; send tools are hidden for the rest of the run and every
  card carries `tainted` / `requires_confirmation`.

### Cards (`cards.py`)
- `QuoteDraftCard` (quote id/number/version, party, lines and persisted totals from the tool output, capabilities,
  "Review" link `/sales/quotes/<id>`, `preview_only`), `ClarificationCard` (exactly the ambiguous candidates, each
  with the `select_option` action the client posts back), `ErrorCard` (code, message, recoverable draft, direct
  controls), `RecordLinkCard`, `ReceiptCard`; `kind` discriminator; provider label on every card.
- Numeric-claim checker on final text: any money/quantity not present in this run's tool outputs becomes "see card"
  and the count is stored on the text step.

### Scenario C (fixtures.md §11)
- "Prepare Nordhaus's usual oak tray quote" (and the Hinglish form) → `resolve_party` → `find_usual_order`
  (LK-QT-2026-0003, LK-OT-0450 × 240) → `resolve_price` (EXP-EUR-2026, EUR 24.0000) → `calculate_quote` (5,760.00,
  recommended 216) → `draft_quote` (LK-QT-2026-0009, draft, owned by Meera, origin agent) → QuoteDraftCard +
  `agents.run.completed`.
- Ambiguity: with "Nordhaus Logistik AG" → ClarificationCard with exactly two options and no draft; the follow-up
  turn with the chosen option completes the draft.
- "change it to 300": sales ships no revise tool, so the plan recalculates the whole draft with `calculate_quote`
  (300 × 24.0000 = EUR 7,200.00) and the server applies it through `sales.service.update_line_command` (optimistic
  on the card's `version`, idempotent per step, recorded as a `sales.update_line` call/result step pair); the
  QuoteDraftCard shows the persisted figures plus a ReceiptCard. If sales is absent or the draft changed meanwhile
  (`version_conflict`) the preview card stands and nothing is written. A `revise_draft_line` tool, if one appears,
  is used instead (seam test).

## 2. Tests
- `tests/unit/agents/`: grammar fixtures (English + Hinglish), request grammar and slot extraction, number words and
  Indian grouping, ID/quantity/price provenance, numeric-claim checker, untrusted detection, screen-context limits,
  turn validation, card models (incl. the sales `QuoteDetail` shape), bare-id typing for object context.
- `tests/integration/agents/` (real PostgreSQL, catalogue lane's persona world): scenario C (English, Hinglish,
  ambiguity, offered-option check, follow-up applied / preview / stale / revise seam), ID and numeric provenance
  rejections before any service call, prices never inputs, extra fields, unknown tools, run-as-member 403 inside a
  step, service authorisation inside a step, budget exceeded (with and without a recoverable draft), cancel (queued
  and running), taint + send-tool hiding, grammar path during a provider outage, out-of-scope help, screen question,
  live mode without key 409, utterance replay, own-scope isolation (Neha → 404), context re-read and silent drop,
  changed list, context limits 422, ordinal fallback, deterministic commands, snooze without briefings,
  `@committed` RLS tenant isolation and append-only.
- `tests/contract/agents/`: route authz and operationIds, events ⊆ frozen catalogue, tool inputs carry no identity
  fields and forbid extras, job kind and policies registered, model flags, forced RLS + append-only triggers + enum
  checks, no wall clock, migration revision, grammar needs no provider.
- `tests/integration/agents/fake_sales.py` is the single swap point (see §4).

## 3. Gates (2026-10-30)
- `npm run test:api`: **413 passed** in 299 s (the agents suites alone: 139 passed).
- `npm run check -- --keep-going`: ruff PASS; pytest unit + contract PASS (255 passed); alembic heads == 1 PASS;
  **api:check FAIL** only with "backend/openapi.json is out of date" (expected: new routes); web lint PASS; web
  typecheck PASS; web vitest PASS (134 tests).

## 4. Fake → real sales tools (integrator)
The fakes mirror `lane/s1w2-sales` `app/modules/sales/tools.py` and `schemas.py` field for field
(`FindUsualOrderInput`, `UsualOrderOutput`/`BasisLine` with `unit_code`, `DraftQuoteInput`/`DraftQuoteLine` with
`unit_code` and `extra="forbid"`, `QuoteDetail` with `id`, `party{}`, `version`, `QuoteLineRead.product_snapshot`,
`totals`, `calculation`; `update_line_command(uow, quote_id, line_id, QuoteLineUpdate)`). `register()` skips names
the registry already holds and spies on every sales-facing handler (fake or real). The swap: seed the sales world
instead of `seed_prior_won_quote`, drop the fake `FIND_USUAL_ORDER` / `DRAFT_QUOTE` and the service stand-in,
re-point `drafts()` / `quote_view()` at `sales.service`, drop the revise-seam test unless sales ships the tool.

Mismatches found against the sales lane (none block the swap; agents already reads the real shapes):
1. Sales ships no `revise_draft_line` tool → the follow-up uses `calculate_quote` + `update_line_command` (done).
2. Sales registers no `sales.quote_line` source reader → a screen focus on a quote line is dropped; the line comes
   in through the previous card instead. Multi-line drafts need the reader for "change *this line*".
3. The real `draft_quote` handler calls `quotes.create_quote` / `add_line` directly, not through `idempotent(...)`,
   so the per-step idempotency key the runtime sets is ignored (`requires_idempotency=True` is declared). Low risk
   (`agent.run` has `max_attempts=1`) but a retried step would create a second draft.
4. Sales sets `origin=agent` only when `actor.actor_type == "agent"`; the runtime now runs tool calls (and the line
   update) with actor type `agent` and the member's permissions.
5. No module ships a `resolve_product` ToolDef (sales' docstring says catalogue does); the fake one (a thin wrapper
   over `catalogue.service.resolve_product`) stays registered after the swap until catalogue provides it.

## 5. Requests for the integrator
- Regenerate `backend/openapi.json` and `apps/web/src/lib/api/schema.d.ts` (new `agents_*` routes).
- Reparent `0008_agents_slice1.py` onto the merged head.
- Sales: register a `sales.quote_line` source reader; wrap `draft_quote` in the idempotent helper; consider a
  `revise_draft_line` tool (the plan prefers it when present).
- Catalogue: ship a `resolve_product` ToolDef in `catalogue/tools.py`.
- After the sales merge, apply the swap in §4 and rerun `tests/integration/agents`.
- The `integration_status` registry (PLAN §"one integration_status registry") does not exist in the kernel yet; when
  it lands, agents should register the AI provider entry with mode `demo` (one call in the manifest).
