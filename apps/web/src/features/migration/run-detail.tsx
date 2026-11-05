"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Link as RacLink } from "react-aria-components";
import { StatusPill } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DataTable, OffsetPagination, type DataTableColumn } from "@/components/ui/data-table";
import { LocalDateTime } from "@/components/ui/format";
import { KeyValueGrid, type KeyValue } from "@/components/ui/key-value-grid";
import { LinkButton } from "@/components/ui/link";
import { PageHeader } from "@/components/ui/page-header";
import { SectionCard } from "@/components/ui/section-card";
import { Select } from "@/components/ui/select";
import { EmptyState, Loading, NotAvailable, PermissionDenied } from "@/components/ui/states";
import { isProblemError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { formatCount } from "@/lib/format/money";
import { useSession, useZone } from "@/lib/session/context";
import { migrationMessages as m } from "@/messages/migration";
import {
  ISSUE_SEVERITIES,
  fetchIssueFacets,
  fetchIssues,
  fetchRun,
  issueFiltersHref,
  issuesCsvHref,
  type Issue,
  type IssueFilters,
  type IssueSeverity,
  type RunDetail,
} from "./api";
import { RUN_READ } from "./migration-page";
import { readReport, type CurrencyTotals, type Discrepancy, type EntityRow, type FileRow, type LinkRow, type RunReport } from "./report";
import { QueryProblem, RunStatusPill, SeverityPill, entityLabel, shortSha } from "./shared";

const r = m.run;

function entityColumns(locale: string): DataTableColumn<EntityRow>[] {
  const c = r.entities.columns;
  const n = (v: number) => formatCount(v, locale);
  return [
    { id: "entity", header: c.entity, isRowHeader: true, mobile: "title", cell: (row) => entityLabel(row.entity) },
    { id: "rows", header: c.rows, numeric: true, mobile: "amount", cell: (row) => n(row.rows) },
    { id: "accepted", header: c.accepted, numeric: true, cell: (row) => n(row.accepted) },
    { id: "quarantined", header: c.quarantined, numeric: true, cell: (row) => n(row.quarantined) },
    { id: "rejected", header: c.rejected, numeric: true, cell: (row) => n(row.rejected) },
    { id: "repeats", header: c.repeats, numeric: true, cell: (row) => n(row.repeats) },
    {
      id: "balanced",
      header: c.balanced,
      mobile: "status",
      cell: (row) => <StatusPill tone={row.balanced ? "success" : "danger"}>{row.balanced ? m.yes : m.no}</StatusPill>,
    },
  ];
}

function totalsColumns(locale: string): DataTableColumn<CurrencyTotals>[] {
  const c = r.totals.columns;
  const money = (v: string | null) => <span className="tabular">{v ?? "—"}</span>;
  return [
    { id: "currency", header: c.currency, isRowHeader: true, mobile: "title", cell: (row) => <span className="font-mono">{row.currency}</span> },
    { id: "sourceQuotes", header: c.sourceQuotes, numeric: true, cell: (row) => formatCount(row.sourceQuotes, locale) },
    { id: "sourceTotal", header: c.sourceTotal, numeric: true, cell: (row) => money(row.sourceTotal) },
    { id: "acceptedTotal", header: c.acceptedTotal, numeric: true, mobile: "amount", cell: (row) => money(row.acceptedTotal) },
    { id: "recomputed", header: c.recomputed, numeric: true, cell: (row) => money(row.recomputedTotal) },
    { id: "difference", header: c.difference, numeric: true, cell: (row) => money(row.difference) },
    { id: "discrepant", header: c.discrepant, numeric: true, mobile: "meta", cell: (row) => formatCount(row.discrepant, locale) },
  ];
}

function discrepancyColumns(): DataTableColumn<Discrepancy>[] {
  const c = r.totals.discrepancyColumns;
  return [
    { id: "quote", header: c.quote, isRowHeader: true, mobile: "title", cell: (row) => <span className="font-mono">{row.quoteNumber ?? row.key}</span> },
    { id: "currency", header: c.currency, cell: (row) => row.currency },
    { id: "legacy", header: c.legacy, numeric: true, cell: (row) => row.legacy ?? "—" },
    { id: "lines", header: c.lines, numeric: true, cell: (row) => row.lines ?? "—" },
    { id: "difference", header: c.difference, numeric: true, mobile: "amount", cell: (row) => row.difference ?? "—" },
  ];
}

function linkColumns(locale: string): DataTableColumn<LinkRow>[] {
  const c = r.links.columns;
  const n = (v: number | null) => (v === null ? "—" : formatCount(v, locale));
  return [
    { id: "link", header: c.link, isRowHeader: true, mobile: "title", cell: (row) => <span className="font-mono text-xs">{row.link.replace("->", " → ")}</span> },
    { id: "linked", header: c.linked, numeric: true, cell: (row) => n(row.linked) },
    { id: "orphans", header: c.orphans, numeric: true, mobile: "amount", cell: (row) => n(row.orphans) },
    { id: "unresolved", header: c.unresolved, numeric: true, cell: (row) => n(row.unresolved) },
  ];
}

function fileColumns(locale: string): DataTableColumn<FileRow>[] {
  const c = r.files.columns;
  return [
    { id: "file", header: c.file, isRowHeader: true, mobile: "title", cell: (row) => <span className="font-mono text-xs">{row.file}</span> },
    { id: "collection", header: c.collection, cell: (row) => entityLabel(row.entity) },
    { id: "format", header: c.format, cell: (row) => row.format.toUpperCase() },
    { id: "rows", header: c.rows, numeric: true, cell: (row) => formatCount(row.rows, locale) },
    { id: "sha", header: c.sha, mobile: "meta", cell: (row) => <span className="font-mono text-xs select-all" title={row.sha256}>{shortSha(row.sha256)}</span> },
  ];
}

function issueColumns(): DataTableColumn<Issue>[] {
  const c = r.issues.columns;
  return [
    {
      id: "reference",
      header: c.reference,
      isRowHeader: true,
      className: "min-w-44",
      mobile: "title",
      cell: (row) => (
        <span className="flex flex-col gap-0.5">
          <span className="font-semibold text-ink">{entityLabel(row.entity)}</span>
          <span className="font-mono text-xs text-ink-muted [overflow-wrap:anywhere]">
            {r.issues.row(row.source_file, row.row_number)}
            {row.source_key ? ` · ${row.source_key}` : ""}
          </span>
        </span>
      ),
    },
    { id: "severity", header: c.severity, mobile: "status", cell: (row) => <SeverityPill severity={row.severity} /> },
    { id: "code", header: c.code, mobile: "key", cell: (row) => <span className="font-mono text-xs">{row.code}</span> },
    {
      id: "message",
      header: c.message,
      mobile: "meta",
      className: "min-w-72",
      cell: (row) => (
        <span className="flex flex-col gap-1">
          <span>{row.message}</span>
          {row.raw_value ? <span className="font-mono text-xs text-ink-muted [overflow-wrap:anywhere]">{row.raw_value}</span> : null}
          {row.raw ? (
            <details>
              <summary className="cursor-pointer text-sm text-forest">{r.issues.showValues}</summary>
              <dl className="mt-2 flex flex-col gap-1 text-xs">
                {Object.entries(row.raw).map(([key, value]) => (
                  <div key={key} className="flex flex-wrap gap-x-2">
                    <dt className="font-mono text-ink-muted">{key}</dt>
                    <dd className="min-w-0 font-mono [overflow-wrap:anywhere]">{typeof value === "string" ? value : JSON.stringify(value)}</dd>
                  </div>
                ))}
              </dl>
            </details>
          ) : null}
        </span>
      ),
    },
  ];
}

function IssueBrowser({ run, filters }: { run: RunDetail; filters: IssueFilters }) {
  const router = useRouter();
  const [draft, setDraft] = useState(filters);
  const facets = useQuery({ queryKey: queryKeys.migration.facets(run.id), queryFn: ({ signal }) => fetchIssueFacets(run.id, signal) });
  const issues = useQuery({
    queryKey: queryKeys.migration.issues(run.id, { ...filters }),
    queryFn: ({ signal }) => fetchIssues(run.id, filters, signal),
  });
  const f = r.issues.filters;
  const go = (next: IssueFilters) => router.push(issueFiltersHref(run.id, next) as Parameters<typeof router.push>[0]);
  const option = (value: string, count: number, label: string) => ({ id: value, label: `${label} (${count})` });
  return (
    <SectionCard
      title={r.issues.title}
      description={r.issues.description}
      actions={
        <LinkButton href={issuesCsvHref(run.id)} size="sm" download>
          {r.issues.csv}
        </LinkButton>
      }
    >
      <div id="issues" className="grid grid-cols-1 gap-4 md:grid-cols-[repeat(3,minmax(0,1fr))_auto] md:items-end">
        <Select
          label={f.severity}
          options={[{ id: "", label: f.any }, ...(facets.data?.severity ?? []).map((x) => option(x.value, x.count, r.severities[x.value] ?? x.value))]}
          value={draft.severity ?? ""}
          onChange={(value) => setDraft((d) => ({ ...d, severity: (ISSUE_SEVERITIES.find((s) => s === value) ?? null) as IssueSeverity | null }))}
        />
        <Select
          label={f.entity}
          options={[{ id: "", label: f.any }, ...(facets.data?.entity ?? []).map((x) => option(x.value, x.count, entityLabel(x.value)))]}
          value={draft.entity ?? ""}
          onChange={(value) => setDraft((d) => ({ ...d, entity: value || null }))}
        />
        <Select
          label={f.code}
          options={[{ id: "", label: f.any }, ...(facets.data?.code ?? []).map((x) => option(x.value, x.count, x.value))]}
          value={draft.code ?? ""}
          onChange={(value) => setDraft((d) => ({ ...d, code: value || null }))}
        />
        <div className="flex gap-2">
          <Button variant="primary" onPress={() => go({ ...draft, offset: 0 })}>
            {f.apply}
          </Button>
          <Button
            onPress={() => {
              const cleared = { severity: null, entity: null, code: null, offset: 0 };
              setDraft(cleared);
              go(cleared);
            }}
          >
            {f.clear}
          </Button>
        </div>
      </div>
      {issues.isPending ? (
        <Loading label={r.issues.title} />
      ) : issues.isError ? (
        <QueryProblem error={issues.error} what={r.issues.title} retry={() => fetchIssues(run.id, filters).then(() => issues.refetch())} />
      ) : (
        <DataTable
          caption={r.issues.caption}
          hideCaption
          columns={issueColumns()}
          rows={issues.data.items}
          rowId={(row) => row.id}
          empty={<EmptyState title={r.issues.empty} />}
          footer={
            issues.data.total > issues.data.limit ? (
              <OffsetPagination
                label={r.issues.pages}
                total={issues.data.total}
                limit={issues.data.limit}
                offset={issues.data.offset}
                shown={issues.data.items.length}
                control={(next) => ({ href: issueFiltersHref(run.id, { ...filters, offset: next }) })}
              />
            ) : null
          }
        />
      )}
    </SectionCard>
  );
}

export function ReportSections({ run, report }: { run: RunDetail; report: RunReport }) {
  const { locale } = useZone();
  const n = (v: number) => formatCount(v, locale);
  const d = r.documents;
  const facts: KeyValue[] = [];
  if (report.challans) {
    facts.push({ term: d.challans, description: n(report.challans.documents), numeric: true });
    facts.push({ term: d.stock, description: n(report.challans.stockMovements), numeric: true });
  }
  if (report.users) {
    facts.push({ term: d.users, description: n(report.users.invitations), numeric: true });
    facts.push({ term: d.historical, description: n(report.users.historical), numeric: true });
    facts.push({ term: d.credentials, description: n(report.users.credentialsDropped), numeric: true });
  }
  facts.push({ term: d.idMaps, description: `${n(report.idMaps.new)} / ${n(report.idMaps.changed)} / ${n(report.idMaps.unchanged)}`, numeric: true });
  if (report.openingLines !== null) facts.push({ term: d.opening, description: n(report.openingLines), numeric: true });
  return (
    <>
      <SectionCard title={r.entities.title} description={r.entities.description}>
        <DataTable caption={r.entities.caption} hideCaption columns={entityColumns(locale)} rows={report.entities} rowId={(row) => row.entity} />
      </SectionCard>
      {report.totals.length > 0 ? (
        <SectionCard title={r.totals.title} description={r.totals.description}>
          <DataTable caption={r.totals.caption} hideCaption columns={totalsColumns(locale)} rows={report.totals} rowId={(row) => row.currency} />
          {report.discrepancies.length > 0 ? (
            <>
              <h3 className="text-base font-semibold text-ink">{r.totals.discrepancies}</h3>
              <DataTable caption={r.totals.discrepancyCaption} hideCaption columns={discrepancyColumns()} rows={report.discrepancies} rowId={(row) => row.key} />
            </>
          ) : null}
        </SectionCard>
      ) : null}
      <SectionCard title={d.title}>
        <KeyValueGrid items={facts} />
      </SectionCard>
      {report.links.length > 0 ? (
        <SectionCard title={r.links.title}>
          <DataTable caption={r.links.caption} hideCaption columns={linkColumns(locale)} rows={report.links} rowId={(row) => row.link} />
        </SectionCard>
      ) : null}
      {report.media ? (
        <SectionCard title={r.media.title}>
          <KeyValueGrid
            items={[
              { term: r.media.accessible, description: n(report.media.accessible), numeric: true },
              { term: r.media.notFetched, description: n(report.media.notFetched), numeric: true },
              { term: r.media.inaccessible, description: n(report.media.inaccessible.length), numeric: true },
            ]}
          />
          {report.media.inaccessible.length > 0 ? (
            <DataTable
              caption={r.media.caption}
              columns={[
                { id: "key", header: r.media.columns.key, isRowHeader: true, mobile: "title", cell: (row) => <span className="font-mono text-xs [overflow-wrap:anywhere]">{row.key}</span> },
                { id: "location", header: r.media.columns.location, cell: (row) => <span className="font-mono text-xs [overflow-wrap:anywhere]">{row.location}</span> },
                { id: "reason", header: r.media.columns.reason, mobile: "status", cell: (row) => row.reason },
              ]}
              rows={report.media.inaccessible}
              rowId={(row) => `${row.key}|${row.location}`}
            />
          ) : null}
        </SectionCard>
      ) : null}
      <SectionCard title={r.files.title} description={report.ignored.length ? r.files.ignored(report.ignored.join(", ")) : undefined}>
        <DataTable caption={r.files.caption} hideCaption columns={fileColumns(locale)} rows={report.files} rowId={(row) => row.file} />
      </SectionCard>
      <span className="sr-only">{run.id}</span>
    </>
  );
}

/** One migration run: source facts, the reconciliation report and the quarantine browser. */
export function RunDetailView({ runId, filters }: { runId: string | null; filters: IssueFilters }) {
  const { permissionKeys } = useSession();
  const allowed = permissionKeys.has(RUN_READ);
  const query = useQuery({
    queryKey: queryKeys.migration.run(runId ?? "none"),
    queryFn: ({ signal }) => fetchRun(runId!, signal),
    enabled: allowed && runId !== null,
  });
  if (!allowed) return <PermissionDenied area={m.area} />;
  if (runId === null || (query.isError && isProblemError(query.error) && query.error.status === 404)) return <NotAvailable />;
  const back = (
    <RacLink href="/settings/migration" className="text-sm text-forest underline underline-offset-2">
      {r.back}
    </RacLink>
  );
  if (query.isPending) return <Loading label={r.what} variant="detail" />;
  if (query.isError) {
    return (
      <div className="flex flex-col gap-6">
        <PageHeader title={m.title} eyebrow={r.eyebrow} nav={back} />
        <QueryProblem error={query.error} what={r.what} retry={() => fetchRun(runId).then(() => query.refetch())} />
      </div>
    );
  }
  const run = query.data;
  const report = readReport(run.report);
  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={r.title(run.source_label)} eyebrow={`${r.eyebrow} · ${m.runs.kinds[run.kind] ?? run.kind}`} nav={back} />
      <SectionCard title={r.source} actions={<RunStatusPill status={run.status} />}>
        <KeyValueGrid
          items={[
            { term: m.runs.columns.started, description: <LocalDateTime value={run.started_at} /> },
            { term: m.runs.columns.by, description: run.started_by_name || "—" },
            { term: r.digest, description: <span title={run.source_digest}>{shortSha(run.source_digest)}</span>, mono: true },
            { term: r.authorisedBy, description: report.authorised ? report.manifest.authorisedBy ?? "—" : r.notAuthorised },
            { term: r.exportedAt, description: report.manifest.exportedAt ? <LocalDateTime value={report.manifest.exportedAt} /> : "—" },
            { term: m.facts.reconciled, description: report.reconciled ? m.yes : m.no },
            ...(run.backup_id ? [{ term: r.backup, description: run.backup_id, mono: true }] : []),
          ]}
        />
        {run.error_detail ? <p className="text-sm text-danger">{run.error_detail}</p> : null}
      </SectionCard>
      {run.status === "completed" || run.kind === "apply" ? <ReportSections run={run} report={report} /> : null}
      <IssueBrowser run={run} filters={filters} />
    </div>
  );
}
