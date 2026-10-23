"use client";

import type { Key, Selection } from "react-aria-components";
import { Button as RacButton } from "react-aria-components";
import { ChevronDownIcon, MonitorIcon, MoonIcon, SignOutIcon, SunIcon } from "@/components/ui/icons";
import { Menu, MenuItem, MenuSection, MenuSeparator, MenuTrigger } from "@/components/ui/menu";
import { THEMES, type ThemePreference } from "@/lib/ui-preferences";
import { shellMessages as m } from "@/messages/shell";

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  const letters = parts.length > 1 ? [parts[0]!, parts[parts.length - 1]!] : parts.slice(0, 1);
  return letters.map((part) => part.charAt(0).toLocaleUpperCase()).join("") || "?";
}

export const THEME_LABELS: Record<ThemePreference, string> = {
  system: m.user.themeSystem,
  light: m.user.themeLight,
  dark: m.user.themeDark,
};

const themeIcon = { system: <MonitorIcon size={18} />, light: <SunIcon size={18} />, dark: <MoonIcon size={18} /> };

function themeFromSelection(selection: Selection): ThemePreference | null {
  if (selection === "all") return null;
  const [first] = [...selection];
  return THEMES.find((theme) => theme === first) ?? null;
}

/** Account menu: who is signed in, theme (menuitemradio choices) and sign-out. */
export function UserMenu({
  name,
  roleLabel,
  theme,
  onThemeChange,
  onSignOut,
}: {
  name: string;
  roleLabel: string | null;
  theme: ThemePreference;
  onThemeChange: (theme: ThemePreference) => void;
  onSignOut: () => void;
}) {
  return (
    <MenuTrigger>
      <RacButton
        aria-label={m.user.menu(name)}
        className="flex min-h-11 items-center gap-2 rounded-md px-1.5 text-ink outline-none hover:bg-surface-sunken pointer-fine:min-h-9 md:px-2"
      >
        <span aria-hidden="true" className="flex size-8 items-center justify-center rounded-full bg-forest-tint text-xs font-bold text-forest">
          {initials(name)}
        </span>
        <span className="hidden max-w-40 truncate text-sm font-semibold lg:inline">{name}</span>
        <ChevronDownIcon size={16} className="hidden text-ink-muted lg:block" />
      </RacButton>
      <Menu
        aria-label={m.user.menu(name)}
        onAction={(key: Key) => {
          if (key === "sign-out") onSignOut();
        }}
      >
        <MenuSection
          id="theme"
          title={m.user.theme}
          selectionMode="single"
          disallowEmptySelection
          selectedKeys={[theme]}
          onSelectionChange={(selection) => {
            const next = themeFromSelection(selection);
            if (next && next !== theme) onThemeChange(next);
          }}
        >
          {THEMES.map((option) => (
            <MenuItem key={option} id={option} icon={themeIcon[option]}>
              {THEME_LABELS[option]}
            </MenuItem>
          ))}
        </MenuSection>
        <MenuSeparator />
        <MenuSection id="account" title={roleLabel ? `${name} · ${roleLabel}` : name}>
          <MenuItem id="sign-out" icon={<SignOutIcon size={18} />}>
            {m.user.signOut}
          </MenuItem>
        </MenuSection>
      </Menu>
    </MenuTrigger>
  );
}
