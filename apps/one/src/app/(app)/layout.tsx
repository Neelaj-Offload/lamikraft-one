import type { Route } from "next";
import { redirect } from "next/navigation";
import type { ReactNode } from "react";
import { loginUrl } from "@/lib/api/client";
import { SessionProvider } from "@/lib/session/context";
import { loadSession, requestedPath } from "@/lib/session/server";
import { AppShell } from "~/shell/app-shell";
import { SessionUnavailable } from "~/shell/session-unavailable";

/**
 * The signed-in frame. The session is loaded on the server (the browser's cookies are forwarded
 * to the API), so the menu renders only what this person may open, with no flash. A 401 goes to
 * sign-in and returns here afterwards; any other failure shows a reload screen rather than
 * pretending the person is signed out.
 */
export default async function AppLayout({ children }: { children: ReactNode }) {
  const result = await loadSession();
  if (result.status === "unauthenticated") redirect(loginUrl(await requestedPath()) as Route);
  if (result.status === "error") return <SessionUnavailable problem={result.problem} />;

  return (
    <SessionProvider bootstrap={result.bootstrap}>
      <AppShell>{children}</AppShell>
    </SessionProvider>
  );
}
