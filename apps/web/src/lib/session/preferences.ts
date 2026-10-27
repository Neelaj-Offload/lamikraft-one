/**
 * UI preference changes from the shell (theme, context rail). The change applies at once on
 * this device; it is saved to the user's profile through
 * `PATCH /api/v1/identity/me/preferences` (api-conventions §7.1, typed `ui` section), which
 * also re-issues the `lk_ui` cookie the root layout reads.
 */

import { api, requestUntyped, type ApiClient } from "@/lib/api/client";
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

/** Saves the given fields of the `ui` preference section. Rejects with ProblemError/NetworkError. */
export async function saveUiPreferences(patch: UiPreferencePatch, client: ApiClient = api): Promise<void> {
  await requestUntyped<unknown>(client, "patch", PREFERENCES_PATH, { body: { ui: patch } });
}
