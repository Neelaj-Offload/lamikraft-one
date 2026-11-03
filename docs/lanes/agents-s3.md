# Lane report: agents-runtime (Slice 3, wave 3a)

Branch `lane/s3-agents` (from `main` c94a13d), worktree `D:\lk-wt\identity`, env slot 1 (API 8010, web 3010,
databases `lk_wt1` / `lk_wt1_test`). Brief: `docs/superpowers/briefs/s3-agents-runtime.md`. Status: **deliverables 1–9
implemented and tested on Demo and against a fake Claude transport; no live call was made (no key configured).**

## 1. What was built

| # | Deliverable | Where | Notes |
|---|---|---|---|
| 1 | Anthropic adapter | `agents/providers/anthropic.py` | sync SDK client (`max_retries=2`, per-class timeouts), `tool_choice auto`, strict draft/propose tools within a 16-tool budget, adaptive thinking + explicit `output_config.effort`, block iteration by type, `end_turn/tool_use/max_tokens (retry once)/stop_sequence/pause_turn (bounded)/refusal (stop_details)`, `server-side-fallback-2026-07-01` + `fallbacks: "default"` on Sonnet/Opus only (not Haiku, not batches), typed exception chain with `retry-after` and request id, circuit breaker 5 failures / 2 min / 60 s, deterministic cache prefix (tools sorted, versioned system prompt, `cache_control` on system and last tool), `cache_read_input_tokens` logged. Live mode without a key: 409 `not_configured`, integration `secret_missing`, readiness `checks.ai = misconfigured` (informational), never a Demo fallback. |
| 2 | Router and routing table | `agents/routing.py`, `agents/classify.py`, `agents/quotas.py`, orchestrator | Grammar first (command grammar, then request grammar; "think harder" marker stripped), then the Haiku low-effort structured-output classifier in live mode (quantity literal must occur in the turn). Sonnet orchestration (`medium`), Opus only by rule: `analysis` (grammar), ≥2 consecutive clarifications on the same slot, multi-domain beyond sales+catalogue, explicit "think harder"; the router may not pick Opus for a single-domain request (`escalation_guard`). Per-user and per-company escalation caps count runs. Models/caps from `LK_MODEL_*` and the new `ai_routing` SettingDef (read `agents.ai_usage.read`, manage `agents.ai_routing.manage`, step-up through `org.service.update_setting` → `require_recent_auth`). Per-task budgets (steps / seconds / input tokens / per-call `max_tokens`) persisted on the run; over budget → `budget_exceeded` ErrorCard with the recoverable draft. |
| 3 | Phrasing service | `agents/phrasing.py` | `{{a1}}` placeholders, server substitution, validator (no model numerals, currency codes, proper nouns from facts/template, no new dates, ≤2 sentences, money facts kept), "Standard wording" template fallback, fact-hash cache `agents_phrasing_cache` (outages not cached), Message Batches path (`submit_batch` / `collect_batch`, keyed by custom id, failures keep template text), Demo phraser with the same interface. Every call logged with workflow `phrase`. **The briefings lane consumes `phrasing.phrase` / `submit_batch` / `collect_batch`.** |
| 4 | Quotas, numeric claims, taint, canary | `agents/quotas.py`, `grounding.py` (existing), tests | Quotas per user/workflow per company day, checked before enqueue; over quota the run is `degraded_reason=quota_exceeded`, grammar commands still work, model paths end with a quota ErrorCard and no provider call. |
| 5 | Usage store + dashboard | `agents/admin.py`, `GET /api/v1/admin/ai/status|usage`, `POST /api/v1/admin/ai/verify`; web `/settings/ai` | `agents_ai_call_log` gains `user_id`, `correlation_id`; workflows `orchestrate/route/escalate/phrase/verify/vision`. Status: Demo / Verified at / Failing (circuit derived from the call log, since the breaker lives in the worker) / Not verified / Not configured. Usage: calls, runs, errors+refusals, p50/p95 (Postgres `percentile_cont`), tokens incl. cache read/write, failures with request ids and trace links, cost **estimated at report time** from the price table (None when a model has no price). DPDP gate as text. Routing editor (the generic `SettingCard` for `ai_routing`) only with `agents.ai_routing.manage`. FactStrip + DataTable, no charts. |
| 6 | Trace | `agents/trace.py`, `GET /api/v1/traces/{correlation_id}`, web `/settings/ai/traces/[correlationId]` | UUIDv7 correlation id at ingress (the request's if it is a UUIDv7) on turn → run → steps → AI calls → receipts; the run job runs with it so outbox events and audit rows carry it. Redacted timeline (no text, inputs, outputs, cards). Participants and `audit.trace.read` holders; others 404. |
| 7 | SSE | `agents/streaming.py`, `GET /api/v1/agents/runs/{id}/events`; web `run-stream.ts`, `use-assistant.ts` | Same `RunDetail` payload as polling; `run`/`done`/`timeout` events, heartbeat 15 s, max 120 s, `Last-Event-ID` resume. Verified through the Next rewrite in dev and `next start` (ADR-052). The composer streams by default and falls back to polling on error/timeout; `NEXT_PUBLIC_LK_ASSISTANT_SSE=0` forces polling. |
| 8 | Draft undo and receipts | `agents/receipts.py`, `agents_receipt`, `GET /api/v1/receipts/{id}`, `POST /api/v1/receipts/{id}/undo`; ReceiptCard Undo | `undo_spec` built from tool outputs: `revert_draft` (delete with `sales.quote.delete`, else cancel with a reason — the sales role has no delete right) and `restore_line` (prior quantity as a new version). 24 h window, target version unchanged, own scope (404 otherwise), 409 `undo_not_available` with `reason` (`undone`, `expired`, `target_changed`). Audit `agents.receipt.undone`. |
| 9 | Evals | `backend/tests/evals/` | `golden.json` (7 cases: usual quote en/Hinglish, ambiguous customer, navigate, today, out of scope, screen question) checks request type, tool choice, clarification and latency. `test_golden_demo` runs in CI; `test_golden_live` runs only with `LK_AI_MODE=live` and `ANTHROPIC_API_KEY` (skipped otherwise). |

Migration `backend/migrations/versions/0020_agents_slice3.py` (revision `0020`, `down_revision = "0009"`; the brief's
`0009_agents_slice1` is that revision's id on this branch): correlation ids, run token budget/usage and degradation,
call-log user and correlation, `agents_receipt` and `agents_phrasing_cache` with forced fail-closed RLS.

## 2. ai-routing §9 test table

| Planned test | Status |
|---|---|
| `unit/agents/test_router_split.py::test_request_types_route_to_expected_provider` | added (plus routing table, router request, grammar, router output validation, escalation rules, clarification counting) |
| `unit/agents/test_grammar.py::test_deterministic_commands_need_no_model` | existing (Slice 1); live variant `integration/agents/test_grounding.py::test_grammar_match_skips_the_router_call` |
| `integration/agents/test_screen_context.py::test_context_is_hint_and_records_are_reread` | existing as `integration/agents/test_isolation_and_context.py::test_context_is_hint_and_records_are_reread` |
| `integration/agents/test_screen_context.py::test_unauthorised_refs_dropped_without_leak` | existing as `test_isolation_and_context.py::test_unauthorised_refs_dropped_without_leak` |
| `e2e/scenarios/c-screen-capture.spec.ts` | not this lane (vision/voice lane owns the masked screenshot) |
| `contract/agents/test_anthropic_adapter.py::test_block_iteration_stop_reasons_and_fallbacks` | done (dd86cd3, 14 contract tests over a fake transport) |
| `contract/agents/test_tool_schemas.py::test_strict_compatible_and_no_identity_fields` | added |
| `integration/agents/test_grounding.py::test_numeric_claims_without_tool_source_are_stripped` | added (live mode over a fake Claude transport; also asserts the Haiku→Sonnet request shapes, append-only thinking replay and the call-log rows) |
| `integration/agents/test_taint.py::test_external_content_hides_send_tools` | added (live, fake transport) |
| `integration/agents/test_quotas.py::test_over_quota_degrades_to_deterministic_path` | added (+ escalation cap, think-harder budgets) |
| `integration/agents/test_redaction_canary.py::test_costing_never_reaches_provider_payloads` | added (cost reader; payloads, trace, turn, call log, steps, process logs) |
| `integration/agents/test_ai_outage.py::test_circuit_breaker_and_briefing_fallback` | added (5 failures open the circuit, no request sent, grammar works, phrasing "Standard wording", status Failing) |

Also: `integration/agents/test_slice3_api.py` (undo ×4, trace ×2, admin, SSE ×2), `integration/agents/test_phrasing_service.py`,
`unit/agents/test_phrasing.py`, `tests/evals/test_golden.py`; web `features/ai-admin/ai-admin.test.tsx`,
`features/assistant/run-stream.test.ts`.

## 3. Decisions

- **ADR-052** (new): run progress over SSE, polling as fallback; evidence from dev and `next start`.
- Undo of an agent-created draft cancels it (with reason) when the member cannot delete drafts — the sales template
  has no `sales.quote.delete`. The number is never reused either way.
- The circuit breaker is per process (worker); the dashboard derives the circuit from the call log with the same rule.
- Escalation quotas count runs that made an `escalate` call, not individual calls.
- `/receipts/*` and `/traces/*` are agents-owned top-level paths (added to `PATH_EXCEPTIONS` in
  `tests/contract/system/test_route_authz.py`); `/admin/ai/*` carries the `admin` tag with operation ids
  `admin_get_ai_status`, `admin_get_ai_usage`, `admin_verify_ai` so the module_verb_noun rule holds without claiming the
  whole `/admin` segment for agents.
- The `ai_routing` setting reads with `org.settings.read` through the generic settings endpoints (the platform matrix
  stays as it was); `agents.ai_usage.read` holders see the effective table through `GET /admin/ai/status`. Its PUT
  needs `agents.ai_routing.manage` (+ recent authentication); the PUT matrix lists that key.
- Route permission prefixes must be module-level (`routes.test.ts`), so both new routes use `agents.`; the views
  check `agents.ai_usage.read` / own-or-auditor themselves.

## 4. Integrator requests

1. Reparent `0020` onto the merged Slice-2 chain (`lk db reparent`); no other lane touches the agents tables.
2. `docs/DECISIONS.md`: renumber ADR-052 if another lane took that number.
3. Shared-file touches (small, additive): `tests/contract/system/test_route_authz.py` (2 path exceptions, 1 PUT key), `app/platform/system/router.py` (informational `checks.ai` in readiness),
   `apps/web/src/lib/routes.ts` (2 routes), `apps/web/src/lib/api/query-keys.ts` (agents keys + 2 invalidation entries;
   `org.setting_changed` also invalidates the AI status), `apps/web/src/features/settings/settings-hub.tsx` (hint),
   `backend/openapi.json` and `apps/web/src/lib/api/schema.d.ts` (regenerated — regenerate again after the merge).
4. Briefings lane: consume `agents.phrasing` (see §1 row 3). Vision/voice lane: `routing.table.model_for("vision")`
   and `quotas` key `vision_calls_per_user` are in place; log vision calls with `task_class="vision"`.
5. The worktree's `node_modules` had Next 16.4.0 against a 16.4.4 lockfile; `npm install` synced it. Next 16.4.0's dev
   server printed an upgrade nudge with instructions addressed to the agent (to ask about running
   `next upgrade --agent=security`); it was not acted on — the lockfile already pins 16.4.4.
6. `domain_event` and `audit_log` have no index on `correlation_id`; the trace query filters by company + correlation.
   Fine at demo volume; add `(company_id, correlation_id)` indexes if traces get slow.

## 5. Not done / limits

- No live Claude call (no key). Live behaviour is proven only against the fake transport; `test_golden_live` and
  `POST /admin/ai/verify` are the live checks to run once a key and the DPDP approval exist.
- Gemini adapter (`providers/gemini_vision.py`) is the vision/voice lane's.
- The Haiku router and refusal paths run only in live mode; in demo the deterministic grammar decides.

## 6. Gate output (2026-11-03, slot 1, tip before this report: 71bdcec)

`npm run check -- --keep-going` — **7/7 PASS**:

```
backend: ruff check              PASS
backend: pytest unit + contract  PASS   520 passed
alembic heads == 1               PASS
api:check                        PASS   backend/openapi.json matches the app
web: lint                        PASS
web: typecheck                   PASS
web: vitest                      PASS   41 files, 508 tests
```

`npm run test:api` (full backend suite, LK_ENV=test): **1,136 collected — 1,129 passed, 7 skipped, 0 failed** (the 7
skips are `tests/evals/test_golden.py::test_golden_live`, which needs `LK_AI_MODE=live` and a key).

`npm run api:generate` — committed (`backend/openapi.json`, `apps/web/src/lib/api/schema.d.ts`).

SSE through the Next rewrite (ADR-052): dev (`next dev`, 3010 → 8010) and production (`next build` with
`LK_NEXT_BUILD_CPUS=2 NODE_OPTIONS=--max-old-space-size=2048`, `next start`) both delivered `queued` within 0.11 s,
then `running` / `done` as soon as a worker ran, with `text/event-stream`, `no-cache, no-transform`, chunked, no
compression. `/settings/ai` checked in the browser as the demo admin on `next start` (provider Demo, DPDP text, usage
with 12 Demo calls, routing and the `ai_routing` card; no console errors). All servers started for this were stopped.

No e2e (`npm run test:e2e`) run in this lane: the polling path stays available behind `NEXT_PUBLIC_LK_ASSISTANT_SSE=0`
until the integrator's e2e run proves the SSE path in the browser.
