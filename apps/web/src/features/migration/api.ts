/**
 * Migration and backup API (backend/app/modules/migration/router.py), typed from the generated schema:
 * - migration_list_migration_runs          GET  /api/v1/migration/runs                          (migration.run.read, MFA)
 * - migration_get_migration_run            GET  /api/v1/migration/runs/{run_id}
 * - migration_list_migration_issues        GET  /api/v1/migration/runs/{run_id}/issues
 * - migration_get_migration_issue_facets   GET  /api/v1/migration/runs/{run_id}/issue-facets
 * - migration_get_migration_issues_csv     GET  /api/v1/migration/runs/{run_id}/issues.csv      (a download link)
 * - migration_list_party_candidates        GET  /api/v1/migration/party-candidates
 * - migration_decide_party_candidate       POST /api/v1/migration/party-candidates/{id}/decision (migration.party_candidate.update)
 * - migration_list_opening_balance_batches GET  /api/v1/migration/opening-balance-batches
 * - system_get_backup_facts                GET  /api/v1/system/backups                           (system.backup.read, MFA)
 */

import { api, unwrap, type ApiClient } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

type Schemas = components["schemas"];
export type RunSummary = Schemas["MigrationRunSummary"];
export type RunDetail = Schemas["MigrationRunDetail"];
export type Issue = Schemas["MigrationIssueRead"];
export type IssueFacets = Schemas["IssueFacets"];
export type Candidate = Schemas["CandidateRead"];
export type CandidateDecision = Schemas["CandidateDecision"];
export type OpeningBatch = Schemas["OpeningBatchRead"];
export type BackupFacts = Schemas["BackupFacts"];
export type Backup = Schemas["BackupRead"];
export type IssueSeverity = Schemas["IssueSeverity"];
export type CandidateStatus = Schemas["CandidateStatus"];
export type Page<T> = { items: T[]; total: number; limit: number; offset: number };

export const MIGRATION_PATH = "/api/v1/migration";
export const PAGE_SIZE = 25;
export const ISSUE_SEVERITIES: readonly IssueSeverity[] = ["quarantine", "error", "warning", "info"];
export const CANDIDATE_STATUSES: readonly CandidateStatus[] = ["proposed", "linked", "new_party", "rejected"];

export interface IssueFilters {
  severity: IssueSeverity | null;
  entity: string | null;
  code: string | null;
  offset: number;
}

export function fetchRuns(offset: number, signal?: AbortSignal, client: ApiClient = api): Promise<Page<RunSummary>> {
  return unwrap(client.GET("/api/v1/migration/runs", { params: { query: { limit: PAGE_SIZE, offset } }, signal }));
}

export function fetchRun(runId: string, signal?: AbortSignal, client: ApiClient = api): Promise<RunDetail> {
  return unwrap(client.GET("/api/v1/migration/runs/{run_id}", { params: { path: { run_id: runId } }, signal }));
}

export function fetchIssues(runId: string, filters: IssueFilters, signal?: AbortSignal, client: ApiClient = api): Promise<Page<Issue>> {
  return unwrap(
    client.GET("/api/v1/migration/runs/{run_id}/issues", {
      params: {
        path: { run_id: runId },
        query: {
          severity: filters.severity ?? undefined,
          entity: filters.entity ?? undefined,
          code: filters.code ?? undefined,
          limit: PAGE_SIZE,
          offset: filters.offset,
        },
      },
      signal,
    }),
  );
}

export function fetchIssueFacets(runId: string, signal?: AbortSignal, client: ApiClient = api): Promise<IssueFacets> {
  return unwrap(client.GET("/api/v1/migration/runs/{run_id}/issue-facets", { params: { path: { run_id: runId } }, signal }));
}

export function issuesCsvHref(runId: string): string {
  return `${MIGRATION_PATH}/runs/${encodeURIComponent(runId)}/issues.csv`;
}

export function fetchCandidates(status: CandidateStatus | null, offset: number, signal?: AbortSignal, client: ApiClient = api): Promise<Page<Candidate>> {
  return unwrap(
    client.GET("/api/v1/migration/party-candidates", { params: { query: { status: status ?? undefined, limit: PAGE_SIZE, offset } }, signal }),
  );
}

export function decideCandidate(
  candidate: Pick<Candidate, "id" | "version">,
  decision: CandidateDecision,
  partyId: string | null,
  client: ApiClient = api,
): Promise<Candidate> {
  return unwrap(
    client.POST("/api/v1/migration/party-candidates/{candidate_id}/decision", {
      params: { path: { candidate_id: candidate.id } },
      body: { expected_version: candidate.version, decision, party_id: partyId },
    }),
  );
}

export function fetchOpeningBatches(signal?: AbortSignal, client: ApiClient = api): Promise<Page<OpeningBatch>> {
  return unwrap(client.GET("/api/v1/migration/opening-balance-batches", { params: { query: { limit: PAGE_SIZE, offset: 0 } }, signal }));
}

export function fetchBackupFacts(signal?: AbortSignal, client: ApiClient = api): Promise<BackupFacts> {
  return unwrap(client.GET("/api/v1/system/backups", { signal }));
}

/** Route parameters are ids; anything else is treated as not found. */
export function parseRunId(raw: string | undefined): string | null {
  return raw && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(raw) ? raw.toLowerCase() : null;
}

export function issueFiltersFrom(search: Record<string, string | string[] | undefined>): IssueFilters {
  const one = (key: string) => (typeof search[key] === "string" ? (search[key] as string).slice(0, 60) : null);
  const severity = one("severity");
  const offset = Number.parseInt(one("offset") ?? "0", 10);
  return {
    severity: ISSUE_SEVERITIES.includes(severity as IssueSeverity) ? (severity as IssueSeverity) : null,
    entity: one("entity") && /^[a-z_]+$/.test(one("entity")!) ? one("entity") : null,
    code: one("code") && /^[A-Z_]+$/.test(one("code")!) ? one("code") : null,
    offset: Number.isFinite(offset) && offset > 0 ? offset - (offset % PAGE_SIZE) : 0,
  };
}

export function issueFiltersHref(runId: string, filters: IssueFilters): string {
  const query = new URLSearchParams();
  if (filters.severity) query.set("severity", filters.severity);
  if (filters.entity) query.set("entity", filters.entity);
  if (filters.code) query.set("code", filters.code);
  if (filters.offset) query.set("offset", String(filters.offset));
  const text = query.toString();
  return `/settings/migration/runs/${runId}${text ? `?${text}` : ""}#issues`;
}
