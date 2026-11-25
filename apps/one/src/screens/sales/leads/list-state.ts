/**
 * URL search params <-> the leads list state. Plain module (no "use client"): the server page parses its search
 * params with it and the client list builds its links. Anything unknown falls back to the default.
 */

import type { Interest, LeadQuery, LeadStage, Priority, Temperature } from "~/data/leads";
import { LEADS_PAGE_SIZE } from "~/data/leads";
import { INTERESTS, LEAD_STAGES, PRIORITIES, TEMPERATURES } from "./labels";

type Search = Record<string, string | string[] | undefined>;
const first = (value: string | string[] | undefined) => (Array.isArray(value) ? value[0] : value);
const all = (value: string | string[] | undefined) => (Array.isArray(value) ? value : value ? value.split(",") : []);

export type FollowUpFilter = "overdue" | "today" | "week";
export type LeadSort = "name" | "follow_up" | "recent";

export interface LeadListState {
  q: string;
  stages: LeadStage[];
  source: string | null;
  interest: Interest | null;
  priority: Priority | null;
  temperature: Temperature | null;
  follow_up: FollowUpFilter | null;
  mine: boolean;
  sort: LeadSort;
  offset: number;
}

export const DEFAULT_LEAD_STATE: LeadListState = {
  q: "",
  stages: [],
  source: null,
  interest: null,
  priority: null,
  temperature: null,
  follow_up: null,
  mine: false,
  sort: "follow_up",
  offset: 0,
};

const pick = <T extends string>(options: readonly T[], value: string | undefined): T | null =>
  options.find((option) => option === value) ?? null;

export function leadListStateFrom(search: Search): LeadListState {
  const stages = LEAD_STAGES.filter((stage) => all(search.stage).includes(stage));
  const rawSource = (first(search.source) ?? "").trim().toLowerCase();
  const rawOffset = Number.parseInt(first(search.offset) ?? "0", 10);
  return {
    q: (first(search.q) ?? "").slice(0, 200),
    stages,
    source: /^[a-z][a-z0-9_]{1,19}$/.test(rawSource) ? rawSource : null,
    interest: pick(INTERESTS, first(search.interest)),
    priority: pick(PRIORITIES, first(search.priority)),
    temperature: pick(TEMPERATURES, first(search.temperature)),
    follow_up: pick(["overdue", "today", "week"] as const, first(search.follow_up)),
    mine: first(search.mine) === "1" || first(search.mine) === "true",
    sort: pick(["name", "follow_up", "recent"] as const, first(search.sort)) ?? DEFAULT_LEAD_STATE.sort,
    offset: Number.isFinite(rawOffset) && rawOffset > 0 ? rawOffset - (rawOffset % LEADS_PAGE_SIZE) : 0,
  };
}

/** The list URL; `status=prospect` keeps the Leads view of /sales/parties. */
export function leadListHref(state: Partial<LeadListState>): string {
  const query = new URLSearchParams({ status: "prospect" });
  if (state.q?.trim()) query.set("q", state.q.trim());
  if (state.stages && state.stages.length > 0) query.set("stage", state.stages.join(","));
  if (state.source) query.set("source", state.source);
  if (state.interest) query.set("interest", state.interest);
  if (state.priority) query.set("priority", state.priority);
  if (state.temperature) query.set("temperature", state.temperature);
  if (state.follow_up) query.set("follow_up", state.follow_up);
  if (state.mine) query.set("mine", "1");
  if (state.sort && state.sort !== DEFAULT_LEAD_STATE.sort) query.set("sort", state.sort);
  if (state.offset) query.set("offset", String(state.offset));
  return `/sales/parties?${query.toString()}`;
}

export function leadListKey(state: LeadListState): string {
  return leadListHref(state);
}

/** The API query for one state; `mine` needs the signed-in user's id. */
export function leadQueryOf(state: LeadListState, userId: string | null): LeadQuery {
  return {
    q: state.q,
    lead_stage: state.stages,
    lead_source: state.source,
    interest: state.interest,
    priority: state.priority,
    temperature: state.temperature,
    follow_up: state.follow_up,
    owner_user_id: state.mine ? userId : null,
    sort: state.sort,
    offset: state.offset,
  };
}

export function hasLeadFilters(state: LeadListState): boolean {
  return Boolean(
    state.q || state.stages.length || state.source || state.interest || state.priority || state.temperature || state.follow_up || state.mine,
  );
}
