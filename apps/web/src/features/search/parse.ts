import type { SearchGroup, SearchHit, SearchResponse } from "./types";

/** Narrows an unknown payload to SearchResponse, dropping malformed entries. */
export function parseSearchResponse(raw: unknown, q: string): SearchResponse {
  const body = raw !== null && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
  const groups: SearchGroup[] = [];
  for (const entry of Array.isArray(body.groups) ? body.groups : []) {
    if (entry === null || typeof entry !== "object") continue;
    const group = entry as Record<string, unknown>;
    const items: SearchHit[] = [];
    for (const hit of Array.isArray(group.items) ? group.items : []) {
      if (hit === null || typeof hit !== "object") continue;
      const h = hit as Record<string, unknown>;
      // Only same-origin, absolute app paths are navigable; anything else is dropped.
      if (typeof h.title !== "string" || typeof h.path !== "string" || !h.path.startsWith("/") || h.path.startsWith("//")) continue;
      items.push({
        resource_type: typeof h.resource_type === "string" ? h.resource_type : String(group.resource_type ?? ""),
        resource_id: typeof h.resource_id === "string" ? h.resource_id : h.path,
        title: h.title,
        subtitle: typeof h.subtitle === "string" ? h.subtitle : null,
        path: h.path,
      });
    }
    if (items.length === 0 || typeof group.group !== "string") continue;
    groups.push({
      group: group.group,
      resource_type: typeof group.resource_type === "string" ? group.resource_type : "",
      total: typeof group.total === "number" ? group.total : items.length,
      items,
    });
  }
  return { q: typeof body.q === "string" ? body.q : q, groups };
}
