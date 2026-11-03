# Lane brief: Slice 3 — agent runtime (providers, routing, usage, trace, streaming)

Branch `lane/s3-agents` from `main`. Worktree and env slot are assigned by the integrator (the brief says
which). Module owner: `backend/app/modules/agents/**`, `apps/web/src/features/assistant/**` (runtime parts only;
the voice lane owns push-to-talk and transcripts), `apps/web/src/features/ai-admin/**`, `src/messages/ai.ts`.
Never push; small named commits; never two test suites at once; never leave dev servers running.

## Contracts (read first, in this order)
1. `docs/architecture/ai-routing.md` — the frozen contract: routing table §2, split by request §3, screen context
   §4 (the voice/vision lane owns the masked screenshot), runtime rules §5, Anthropic adapter §5.1, grounding and
   taint §6, cost controls §7, DPDP gate §8, tests §9.
2. `docs/design/source/agent_voice_whatsapp.md` §3–§9 (core contracts, tables, orchestrator, registry, object
   context, grounding, proposals), §10 memory, §11 automations, §12 providers, §13 observability, §16 endpoints,
   §17 events.
3. The Slice-1 runtime you extend: `backend/app/modules/agents/{orchestrator,run_job,tools_runtime,service,router,
   grounding,context,cards,policies,schemas,models}.py`, `providers/{base,demo,demo_intents}.py`,
   `docs/lanes/agents.md`. The Demo provider stays the default and must keep passing its tests.
4. `docs/architecture/{permissions (§agents.*), events (§3.7), api-conventions, conventions, fixtures}.md`;
   `backend/app/platform/system/integrations.py` (`ai.anthropic`, `ai.gemini` defs); `docs/DECISIONS.md`
   ADR-050 (SSE spike deferred to Slice 3).
5. Claude API reference for the SDK specifics: the `claude-api` skill in this environment (load it before writing
   the adapter) — adaptive thinking, `output_config.effort`, strict tools, server-side fallbacks, stop reasons,
   prompt caching, Message Batches, typed exceptions.

## Deliverables
1. **Anthropic adapter** `providers/anthropic.py` implementing `generate(ModelRequest) -> ModelResponse` exactly
   as ai-routing §5.1 (sync client, `max_retries=2`, timeouts; `tool_choice auto`; strict write/proposal tools
   within the strict budget; adaptive thinking + explicit effort; iterate blocks by type; stop reasons incl.
   `pause_turn`, `refusal` with `stop_details`, `max_tokens` retry once; server-side fallback beta on Sonnet/Opus;
   typed exception chain with `retry-after`; request-id stored; circuit breaker 5 failures / 2 min / 60 s; prompt
   caching with a deterministic prefix and `cache_read_input_tokens` logged). Unit tests with a fake transport;
   a contract test that never needs a key. Live mode with a missing key: readiness `ai: misconfigured`
   (integration status `not_configured`), never a silent Demo fallback.
2. **Router and routing table**: Haiku low-effort classifier returning the request type and slots (§3), the
   deterministic grammar first; Sonnet orchestration; Opus escalation only by the rules in §2 (≥2 clarification
   failures on a slot, multi-domain, explicit "think harder"), with the per-company daily cap. Models and caps
   from env (`LK_MODEL_*`) and the `ai_routing` org setting (new SettingDef, `agents.ai_routing.manage`, MFA step-up
   via the platform's step-up helper). Per-call `max_tokens` caps and run budgets per task class; over budget →
   `budget_exceeded` + ErrorCard + recoverable draft.
3. **Phrasing service** `agents/phrasing.py`: Haiku structured output with `{{a1}}` placeholders, the validator
   (§6: numerals equal facts, currency codes preserved, proper nouns from facts, no new dates, ≤2 sentences),
   template fallback labelled "Standard wording", fact-hash cache, Message Batches path for pre-shift phrasing
   (Demo provider implements the same interface deterministically). The briefings lane consumes this.
4. **Quotas** (§7) per user and workflow per day, checked before enqueue; over quota degrades to the
   deterministic path with a clear message. **Numeric-claim checker** and **taint** per §6 — extend what
   `grounding.py` already does and add the tests named in §9. **Redaction canary** test.
5. **Usage store and admin dashboard**: `agents_ai_call_log` as the single store (workflow, provider, model,
   status, tokens incl. cache read/write, latency, request id, run id); `GET /api/v1/admin/ai/status|usage`,
   `POST /api/v1/admin/ai/verify` (Graph-like verification: a minimal real call in live, deterministic in demo);
   web page `/settings/ai` (route `settings-ai`, context tab of Settings, permission `agents.ai_usage.read`;
   routing editor shown only with `agents.ai_routing.manage`): provider status (Demo / Verified at / Failing with
   circuit state), per-workflow runs, p50/p95 latency, tokens, error rate, failures with request ids, cost
   **estimated at report time** from a configurable price table (never stored as money), the DPDP gate status
   (§8) as text. Use `FactStrip`/`DataTable`; no charts library; no fabricated numbers.
6. **Trace**: UUIDv7 `correlation_id` at ingress through turn → run → steps → proposal → decision → receipt →
   outbox; `GET /api/v1/traces/{correlation_id}` returns a redacted timeline to participants and
   `audit.trace.view` holders; web page `/settings/ai/traces/[correlationId]` (or a drawer from the run) listing
   the timeline with `LocalDateTime` and mono ids.
7. **Streaming spike and implementation** (ADR-050): SSE `GET /api/v1/agents/runs/{id}/events` with
   `Cache-Control: no-cache, no-transform`, verified through the Next `/api` rewrite in dev and `next start`;
   the composer consumes it with the existing polling as fallback (keep `use-assistant.ts` polling path working
   under a feature flag until SSE is proven in e2e). Record the result as a new ADR in `docs/DECISIONS.md`.
8. **Draft undo and receipts** (design §9 "Undo"): `undo_spec` on draft receipts, `POST /api/v1/receipts/{id}/undo`
   within 24 h while the target is unchanged; ReceiptCard shows Undo.
9. **Evals**: `backend/tests/evals/` golden set (tool choice, clarification, latency) running on Demo in CI and on
   Anthropic manually with a key (`LK_AI_MODE=live` guarded, skipped without a key).

## Migration
One file `backend/migrations/versions/0020_agents_slice3.py` with `down_revision = "0009_agents_slice1"` (the
integrator reparents it onto the Slice-2 chain; never renumber the merged chain yourself).

## Events, permissions, settings
Events exactly as `events.md` §3.7 (`agents.run.completed/failed`, `agents.memory_item.approved`,
`agents.automation_run.completed` are emitted by the memory/automations lane — coordinate through the registry,
do not duplicate). Permissions from `permissions.md` (`agents.ai_usage.read`, `agents.ai_routing.manage`).
Integration status keys `ai.anthropic`, `ai.gemini` already exist: fill their verification.

## Web rules
`docs/superpowers/specs/2026-11-02-checkpoint-2-build-guide.md` §0 ground rules (plain parsers for server pages,
copy in messages, states catalogue, `design-lint`), route registered in `src/lib/routes.ts`, query keys in
`src/lib/api/query-keys.ts` (`agents` group additions), `AreaNav` under `PageHeader`.

## Verification
`npm run check -- --keep-going` 7/7, `npm run test:api` (count), `npm run api:generate` committed, web gates;
`docs/lanes/agents-s3.md` with: what was built, the §9 test table, decisions (ADR for SSE), integrator requests,
gate output. Final message: branch tip, counts, unfinished items with reasons.
