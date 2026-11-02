/**
 * URL search params <-> audit log list state. Plain functions (no "use client"), so the server
 * page can read its search params and the client view can build links.
 *
 * Dates in the URL are business dates (`YYYY-MM-DD`) in the user's zone; the API wants zoned
 * instants, with `occurred_to` exclusive, so a day range becomes [start of from, start of the
 * day after to) in that zone (`auditQueryFrom`).
 */

import { parseDate, toZoned } from "@internationalized/date";
import type { AuditQuery } from "./api";
import { AUDIT_OUTCOMES, type AuditOutcome } from "./types";

type Search = Record<string, string | string[] | undefined>;
const first = (value: string | string[] | undefined) => (Array.isArray(value) ? value[0] : value);

export const AUDIT_PATH_URL = "/settings/audit";

export interface AuditListState {
  action_prefix: string;
  outcome: AuditOutcome | null;
  /** `YYYY-MM-DD` or null. */
  occurred_from: string | null;
  occurred_to: string | null;
  cursor: string | null;
}

const DATE = /^\d{4}-\d{2}-\d{2}$/;
const ACTION_PREFIX = /^[a-z0-9_.:-]{1,120}$/i;

/** A valid calendar date string, else null (never forwarded raw). */
export function businessDateFrom(value: string | string[] | undefined): string | null {
  const raw = first(value);
  if (!raw || !DATE.test(raw)) return null;
  try {
    parseDate(raw);
    return raw;
  } catch {
    return null;
  }
}

/** Opaque keyset cursors are base64url; anything else is ignored. */
export function cursorFrom(value: string | string[] | undefined): string | null {
  const raw = first(value);
  return raw && /^[A-Za-z0-9_\-=.]{1,200}$/.test(raw) ? raw : null;
}

export function auditListStateFrom(search: Search): AuditListState {
  const prefix = (first(search.action_prefix) ?? "").trim();
  return {
    action_prefix: ACTION_PREFIX.test(prefix) ? prefix : "",
    outcome: AUDIT_OUTCOMES.find((candidate) => candidate === first(search.outcome)) ?? null,
    occurred_from: businessDateFrom(search.occurred_from),
    occurred_to: businessDateFrom(search.occurred_to),
    cursor: cursorFrom(search.cursor),
  };
}

export function auditListHref(state: Partial<AuditListState>): string {
  const query = new URLSearchParams();
  if (state.action_prefix?.trim()) query.set("action_prefix", state.action_prefix.trim());
  if (state.outcome) query.set("outcome", state.outcome);
  if (state.occurred_from) query.set("occurred_from", state.occurred_from);
  if (state.occurred_to) query.set("occurred_to", state.occurred_to);
  if (state.cursor) query.set("cursor", state.cursor);
  const search = query.toString();
  return search ? `${AUDIT_PATH_URL}?${search}` : AUDIT_PATH_URL;
}

/** Start of the business date in `timeZone`, as a UTC instant without milliseconds. */
export function startOfDayUtc(date: string, timeZone: string, plusDays = 0): string | null {
  try {
    const day = parseDate(date).add({ days: plusDays });
    return toZoned(day, timeZone).toDate().toISOString().replace(/\.\d{3}Z$/, "Z");
  } catch {
    return null;
  }
}

/** The API query for a list state: the day range becomes zoned instants, `occurred_to` exclusive. */
export function auditQueryFrom(state: AuditListState, timeZone: string): AuditQuery {
  return {
    action_prefix: state.action_prefix || null,
    outcome: state.outcome,
    occurred_from: state.occurred_from ? startOfDayUtc(state.occurred_from, timeZone) : null,
    occurred_to: state.occurred_to ? startOfDayUtc(state.occurred_to, timeZone, 1) : null,
    cursor: state.cursor,
  };
}
