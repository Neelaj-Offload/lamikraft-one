"use client";

import { ErrorState } from "@/components/ui/states";
import { stateMessages as m } from "@/messages/states";

/**
 * Error boundary for the signed-in pages: an unexpected rendering error replaces the page
 * content only, so the shell (navigation, search, account menu) stays usable. Retry re-fetches
 * and re-renders the segment; the digest matches the server-side log entry.
 */
export default function AppError({ error, retry }: { error: Error & { digest?: string }; retry: () => void }) {
  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-[28px] font-bold tracking-tight md:text-3xl">{m.pageError.title}</h1>
      <ErrorState error={error} what="this page" onRetry={retry} />
      {error.digest ? (
        <p className="text-sm text-ink-muted">
          {m.requestId}: <span className="font-mono text-ink select-all">{error.digest}</span>
        </p>
      ) : null}
    </div>
  );
}
