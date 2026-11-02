/**
 * The settings area's API calls (INTERIM(api-generate): see types.ts):
 * - org_list_settings           GET  /api/v1/org/settings
 * - org_get_setting             GET  /api/v1/org/settings/{key}
 * - org_update_setting          PUT  /api/v1/org/settings/{key}      {value, expected_version, change_reason}
 * - org_list_setting_revisions  GET  /api/v1/org/settings/{key}/revisions
 * - org_list_currencies         GET  /api/v1/org/currencies
 * - org_list_uoms               GET  /api/v1/org/uoms
 * - org_get_my_calendar         GET  /api/v1/org/calendar/me          (org.calendar.read)
 * - identity_get_me             GET  /api/v1/identity/me
 * - identity_update_password    POST /api/v1/identity/me/password     {current_password, new_password}
 * - system_list_integrations    GET  /api/v1/system/integrations      (system.integration.read)
 * - audit_list_entries          GET  /api/v1/audit                    (audit.log.read; CursorPage)
 */

import { api, idempotencyHeaders, requestUntyped, type ApiClient } from "@/lib/api/client";
import { saveUiPreferences, type UiPreferencePatch } from "@/lib/session/preferences";
import type { UiPreferencesState } from "@/lib/session/types";
import {
  needSetting,
  parseAuditPage,
  parseCalendar,
  parseCurrencies,
  parseIntegrations,
  parseMe,
  parseRevisions,
  parseSettings,
  parseUoms,
} from "./parse";
import type { AuditEntry, Currency, CursorPage, Integration, Json, Me, MyCalendar, SettingRead, SettingRevision, Uom } from "./types";

export const SETTINGS_PATH = "/api/v1/org/settings";
export const ME_PATH = "/api/v1/identity/me";
export const AUDIT_PATH = "/api/v1/audit";
export const AUDIT_PAGE_SIZE = 50;

const settingPath = (key: string): `/api/v1/${string}` => `${SETTINGS_PATH}/${encodeURIComponent(key)}`;

// ---- org settings -----------------------------------------------------------------------------

export async function fetchSettings(signal?: AbortSignal, client: ApiClient = api): Promise<SettingRead[]> {
  return parseSettings(await requestUntyped<unknown>(client, "get", SETTINGS_PATH, { signal }));
}

export async function fetchSetting(key: string, signal?: AbortSignal, client: ApiClient = api): Promise<SettingRead> {
  return needSetting(await requestUntyped<unknown>(client, "get", settingPath(key), { signal }));
}

export async function fetchSettingRevisions(key: string, signal?: AbortSignal, client: ApiClient = api): Promise<SettingRevision[]> {
  return parseRevisions(await requestUntyped<unknown>(client, "get", `${settingPath(key)}/revisions`, { params: { query: { limit: 50 } }, signal }));
}

export interface SettingUpdate {
  value: Json;
  expected_version: number;
  change_reason: string | null;
}

/** Replaces a setting's value; a 409 `version_conflict` carries the current value (`ProblemError`). */
export async function updateSetting(key: string, update: SettingUpdate, idempotencyKey: string, client: ApiClient = api): Promise<SettingRead> {
  const body: Json = { value: update.value, expected_version: update.expected_version };
  if (update.change_reason?.trim()) body.change_reason = update.change_reason.trim();
  return needSetting(await requestUntyped<unknown>(client, "put", settingPath(key), { body, headers: idempotencyHeaders(idempotencyKey) }));
}

// ---- reference data ---------------------------------------------------------------------------

export async function fetchCurrencies(signal?: AbortSignal, client: ApiClient = api): Promise<Currency[]> {
  return parseCurrencies(await requestUntyped<unknown>(client, "get", "/api/v1/org/currencies", { signal }));
}

export async function fetchUoms(signal?: AbortSignal, client: ApiClient = api): Promise<Uom[]> {
  return parseUoms(await requestUntyped<unknown>(client, "get", "/api/v1/org/uoms", { signal }));
}

export async function fetchMyCalendar(signal?: AbortSignal, client: ApiClient = api): Promise<MyCalendar> {
  return parseCalendar(await requestUntyped<unknown>(client, "get", "/api/v1/org/calendar/me", { signal }));
}

// ---- identity ---------------------------------------------------------------------------------

export async function fetchMe(signal?: AbortSignal, client: ApiClient = api): Promise<Me> {
  return parseMe(await requestUntyped<unknown>(client, "get", ME_PATH, { signal }));
}

/**
 * `POST /identity/me/password` (PasswordChangeRequest). On success the server rotates this
 * session (new cookies and CSRF, both set on the response) and ends the user's other sessions.
 */
export async function changePassword(
  body: { current_password: string; new_password: string },
  idempotencyKey: string,
  client: ApiClient = api,
): Promise<void> {
  await requestUntyped<unknown>(client, "post", `${ME_PATH}/password`, { body, headers: idempotencyHeaders(idempotencyKey) });
}

/**
 * The full `ui` preference section. `saveUiPreferences` (src/lib/session/preferences.ts) owns the
 * `expected_version` queue; its patch type names only the fields the shell changes, while the
 * server's `UiPreferencesPatch` accepts all six, so the wider patch is passed through here.
 */
export type UiPreferenceChange = Partial<UiPreferencesState>;

export function saveUiPreference(change: UiPreferenceChange, client?: ApiClient): Promise<void> {
  return saveUiPreferences(change as UiPreferencePatch, client);
}

// ---- system -----------------------------------------------------------------------------------

export async function fetchIntegrations(signal?: AbortSignal, client: ApiClient = api): Promise<Integration[]> {
  return parseIntegrations(await requestUntyped<unknown>(client, "get", "/api/v1/system/integrations", { signal }));
}

// ---- audit ------------------------------------------------------------------------------------

export interface AuditQuery {
  action_prefix?: string | null;
  outcome?: string | null;
  /** RFC 3339 UTC instants (the API refuses naive timestamps). */
  occurred_from?: string | null;
  occurred_to?: string | null;
  cursor?: string | null;
}

export function auditSearch(params: AuditQuery): URLSearchParams {
  const query = new URLSearchParams({ limit: String(AUDIT_PAGE_SIZE) });
  if (params.action_prefix?.trim()) query.set("action_prefix", params.action_prefix.trim());
  if (params.outcome) query.set("outcome", params.outcome);
  if (params.occurred_from) query.set("occurred_from", params.occurred_from);
  if (params.occurred_to) query.set("occurred_to", params.occurred_to);
  if (params.cursor) query.set("cursor", params.cursor);
  return query;
}

export async function fetchAuditEntries(params: AuditQuery, signal?: AbortSignal, client: ApiClient = api): Promise<CursorPage<AuditEntry>> {
  const query = auditSearch(params);
  const raw = await requestUntyped<unknown>(client, "get", AUDIT_PATH, {
    params: { query: Object.fromEntries(query.entries()) },
    signal,
  });
  return parseAuditPage(raw);
}
