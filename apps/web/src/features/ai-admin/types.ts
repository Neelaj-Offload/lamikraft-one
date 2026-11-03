/**
 * Shapes of the AI administration and trace endpoints (INTERIM(api-generate): hand-written until the generated
 * schema is consumed here; `parse.ts` reads every response defensively):
 * - admin_get_ai_status   GET  /api/v1/admin/ai/status            (agents.ai_usage.read)
 * - admin_get_ai_usage    GET  /api/v1/admin/ai/usage?days=N      (agents.ai_usage.read)
 * - admin_verify_ai       POST /api/v1/admin/ai/verify            (system.integration.manage)
 * - agents_get_trace      GET  /api/v1/traces/{correlation_id}    (participants, audit.trace.read)
 */

export type ProviderState = "demo" | "verified" | "failing" | "not_verified" | "misconfigured";

export interface Circuit {
  state: string;
  recent_failures: number;
}

export interface ProviderStatus {
  mode: "demo" | "live";
  provider: string;
  label: string;
  state: ProviderState;
  verified_at: string | null;
  last_checked_at: string | null;
  last_error_code: string | null;
  circuit: Circuit;
  readiness: string;
}

export interface Budget {
  steps: number;
  seconds: number;
  input_tokens: number;
  max_tokens: number;
}

export interface PriceRow {
  model: string;
  input: string;
  output: string;
  cache_read: string;
  cache_write: string;
}

export interface AiStatus {
  provider: ProviderStatus;
  models: Record<string, string>;
  effort: Record<string, string>;
  budgets: Record<string, Budget>;
  quotas: Record<string, number>;
  price_currency: string;
  prices: PriceRow[];
  dpdp_text: string;
  can_manage_routing: boolean;
}

export interface WorkflowUsage {
  workflow: string;
  calls: number;
  runs: number;
  errors: number;
  refusals: number;
  p50_latency_ms: number | null;
  p95_latency_ms: number | null;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
  /** USD, estimated at report time; null when a model has no price row. */
  estimated_cost: string | null;
}

export interface ModelUsage {
  provider: string;
  model: string;
  calls: number;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
  estimated_cost: string | null;
  priced: boolean;
}

export interface AiFailure {
  at: string;
  workflow: string;
  provider: string;
  model: string;
  outcome: string;
  error_type: string | null;
  request_id: string | null;
  run_id: string | null;
  correlation_id: string | null;
}

export interface AiUsage {
  window_days: number;
  price_currency: string;
  totals: WorkflowUsage;
  by_workflow: WorkflowUsage[];
  by_model: ModelUsage[];
  failures: AiFailure[];
}

export interface TraceEntry {
  at: string;
  kind: string;
  name: string;
  status: string | null;
  ref_type: string | null;
  ref_id: string | null;
  detail: Record<string, unknown>;
}

export interface Trace {
  correlation_id: string;
  access: string;
  run_ids: string[];
  entries: TraceEntry[];
}
