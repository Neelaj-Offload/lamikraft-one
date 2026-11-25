/**
 * The lead pipeline API (backend/app/modules/parties/router.py, spec 2026-11-25-leads-module-design.md):
 * - GET   /api/v1/parties/parties                     list with lead filters (lead_stage[], lead_source, interest,
 *                                                     priority, temperature, follow_up, sort)
 * - GET   /api/v1/parties/parties/lead-summary        pipeline numbers in the caller's scope
 * - GET   /api/v1/parties/parties/{id}                 the full record incl. lead fields and capabilities
 * - POST  /api/v1/parties/parties/{id}/lead-stage      move stage (lost needs lost_reason; won is final)
 * - GET   /api/v1/parties/parties/{id}/activities      activity log, newest first (cursor)
 * - POST  /api/v1/parties/parties/{id}/activities      log a call/email/WhatsApp/meeting/visit/note
 * - GET/POST/PATCH /api/v1/parties/lead-sources        the managed list of lead sources
 * Every key lives under ["parties"], so the old app's `parties.party_changed` invalidation refreshes it too.
 */

import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { api, idempotencyHeaders, requestUntyped, type ApiClient } from "@/lib/api/client";
import { invalidationMap, queryKeys } from "@/lib/api/query-keys";
import type { components } from "@/lib/api/schema";

type S = components["schemas"];
export type LeadRow = S["PartySummary"];
export type LeadDetail = S["PartyDetail"];
export type Activity = S["ActivityRead"];
export type ActivityPage = S["PartyActivityPage"];
export type LeadSource = S["LeadSourceRead"];
export type LeadSummary = S["LeadSummary"];
export type LeadStage = NonNullable<LeadRow["lead_stage"]>;
export type Interest = S["Interest"];
export type Priority = S["Priority"];
export type Temperature = S["Temperature"];
export type ActivityKind = S["ActivityKind"];
export interface LeadPage {
  items: LeadRow[];
  total: number;
  limit: number;
  offset: number;
}

const PARTIES = "/api/v1/parties/parties";
const SOURCES = "/api/v1/parties/lead-sources";
export const LEADS_PAGE_SIZE = 25;
const partyPath = (id: string): `/api/v1/${string}` => `${PARTIES}/${encodeURIComponent(id)}`;

export const leadKeys = {
  list: (params: Record<string, unknown>) => ["parties", "leads", params] as const,
  detail: (id: string) => ["parties", "lead", { party_id: id }] as const,
  activities: (id: string) => ["parties", "activities", { party_id: id }] as const,
  summary: () => ["parties", "lead-summary"] as const,
  sources: () => ["parties", "lead-sources"] as const,
};

/** What a lead command refreshes: every party view, Today and the task inbox (follow-up tasks). */
export const LEAD_INVALIDATE = [...invalidationMap["parties.party_changed"], queryKeys.tasks.all(), queryKeys.briefings.today()] as const;

// ---- reads ----------------------------------------------------------------------------------------------------
export interface LeadQuery {
  q?: string;
  lead_stage?: LeadStage[];
  lead_source?: string | null;
  interest?: Interest | null;
  priority?: Priority | null;
  temperature?: Temperature | null;
  follow_up?: "overdue" | "today" | "week" | null;
  owner_user_id?: string | null;
  sort?: "name" | "follow_up" | "recent";
  offset?: number;
}

export function leadQueryParams(q: LeadQuery): Record<string, string | number | boolean | string[] | undefined> {
  return {
    status: "prospect",
    role: "customer",
    q: q.q?.trim() || undefined,
    lead_stage: q.lead_stage && q.lead_stage.length > 0 ? q.lead_stage : undefined,
    lead_source: q.lead_source || undefined,
    interest: q.interest || undefined,
    priority: q.priority || undefined,
    temperature: q.temperature || undefined,
    follow_up: q.follow_up || undefined,
    owner_user_id: q.owner_user_id || undefined,
    sort: q.sort && q.sort !== "name" ? q.sort : undefined,
    offset: q.offset ?? 0,
    limit: LEADS_PAGE_SIZE,
  };
}

export async function fetchLeads(q: LeadQuery, signal?: AbortSignal, client: ApiClient = api): Promise<LeadPage> {
  // openapi-fetch sends an array as repeated parameters (lead_stage=new&lead_stage=contacted), as FastAPI expects
  const query = leadQueryParams(q) as unknown as Record<string, string | number | boolean | undefined>;
  return requestUntyped<LeadPage>(client, "get", PARTIES, { params: { query }, signal });
}

export function useLeads(q: LeadQuery) {
  const params = leadQueryParams(q);
  return useQuery({ queryKey: leadKeys.list(params), queryFn: ({ signal }) => fetchLeads(q, signal) });
}

export async function fetchLeadDetail(id: string, signal?: AbortSignal, client: ApiClient = api): Promise<LeadDetail> {
  return requestUntyped<LeadDetail>(client, "get", partyPath(id), { signal });
}

export function useLeadDetail(id: string, enabled = true) {
  return useQuery({ queryKey: leadKeys.detail(id), queryFn: ({ signal }) => fetchLeadDetail(id, signal), enabled });
}

export function useLeadSummary(enabled = true) {
  return useQuery({
    queryKey: leadKeys.summary(),
    queryFn: ({ signal }) => requestUntyped<LeadSummary>(api, "get", `${PARTIES}/lead-summary`, { signal }),
    enabled,
  });
}

export function useActivities(id: string, enabled = true) {
  return useInfiniteQuery({
    queryKey: leadKeys.activities(id),
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) =>
      requestUntyped<ActivityPage>(api, "get", `${partyPath(id)}/activities`, {
        params: { query: { limit: 20, cursor: pageParam ?? undefined } },
        signal,
      }),
    getNextPageParam: (last) => last.next_cursor ?? null,
    enabled,
  });
}

export function useLeadSources(enabled = true) {
  return useQuery({
    queryKey: leadKeys.sources(),
    queryFn: ({ signal }) => requestUntyped<LeadSource[]>(api, "get", SOURCES, { signal }),
    enabled,
    staleTime: 5 * 60_000,
  });
}

// ---- commands -------------------------------------------------------------------------------------------------
export interface ActivityInput {
  kind: ActivityKind;
  occurred_at?: string | null;
  outcome?: string | null;
  notes?: string | null;
  next_follow_up_on?: string | null;
}

export function logActivity(id: string, body: ActivityInput, idempotencyKey: string, client: ApiClient = api): Promise<Activity> {
  return requestUntyped<Activity>(client, "post", `${partyPath(id)}/activities`, { body, headers: idempotencyHeaders(idempotencyKey) });
}

export function changeLeadStage(
  id: string,
  body: { expected_version: number; stage: LeadStage; lost_reason?: string | null },
  idempotencyKey: string,
  client: ApiClient = api,
): Promise<LeadDetail> {
  return requestUntyped<LeadDetail>(client, "post", `${partyPath(id)}/lead-stage`, { body, headers: idempotencyHeaders(idempotencyKey) });
}

export interface LeadFieldsInput {
  expected_version: number;
  website?: string | null;
  lead_source?: string | null;
  interests?: Interest[];
  requirement?: string | null;
  first_contact_on?: string | null;
  priority?: Priority;
  temperature?: Temperature;
}

export function updateLeadFields(id: string, body: LeadFieldsInput, idempotencyKey: string, client: ApiClient = api): Promise<LeadDetail> {
  return requestUntyped<LeadDetail>(client, "patch", partyPath(id), { body, headers: idempotencyHeaders(idempotencyKey) });
}

export function createLeadSource(
  body: { code: string; label: string; display_order?: number },
  client: ApiClient = api,
): Promise<LeadSource> {
  return requestUntyped<LeadSource>(client, "post", SOURCES, { body });
}

export function updateLeadSource(
  id: string,
  body: { expected_version: number; label?: string; display_order?: number; is_active?: boolean },
  client: ApiClient = api,
): Promise<LeadSource> {
  return requestUntyped<LeadSource>(client, "patch", `${SOURCES}/${encodeURIComponent(id)}`, { body });
}

// ---- customer facts (module 2) ----------------------------------------------------------------------------------
export type CustomerFacts = S["CustomerFacts"];

export function useCustomerFacts(id: string, enabled = true) {
  return useQuery({
    queryKey: ["parties", "customer-facts", { party_id: id }] as const,
    queryFn: ({ signal }) => requestUntyped<CustomerFacts>(api, "get", `/api/v1/sales/customers/${encodeURIComponent(id)}/facts`, { signal }),
    enabled,
  });
}
