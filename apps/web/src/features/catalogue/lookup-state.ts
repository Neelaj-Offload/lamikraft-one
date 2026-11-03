/** URL state for this screen: a plain module (no "use client"), so its server page can parse search params. */

type Search = Record<string, string | string[] | undefined>;
const first = (value: string | string[] | undefined) => (Array.isArray(value) ? value[0] : value);

export interface LookupListState {
  lookupType: string | null;
  q: string;
  offset: number;
}

export function lookupStateFrom(search: Search): LookupListState {
  const raw = Number.parseInt(first(search.offset) ?? "0", 10);
  return {
    lookupType: (first(search.type) ?? "").slice(0, 80) || null,
    q: (first(search.q) ?? "").slice(0, 200),
    offset: Number.isFinite(raw) && raw > 0 ? raw - (raw % 50) : 0,
  };
}

export function lookupHref(state: LookupListState): string {
  const query = new URLSearchParams();
  if (state.lookupType) query.set("type", state.lookupType);
  if (state.q.trim()) query.set("q", state.q.trim());
  if (state.offset) query.set("offset", String(state.offset));
  const search = query.toString();
  return search ? `/settings/lookups?${search}` : "/settings/lookups";
}
