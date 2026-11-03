/**
 * Runtime readers for the AI administration and trace responses (see types.ts). Required fields are checked;
 * decimals stay strings; unknown values are dropped rather than guessed. Plain module: server pages may import it.
 */

import type { AiFailure, AiStatus, AiUsage, Budget, ModelUsage, PriceRow, ProviderState, ProviderStatus, Trace, TraceEntry, WorkflowUsage } from "./types";

export class AiShapeError extends Error {
  override readonly name = "AiShapeError";
}

type Obj = Record<string, unknown>;
const isObject = (value: unknown): value is Obj => value !== null && typeof value === "object" && !Array.isArray(value);
const str = (value: unknown): string | null => (typeof value === "string" && value !== "" ? value : null);
const int = (value: unknown): number => (typeof value === "number" && Number.isFinite(value) ? Math.trunc(value) : 0);
const intOrNull = (value: unknown): number | null => (typeof value === "number" && Number.isFinite(value) ? Math.trunc(value) : null);
const arr = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);
const DECIMAL = /^-?\d+(\.\d+)?$/;
const decimal = (value: unknown): string | null => (typeof value === "string" && DECIMAL.test(value) ? value : null);

const PROVIDER_STATES: readonly ProviderState[] = ["demo", "verified", "failing", "not_verified", "misconfigured"];
/** UUIDv7-like or any request id the server minted: letters, digits and . _ : - only. */
const CORRELATION = /^[A-Za-z0-9._:-]{8,64}$/;

function fail(what: string): never {
  throw new AiShapeError(`The AI response could not be read (${what}).`);
}

function stringMap(value: unknown): Record<string, string> {
  const out: Record<string, string> = {};
  if (isObject(value)) for (const [key, entry] of Object.entries(value)) if (typeof entry === "string") out[key] = entry;
  return out;
}

function provider(value: unknown): ProviderStatus {
  if (!isObject(value)) fail("provider");
  const state = PROVIDER_STATES.find((s) => s === value.state);
  if (!state) fail("provider state");
  const circuit = isObject(value.circuit) ? value.circuit : {};
  return {
    mode: value.mode === "live" ? "live" : "demo",
    provider: str(value.provider) ?? "demo",
    label: str(value.label) ?? "Demo",
    state,
    verified_at: str(value.verified_at),
    last_checked_at: str(value.last_checked_at),
    last_error_code: str(value.last_error_code),
    circuit: { state: str(circuit.state) ?? "closed", recent_failures: int(circuit.recent_failures) },
    readiness: str(value.readiness) ?? "ok",
  };
}

function budget(value: unknown): Budget | null {
  if (!isObject(value)) return null;
  return { steps: int(value.steps), seconds: int(value.seconds), input_tokens: int(value.input_tokens), max_tokens: int(value.max_tokens) };
}

function price(value: unknown): PriceRow | null {
  if (!isObject(value) || !str(value.model)) return null;
  return {
    model: str(value.model)!,
    input: decimal(value.input) ?? "0",
    output: decimal(value.output) ?? "0",
    cache_read: decimal(value.cache_read) ?? "0",
    cache_write: decimal(value.cache_write) ?? "0",
  };
}

export function parseAiStatus(raw: unknown): AiStatus {
  if (!isObject(raw)) fail("status");
  const budgets: Record<string, Budget> = {};
  if (isObject(raw.budgets)) for (const [key, value] of Object.entries(raw.budgets)) { const b = budget(value); if (b) budgets[key] = b; }
  const quotas: Record<string, number> = {};
  if (isObject(raw.quotas)) for (const [key, value] of Object.entries(raw.quotas)) if (typeof value === "number") quotas[key] = Math.trunc(value);
  return {
    provider: provider(raw.provider),
    models: stringMap(raw.models),
    effort: stringMap(raw.effort),
    budgets,
    quotas,
    price_currency: str(raw.price_currency) ?? "USD",
    prices: arr(raw.prices).map(price).filter((row): row is PriceRow => row !== null),
    dpdp_text: str(raw.dpdp_text) ?? "",
    can_manage_routing: raw.can_manage_routing === true,
  };
}

function workflow(value: unknown): WorkflowUsage | null {
  if (!isObject(value) || !str(value.workflow)) return null;
  return {
    workflow: str(value.workflow)!,
    calls: int(value.calls),
    runs: int(value.runs),
    errors: int(value.errors),
    refusals: int(value.refusals),
    p50_latency_ms: intOrNull(value.p50_latency_ms),
    p95_latency_ms: intOrNull(value.p95_latency_ms),
    input_tokens: int(value.input_tokens),
    output_tokens: int(value.output_tokens),
    cache_read_tokens: int(value.cache_read_tokens),
    cache_write_tokens: int(value.cache_write_tokens),
    estimated_cost: decimal(value.estimated_cost),
  };
}

function modelUsage(value: unknown): ModelUsage | null {
  if (!isObject(value) || !str(value.model)) return null;
  return {
    provider: str(value.provider) ?? "demo",
    model: str(value.model)!,
    calls: int(value.calls),
    input_tokens: int(value.input_tokens),
    output_tokens: int(value.output_tokens),
    cache_read_tokens: int(value.cache_read_tokens),
    cache_write_tokens: int(value.cache_write_tokens),
    estimated_cost: decimal(value.estimated_cost),
    priced: value.priced === true,
  };
}

function failure(value: unknown): AiFailure | null {
  if (!isObject(value) || !str(value.at)) return null;
  const correlation = str(value.correlation_id);
  return {
    at: str(value.at)!,
    workflow: str(value.workflow) ?? "",
    provider: str(value.provider) ?? "",
    model: str(value.model) ?? "",
    outcome: str(value.outcome) ?? "error",
    error_type: str(value.error_type),
    request_id: str(value.request_id),
    run_id: str(value.run_id),
    correlation_id: correlation && CORRELATION.test(correlation) ? correlation : null,
  };
}

export function parseAiUsage(raw: unknown): AiUsage {
  if (!isObject(raw)) fail("usage");
  const totals = workflow(raw.totals);
  if (!totals) fail("usage totals");
  return {
    window_days: int(raw.window_days) || 7,
    price_currency: str(raw.price_currency) ?? "USD",
    totals,
    by_workflow: arr(raw.by_workflow).map(workflow).filter((row): row is WorkflowUsage => row !== null),
    by_model: arr(raw.by_model).map(modelUsage).filter((row): row is ModelUsage => row !== null),
    failures: arr(raw.failures).map(failure).filter((row): row is AiFailure => row !== null),
  };
}

function entry(value: unknown): TraceEntry | null {
  if (!isObject(value) || !str(value.at) || !str(value.kind) || !str(value.name)) return null;
  return {
    at: str(value.at)!,
    kind: str(value.kind)!,
    name: str(value.name)!,
    status: str(value.status),
    ref_type: str(value.ref_type),
    ref_id: str(value.ref_id),
    detail: isObject(value.detail) ? value.detail : {},
  };
}

export function parseTrace(raw: unknown): Trace {
  if (!isObject(raw) || !str(raw.correlation_id)) fail("trace");
  return {
    correlation_id: str(raw.correlation_id)!,
    access: str(raw.access) ?? "participant",
    run_ids: arr(raw.run_ids).filter((id): id is string => typeof id === "string"),
    entries: arr(raw.entries).map(entry).filter((row): row is TraceEntry => row !== null),
  };
}

/** The trace route parameter, or null when it cannot be a correlation id (the page then shows Not available). */
export function parseCorrelationId(value: string | string[] | undefined): string | null {
  const raw = Array.isArray(value) ? value[0] : value;
  if (!raw) return null;
  const decoded = decodeURIComponent(raw);
  return CORRELATION.test(decoded) ? decoded : null;
}

/** Error rate in tenths of a percent from integer counts (no float money; nothing estimated client-side). */
export function errorRateTenths(errors: number, calls: number): number | null {
  return calls > 0 ? Math.round((errors * 1000) / calls) : null;
}

/** The usage window from `?days=`: one of the offered windows, else 7. */
export function parseUsageDays(value: string | string[] | undefined, allowed: readonly number[] = [1, 7, 30]): number {
  const raw = Array.isArray(value) ? value[0] : value;
  const days = Number.parseInt(raw ?? "", 10);
  return allowed.includes(days) ? days : 7;
}
