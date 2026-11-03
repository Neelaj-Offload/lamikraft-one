import type { Route } from "next";
import { redirect } from "next/navigation";
import type { ReactNode } from "react";
import { SessionUnavailable } from "@/components/shell/session-unavailable";
import { loginUrl } from "@/lib/api/client";
import { SessionProvider } from "@/lib/session/context";
import { loadSession, requestedPath } from "@/lib/session/server";

/**
 * Printable documents: the signed-in session without the app shell (no sidebar, top bar or rail), so the browser
 * prints the document alone. Same session handling as the (app) layout.
 */
export default async function PrintLayout({ children }: { children: ReactNode }) {
  const result = await loadSession();
  if (result.status === "unauthenticated") redirect(loginUrl(await requestedPath()) as Route);
  if (result.status === "error") return <SessionUnavailable problem={result.problem} />;

  return (
    <SessionProvider bootstrap={result.bootstrap}>
      <main id="main" className="mx-auto w-full max-w-[210mm] px-4 py-6 print:max-w-none print:p-0">
        {children}
      </main>
    </SessionProvider>
  );
}
