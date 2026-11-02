"use client";

import { useQuery } from "@tanstack/react-query";
import { StatusPill, type Tone } from "@/components/ui/badge";
import { DataTable, type DataTableColumn } from "@/components/ui/data-table";
import { LocalDateTime } from "@/components/ui/format";
import { InfoIcon } from "@/components/ui/icons";
import { PageHeader } from "@/components/ui/page-header";
import { EmptyState, ErrorState, Loading, StateView } from "@/components/ui/states";
import { queryKeys } from "@/lib/api/query-keys";
import { useSession } from "@/lib/session/context";
import { settingsMessages } from "@/messages/settings";
import { shellMessages } from "@/messages/shell";
import { fetchIntegrations } from "./api";
import { ModeBadge } from "./mode-badge";
import { SettingsAreaNav } from "./settings-hub";
import type { Integration, IntegrationState } from "./types";

const m = settingsMessages.integrations;

export const STATE_TONE: Record<IntegrationState, Tone> = { connected: "success", not_connected: "neutral", error: "danger" };

export function integrationColumns(): DataTableColumn<Integration>[] {
  const c = m.columns;
  const never = <span className="text-ink-muted">{m.never}</span>;
  return [
    { id: "label", header: c.label, isRowHeader: true, mobile: "title", cell: (row) => row.label },
    { id: "mode", header: c.mode, mobile: "key", cell: (row) => <ModeBadge mode={row.mode} /> },
    {
      id: "state",
      header: c.state,
      mobile: "status",
      cell: (row) => <StatusPill tone={STATE_TONE[row.state]}>{row.mode === "demo" ? (m.states[row.state] ?? row.label_text) : row.label_text}</StatusPill>,
    },
    { id: "verified", header: c.verifiedAt, mobile: "meta", cell: (row) => (row.verified_at ? <LocalDateTime value={row.verified_at} /> : never) },
    { id: "checked", header: c.lastChecked, cell: (row) => (row.last_checked_at ? <LocalDateTime value={row.last_checked_at} /> : never) },
    {
      id: "error",
      header: c.lastError,
      cell: (row) => (row.last_error_code ? <span className="font-mono text-xs select-all">{row.last_error_code}</span> : <span className="text-ink-muted">{m.none}</span>),
    },
  ];
}

function IntegrationTable() {
  const query = useQuery({ queryKey: queryKeys.system.integrations(), queryFn: ({ signal }) => fetchIntegrations(signal) });
  if (query.isPending) return <Loading label={m.what} rows={3} />;
  if (query.isError) return <ErrorState error={query.error} what={m.what} onRetry={() => void query.refetch()} />;
  return <DataTable caption={m.title} hideCaption columns={integrationColumns()} rows={query.data} rowId={(row) => row.key} empty={<EmptyState title={m.empty} />} />;
}

/** Without `system.integration.read`: the modes the bootstrap reported, no verification details. */
function IntegrationSummary() {
  const { bootstrap } = useSession();
  if (bootstrap.integrations.status !== "ok") return <EmptyState title={m.unavailableTitle}>{m.unavailableBody}</EmptyState>;
  if (bootstrap.integrations.value.length === 0) return <EmptyState title={m.empty} />;
  return (
    <div className="flex flex-col gap-2">
      <p className="text-sm text-ink-muted">{m.summaryIntro}</p>
      <ul className="flex flex-col divide-y rounded-lg border bg-surface px-4">
        {bootstrap.integrations.value.map((integration) => (
          <li key={integration.key} className="flex min-h-12 items-center justify-between gap-3 py-2">
            <span className="font-semibold text-ink">{integration.label}</span>
            <ModeBadge mode={integration.mode} />
          </li>
        ))}
      </ul>
    </div>
  );
}

export function IntegrationsView() {
  const { permissionKeys } = useSession();
  return (
    <div className="flex max-w-5xl flex-col gap-6">
      <PageHeader title={m.title} intro={m.intro} eyebrow={settingsMessages.hub.title} nav={<SettingsAreaNav />} />
      <StateView icon={<InfoIcon />} title={m.demoTitle} compact>
        <p>{shellMessages.demo.body}</p>
        <p className="mt-1">{m.credentials}</p>
      </StateView>
      {permissionKeys.has("system.integration.read") ? <IntegrationTable /> : <IntegrationSummary />}
    </div>
  );
}
