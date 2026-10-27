import type { Route } from "next";
import { redirect } from "next/navigation";
import type { ReactNode } from "react";
import { AppShell } from "@/components/shell/app-shell";
import { SessionUnavailable } from "@/components/shell/session-unavailable";
import { loginUrl } from "@/lib/api/client";
import { SessionProvider } from "@/lib/session/context";
import { loadSession, requestedPath } from "@/lib/session/server";

/**
 * Signed-in frame. Awaits `GET /api/v1/session/bootstrap` on the server (forwarding the
 * browser's cookies to LK_API_INTERNAL_URL) so navigation renders only authorised areas with
 * no flash; a 401 goes to /login with a validated `next`, any other failure shows a reload
 * screen instead of pretending the user is signed out.
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
