"use client";

import type { ReactNode } from "react";
import { StatusPill, type Tone } from "@/components/ui/badge";
import { ErrorState, Loading, PermissionDenied } from "@/components/ui/states";
import { isProblemError } from "@/lib/api/errors";
import { useSession } from "@/lib/session/context";

/** Page frame of every settings screen: one h1, an optional intro line, actions on the right. */
export function SettingsPage({ title, intro, actions, children }: { title: string; intro?: ReactNode; actions?: ReactNode; children: ReactNode }) {
  return (
    <div className="flex max-w-5xl flex-col gap-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h1 className="text-[28px] font-bold tracking-tight md:text-3xl">{title}</h1>
          {intro ? <p className="max-w-prose text-ink-muted">{intro}</p> : null}
        </div>
        {actions ? <div className="flex flex-wrap gap-2">{actions}</div> : null}
      </header>
      {children}
    </div>
  );
}

/** A titled block inside a settings page. */
export function Section({ title, description, actions, children }: { title: string; description?: ReactNode; actions?: ReactNode; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-3 rounded-xl border bg-surface p-4 md:p-5" aria-label={title}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-lg font-semibold">{title}</h2>
          {description ? <p className="text-sm text-ink-muted">{description}</p> : null}
        </div>
        {actions ? <div className="flex flex-wrap gap-2">{actions}</div> : null}
      </div>
      {children}
    </section>
  );
}

/** True when the signed-in member holds any of the keys (navigation and control hints only; the server decides). */
export function useHasAny(...keys: string[]): boolean {
  const { permissionKeys } = useSession();
  return keys.some((key) => permissionKeys.has(key));
}

/**
 * Loading / error / forbidden states of a settings query, in one place. 403 shows the permission-denied view (no
 * data), 404 a not-found message; everything else the retryable error state.
 */
export function QueryState({ isPending, error, what, area, onRetry }: { isPending: boolean; error: unknown; what: string; area: string; onRetry: () => void }) {
  if (isPending) return <Loading label={what} />;
  if (isProblemError(error) && error.status === 403) return <PermissionDenied area={area} headingLevel={2} />;
  return <ErrorState error={error} what={what} onRetry={onRetry} />;
}

/** Field messages from a 422 problem, keyed by the last location segment (``body.email`` → ``email``). */
export function fieldErrors(error: unknown): Record<string, string> {
  if (!isProblemError(error)) return {};
  const out: Record<string, string> = {};
  for (const issue of error.validationIssues) {
    const field = String(issue.loc[issue.loc.length - 1] ?? "");
    const parent = String(issue.loc[issue.loc.length - 2] ?? "");
    const key = /^\d+$/.test(field) ? parent : field;
    if (key && !out[key]) out[key] = issue.msg;
  }
  return out;
}

/** A short sentence for a failed command (the problem's detail, or its title). */
export function problemText(error: unknown): string {
  if (isProblemError(error)) return error.detail || error.title;
  if (error instanceof Error && error.message === "step_up_cancelled") return "Not changed: confirmation was cancelled.";
  return "Something went wrong. Try again.";
}

const MEMBER_TONE: Record<string, Tone> = { active: "success", invited: "info", suspended: "warning", deactivated: "neutral" };
const MEMBER_LABEL: Record<string, string> = { active: "Active", invited: "Invited", suspended: "Suspended", deactivated: "Inactive" };

export function MemberStatus({ status }: { status: string }) {
  return <StatusPill tone={MEMBER_TONE[status] ?? "neutral"}>{MEMBER_LABEL[status] ?? status}</StatusPill>;
}

const REQUEST_TONE: Record<string, Tone> = {
  pending: "warning",
  requested: "warning",
  approved: "success",
  active: "success",
  scheduled: "info",
  rejected: "danger",
  withdrawn: "neutral",
  cancelled: "neutral",
  ended: "neutral",
};

export function RequestStatus({ status }: { status: string }) {
  return <StatusPill tone={REQUEST_TONE[status] ?? "neutral"}>{status.charAt(0).toUpperCase() + status.slice(1)}</StatusPill>;
}

export const SCOPE_LABEL: Record<string, string> = { own: "Own records", team: "Team", branch: "Branch", company: "Whole company" };

/** Human name of a permission key: ``sales.quote.export`` → "Sales · quote · export". */
export function keyLabel(key: string): string {
  return key.split(".").map((part) => part.replace(/_/g, " ")).join(" · ");
}
