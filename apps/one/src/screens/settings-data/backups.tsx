"use client";

import { fetchBackupFacts, type Backup } from "@/features/migration/api";
import { formatCount } from "@/lib/format/money";
import { useSession } from "@/lib/session/context";
import { BACKUP_READ, useBackupFacts } from "~/data/settings-data";
import { Page, PageHeader } from "~/shell/page";
import { LoadingBlock, NotPermitted } from "~/shell/states";
import { Banner, DataTable, DateText, EmptyState, GlassPanel, KeyValue, StatRow, StatTile, type Column } from "~/ui";
import { bytesText, Mono, Quiet, ServerCommand, SETTINGS_CRUMBS, shortSha, StatusBadge, type StatusLook } from "./shared";
import { ProtectedReadProblem } from "./step-up";

/**
 * When the database was last backed up and whether its restore rehearsal passed. Read only: backups
 * and rehearsals run on the server. The facts are a protected read (second factor).
 */

type Check = Backup["rehearsal_checks"][number];

const STEP_UP_REASON = "Backup facts describe your whole database. Confirm with your authenticator to see them.";
const BACKUP_STATUS: Record<string, StatusLook> = {
  completed: { label: "Completed", tone: "leaf" },
  failed: { label: "Failed", tone: "ember" },
};
const CHECK: Record<string, string> = {
  dump_checksum: "Dump checksum",
  pg_restore: "Restore into a temporary database",
  alembic_revision: "Schema revision",
  tables_present: "Tables present",
  row_counts: "Row counts",
  rls_forced: "Row-level security",
  rls_fails_closed: "Company data stays separated when a check fails",
  storage_checksums: "File store checksums",
  temporary_database_dropped: "Temporary database removed",
  rehearsal_error: "Rehearsal error",
};

function Outcome({ outcome, size }: { outcome: string | null | undefined; size?: "sm" }) {
  if (!outcome) return <Quiet>Not rehearsed</Quiet>;
  return <StatusBadge size={size} look={outcome === "passed" ? { label: "Passed", tone: "leaf", icon: "check" } : { label: "Failed", tone: "ember", icon: "alert" }} />;
}

function LastBackup({ backup }: { backup: Backup }) {
  const { zone } = useSession();
  const files = backup.storage_files ?? 0;
  return (
    <GlassPanel
      as="section"
      padding="lg"
      className="rise"
      eyebrow="Last backup"
      title={<DateText value={backup.started_at} style="dayTime" />}
      titleAs="h2"
      action={<StatusBadge look={BACKUP_STATUS[backup.status] ?? { label: backup.status, tone: "neutral" }} />}
    >
      <KeyValue
        rows
        items={[
          { label: "Backup", value: <Mono>{backup.backup_id}</Mono> },
          { label: "Database", value: <Mono>{backup.database}</Mono> },
          { label: "Schema revision", value: backup.alembic_revision ? <Mono>{backup.alembic_revision}</Mono> : null },
          { label: "Database dump", value: <span className="lk-tnum">{bytesText(backup.dump_bytes, zone.locale)}</span> },
          { label: "Dump SHA-256", value: backup.dump_sha256 ? <Mono title={backup.dump_sha256}>{shortSha(backup.dump_sha256)}</Mono> : null },
          {
            label: "File store",
            value: (
              <span className="lk-tnum">
                {formatCount(files, zone.locale)} {files === 1 ? "file" : "files"}
                {backup.storage_bytes !== null && backup.storage_bytes !== undefined ? `, ${bytesText(backup.storage_bytes, zone.locale)}` : ""}
              </span>
            ),
          },
          {
            label: "Tables and rows",
            value: (
              <span className="lk-tnum">
                {formatCount(backup.table_count ?? 0, zone.locale)} tables, {formatCount(backup.row_total ?? 0, zone.locale)} rows
              </span>
            ),
          },
        ]}
      />
    </GlassPanel>
  );
}

const checkColumns: Column<Check>[] = [
  { key: "check", header: "Check", primary: true, cell: (row) => CHECK[row.check] ?? row.check },
  { key: "result", header: "Result", mobileLabel: "Result", width: "120px", cell: (row) => <Outcome outcome={row.passed ? "passed" : "failed"} size="sm" /> },
  { key: "detail", header: "Detail", mobileLabel: "Detail", cell: (row) => (row.detail ? <span className="t-body-sm [overflow-wrap:anywhere]">{row.detail}</span> : <Quiet>None</Quiet>) },
];

function LastRehearsal({ backup }: { backup: Backup }) {
  const seconds = backup.rehearsal_seconds;
  return (
    <GlassPanel
      as="section"
      padding="none"
      className="rise"
      eyebrow="Last restore rehearsal"
      title={backup.rehearsed_at ? <DateText value={backup.rehearsed_at} style="dayTime" /> : "Not dated"}
      titleAs="h2"
      action={<Outcome outcome={backup.rehearsal_outcome} />}
    >
      <div className="flex min-w-0 flex-col gap-4">
        <div className="px-6">
          <KeyValue
            columns={2}
            items={[
              { label: "Backup restored", value: <Mono>{backup.backup_id}</Mono> },
              { label: "Took", value: seconds ? <span className="lk-tnum">{String(seconds)} s</span> : null },
            ]}
          />
        </div>
        <DataTable
          label="Checks run on the restored copy"
          columns={checkColumns}
          rows={backup.rehearsal_checks}
          rowKey={(row) => row.check}
          empty={<EmptyState compact icon="clipboardCheck" title="No check was recorded" text="Run the rehearsal again to record its checks." />}
        />
      </div>
    </GlassPanel>
  );
}

function historyColumns(locale: string): Column<Backup>[] {
  return [
    { key: "at", header: "Taken", primary: true, cell: (row) => <DateText value={row.started_at} style="dayTime" /> },
    { key: "id", header: "Backup", mobileLabel: "Backup", cell: (row) => <Mono>{row.backup_id}</Mono> },
    { key: "status", header: "Status", mobileLabel: "Status", cell: (row) => <StatusBadge look={BACKUP_STATUS[row.status] ?? { label: row.status, tone: "neutral" }} size="sm" /> },
    { key: "size", header: "Dump size", mobileLabel: "Dump size", numeric: true, cell: (row) => <span className="lk-tnum">{bytesText(row.dump_bytes, locale) ?? ""}</span> },
    { key: "rehearsal", header: "Rehearsal", mobileLabel: "Rehearsal", cell: (row) => <Outcome outcome={row.rehearsal_outcome} size="sm" /> },
  ];
}

export function Backups() {
  const { permissionKeys, zone } = useSession();
  const allowed = permissionKeys.has(BACKUP_READ);
  const query = useBackupFacts(allowed);

  const header = (
    <PageHeader
      breadcrumb={SETTINGS_CRUMBS}
      title="Backups"
      lead="When your data was last backed up, and whether a restore of it was rehearsed and passed. Backups run on the server; this page reports them."
    />
  );

  if (!allowed) {
    return (
      <Page>
        {header}
        <NotPermitted what="Backups" icon="archive" />
      </Page>
    );
  }
  if (query.isPending) {
    return (
      <Page>
        {header}
        <LoadingBlock lines={10} label="Loading the backup facts" />
      </Page>
    );
  }
  if (query.isError) {
    return (
      <Page>
        {header}
        <ProtectedReadProblem error={query.error} what="The backup facts" reason={STEP_UP_REASON} retry={() => fetchBackupFacts().then(() => query.refetch())} />
      </Page>
    );
  }

  const facts = query.data;
  const last = facts.last_backup;
  const rehearsal = facts.last_rehearsal;
  const hours = facts.max_age_hours_for_apply;

  return (
    <Page>
      {header}
      <StatRow>
        <StatTile
          label="Last backup"
          value={last ? <DateText value={last.started_at} style="relative" /> : "None yet"}
          foot={last ? (BACKUP_STATUS[last.status]?.label ?? last.status) : "No backup recorded"}
        />
        <StatTile
          label="Last rehearsal"
          value={rehearsal ? (rehearsal.rehearsal_outcome === "passed" ? "Passed" : rehearsal.rehearsal_outcome ? "Failed" : "Not rehearsed") : "None yet"}
          foot={rehearsal?.rehearsed_at ? <DateText value={rehearsal.rehearsed_at} style="relative" /> : "No rehearsal recorded"}
        />
        <StatTile label="Apply window" value={<span className="lk-tnum">{formatCount(hours, zone.locale)} h</span>} foot="Newest backup an apply accepts" />
      </StatRow>

      <Banner tone="cobalt" icon="shield">
        A migration apply needs a backup from the last {formatCount(hours, zone.locale)} hours whose restore rehearsal passed.
      </Banner>

      <div className="grid min-w-0 grid-cols-1 gap-6 xl:grid-cols-2 xl:items-start">
        {last ? (
          <LastBackup backup={last} />
        ) : (
          <GlassPanel padding="lg" className="rise">
            <EmptyState icon="archive" title="Take the first backup" text="Run this on the server, then rehearse a restore of it." actions={<ServerCommand>lk backup create</ServerCommand>} />
          </GlassPanel>
        )}
        {rehearsal ? (
          <LastRehearsal backup={rehearsal} />
        ) : (
          <GlassPanel padding="lg" className="rise">
            <EmptyState icon="clipboardCheck" title="Rehearse a restore" text="A rehearsal restores the last backup into a temporary database and checks it. Run it on the server." actions={<ServerCommand>lk backup restore-rehearsal</ServerCommand>} />
          </GlassPanel>
        )}
      </div>

      {facts.history.length > 0 ? (
        <GlassPanel as="section" padding="none" className="rise" title="Recent backups" titleAs="h2">
          <DataTable label="Recent backups, newest first" columns={historyColumns(zone.locale)} rows={facts.history} rowKey={(row) => row.backup_id} />
        </GlassPanel>
      ) : null}
    </Page>
  );
}
