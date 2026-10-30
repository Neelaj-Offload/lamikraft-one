/**
 * The structured screen context sent with every assistant turn (ai-routing.md §4.1).
 *
 * Screens contribute what the person is looking at (the focused record and its version, the
 * rows of the current list with stable refs, the selection, filters and the dirty fields of an
 * unsaved form); the builder assembles the payload and keeps it within the server's limits:
 * at most 50 visible items and 16 KB of JSON (larger payloads are refused with 422). When it
 * must trim, it keeps the focused list and drops the rest in a fixed order, so the person's
 * focus survives. The context is a hint only: the server re-reads every reference with the
 * person's permissions, so nothing here is trusted as a fact.
 */

import { compileRoutePattern, matchRoute } from "@/lib/routes";
import type { ScreenContext, ScreenDraft, ScreenFilterValue, ScreenRecordRef, ScreenVisibleItem } from "./types";

export const SCREEN_CONTEXT_MAX_BYTES = 16 * 1024;
export const SCREEN_CONTEXT_MAX_ITEMS = 50;

/** A row of a list on screen, before refs are assigned. */
export interface ListRow extends ScreenRecordRef {
  ordinal: number;
}

export interface ScreenList {
  key: string;
  rows: readonly ListRow[];
}

/** What one screen (or one part of it) contributes. */
export interface ScreenContribution {
  focus?: ScreenRecordRef | null;
  related?: readonly ScreenRecordRef[];
  lists?: readonly ScreenList[];
  /** Ids of selected rows (any list). */
  selectedIds?: readonly string[];
  filters?: Record<string, ScreenFilterValue | null | undefined>;
  draft?: (Omit<ScreenDraft, "values"> & { values: ScreenDraft["values"]; restricted?: readonly string[] }) | null;
}

export interface BuildInput {
  pathname: string;
  contributions: readonly ScreenContribution[];
  now: Date;
  viewport?: { width: number; height: number } | null;
}

export interface BuildLimits {
  maxBytes?: number;
  maxItems?: number;
}

const encoder = new TextEncoder();

export function contextBytes(context: ScreenContext): number {
  return encoder.encode(JSON.stringify(context)).length;
}

/** The manifest pattern, its params and area for a concrete pathname. */
export function routeContext(pathname: string): ScreenContext["route"] {
  const clean = pathname.split(/[?#]/, 1)[0] || "/";
  const route = matchRoute(clean);
  if (!route) return { path: clean, params: {}, area: "unknown" };
  const params: Record<string, string> = {};
  const patternSegments = route.path.split("/").filter(Boolean);
  const actualSegments = clean.split("/").filter(Boolean);
  if (compileRoutePattern(route.path).test(clean)) {
    patternSegments.forEach((segment, index) => {
      const name = /^\[([^\].]+)\]$/.exec(segment)?.[1];
      const value = actualSegments[index];
      if (name && value) params[name] = decodeURIComponent(value);
    });
  }
  return { path: route.path, params, area: route.area };
}

/** Stable refs: `i{ordinal}` for the primary (first) list, `{list_key}.{ordinal}` for others. */
export function refFor(listIndex: number, listKey: string, ordinal: number): string {
  return listIndex === 0 ? `i${ordinal}` : `${listKey}.${ordinal}`;
}

function sameRef(a: ScreenRecordRef, b: ScreenRecordRef): boolean {
  return a.type === b.type && a.id === b.id;
}

/**
 * Builds the payload. Contributions are merged in order (later ones win for focus and draft).
 * Trimming order when over a limit: draft values (dirty field names stay), rows of other
 * lists, related records, filters, then rows from the end of the focused list.
 */
export function buildScreenContext(input: BuildInput, limits: BuildLimits = {}): ScreenContext {
  const maxBytes = limits.maxBytes ?? SCREEN_CONTEXT_MAX_BYTES;
  const maxItems = limits.maxItems ?? SCREEN_CONTEXT_MAX_ITEMS;

  let focus: ScreenRecordRef | null = null;
  let draft: ScreenDraft | null = null;
  const related: ScreenRecordRef[] = [];
  const lists: ScreenList[] = [];
  const selectedIds = new Set<string>();
  const filters: Record<string, ScreenFilterValue> = {};
  for (const part of input.contributions) {
    if (part.focus !== undefined) focus = part.focus;
    for (const ref of part.related ?? []) if (!related.some((known) => sameRef(known, ref))) related.push(ref);
    for (const list of part.lists ?? []) if (!lists.some((known) => known.key === list.key)) lists.push(list);
    for (const id of part.selectedIds ?? []) selectedIds.add(id);
    for (const [key, value] of Object.entries(part.filters ?? {})) {
      if (value === null || value === undefined || value === "") continue;
      if (Array.isArray(value) && value.length === 0) continue;
      filters[key] = value;
    }
    if (part.draft !== undefined) {
      if (part.draft === null) draft = null;
      else {
        const restricted = new Set(part.draft.restricted ?? []);
        const values = Object.fromEntries(
          Object.entries(part.draft.values).filter(([field]) => !restricted.has(field) && part.draft!.dirty_fields.includes(field)),
        );
        draft = {
          form_key: part.draft.form_key,
          record_ref: part.draft.record_ref,
          dirty_fields: part.draft.dirty_fields.filter((field) => !restricted.has(field)),
          values,
        };
      }
    }
  }

  // The focused list holds the selection, else the focus; otherwise the first list.
  const focusedIndex = Math.max(
    0,
    lists.findIndex((list) => list.rows.some((row) => selectedIds.has(row.id) || (focus !== null && sameRef(row, focus)))),
  );
  const ordered = lists.length > 0 ? [lists[focusedIndex]!, ...lists.filter((_, index) => index !== focusedIndex)] : [];

  const items: ScreenVisibleItem[] = [];
  ordered.forEach((list, listIndex) => {
    for (const row of list.rows) {
      items.push({ ref: refFor(listIndex, list.key, row.ordinal), list_key: list.key, ordinal: row.ordinal, type: row.type, id: row.id, version: row.version });
    }
  });
  const focusedKey = ordered[0]?.key ?? null;

  const context: ScreenContext = {
    schema_version: 1,
    captured_at: input.now.toISOString().replace(/\.\d{3}Z$/, "Z"),
    route: routeContext(input.pathname),
    focus,
    records: [
      ...(focus ? [{ ...focus, role: "primary" as const }] : []),
      ...related.filter((ref) => !focus || !sameRef(ref, focus)).map((ref) => ({ ...ref, role: "related" as const })),
    ],
    visible_items: items,
    selection: [],
    filters,
    draft,
    briefing_pin: null,
    viewport: input.viewport ?? null,
  };

  const syncSelection = () => {
    context.selection = context.visible_items.filter((item) => selectedIds.has(item.id)).map((item) => item.ref);
  };

  // Item limit: the focused list first, then the others, cut at the limit.
  if (context.visible_items.length > maxItems) context.visible_items = context.visible_items.slice(0, maxItems);
  syncSelection();

  const steps: (() => boolean)[] = [
    () => {
      if (!context.draft || Object.keys(context.draft.values).length === 0) return false;
      context.draft = { ...context.draft, values: {} };
      return true;
    },
    () => {
      const kept = context.visible_items.filter((item) => item.list_key === focusedKey);
      if (kept.length === context.visible_items.length) return false;
      context.visible_items = kept;
      syncSelection();
      return true;
    },
    () => {
      const kept = context.records.filter((record) => record.role === "primary");
      if (kept.length === context.records.length) return false;
      context.records = kept;
      return true;
    },
    () => {
      if (Object.keys(context.filters).length === 0) return false;
      context.filters = {};
      return true;
    },
  ];
  for (const step of steps) {
    if (contextBytes(context) <= maxBytes) return context;
    step();
  }
  // Finally drop rows from the end of the focused list, keeping the selected and focused rows.
  while (contextBytes(context) > maxBytes && context.visible_items.length > 0) {
    const removable = context.visible_items.findLastIndex(
      (item) => !selectedIds.has(item.id) && !(focus !== null && sameRef(item, focus)),
    );
    context.visible_items.splice(removable === -1 ? context.visible_items.length - 1 : removable, 1);
    syncSelection();
  }
  return context;
}
