/** URL state for this screen: a plain module (no "use client"), so its server page can parse search params. */

export const PAGE_SIZE = 20;

export interface SearchPageState {
  q: string;
  /** one resource type to page through ("See all" of a group), or null for every group */
  type: string | null;
  offset: number;
}

export function searchPageStateFrom(params: Record<string, string | string[] | undefined>): SearchPageState {
  const one = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v) ?? "";
  const raw = one(params.type) || one(params.types);
  const type = /^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$/.test(raw) ? raw : null;
  const offset = Number.parseInt(one(params.offset) || "0", 10);
  return {
    q: one(params.q).trim().slice(0, 200),
    type,
    offset: type && Number.isFinite(offset) && offset > 0 ? Math.min(offset, 200) : 0,
  };
}

export function searchPageHref(state: SearchPageState): string {
  const p = new URLSearchParams();
  if (state.q) p.set("q", state.q);
  if (state.type) p.set("type", state.type);
  if (state.type && state.offset) p.set("offset", String(state.offset));
  return `/search?${p.toString()}`;
}
