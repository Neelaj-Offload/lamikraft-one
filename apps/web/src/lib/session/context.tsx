"use client";

import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { I18nProvider } from "react-aria-components";
import { seedCsrfToken } from "@/lib/api/client";
import { DEFAULT_LOCALE } from "@/lib/format/money";
import { DEFAULT_TIME_ZONE, type ZoneOptions } from "@/lib/format/time";
import { seedPreferencesVersion } from "./preferences";
import type { SessionBootstrap } from "./types";

interface SessionContextValue {
  bootstrap: SessionBootstrap;
  permissionKeys: ReadonlySet<string>;
  zone: ZoneOptions;
}

const SessionContext = createContext<SessionContextValue | null>(null);
const NowContext = createContext<Date | null>(null);

const MINUTE_MS = 60_000;

/**
 * Provides the bootstrap loaded by the (app) layout on the server. "Now" starts at the
 * server's `server_now`, so server HTML and hydration agree, then follows the browser clock
 * once mounted (labels such as "Updated 5 minutes ago" refresh every minute).
 */
export function SessionProvider({ bootstrap, children }: { bootstrap: SessionBootstrap; children: ReactNode }) {
  const value = useMemo<SessionContextValue>(
    () => ({
      bootstrap,
      permissionKeys: new Set(bootstrap.permissions.map((permission) => permission.key)),
      zone: { timeZone: bootstrap.time_zone, locale: bootstrap.locale },
    }),
    [bootstrap],
  );
  const [now, setNow] = useState(() => new Date(bootstrap.server_now));

  // The server-side bootstrap rotated the CSRF secret; its new value is only in the body.
  useEffect(() => {
    seedCsrfToken(bootstrap.csrf_token);
  }, [bootstrap.csrf_token]);

  // Preference writes carry the version this bootstrap read (409 version_conflict otherwise).
  useEffect(() => {
    seedPreferencesVersion(bootstrap.preferences_version);
  }, [bootstrap.preferences_version]);

  useEffect(() => {
    const tick = () => setNow(new Date());
    const first = window.setTimeout(tick, 0);
    const timer = window.setInterval(tick, MINUTE_MS);
    return () => {
      window.clearTimeout(first);
      window.clearInterval(timer);
    };
  }, []);

  return (
    <SessionContext value={value}>
      <NowContext value={now}>
        <I18nProvider locale={bootstrap.locale}>{children}</I18nProvider>
      </NowContext>
    </SessionContext>
  );
}

export function useSession(): SessionContextValue {
  const value = useContext(SessionContext);
  if (!value) throw new Error("useSession must be used inside the signed-in (app) layout");
  return value;
}

/** For components that also render outside a session (sign-in pages, tests). */
export function useOptionalSession(): SessionContextValue | null {
  return useContext(SessionContext);
}

/** The user's zone and locale; Asia/Kolkata and en-IN before sign-in. */
export function useZone(): ZoneOptions {
  return useContext(SessionContext)?.zone ?? { timeZone: DEFAULT_TIME_ZONE, locale: DEFAULT_LOCALE };
}

/** The current instant for labels; null outside a session (callers then omit relative text). */
export function useNow(): Date | null {
  return useContext(NowContext);
}
