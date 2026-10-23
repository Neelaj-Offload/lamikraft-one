/**
 * The `lk_ui` cookie mirrors the server-side UI preferences so the root layout
 * can render <html data-theme data-motion> without an inline script.
 *
 * Wire format (set by FastAPI on login and on PATCH /me/ui-preferences):
 *   theme=<light|dark|system>&motion=<full|reduced>
 * Python's SimpleCookie wraps values containing "=" in double quotes; those are
 * tolerated. Unknown keys and invalid values fall back to the defaults.
 */

export const UI_COOKIE = "lk_ui";

export const THEMES = ["light", "dark", "system"] as const;
export const MOTION_PREFERENCES = ["full", "reduced"] as const;

export type ThemePreference = (typeof THEMES)[number];
export type MotionPreference = (typeof MOTION_PREFERENCES)[number];

export interface UiPreferences {
  theme: ThemePreference;
  motion: MotionPreference;
}

export const DEFAULT_UI_PREFERENCES: Readonly<UiPreferences> = Object.freeze({
  theme: "system",
  motion: "full",
});

function isOneOf<T extends string>(options: readonly T[], value: string | null): value is T {
  return value !== null && (options as readonly string[]).includes(value);
}

export function parseUiPreferences(raw: string | null | undefined): UiPreferences {
  if (!raw) return { ...DEFAULT_UI_PREFERENCES };

  let value = raw.trim();
  if (value.length >= 2 && value.startsWith('"') && value.endsWith('"')) {
    value = value.slice(1, -1);
  }
  try {
    value = decodeURIComponent(value);
  } catch {
    return { ...DEFAULT_UI_PREFERENCES };
  }

  const params = new URLSearchParams(value);
  const theme = params.get("theme");
  const motion = params.get("motion");
  return {
    theme: isOneOf(THEMES, theme) ? theme : DEFAULT_UI_PREFERENCES.theme,
    motion: isOneOf(MOTION_PREFERENCES, motion) ? motion : DEFAULT_UI_PREFERENCES.motion,
  };
}

export function serializeUiPreferences(preferences: UiPreferences): string {
  return new URLSearchParams({ theme: preferences.theme, motion: preferences.motion }).toString();
}

/** Attributes for <html>. `system` leaves data-theme unset so prefers-color-scheme applies. */
export function htmlThemeAttributes(preferences: UiPreferences): {
  "data-theme"?: "light" | "dark";
  "data-motion": MotionPreference;
} {
  return {
    ...(preferences.theme === "system" ? {} : { "data-theme": preferences.theme }),
    "data-motion": preferences.motion,
  };
}
