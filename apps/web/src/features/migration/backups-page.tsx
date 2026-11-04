"use client";

import { useQuery } from "@tanstack/react-query";
import { StatusPill } from "@/components/ui/badge";
import { DataTable, type DataTableColumn } from "@/components/ui/data-table";
import { LocalDateTime } from "@/components/ui/format";
import { KeyValueGrid } from "@/components/ui/key-value-grid";
import { PageHeader } from "@/components/ui/page-header";
import { SectionCard } from "@/components/ui/section-card";
import { EmptyState, Loading, PermissionDenied } from "@/components/ui/states";
import { SettingsAreaNav } from "@/features/settings/settings-hub";
import { queryKeys } from "@/lib/api/query-keys";
import { formatCount } from "@/lib/format/money";
import { useSession, useZone } from "@/lib/session/context";
import { migrationMessages } from "@/messages/migration";
import { settingsMessages } from "@/messages/settings";
import { fetchBackupFacts, type Backup } from "./api";
import { QueryProblem, bytesText, shortSha } from "./shared";

const m = migrationMessages.backups;
export const BACKUP_READ = "system.backup.read";

type Check = Backup["rehearsal_checks"][number];

export function OutcomePill({ outcome }: { outcome: string | null | undefined }) {
  if (!outcome) return <span className="text-ink-muted">{m.notRehearsed}</span>;
  return <StatusPill tone={outcome === "passed" ? "success" : "danger"}>{outcome === "passed" ? m.passed : m.failed}</StatusPill>;
}

function BackupFactsCard({ backup }: { backup: Backup }) {
  const { locale } = useZone();
  const f = m.fields;
  return (
    <SectionCard
      title={m.lastBackup}
      description={<LocalDateTime value={backup.started_at} />}
      actions={<StatusPill tone={backup.status === "completed" ? "success" : "danger"}>{m.statuses[backup.status] ?? backup.status}</StatusPill>}
    >
      <KeyValueGrid
        items={[
          { term: f.id, description: backup.backup_id, mono: true },
          { term: f.database, description: backup.database, mono: true },
          { term: f.revision, description: backup.alembic_revision ?? "—", mono: true },
          { term: f.dump, description: bytesText(backup.dump_bytes, locale), numeric: true },
          { term: f.dumpSha, description: <span title={backup.dump_sha256 ?? undefined}>{shortSha(backup.dump_sha256)}</span>, mono: true },
          {
            term: f.storage,
            description: `${formatCount(backup.storage_files ?? 0, locale)} files, ${bytesText(backup.storage_bytes, locale)}`,
            numeric: true,
          },
          {
            term: f.tables,
            description: `${formatCount(backup.table_count ?? 0, locale)} / ${formatCount(backup.row_total ?? 0, locale)}`,
            numeric: true,
          },
        ]}
      />
    </SectionCard>
  );
}

function checkColumns(): DataTableColumn<Check>[] {
  const c = m.checkColumns;
  return [
    { id: "check", header: c.check, isRowHeader: true, mobile: "title", cell: (row) => m.checks[row.check] ?? row.check },
    { id: "result", header: c.result, mobile: "status", cell: (row) => <OutcomePill outcome={row.passed ? "passed" : "failed"} /> },
    { id: "detail", header: c.detail, cell: (row) => <span className="text-sm [overflow-wrap:anywhere]">{row.detail ?? "—"}</span> },
  ];
}

function RehearsalCard({ backup }: { backup: Backup }) {
  const f = m.fields;
  return (
    <SectionCard title={m.lastRehearsal} description={<LocalDateTime value={backup.rehearsed_at} />} actions={<OutcomePill outcome={backup.rehearsal_outcome} />}>
      <KeyValueGrid
        items={[
          { term: f.id, description: backup.backup_id, mono: true },
          { term: f.duration, description: backup.rehearsal_seconds ? `${backup.rehearsal_seconds} s` : "—", numeric: true },
        ]}
        columns={2}
      />
      <DataTable caption={m.checksCaption} columns={checkColumns()} rows={backup.rehearsal_checks} rowId={(row) => row.check} />
    </SectionCard>
  );
}

function historyColumns(locale: string): DataTableColumn<Backup>[] {
  const c = m.historyColumns;
  return [
    { id: "at", header: c.at, isRowHeader: true, mobile: "title", cell: (row) => <LocalDateTime value={row.started_at} /> },
    { id: "id", header: c.id, mobile: "key", cell: (row) => <span className="font-mono text-xs">{row.backup_id}</span> },
    { id: "status", header: c.status, cell: (row) => m.statuses[row.status] ?? row.status },
    { id: "size", header: c.size, numeric: true, mobile: "amount", cell: (row) => bytesText(row.dump_bytes, locale) },
    { id: "rehearsal", header: c.rehearsal, mobile: "status", cell: (row) => <OutcomePill outcome={row.rehearsal_outcome} /> },
  ];
}

/** Settings › Backups: read-only facts of `lk backup create` and `lk backup restore-rehearsal`. */
export function BackupsPage() {
  const { permissionKeys } = useSession();
  const { locale } = useZone();
  const allowed = permissionKeys.has(BACKUP_READ);
  const query = useQuery({ queryKey: queryKeys.migration.backups(), queryFn: ({ signal }) => fetchBackupFacts(signal), enabled: allowed });
  if (!allowed) return <PermissionDenied area={m.area} />;
  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={m.title} intro={m.intro} eyebrow={settingsMessages.hub.title} nav={<SettingsAreaNav currentId="settings-backups" />} />
      {query.isPending ? (
        <Loading label={m.what} variant="detail" />
      ) : query.isError ? (
        <QueryProblem error={query.error} what={m.what} retry={() => fetchBackupFacts().then(() => query.refetch())} />
      ) : (
        <>
          {query.data.last_backup ? <BackupFactsCard backup={query.data.last_backup} /> : <EmptyState title={m.none}>{m.noneBody}</EmptyState>}
          {query.data.last_rehearsal ? <RehearsalCard backup={query.data.last_rehearsal} /> : <EmptyState title={m.noRehearsal} />}
          <p className="text-sm text-ink-muted">{m.applyRule(query.data.max_age_hours_for_apply)}</p>
          {query.data.history.length > 0 ? (
            <SectionCard title={m.history}>
              <DataTable caption={m.historyCaption} hideCaption columns={historyColumns(locale)} rows={query.data.history} rowId={(row) => row.backup_id} />
            </SectionCard>
          ) : null}
        </>
      )}
    </div>
  );
}
