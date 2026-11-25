"use client";

/**
 * Data hooks for Settings: company, reference data, quotation defaults, FX, customer types,
 * lookups, imports, migration, backups and the audit log. Every call goes through the old app's
 * API modules and reuses its query keys, so the caches of both apps stay interchangeable.
 * Rates and totals stay decimal strings.
 */

import { useQuery } from "@tanstack/react-query";
import { fetchLookups, fetchLookupTypes } from "@/features/catalogue/api";
import type { LookupListState } from "@/features/catalogue/lookup-state";
import {
  fetchDemoReset,
  fetchIssues as fetchImportIssues,
  fetchJob,
  fetchJobs,
  fetchPreview,
  fetchRollbackPlan,
  fetchRows,
  fetchTypes,
  isBusy,
} from "@/features/imports/api";
import {
  fetchBackupFacts,
  fetchCandidates,
  fetchIssueFacets,
  fetchIssues as fetchRunIssues,
  fetchOpeningBatches,
  fetchRun,
  fetchRuns,
  type CandidateStatus,
  type IssueFilters,
} from "@/features/migration/api";
import { fetchCustomerTypes } from "@/features/parties/customer-types-api";
import { fetchFxPolicy, fetchFxRates } from "@/features/pricing/api";
import { auditSearch, fetchAuditEntries, fetchCurrencies, fetchMyCalendar, fetchSettingRevisions, fetchSettings, fetchUoms } from "@/features/settings/api";
import { auditQueryFrom, type AuditListState } from "@/features/settings/list-state";
import { api, requestUntyped, type ApiClient } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";

// ---- permission keys (the same ones the old screens check) ----

export const AUDIT_READ = "audit.log.read";
export const CALENDAR_READ = "org.calendar.read";
export const CUSTOMERS_READ = "parties.party.read";
export const CUSTOMER_TYPE_MANAGE = "parties.customer_type.manage";
export const FX_READ = "pricing.fx_rate.read";
export const FX_CREATE = "pricing.fx_rate.create";
export const LOOKUPS_READ = "catalogue.lookup.read";
export const QUOTATIONS_READ = "sales.quote.read";
export const IMPORTS_READ = "imports.job.read";
export const IMPORTS_RUN = "imports.job.run";
export const DEMO_DATA_DELETE = "system.demo_data.delete";
export const MIGRATION_READ = "migration.run.read";
export const CANDIDATE_UPDATE = "migration.party_candidate.update";
export const BACKUP_READ = "system.backup.read";

/** Company settings are readable by anyone holding an `org.*` permission; the server filters the list. */
export function hasOrgPermission(permissionKeys: ReadonlySet<string>): boolean {
  for (const key of permissionKeys) if (key.startsWith("org.")) return true;
  return false;
}

// ---- company settings and reference data ----

export function useCompanySettings(enabled = true) {
  return useQuery({ queryKey: queryKeys.org.settings(), queryFn: ({ signal }) => fetchSettings(signal), enabled });
}

export function useSettingRevisions(key: string) {
  return useQuery({ queryKey: queryKeys.org.settingRevisions(key), queryFn: ({ signal }) => fetchSettingRevisions(key, signal) });
}

export function useCurrencies(enabled = true) {
  return useQuery({ queryKey: queryKeys.org.currencies(), queryFn: ({ signal }) => fetchCurrencies(signal), enabled });
}

export function useUoms(enabled = true) {
  return useQuery({ queryKey: queryKeys.org.uoms(), queryFn: ({ signal }) => fetchUoms(signal), enabled });
}

export function useMyCalendar(enabled = true) {
  return useQuery({ queryKey: queryKeys.org.calendar(), queryFn: ({ signal }) => fetchMyCalendar(signal), enabled });
}

// ---- audit log ----

/** The key the server page prefetches under; dated ranges depend on the person's time zone. */
export function auditQueryKey(state: AuditListState, timeZone: string) {
  return queryKeys.audit.entries(Object.fromEntries(auditSearch(auditQueryFrom(state, timeZone)).entries()));
}

export function useAuditEntries(state: AuditListState, timeZone: string, enabled = true) {
  return useQuery({
    queryKey: auditQueryKey(state, timeZone),
    queryFn: ({ signal }) => fetchAuditEntries(auditQueryFrom(state, timeZone), signal),
    enabled,
  });
}

// ---- customer types, FX, lookups ----

export function useCustomerTypes(enabled = true) {
  return useQuery({ queryKey: queryKeys.parties.customerTypes(), queryFn: ({ signal }) => fetchCustomerTypes(signal), enabled });
}

export function useFxRates(enabled = true) {
  return useQuery({ queryKey: queryKeys.pricing.fxRates({}), queryFn: ({ signal }) => fetchFxRates({}, signal), enabled });
}

export function useFxPolicy(enabled = true) {
  return useQuery({ queryKey: queryKeys.pricing.fxPolicy(), queryFn: ({ signal }) => fetchFxPolicy(signal), enabled });
}

export function useLookupTypes(enabled = true) {
  return useQuery({ queryKey: queryKeys.catalogue.lookupTypes(), queryFn: ({ signal }) => fetchLookupTypes(signal), enabled });
}

export function useLookups(state: LookupListState, enabled = true) {
  return useQuery({
    queryKey: queryKeys.catalogue.lookups({ type: state.lookupType, q: state.q, offset: state.offset }),
    queryFn: ({ signal }) => fetchLookups(state, signal),
    enabled,
  });
}

// ---- quotation settings (the old calls live inside a view file) ----

const QUOTE_SETTINGS_PATH = "/api/v1/sales/quote-settings";

export interface QuoteSettings {
  defaults: Record<string, unknown>;
  version: number;
  brands: string[];
  next_quote_numbers: Record<string, string>;
  next_custom_product_code: string;
  next_sample_number: string;
  quote_sequence_reset_policy: string;
  capabilities: Record<string, { allowed: boolean; reason_code?: string | null }>;
}

export function fetchQuoteSettings(signal?: AbortSignal, client: ApiClient = api): Promise<QuoteSettings> {
  return requestUntyped<QuoteSettings>(client, "get", QUOTE_SETTINGS_PATH, { signal });
}

/** Replaces the defaults; a 409 means someone else saved first. */
export function saveQuoteSettings(settings: Pick<QuoteSettings, "version">, defaults: Record<string, unknown>, reason: string | null, client: ApiClient = api): Promise<QuoteSettings> {
  return requestUntyped<QuoteSettings>(client, "put", QUOTE_SETTINGS_PATH, {
    body: { defaults, expected_version: settings.version, ...(reason?.trim() ? { change_reason: reason.trim() } : {}) },
  });
}

export function useQuoteSettings(enabled = true) {
  return useQuery({ queryKey: queryKeys.sales.quoteSettings(), queryFn: ({ signal }) => fetchQuoteSettings(signal), enabled });
}

// ---- imports ----

export function useImportTypes(enabled = true) {
  return useQuery({ queryKey: queryKeys.imports.types(), queryFn: ({ signal }) => fetchTypes(signal), enabled });
}

export function useImportJobs(importType: string | null, offset: number, enabled = true) {
  return useQuery({
    queryKey: queryKeys.imports.jobs({ import_type: importType, offset }),
    queryFn: ({ signal }) => fetchJobs({ importType, status: null, offset }, signal),
    enabled,
  });
}

/** One import; polled every second while the server is checking or writing rows. */
export function useImportJob(jobId: string) {
  return useQuery({
    queryKey: queryKeys.imports.job(jobId),
    queryFn: ({ signal }) => fetchJob(jobId, signal),
    refetchInterval: (query) => (query.state.data && isBusy(query.state.data) ? 1000 : false),
  });
}

export function useImportPreview(jobId: string) {
  return useQuery({ queryKey: queryKeys.imports.preview(jobId), queryFn: ({ signal }) => fetchPreview(jobId, signal) });
}

export function useImportIssues(jobId: string, severity: string | null, offset: number) {
  return useQuery({
    queryKey: queryKeys.imports.issues(jobId, { severity, offset }),
    queryFn: ({ signal }) => fetchImportIssues(jobId, { severity, offset }, signal),
  });
}

export function useImportRows(jobId: string, status: string | null, offset: number) {
  return useQuery({
    queryKey: queryKeys.imports.rows(jobId, { status, offset }),
    queryFn: ({ signal }) => fetchRows(jobId, { status, offset }, signal),
  });
}

export function useRollbackPlan(jobId: string) {
  return useQuery({ queryKey: ["imports", "rollback-plan", jobId], queryFn: () => fetchRollbackPlan(jobId) });
}

export function useDemoReset(enabled = true) {
  return useQuery({ queryKey: queryKeys.imports.demoReset(), queryFn: ({ signal }) => fetchDemoReset(signal), enabled });
}

// ---- migration and backups (reads the server may ask a second factor for) ----

export function useMigrationRuns(offset: number, enabled = true) {
  return useQuery({ queryKey: queryKeys.migration.runs(offset), queryFn: ({ signal }) => fetchRuns(offset, signal), enabled });
}

export function useMigrationRun(runId: string | null, enabled = true) {
  return useQuery({
    queryKey: queryKeys.migration.run(runId ?? "none"),
    queryFn: ({ signal }) => fetchRun(runId!, signal),
    enabled: enabled && runId !== null,
  });
}

export function useRunIssues(runId: string, filters: IssueFilters, enabled = true) {
  return useQuery({
    queryKey: queryKeys.migration.issues(runId, { ...filters }),
    queryFn: ({ signal }) => fetchRunIssues(runId, filters, signal),
    enabled,
  });
}

export function useRunIssueFacets(runId: string, enabled = true) {
  return useQuery({ queryKey: queryKeys.migration.facets(runId), queryFn: ({ signal }) => fetchIssueFacets(runId, signal), enabled });
}

export function useCandidates(status: CandidateStatus | null, offset: number, enabled = true) {
  return useQuery({
    queryKey: queryKeys.migration.candidates({ status, offset }),
    queryFn: ({ signal }) => fetchCandidates(status, offset, signal),
    enabled,
  });
}

export function useOpeningBatches(enabled = true) {
  return useQuery({ queryKey: queryKeys.migration.opening(), queryFn: ({ signal }) => fetchOpeningBatches(signal), enabled });
}

export function useBackupFacts(enabled = true) {
  return useQuery({ queryKey: queryKeys.migration.backups(), queryFn: ({ signal }) => fetchBackupFacts(signal), enabled });
}
