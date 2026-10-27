"use client";

import { createContext, useContext } from "react";
import type { ThemePreference } from "@/lib/ui-preferences";

export interface ShellContextValue {
  openSearch: () => void;
  theme: ThemePreference;
  setTheme: (theme: ThemePreference) => void;
  requestSignOut: () => void;
  signingOut: boolean;
}

export const ShellContext = createContext<ShellContextValue | null>(null);

/** Shell actions for pages (the phone "More" page opens search, changes theme, signs out). */
export function useShell(): ShellContextValue {
  const value = useContext(ShellContext);
  if (!value) throw new Error("useShell must be used inside the app shell");
  return value;
}
