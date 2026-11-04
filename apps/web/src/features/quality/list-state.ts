/** URL state of /operations/quality (a plain module: server pages read it, client screens build links). */

type Params = Record<string, string | string[] | undefined>;

export interface InspectionListState {
  status: string | null;
  offset: number;
}

export function inspectionStateFrom(params: Params): InspectionListState {
  const one = (k: string) => (Array.isArray(params[k]) ? params[k]?.[0] : params[k]) as string | undefined;
  const raw = one("offset") ?? "";
  // pending first: the default view is what still needs inspecting
  const status = one("status");
  return { status: status === "all" ? null : (status ?? "pending"), offset: /^\d{1,7}$/.test(raw) ? Number.parseInt(raw, 10) : 0 };
}

export function inspectionListHref(state: InspectionListState): string {
  const search = new URLSearchParams();
  search.set("status", state.status ?? "all");
  if (state.offset) search.set("offset", String(state.offset));
  return `/operations/quality?${search.toString()}`;
}
