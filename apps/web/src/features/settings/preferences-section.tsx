"use client";

import { useContext, useState } from "react";
import { ShellContext } from "@/components/shell/shell-context";
import { THEME_LABELS } from "@/components/shell/user-menu";
import { RadioGroup, Switch } from "@/components/ui/choice";
import { SectionCard } from "@/components/ui/section-card";
import { toast } from "@/components/ui/toast";
import { useSession } from "@/lib/session/context";
import { applyThemeLocally } from "@/lib/session/preferences";
import type { UiPreferencesState } from "@/lib/session/types";
import { MOTION_PREFERENCES, THEMES, type MotionPreference, type ThemePreference } from "@/lib/ui-preferences";
import { settingsMessages } from "@/messages/settings";
import { saveUiPreference } from "./api";

const m = settingsMessages.profile.preferences;

/** Mirrors the motion choice on <html data-motion>, which use-motion-preference.ts reads live. */
export function applyMotionLocally(motion: MotionPreference): void {
  if (typeof document === "undefined") return;
  if (motion === "reduced") document.documentElement.dataset.motion = "reduced";
  else delete document.documentElement.dataset.motion;
}

/**
 * The `ui` preference section. Every change applies on this device at once (where a local
 * helper exists) and is saved through the shared versioned PATCH; a failed save says so.
 */
export function PreferencesSection() {
  const { bootstrap } = useSession();
  const shell = useContext(ShellContext);
  const [ui, setUi] = useState<UiPreferencesState>(bootstrap.ui);

  const save = (change: Partial<UiPreferencesState>) => {
    setUi((current) => ({ ...current, ...change }));
    saveUiPreference(change).catch(() => toast.warning(m.saveFailed));
  };

  const setTheme = (theme: ThemePreference) => {
    setUi((current) => ({ ...current, theme }));
    // The shell owns the theme while mounted (its menu stays in step and it saves the change).
    if (shell) shell.setTheme(theme);
    else {
      applyThemeLocally(theme);
      saveUiPreference({ theme }).catch(() => toast.warning(m.saveFailed));
    }
  };

  const setMotion = (motion: MotionPreference) => {
    applyMotionLocally(motion);
    save({ motion });
  };

  return (
    <SectionCard title={m.title} description={m.intro}>
      <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
        <RadioGroup
          label={m.theme}
          value={ui.theme}
          onChange={(value) => {
            const theme = THEMES.find((candidate) => candidate === value);
            if (theme) setTheme(theme);
          }}
          options={THEMES.map((theme) => ({ value: theme, label: THEME_LABELS[theme] }))}
        />
        <RadioGroup
          label={m.motion}
          value={ui.motion}
          onChange={(value) => {
            const motion = MOTION_PREFERENCES.find((candidate) => candidate === value);
            if (motion) setMotion(motion);
          }}
          options={[
            { value: "full", label: m.motionFull, description: m.motionFullHint },
            { value: "reduced", label: m.motionReduced, description: m.motionReducedHint },
          ]}
        />
        <RadioGroup
          label={m.density}
          value={ui.density}
          onChange={(value) => save({ density: value === "compact" ? "compact" : "comfortable" })}
          options={[
            { value: "comfortable", label: m.densityComfortable },
            { value: "compact", label: m.densityCompact },
          ]}
        />
      </div>
      <div className="flex flex-col gap-1">
        <Switch isSelected={ui.shortcuts_enabled} onChange={(value) => save({ shortcuts_enabled: value })}>
          {m.shortcuts}
        </Switch>
        <Switch isSelected={ui.sidebar_collapsed} onChange={(value) => save({ sidebar_collapsed: value })}>
          {m.sidebarCollapsed}
        </Switch>
        <Switch isSelected={ui.context_rail_open} onChange={(value) => save({ context_rail_open: value })}>
          {m.railOpen}
        </Switch>
      </div>
    </SectionCard>
  );
}
