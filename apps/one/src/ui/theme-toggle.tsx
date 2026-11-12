"use client";

import { useRef, useSyncExternalStore } from "react";
import { useOptionalSession } from "@/lib/session/context";
import { applyThemeLocally, saveUiPreferences } from "@/lib/session/preferences";
import { THEMES, type ThemePreference } from "@/lib/ui-preferences";
import { IconButton } from "./button";
import { Icon, type IconName } from "./icon";
import { SegmentedControl } from "./segmented";
import { toast } from "./toast";

const look: Record<ThemePreference, { name: string; icon: IconName }> = {
  light: { name: "Light", icon: "sun" },
  dark: { name: "Dark", icon: "moon" },
  system: { name: "System", icon: "monitor" },
};

/** The order the icon button steps through. */
const following: Record<ThemePreference, ThemePreference> = { light: "dark", dark: "system", system: "light" };

function isTheme(value: string): value is ThemePreference {
  return (THEMES as readonly string[]).includes(value);
}

/** The theme on screen is <html data-theme>; no attribute means "follow the system". */
function readAppliedTheme(): ThemePreference {
  const applied = document.documentElement.dataset.theme;
  return applied === "light" || applied === "dark" ? applied : "system";
}

function subscribeAppliedTheme(onChange: () => void): () => void {
  const observer = new MutationObserver(onChange);
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  return () => observer.disconnect();
}

export interface ThemeToggleProps {
  /** segmented: all three choices side by side. icon: one button that steps through them. */
  variant?: "segmented" | "icon";
  size?: "sm" | "md";
  className?: string;
}

/**
 * Light, Dark or System. The choice applies at once on this device and is saved to the signed-in
 * person's profile; if the save fails the previous theme comes back and a toast says so. Outside
 * a session (sign-in pages) it only applies on this device.
 */
export function ThemeToggle({ variant = "segmented", size = "md", className }: ThemeToggleProps) {
  const session = useOptionalSession();
  const profileTheme = session?.bootstrap.ui.theme ?? "system";
  // What is applied to <html> is the instant, local state; the profile value seeds the server render.
  const theme = useSyncExternalStore(subscribeAppliedTheme, readAppliedTheme, () => profileTheme);
  /** The last theme known to be stored, to return to when a save fails. */
  const stored = useRef<ThemePreference | null>(null);
  const requests = useRef(0);

  const choose = (next: ThemePreference) => {
    if (next === theme) return;
    stored.current ??= theme;
    applyThemeLocally(next);
    if (!session) return;
    requests.current += 1;
    const request = requests.current;
    saveUiPreferences({ theme: next }).then(
      () => {
        stored.current = next;
      },
      () => {
        // A newer choice is on its way; it decides what happens next.
        if (request !== requests.current) return;
        applyThemeLocally(stored.current ?? "system");
        toast.error("Theme not saved", { description: "Your choice could not be stored, so the previous theme is back." });
      },
    );
  };

  if (variant === "icon") {
    const next = following[theme];
    return (
      <IconButton
        className={className}
        icon={look[theme].icon}
        size={size}
        label={`Theme: ${look[theme].name}. Switch to ${look[next].name}`}
        onPress={() => choose(next)}
      />
    );
  }

  return (
    <SegmentedControl
      className={className}
      label="Theme"
      size={size}
      value={theme}
      onChange={(value) => {
        if (isTheme(value)) choose(value);
      }}
      options={THEMES.map((value) => ({
        value,
        label: (
          <>
            <Icon name={look[value].icon} size={14} />
            {look[value].name}
          </>
        ),
      }))}
    />
  );
}
