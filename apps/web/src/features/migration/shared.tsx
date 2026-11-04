"use client";

import type { ReactNode } from "react";
import { needsStepUp, useStepUp } from "@/app/(app)/settings/_lib/step-up";
import { StatusPill, type Tone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { LockIcon } from "@/components/ui/icons";
import { ErrorState, StateView } from "@/components/ui/states";
import { formatCount } from "@/lib/format/money";
import { migrationMessages as m } from "@/messages/migration";

export const SEVERITY_TONE: Record<string, Tone> = { error: "danger", quarantine: "warning", warning: "info", info: "neutral" };
export const RUN_TONE: Record<string, Tone> = { running: "info", completed: "success", failed: "danger" };
export const CANDIDATE_TONE: Record<string, Tone> = { proposed: "warning", linked: "success", new_party: "info", rejected: "neutral" };

export function SeverityPill({ severity }: { severity: string }) {
  return <StatusPill tone={SEVERITY_TONE[severity] ?? "neutral"}>{m.run.severities[severity] ?? severity}</StatusPill>;
}

export function RunStatusPill({ status }: { status: string }) {
  return <StatusPill tone={RUN_TONE[status] ?? "neutral"}>{m.runs.statuses[status] ?? status}</StatusPill>;
}

/** "products_master" -> "Products master" (legacy collection names are shown, not translated). */
export function entityLabel(entity: string): string {
  const text = entity.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function shortSha(sha: string | null | undefined): string {
  return sha ? `${sha.slice(0, 12)}…` : "—";
}

export function bytesText(bytes: number | null | undefined, locale: string): string {
  if (bytes === null || bytes === undefined) return "—";
  if (bytes < 1024) return `${formatCount(bytes, locale)} B`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb.toLocaleString(locale, { maximumFractionDigits: 1 })} KB`;
  return `${(kb / 1024).toLocaleString(locale, { maximumFractionDigits: 1 })} MB`;
}

/**
 * Migration and backup reads are MFA-flagged (permissions.md §7.8). A 401 `mfa_required` / `reauth_required` asks
 * the person to confirm (the shared step-up dialog) and then retries; any other failure is the usual error state.
 */
export function QueryProblem({ error, what, retry }: { error: unknown; what: string; retry: () => Promise<unknown> }): ReactNode {
  const stepUp = useStepUp();
  if (!needsStepUp(error)) return <ErrorState error={error} what={what} onRetry={() => void retry()} />;
  return (
    <>
      <StateView
        icon={<LockIcon />}
        title={m.stepUp.title}
        tone="warning"
        actions={
          <Button variant="primary" onPress={() => void stepUp.run(retry).catch(() => undefined)}>
            {m.stepUp.action}
          </Button>
        }
      >
        {m.stepUp.body}
      </StateView>
      {stepUp.dialog}
    </>
  );
}
