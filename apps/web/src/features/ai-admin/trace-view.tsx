"use client";

import { useQuery } from "@tanstack/react-query";
import { StatusPill, type Tone } from "@/components/ui/badge";
import { DataTable, type DataTableColumn } from "@/components/ui/data-table";
import { LocalDateTime } from "@/components/ui/format";
import { KeyValueGrid } from "@/components/ui/key-value-grid";
import { Link } from "@/components/ui/link";
import { PageHeader } from "@/components/ui/page-header";
import { EmptyState, ErrorState, Loading, NotAvailable } from "@/components/ui/states";
import { ProblemError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { aiMessages } from "@/messages/ai";
import { settingsMessages } from "@/messages/settings";
import { SettingsAreaNav } from "@/features/settings/settings-hub";
import { fetchTrace } from "./api";
import type { TraceEntry } from "./types";

const m = aiMessages.trace;
const OK = new Set(["ok", "succeeded", "success", "dispatched", "active", "undone"]);
const BAD = new Set(["error", "failed", "refusal", "denied", "budget_exceeded"]);

export function statusTone(status: string | null): Tone {
  if (status === null) return "neutral";
  if (OK.has(status)) return "success";
  if (BAD.has(status)) return "danger";
  return "neutral";
}

/** Redacted detail as `key: value` pairs (scalars only; the server never sends text or payloads here). */
export function detailText(detail: Record<string, unknown>): string {
  return Object.entries(detail)
    .filter(([, value]) => value !== null && value !== undefined && value !== "" && (typeof value !== "object" || Array.isArray(value)))
    .map(([key, value]) => `${key}: ${Array.isArray(value) ? value.join(", ") : String(value)}`)
    .join(" · ");
}

export function traceColumns(): DataTableColumn<TraceEntry>[] {
  const c = m.columns;
  return [
    { id: "at", header: c.at, mobile: "meta", cell: (row) => <LocalDateTime value={row.at} /> },
    { id: "kind", header: c.kind, mobile: "key", cell: (row) => m.kinds[row.kind] ?? row.kind },
    { id: "name", header: c.name, isRowHeader: true, mobile: "title", cell: (row) => <span className="font-mono text-xs">{row.name}</span> },
    { id: "status", header: c.status, mobile: "status", cell: (row) => (row.status ? <StatusPill tone={statusTone(row.status)}>{row.status}</StatusPill> : null) },
    { id: "ref", header: c.ref, cell: (row) => (row.ref_id ? <span className="font-mono text-xs select-all">{row.ref_id}</span> : null) },
    { id: "detail", header: c.detail, cell: (row) => <span className="text-xs text-ink-muted">{detailText(row.detail)}</span> },
  ];
}

export function TraceView({ correlationId }: { correlationId: string | null }) {
  const query = useQuery({
    queryKey: queryKeys.agents.trace(correlationId ?? ""),
    queryFn: ({ signal }) => fetchTrace(correlationId!, signal),
    enabled: correlationId !== null,
    retry: (count, error) => !(error instanceof ProblemError && error.status === 404) && count < 2,
  });
  const header = <PageHeader title={m.title} intro={m.intro} eyebrow={settingsMessages.hub.title} nav={<SettingsAreaNav currentId="settings-ai" />} />;
  let body: React.ReactNode;
  if (correlationId === null || (query.isError && query.error instanceof ProblemError && query.error.status === 404)) {
    body = <NotAvailable headingLevel={2} />;
  } else if (query.isPending) body = <Loading label={m.what} rows={6} />;
  else if (query.isError) body = <ErrorState error={query.error} what={m.what} onRetry={() => void query.refetch()} />;
  else {
    const trace = query.data;
    body = (
      <div className="flex flex-col gap-4">
        <KeyValueGrid
          items={[
            { term: m.correlation, description: trace.correlation_id, mono: true },
            { term: m.runs, description: trace.run_ids.join(", "), mono: true },
            { term: m.accessLabel, description: m.access[trace.access] ?? trace.access },
          ]}
        />
        <DataTable caption={m.title} hideCaption columns={traceColumns()} rows={trace.entries} rowId={(row) => `${row.kind}:${row.ref_id ?? ""}:${row.name}:${row.at}`} empty={<EmptyState title={m.empty} />} />
      </div>
    );
  }
  return (
    <div className="flex max-w-6xl flex-col gap-6">
      {header}
      {body}
      <Link href="/settings/ai">{m.back}</Link>
    </div>
  );
}
