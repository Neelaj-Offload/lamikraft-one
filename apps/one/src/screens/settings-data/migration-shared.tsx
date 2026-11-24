import type { Route } from "next";
import type { IssueFilters } from "@/features/migration/api";
import type { Crumb } from "~/shell/page";
import { lookOf, SETTINGS_CRUMBS, StatusBadge, type StatusLook } from "./shared";

/** Names, statuses and links the migration and backup screens share. No directive: usable from server and client files. */

export const MIGRATION_CRUMBS: readonly Crumb[] = [...SETTINGS_CRUMBS, { label: "Migration", href: "/settings/migration" }];

export type MigrationView = "runs" | "customers" | "opening";
export type RunView = "overview" | "reconciliation" | "files" | "issues";

export const RUN_KIND: Record<string, string> = { dry_run: "Dry run", apply: "Apply" };

const RUN_STATUS: Record<string, StatusLook> = {
  running: { label: "Running", tone: "cobalt" },
  completed: { label: "Completed", tone: "leaf" },
  failed: { label: "Failed", tone: "ember" },
};

export function RunStatus({ status, size }: { status: string; size?: "sm" }) {
  return <StatusBadge look={lookOf(RUN_STATUS, status)} size={size} />;
}

export const SEVERITY_LABEL: Record<string, string> = { error: "Rejected", quarantine: "Held back", warning: "Warning", info: "Note" };

const SEVERITY: Record<string, StatusLook> = {
  error: { label: "Rejected", tone: "ember" },
  quarantine: { label: "Held back", tone: "amber" },
  warning: { label: "Warning", tone: "cobalt" },
  info: { label: "Note", tone: "neutral" },
};

export function SeverityBadge({ severity }: { severity: string }) {
  return <StatusBadge look={lookOf(SEVERITY, severity)} size="sm" />;
}

export function migrationHref(view: MigrationView, offset = 0): Route {
  const query = new URLSearchParams();
  if (view !== "runs") query.set("view", view);
  if (offset > 0) query.set("offset", String(offset));
  const text = query.toString();
  return (text ? `/settings/migration?${text}` : "/settings/migration") as Route;
}

export function migrationViewFrom(raw: string | string[] | undefined): MigrationView {
  return raw === "customers" || raw === "opening" ? raw : "runs";
}

export function runViewFrom(raw: string | string[] | undefined): RunView {
  return raw === "reconciliation" || raw === "files" || raw === "issues" ? raw : "overview";
}

/** A run's view; the issue filters ride along only on the issues view. */
export function runHref(runId: string, view: RunView, filters?: IssueFilters): Route {
  const query = new URLSearchParams();
  if (view !== "overview") query.set("view", view);
  if (view === "issues" && filters) {
    if (filters.severity) query.set("severity", filters.severity);
    if (filters.entity) query.set("entity", filters.entity);
    if (filters.code) query.set("code", filters.code);
    if (filters.offset) query.set("offset", String(filters.offset));
  }
  const text = query.toString();
  return `/settings/migration/runs/${encodeURIComponent(runId)}${text ? `?${text}` : ""}` as Route;
}
