/** URL <-> the proforma invoice list. Plain module: the server page parses with it, the client list builds links. */

import { PROFORMA_PAGE_SIZE, type ProformaQuery, type ProformaStatus } from "~/data/proforma";
import { PROFORMA_STATUSES } from "./labels";

type Search = Record<string, string | string[] | undefined>;
const first = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v);

export interface ProformaListState {
  q: string;
  status: ProformaStatus | null;
  offset: number;
}

export function proformaListStateFrom(search: Search): ProformaListState {
  const rawOffset = Number.parseInt(first(search.offset) ?? "0", 10);
  return {
    q: (first(search.q) ?? "").slice(0, 200),
    status: PROFORMA_STATUSES.find((s) => s === first(search.status)) ?? null,
    offset: Number.isFinite(rawOffset) && rawOffset > 0 ? rawOffset - (rawOffset % PROFORMA_PAGE_SIZE) : 0,
  };
}

export function proformaListHref(state: Partial<ProformaListState>): string {
  const query = new URLSearchParams();
  if (state.q?.trim()) query.set("q", state.q.trim());
  if (state.status) query.set("status", state.status);
  if (state.offset) query.set("offset", String(state.offset));
  const search = query.toString();
  return search ? `/sales/proforma-invoices?${search}` : "/sales/proforma-invoices";
}

export function proformaQueryOf(state: ProformaListState): ProformaQuery {
  return { q: state.q, status: state.status, offset: state.offset };
}
