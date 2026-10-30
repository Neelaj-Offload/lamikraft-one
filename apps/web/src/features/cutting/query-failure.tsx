"use client";

import { ErrorState, NotAvailable, PermissionDenied } from "@/components/ui/states";
import { ProblemError } from "@/lib/api/errors";

/** A failed read: 403 names the missing access, 404 is "not found or not available", anything else can retry. */
export function QueryFailure({ error, what, onRetry }: { error: unknown; what: string; onRetry: () => void }) {
  if (error instanceof ProblemError && error.status === 403) return <PermissionDenied area="the sheet optimiser" />;
  if (error instanceof ProblemError && error.status === 404) return <NotAvailable />;
  return <ErrorState error={error} what={what} onRetry={onRetry} />;
}
