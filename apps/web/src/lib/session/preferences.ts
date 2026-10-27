/**
 * UI preference changes from the shell (theme, context rail). The change applies at once on
 * this device; it is saved to the user's profile through
 * `PATCH /api/v1/identity/me/preferences` (api-conventions §7.1, typed `ui` section), which
 * also re-issues the `lk_ui` cookie the root layout reads.
 */

import { api, requestUntyped, type ApiClient } from "@/lib/api/client";
import { ProblemError } from "@/lib/api/errors";
import { parseUiPreferences, serializeUiPreferences, UI_COOKIE, type ThemePreference } from "@/lib/ui-preferences";
import type { UiPreferencesState } from "./types";

export const PREFERENCES_PATH = "/api/v1/identity/me/preferences";

export type UiPreferencePatch = Partial<Pick<UiPreferencesState, "theme" | "context_rail_open" | "sidebar_collapsed">>;

/** Mirrors a theme choice on <html> and in the lk_ui cookie so the next server render matches. */
export function applyThemeLocally(theme: ThemePreference): void {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  if (theme === "system") delete root.dataset.theme;
  else root.dataset.theme = theme;

  const current = parseUiPreferences(readUiCookie());
  const value = encodeURIComponent(serializeUiPreferences({ ...current, theme }));
  const secure = window.location.protocol === "https:" ? "; Secure" : "";
  document.cookie = `${UI_COOKIE}=${value}; Path=/; Max-Age=31536000; SameSite=Lax${secure}`;
}

function readUiCookie(): string | null {
  for (const part of document.cookie.split(";")) {
    const [name, ...rest] = part.trim().split("=");
    if (name === UI_COOKIE) return rest.join("=");
  }
  return null;
}

// ---------------------------------------------------------------------------------------------
// Optimistic versions: every PATCH carries `expected_version` (the version last read; 0 before
// the first save). A 409 `version_conflict` re-reads the current version and retries once:
// the patch only names the fields the person just changed, so it never overwrites others.

let knownVersion = 0;
let queue: Promise<unknown> = Promise.resolve();

/** The preferences version from the bootstrap (or a save); called by the SessionProvider. */
export function seedPreferencesVersion(version: number | null | undefined): void {
  if (typeof version === "number" && Number.isInteger(version) && version >= 0) knownVersion = version;
}

export function currentPreferencesVersion(): number {
  return knownVersion;
}

type Json = Record<string, unknown>;
const isObject = (value: unknown): value is Json => value !== null && typeof value === "object" && !Array.isArray(value);

/** `PreferencesUpdated{preferences{version}}`, a 409's `current`/`current_version`, or `MeRead{preferences{version}}`. */
export function preferencesVersionFrom(body: unknown): number | null {
  if (!isObject(body)) return null;
  if (typeof body.current_version === "number") return body.current_version;
  for (const holder of [body.preferences, body.current, isObject(body.current) ? body.current.preferences : null]) {
    if (isObject(holder) && typeof holder.version === "number") return holder.version;
  }
  return null;
}

async function patchOnce(patch: UiPreferencePatch, client: ApiClient): Promise<void> {
  const result = await requestUntyped<unknown>(client, "patch", PREFERENCES_PATH, {
    body: { expected_version: knownVersion, ui: patch },
  });
  seedPreferencesVersion(preferencesVersionFrom(result));
}

/**
 * Saves the given fields of the `ui` preference section with `expected_version`. Saves are
 * queued so two quick toggles never race each other. Rejects with ProblemError/NetworkError.
 */
export function saveUiPreferences(patch: UiPreferencePatch, client: ApiClient = api): Promise<void> {
  const run = async () => {
    try {
      await patchOnce(patch, client);
    } catch (error) {
      if (!(error instanceof ProblemError) || error.code !== "version_conflict") throw error;
      const fromConflict = preferencesVersionFrom(error.problem);
      if (fromConflict !== null) seedPreferencesVersion(fromConflict);
      else seedPreferencesVersion(preferencesVersionFrom(await requestUntyped<unknown>(client, "get", "/api/v1/identity/me")));
      await patchOnce(patch, client);
    }
  };
  const next = queue.then(run, run);
  queue = next.catch(() => undefined);
  return next;
}
