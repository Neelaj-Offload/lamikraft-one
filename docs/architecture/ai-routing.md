# AI routing, screen awareness and grounding

Status: frozen in Slice 0; live adapters ship in Slice 3, the deterministic Demo path in Slice 1.
Implements `docs/PLAN.md` § AI architecture and the user decisions of 2026-10-12: Claude is the main reasoning
brain (Haiku, Sonnet or Opus by task, cost efficiency a hard constraint); Gemini 3.8 Flash handles vision and
instant answers about what is on screen; each reply is routed by request type; screen awareness is structured
context on every message plus a masked screenshot only on demand.

Model facts below were checked on 2026-10-12 against the bundled Claude API reference (models cached 2026-10-06).
Gemini model identifiers are verified against Google's documentation at build time (Slice 3) before live use.

---

## 1. Principles

1. **Facts come from queries; models only phrase, interpret and propose.** Money, quantities, counts, dates and
   prices are computed by services. A model never does money arithmetic, never generates stock quantities and
   never infers a missing price.
2. **Cheapest adequate path first.** Deterministic grammar → Haiku → Sonnet → Opus, escalating only on rules.
3. **The server decides authority.** `ToolContext` wraps the server-built `ActorContext`; the model cannot set
   identity, and it has no approve tool.
4. **Everything degrades.** With AI unavailable, over quota or not approved for live use, the briefing, direct
   controls and the deterministic grammar keep working; the UI says so.
5. **Keys live only on the server.** Live mode with a missing key fails visibly (integration status
   `not_configured`); there is no silent fallback to Demo and no readiness failure.

## 2. Routing table

Defaults are configurable in Settings → AI routing (`agents.ai_routing.manage`, company scope, MFA). Model ids
come from environment/settings: `LK_MODEL_PHRASING=claude-haiku-5-5`, `LK_MODEL_ORCHESTRATOR=claude-sonnet-5-5`,
`LK_MODEL_ESCALATION=claude-opus-5-5`, `LK_MODEL_VISION=gemini-3.8-flash` (verify), `LK_AI_MODE=demo|live`.

| Task class | Default model | Effort / thinking | Per-call `max_tokens` cap | Notes |
|---|---|---|---|---|
| Deterministic commands: "open the second item", snooze, navigate, stop speaking, "what should I handle today", confirm/approve buttons | grammar parser (`agents/providers/demo_intents.py`), no model | — | — | zero cost; works when AI is down; English + Hinglish fixtures |
| Request routing and intent/entity extraction (customer, product, quantity, unit, currency, date) | `claude-haiku-5-5` | `output_config.effort: "low"`; adaptive thinking (on by default) | 1,024 | structured output; returns request type (§3) and slots with `quantity_source` |
| Briefing phrasing, overview sentence, narration script, Explain elaboration, notification text, follow-up summaries | `claude-haiku-5-5` | `low` | 600 (phrasing), 1,200 (narration), 800 (Explain), 400 (notification) | facts and numbers injected as placeholders (`{{a1}}`) and substituted by the server; output validator (§6); template text is stored first |
| Orchestration with typed tools: draft/revise quote, challan draft, proposals, clarification | `claude-sonnet-5-5` | `medium` set explicitly (Sonnet 5.5 defaults to `high`); adaptive thinking | 8,192 per step; run budget 8 steps / 45 s / 120k input tokens | the main brain |
| Escalation: multi-domain planning, management cross-team analysis, what-if, repeated clarification failure (≥2 on the same slot), explicit "think harder" | `claude-opus-5-5` | `medium` set explicitly (Opus 5.5 default is `medium`; thinking cannot be disabled) | 16,000 per step; run budget 10 steps / 90 s / 200k input tokens | rule-triggered only, never the default; per-company daily cap |
| Vision extraction: photos, handwriting, bills, POs, delivery notes | Gemini 3.8 Flash via `google-genai` (sync client) | read-only, no tools, JSON response schema | 2,048 output | output is untrusted data; uncertain fields go to a structured confirmation card |
| Instant answers about what is on screen | Gemini 3.8 Flash | read-only, no tools | 512 output; 8 s timeout | answers only from the masked screenshot plus the re-read screen context; hands off to Claude whenever data or an action is needed |
| Demo mode (`LK_AI_MODE=demo`, default) | deterministic Demo adapters (Claude-shaped orchestrator and vision) | — | — | labelled "Demo"; no keys needed; exercises the same tool, grounding and card path |

List prices at the time of writing (USD per million tokens, input/output): Haiku 5.5 0.10/0.50 (prompts ≤100K),
Sonnet 5.5 2.00/10.00, Opus 5.5 4.00/20.00. The configurable price table in settings is authoritative for the
usage dashboard; Gemini prices are entered there after verification.

## 3. Split by request

Every assistant message is classified once, deterministic first:

1. **Grammar match** (no model) → execute the deterministic command through the same services.
2. **Router** (Haiku, low effort) returns one request type:

| Request type | Route | Hand-off |
|---|---|---|
| `command` | deterministic service call (rare after step 1) | — |
| `screen_question` (what is shown, where is X, explain this panel) | Gemini instant answer with masked screenshot + re-read screen context | to Sonnet when the answer needs data not on screen or an action |
| `visual_extraction` (attached photo/document) | Gemini extraction → structured confirmation card | to Sonnet with the extraction as untrusted data once the user confirms fields |
| `data_or_action` (lookups, drafts, proposals) | Sonnet orchestrator with typed tools | to Opus on escalation rules |
| `analysis` (cross-team, what-if, planning) | Opus escalation | — |
| `out_of_scope` | deterministic help text listing supported commands | — |

Each reply is produced by exactly one routed model per step; a hand-off starts a new step in the same durable
`agent.run` and is visible in the trace. Model choice is logged per step in `agents_ai_call_log`.

## 4. Screen awareness contract

### 4.1 Structured screen context (every web assistant message)

The composer sends `context` with every turn (`POST /api/v1/agents/conversations/{id}/turns`):

```json
{
  "schema_version": 1,
  "captured_at": "2026-10-12T03:31:04Z",
  "route": {"path": "/sales/quotes/[quoteId]", "params": {"quoteId": "0192..."}, "area": "sales"},
  "focus": {"type": "sales.quote", "id": "0192...", "version": 7},
  "records": [{"type": "sales.quote", "id": "0192...", "version": 7, "role": "primary"}],
  "visible_items": [{"ref": "i2", "list_key": "quote_lines", "ordinal": 2, "type": "sales.quote_line", "id": "0192...", "version": 3}],
  "selection": ["i2"],
  "filters": {"status": "draft"},
  "draft": {"form_key": "quote_header", "record_ref": "0192...", "dirty_fields": ["remarks"], "values": {"remarks": "..."}},
  "briefing_pin": {"pin_id": "0192...", "version": 2},
  "viewport": {"width": 1440, "height": 900}
}
```

Rules:
- Size ≤ 16 KB and ≤ 50 visible items; larger payloads are rejected (422) and the client trims to the focused list.
- The context is a **hint only**. The server re-reads every referenced record through `ScopedRepository` with the
  actor's permissions; unknown or unauthorised references are dropped without revealing existence. Labels and
  values supplied by the client are never trusted as facts.
- Draft values are the user's own input: never persisted from context, never containing fields marked
  `data-restricted`, re-validated by the service that eventually receives them.
- Ordinal references ("the second item") resolve against an active briefing pin first
  (`briefings.resolve_pin`), then against the most recently presented list; a list changed since the user saw
  it produces a clarification, never a guess.

### 4.2 Masked screenshot (on demand only)

- Sent only when (a) the router classifies the request as visual (`screen_question`), (b) the message involves an
  image or document, or (c) the user taps **Look at my screen**. Nothing is captured continuously or in the
  background.
- User preference `assistant.screen_share = ask | auto` (default `ask`): with `ask`, a visual request shows a
  one-tap "Share a masked screenshot" prompt; with `auto`, capture happens only for router-classified visual
  requests. A company admin setting (`agents.screen_capture_enabled`, default true in demo, false until the DPDP
  approval in live) disables capture entirely; the preference cannot override it (mandatory control).
- Capture is client-side from the application's own rendered DOM (never `getDisplayMedia`, so other windows and
  tabs can never be captured). Before rasterising, every element with `data-restricted`, every password field and
  every element marked `data-private` is replaced by an opaque block in a cloned tree; the live UI is not altered.
- The image is downscaled to ≤1568 px on the longest edge, encoded as WebP (≤1.5 MB), hashed (SHA-256) and
  deduplicated within the conversation. It is stored as a `file_object` with purpose `screen_capture`,
  classification `restricted`, purged after 24 hours, never logged, and referenced in `agents_ai_call_log` by hash only.
- The composer shows a removable "Masked screenshot attached" chip before sending.

## 5. Runtime rules (all providers)

- One orchestrator per employee with domain tool groups (Sales, Catalogue, Procurement, Production, Warehouse,
  Finance, Management). Every run is a durable `agent.run` job: resolve → authorised read → validate →
  propose/execute → commit → receipt.
- Tools call the same `service.py` functions as UI endpoints. Tool input models are `extra="forbid"` and contain
  no identity fields (contract test). A tool is advertised only when its slice is ready, the actor holds its
  permissions, the channel is allowed and — for proposal/execute tools — an idempotent executor and an active
  policy exist.
- The model has **no approve tool**. Approvals come only from authenticated human actions bound to an
  `action_ref` nonce plus the proposal content hash.
- Cards (QuoteDraftCard, ProposalCard, ClarificationCard, ReadbackCard, ReceiptCard, ErrorCard, RecordLinkCard)
  are built by the server from tool outputs; model text never carries authoritative figures.

### 5.1 Anthropic adapter (`agents/providers/anthropic.py`, Slice 3)

- Synchronous `anthropic.Anthropic` client in the worker (`max_retries=2`, explicit timeout); a manual,
  provider-neutral loop over `generate(ModelRequest) -> ModelResponse`.
- `tool_choice: {"type": "auto"}` always; forced `any`/`tool` returns 400 on Sonnet 5.5 and Opus 5.5. Write and
  proposal tools set `strict: true` on the tool definition (`additionalProperties: false`, `required`), within the
  per-request strict-tool budget; read tools may be non-strict. Pydantic re-validates every input server-side.
- Adaptive thinking (`thinking: {"type": "adaptive"}`) with explicit `output_config.effort`; no `budget_tokens`
  (400 on these models), no assistant prefill (400).
- Iterate over every content block by type; never assume `content[0]` is text. Thinking blocks are passed back
  unchanged within the same run and the conversation is append-only inside a run; a new run starts from redacted
  text history and object context without replaying earlier thinking blocks.
- Stop reasons handled: `end_turn`, `tool_use`, `max_tokens` (retry once with a higher cap if a tool call is
  truncated), `stop_sequence`, `pause_turn` (continue, bounded), `refusal` (read `stop_details`; deterministic
  fallback text plus direct-control links); any other documented value is treated per the SDK at build time.
- Server-side refusal fallbacks on Sonnet 5.5 and Opus 5.5 requests: beta `server-side-fallback-2026-07-01`
  with `fallbacks: "default"` (Claude API). Haiku 5.5 has no server-side fallback, so its refusals fall back to the
  deterministic template. Message Batches requests do not carry `fallbacks`.
- Typed exception chain, most specific first (`NotFoundError` → `RateLimitError` honouring `retry-after` →
  `APIStatusError` → `APIConnectionError`); the provider `request-id` is stored. A circuit breaker opens after
  5 failures in 2 minutes for 60 seconds.
- Prompt caching: a deterministic prefix per role template — tools sorted by name, then the versioned system
  prompt for the advertised groups — with `cache_control` on the system prompt and the last tool. Volatile content
  (time, screen context, user text) comes after the last breakpoint. Mid-run operator notes use mid-conversation
  system messages so the cached prefix is preserved. `usage.cache_read_input_tokens` is logged.

### 5.2 Gemini adapter (`agents/providers/gemini_vision.py`, Slice 3)

- Synchronous `google-genai` client, model from `LK_MODEL_VISION`, key `GEMINI_API_KEY` server-side only.
- Read-only: no tools or function calling; a JSON response schema per extraction kind (purchase order, bill,
  delivery note, handwritten list, screen answer). Each field carries a confidence; anything below threshold or
  missing becomes a confirmation field, never a default.
- Output is untrusted data (`provenance=external`, run tainted). Extractions never write records; they populate a
  structured confirmation card whose confirmed values go to Claude tools or direct forms.
- Timeouts: 8 s for screen answers, 20 s for extraction; failures show "Vision unavailable — enter details" with
  the manual form.

## 6. Grounding and taint

- **ID provenance**: every entity id in a tool input must come from the re-read screen context, the object context,
  an earlier tool output in this run, or a card action; otherwise the call returns `is_error` before any service
  call. Services still authorise.
- **Numeric provenance**: each quantity carries `quantity_source` (`user_turn`, `record`, `clarification`); the
  literal must appear in that turn (digits, Indian grouping and English number words; Hinglish number words
  labelled untested) or equal the referenced record value. Prices are never model inputs except an explicit
  override `{value, reason, source: user_turn}` gated by `sales.quote_price.override`.
- **Numeric-claim checker**: any money or quantity figure in final model text that did not come from this run's
  tool outputs (or, for screen answers, from the re-read screen records) is replaced by "see card" and counted.
- **Phrasing validator** (briefings, notifications): every numeral and amount equals a fact, currency codes are
  preserved, proper nouns come from the facts, no new dates, at most 2 sentences; on failure the template text is
  used and labelled "Standard wording".
- **Taint**: runs that read external content (customer or vendor messages, attachments, OCR or any vision output)
  are tainted. Tainted runs hide external-send tools, disable the direct-command shortcut and require explicit
  human confirmation for every proposal. External text reaches the model only inside tool results as
  `{"untrusted": true, "source": ..., "text": ...}`; links in it are never fetched.
- **Redaction**: retrieval and search are permission-filtered in SQL before model access. Fields registered with
  `Restricted(..., model_exposure="deny")` — costing, margin, supplier cost, bank details — are removed from model
  context even for users allowed to see them (the card shows them directly). A canary test plants a costing
  sentinel and asserts it never reaches provider payloads, logs, WhatsApp renders or exports.

## 7. Cost controls

| Control | Rule |
|---|---|
| Per-task caps | `max_tokens` per task class (§2); run step/time/token budgets; over budget ends the run as `budget_exceeded` with an ErrorCard and the recoverable draft |
| Phrasing cache | phrasing keyed by a fact hash (facts + template version + language); unchanged items never regenerate |
| Batch | pre-shift briefing phrasing uses Message Batches (results keyed by `custom_id`, any order); failures keep template text |
| Images | downscale and dedupe by SHA-256 before any vision call; one screenshot per request at most |
| Quotas | per user and per workflow per day (defaults: 150 orchestrator runs, 10 escalations, 60 vision calls per user; company escalation cap 100/day), checked before enqueueing; over quota → deterministic paths with a clear message |
| Automations | subscribe only to event types referenced by active automations; quota checked before enqueue; owner, trigger, allowed tools, scope, approval mode and history required |
| Usage store | `agents_ai_call_log` is the single store (workflow, provider, model, status, tokens incl. cache read/write, latency, request id, run id); cost computed at report time from the configurable price table; admin usage, latency and failure dashboard (`agents.ai_usage.read`) |
| Escalation guard | Opus only by rule; the router may never select Opus directly for a single-domain request |

## 8. Data protection gate

Live AI (`LK_AI_MODE=live`) stays off in production until the owner records approval under India's DPDP Act to send
business data (customer names, quote lines and amounts — never costing) and masked screenshots to Anthropic and
Google, including any data-residency constraint. Demo mode needs no approval and no keys. The approval, date and
scope are recorded in `docs/DECISIONS.md` and shown in Settings → AI.

## 9. Tests (planned)

- `backend/tests/unit/agents/test_router_split.py::test_request_types_route_to_expected_provider`
- `backend/tests/unit/agents/test_grammar.py::test_deterministic_commands_need_no_model`
- `backend/tests/integration/agents/test_screen_context.py::test_context_is_hint_and_records_are_reread`
- `backend/tests/integration/agents/test_screen_context.py::test_unauthorised_refs_dropped_without_leak`
- `apps/web/e2e/scenarios/c-screen-capture.spec.ts::masked_regions_are_blacked_out_and_capture_is_explicit`
- `backend/tests/contract/agents/test_anthropic_adapter.py::test_block_iteration_stop_reasons_and_fallbacks`
- `backend/tests/contract/agents/test_tool_schemas.py::test_strict_compatible_and_no_identity_fields`
- `backend/tests/integration/agents/test_grounding.py::test_numeric_claims_without_tool_source_are_stripped`
- `backend/tests/integration/agents/test_taint.py::test_external_content_hides_send_tools`
- `backend/tests/integration/agents/test_quotas.py::test_over_quota_degrades_to_deterministic_path`
- `backend/tests/integration/agents/test_redaction_canary.py::test_costing_never_reaches_provider_payloads`
- `backend/tests/integration/agents/test_ai_outage.py::test_circuit_breaker_and_briefing_fallback`
