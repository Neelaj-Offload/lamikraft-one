import { safeAppPath } from "@/lib/safe-path";
import type { RecentSearch, SearchGroup, SearchHit, SearchResponse } from "./types";

/**
 * Narrows an unknown payload to SearchResponse, dropping malformed entries. Accepts the platform search shape
 * (`groups[].hits`, `has_more`, `offset`, `unavailable_groups`, backend/app/platform/search/schemas.py) and the
 * interim `groups[].items` shape the first web lane used.
 */
export function parseSearchResponse(raw: unknown, q: string): SearchResponse {
  const body = raw !== null && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
  const groups: SearchGroup[] = [];
  for (const entry of Array.isArray(body.groups) ? body.groups : []) {
    if (entry === null || typeof entry !== "object") continue;
    const group = entry as Record<string, unknown>;
    const items: SearchHit[] = [];
    const rawHits = Array.isArray(group.hits) ? group.hits : Array.isArray(group.items) ? group.items : [];
    for (const hit of rawHits) {
      if (hit === null || typeof hit !== "object") continue;
      const h = hit as Record<string, unknown>;
      // Only same-origin, absolute app paths are navigable; anything else is dropped.
      const path = safeAppPath(h.path);
      if (typeof h.title !== "string" || path === null) continue;
      items.push({
        resource_type: typeof h.resource_type === "string" ? h.resource_type : String(group.resource_type ?? ""),
        resource_id: typeof h.resource_id === "string" ? h.resource_id : path,
        title: h.title,
        subtitle: typeof h.subtitle === "string" ? h.subtitle : null,
        path,
      });
    }
    if (items.length === 0 || typeof group.group !== "string") continue;
    const offset = typeof group.offset === "number" ? group.offset : 0;
    groups.push({
      group: group.group,
      resource_type: typeof group.resource_type === "string" ? group.resource_type : "",
      total: typeof group.total === "number" ? group.total : offset + items.length + (group.has_more === true ? 1 : 0),
      items,
      hasMore: group.has_more === true,
      offset,
    });
  }
  const unavailable = Array.isArray(body.unavailable_groups) ? body.unavailable_groups.filter((g): g is string => typeof g === "string") : [];
  return {
    q: typeof body.query === "string" ? body.query : typeof body.q === "string" ? body.q : q,
    groups,
    ...(unavailable.length ? { unavailable } : {}),
  };
}

export function parseRecent(raw: unknown): RecentSearch[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((r): r is Record<string, unknown> => r !== null && typeof r === "object")
    .filter((r) => typeof r.id === "string" && typeof r.query === "string")
    .map((r) => ({ id: String(r.id), query: String(r.query), searched_at: typeof r.searched_at === "string" ? r.searched_at : "" }));
}
