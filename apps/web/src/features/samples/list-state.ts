/** URL state for this screen: a plain module (no "use client"), so its server page can parse search params. */

import { SAMPLE_STATUSES, SAMPLES_PAGE_SIZE, type SampleStatus } from "./api";

type Search = Record<string, string | string[] | undefined>;
const first = (value: string | string[] | undefined) => (Array.isArray(value) ? value[0] : value);

export interface SampleListState {
  q: string;
  status: SampleStatus | null;
  offset: number;
}

export function sampleListStateFrom(search: Search): SampleListState {
  const q = (first(search.q) ?? "").slice(0, 200);
  const status = SAMPLE_STATUSES.find((candidate) => candidate === first(search.status)) ?? null;
  const raw = Number.parseInt(first(search.offset) ?? "0", 10);
  const offset = Number.isFinite(raw) && raw > 0 ? raw - (raw % SAMPLES_PAGE_SIZE) : 0;
  return { q, status, offset };
}

export function sampleListHref(state: Partial<SampleListState>): string {
  const query = new URLSearchParams();
  if (state.q?.trim()) query.set("q", state.q.trim());
  if (state.status) query.set("status", state.status);
  if (state.offset) query.set("offset", String(state.offset));
  const search = query.toString();
  return search ? `/sales/samples?${search}` : "/sales/samples";
}
