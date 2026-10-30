/**
 * Import workbench API adapter and wire types (INTERIM(api-generate): hand-written from
 * `backend/app/modules/imports/schemas.py` until the generated schema has these routes).
 */

import { api, requestUntyped, type ApiClient } from "@/lib/api/client";

export const IMPORTS = "/api/v1/imports";
const job = (id: string): `/api/v1/${string}` => `${IMPORTS}/jobs/${encodeURIComponent(id)}`;

export const IMPORT_TYPES = [
  "category_taxonomy",
  "products_master",
  "pricing",
  "packaging",
  "specifications",
  "media",
  "lookup_reference",
] as const;
export type ImportType = (typeof IMPORT_TYPES)[number];

export interface Capability {
  allowed: boolean;
  reason_code: string | null;
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface ImportTypeRead {
  import_type: ImportType;
  label: string;
  description: string;
  fields: { name: string; required: boolean; aliases: string[] }[];
  depends_on: ImportType[];
  dependency_status: Record<string, number>;
  template_path: string;
}

export interface JobSummary {
  id: string;
  import_type: ImportType;
  status: string;
  file_name: string;
  file_sha256: string;
  file_format: string;
  row_count: number;
  counts: Record<string, number>;
  progress: { state?: string; done?: number };
  parent_job_id: string | null;
  created_at: string;
  created_by_name: string | null;
  committed_at: string | null;
  rolled_back_at: string | null;
  path: string;
}

export interface ImportOptions {
  blank_cells: "ignore" | "clear";
  decor_float_artefact_rule: boolean;
  default_price_type: string | null;
  default_currency: string | null;
  date_order: "DMY" | "MDY";
}

export interface JobDetail extends JobSummary {
  sheet_name: string | null;
  mapping: Record<string, string | null>;
  options: ImportOptions;
  error_code: string | null;
  error_detail: string | null;
  source_file_id: string;
  source_url: string;
  report_url: string;
  version: number;
  capabilities: Record<string, Capability>;
}

export interface PreviewRead {
  headers: { index: number; original: string; normalised: string; field: string | null }[];
  rows: Record<string, string | number>[];
  total_rows: number;
  unmapped_required: string[];
  collisions: Record<string, string[]>;
  blank_required_columns: string[];
  duplicate_keys: { key: string; row_numbers: number[]; identical: boolean }[];
  same_file_jobs: string[];
}

export interface IssueRead {
  id: string;
  row_number: number | null;
  column: string | null;
  field: string | null;
  code: string;
  severity: "error" | "quarantine" | "warning" | "info";
  message: string;
  raw_value: string | null;
}

export interface RowRead {
  id: string;
  row_number: number;
  status: string;
  action: string | null;
  natural_key: string | null;
  diff: Record<string, [unknown, unknown]> | null;
  issue_codes: string[];
}

export interface RollbackPlan {
  job_id: string;
  plan_hash: string;
  reversible: number;
  blocked: number;
  already_removed: number;
  items: { seq: number; entity_table: string; entity_id: string; op: string; status: string; reason_code: string | null; detail: string | null }[];
}

export interface DemoResetPreview {
  company_name: string;
  is_demo: boolean;
  counts: Record<string, number>;
  blocking_references: Record<string, number>;
  allowed: boolean;
  reason_code: string | null;
  phrase: string;
  token: string | null;
}

export const fetchTypes = (signal?: AbortSignal, client: ApiClient = api): Promise<ImportTypeRead[]> =>
  requestUntyped(client, "get", `${IMPORTS}/types`, { signal });

export const fetchJobs = (
  params: { importType: string | null; status: string | null; offset: number },
  signal?: AbortSignal,
  client: ApiClient = api,
): Promise<Page<JobSummary>> =>
  requestUntyped(client, "get", `${IMPORTS}/jobs`, {
    params: { query: { import_type: params.importType, status: params.status, offset: params.offset, limit: 25 } },
    signal,
  });

export const fetchJob = (id: string, signal?: AbortSignal, client: ApiClient = api): Promise<JobDetail> =>
  requestUntyped(client, "get", job(id), { signal });

export const fetchPreview = (id: string, signal?: AbortSignal, client: ApiClient = api): Promise<PreviewRead> =>
  requestUntyped(client, "get", `${job(id)}/preview`, { signal });

export const fetchIssues = (
  id: string,
  params: { severity: string | null; offset: number },
  signal?: AbortSignal,
  client: ApiClient = api,
): Promise<Page<IssueRead>> =>
  requestUntyped(client, "get", `${job(id)}/issues`, { params: { query: { severity: params.severity, offset: params.offset, limit: 50 } }, signal });

export const fetchRows = (
  id: string,
  params: { status: string | null; offset: number },
  signal?: AbortSignal,
  client: ApiClient = api,
): Promise<Page<RowRead>> =>
  requestUntyped(client, "get", `${job(id)}/rows`, { params: { query: { status: params.status, offset: params.offset, limit: 50 } }, signal });

export async function startImport(importType: ImportType, file: File, client: ApiClient = api): Promise<JobDetail> {
  const form = new FormData();
  form.append("file", file);
  const stored = await requestUntyped<{ id: string }>(client, "post", "/api/v1/files", { params: { query: { purpose: "import" } }, body: form });
  return requestUntyped(client, "post", `${IMPORTS}/jobs`, { body: { import_type: importType, file_id: stored.id } });
}

export const saveMapping = (
  detail: Pick<JobDetail, "id" | "version">,
  mapping: Record<string, string | null>,
  options: ImportOptions,
  client: ApiClient = api,
): Promise<JobDetail> =>
  requestUntyped(client, "put", `${job(detail.id)}/mapping`, { body: { expected_version: detail.version, mapping, options } });

export const jobCommand = (
  detail: Pick<JobDetail, "id" | "version">,
  command: "validate" | "commit" | "cancel",
  extra: Record<string, unknown> = {},
  client: ApiClient = api,
): Promise<JobDetail> =>
  requestUntyped(client, "post", `${job(detail.id)}/${command}`, { body: { expected_version: detail.version, ...extra } });

export const recheck = (id: string, client: ApiClient = api): Promise<JobDetail> =>
  requestUntyped(client, "post", `${job(id)}/quarantine/recheck`);

export const fetchRollbackPlan = (id: string, client: ApiClient = api): Promise<RollbackPlan> =>
  requestUntyped(client, "get", `${job(id)}/rollback-plan`);

export const rollback = (id: string, mode: "all" | "reversible_only", planHash: string, client: ApiClient = api): Promise<JobDetail> =>
  requestUntyped(client, "post", `${job(id)}/rollback`, { body: { mode, plan_hash: planHash } });

export const fetchDemoReset = (signal?: AbortSignal, client: ApiClient = api): Promise<DemoResetPreview> =>
  requestUntyped(client, "get", `${IMPORTS}/demo-reset/preview`, { signal });

export const runDemoReset = (token: string, phrase: string, client: ApiClient = api): Promise<{ deleted: Record<string, number> }> =>
  requestUntyped(client, "post", `${IMPORTS}/demo-reset`, { body: { token, phrase } });

/** Where the job is in the stepper (UI-86): upload -> mapping -> validate -> review -> commit -> result. */
export type Step = "mapping" | "validating" | "review" | "committing" | "result";

export function stepOf(detail: Pick<JobDetail, "status" | "progress">): Step {
  if (detail.progress.state === "validating") return "validating";
  if (detail.progress.state === "committing" || detail.status === "committing") return "committing";
  if (detail.status === "parsed") return "mapping";
  if (detail.status === "validated" || detail.status === "commit_failed") return "review";
  return "result";
}

/** The job is still working: poll it. */
export const isBusy = (detail: Pick<JobDetail, "status" | "progress">): boolean => ["validating", "committing"].includes(stepOf(detail));

export const STATUS_LABEL: Record<string, string> = {
  parsed: "Uploaded",
  validated: "Validated",
  committing: "Committing",
  committed: "Committed",
  commit_failed: "Commit failed",
  cancelled: "Cancelled",
  rolled_back: "Rolled back",
  partially_rolled_back: "Partly rolled back",
};
