"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { fetchRun, fetchIssues, ISSUE_SEVERITIES, issuesCsvHref, type Issue, type IssueFilters, type IssueSeverity, type RunDetail } from "@/features/migration/api";
import { readReport, type CurrencyTotals, type Discrepancy, type EntityRow, type FileRow, type LinkRow, type RunReport } from "@/features/migration/report";
import { isProblemError } from "@/lib/api/errors";
import { formatCount } from "@/lib/format/money";
import { useSession } from "@/lib/session/context";
import { MIGRATION_READ, useMigrationRun, useRunIssueFacets, useRunIssues } from "~/data/settings-data";
import { Page, PageHeader, RecordHeader, Split } from "~/shell/page";
import { LoadingBlock, NotPermitted } from "~/shell/states";
import { Badge, Banner, Button, ButtonLink, DataTable, DateText, EmptyState, FactStrip, GlassPanel, KeyValue, Money, Select, Tabs, type Column, type KeyValueItem } from "~/ui";
import { MIGRATION_CRUMBS, RUN_KIND, runHref, RunStatus, SEVERITY_LABEL, SeverityBadge, type RunView } from "./migration-shared";
import { entityLabel, Mono, OffsetPager, Quiet, shortSha } from "./shared";
import { ProtectedReadProblem } from "./step-up";

/**
 * One migration run: where the export came from, how every legacy row was accounted for, the
 * source files with their checksums, and the issues browser. One view each, chosen with `?view=`;
 * the issue filters live in the URL.
 */

const PAGE_SIZE = 25;
const STEP_UP_REASON = "Migration reports hold company data. Confirm with your authenticator to see them.";
const none = <Quiet>None</Quiet>;
const CLEARED: IssueFilters = { severity: null, entity: null, code: null, offset: 0 };

// ---- overview ----

function Overview({ run, report }: { run: RunDetail; report: RunReport }) {
  const { zone } = useSession();
  const n = (value: number) => <span className="lk-tnum">{formatCount(value, zone.locale)}</span>;
  const source: KeyValueItem[] = [
    { label: "Started", value: <DateText value={run.started_at} style="dayTime" /> },
    { label: "Run by", value: run.started_by_name || null },
    { label: "Export digest", value: <Mono title={run.source_digest}>{shortSha(run.source_digest)}</Mono> },
    { label: "Authorised by", value: report.authorised ? report.manifest.authorisedBy : <span className="text-ember-text">Not recorded, so an apply is refused</span> },
    { label: "Exported", value: report.manifest.exportedAt ? <DateText value={report.manifest.exportedAt} style="dayTime" /> : null },
    { label: "Every row accounted for", value: report.reconciled ? "Yes" : "No" },
    ...(run.backup_id ? [{ label: "Backup relied on", value: <Mono>{run.backup_id}</Mono> }] : []),
  ];
  const documents: KeyValueItem[] = [];
  if (report.challans) {
    documents.push({ label: "Old challans, kept as documents", value: n(report.challans.documents) });
    documents.push({ label: "Stock movements planned from them", value: n(report.challans.stockMovements) });
  }
  if (report.users) {
    documents.push({ label: "People to invite", value: n(report.users.invitations) });
    documents.push({ label: "Past people kept for attribution", value: n(report.users.historical) });
    documents.push({ label: "Old password hashes dropped", value: n(report.users.credentialsDropped) });
  }
  documents.push({
    label: "ID maps: new, changed, unchanged",
    value: (
      <span className="lk-tnum">
        {formatCount(report.idMaps.new, zone.locale)} · {formatCount(report.idMaps.changed, zone.locale)} · {formatCount(report.idMaps.unchanged, zone.locale)}
      </span>
    ),
  });
  if (report.openingLines !== null) documents.push({ label: "Opening balance lines, in their own batch", value: n(report.openingLines) });

  return (
    <Split
      main={
        <GlassPanel padding="lg" className="rise" title="Where the export came from" titleAs="h2">
          <div className="flex min-w-0 flex-col gap-5">
            {run.error_detail ? (
              <Banner tone="ember" title="The run stopped.">
                {run.error_detail}
              </Banner>
            ) : null}
            <KeyValue rows items={source} />
          </div>
        </GlassPanel>
      }
      aside={
        <GlassPanel title="Documents and people" titleAs="h2" className="rise">
          <KeyValue rows items={documents} />
        </GlassPanel>
      }
    />
  );
}

// ---- reconciliation ----

function entityColumns(locale: string): Column<EntityRow>[] {
  const n = (value: number) => <span className="lk-tnum">{formatCount(value, locale)}</span>;
  return [
    {
      key: "entity",
      header: "Collection",
      primary: true,
      cell: (row) => (
        <span className="flex min-w-0 flex-wrap items-center gap-2">
          <span className="t-label text-ink">{entityLabel(row.entity)}</span>
          {row.balanced ? (
            <Badge tone="leaf" size="sm" icon="check">
              Balanced
            </Badge>
          ) : (
            <Badge tone="ember" size="sm" icon="alert">
              Not balanced
            </Badge>
          )}
        </span>
      ),
    },
    { key: "rows", header: "Rows", mobileLabel: "Rows", numeric: true, cell: (row) => n(row.rows) },
    { key: "accepted", header: "Accepted", mobileLabel: "Accepted", numeric: true, cell: (row) => n(row.accepted) },
    { key: "held", header: "Held back", mobileLabel: "Held back", numeric: true, cell: (row) => n(row.quarantined) },
    { key: "rejected", header: "Rejected", mobileLabel: "Rejected", numeric: true, cell: (row) => n(row.rejected) },
    { key: "repeats", header: "Exact repeats", mobileLabel: "Exact repeats", numeric: true, cell: (row) => n(row.repeats) },
  ];
}

const amount = (value: string | null, currency: string) => (value === null ? none : <Money value={{ amount: value, currency }} />);

function totalsColumns(locale: string): Column<CurrencyTotals>[] {
  return [
    {
      key: "currency",
      header: "Currency",
      primary: true,
      cell: (row) => (
        <span className="flex flex-col gap-0.5">
          <Mono>{row.currency}</Mono>
          <span className="t-caption text-ink-3">{row.sourceQuotes === 1 ? "1 quotation" : `${formatCount(row.sourceQuotes, locale)} quotations`}</span>
        </span>
      ),
    },
    { key: "export", header: "Export total", mobileLabel: "Export total", numeric: true, cell: (row) => amount(row.sourceTotal, row.currency) },
    { key: "accepted", header: "Accepted total", mobileLabel: "Accepted total", numeric: true, cell: (row) => amount(row.acceptedTotal, row.currency) },
    { key: "lines", header: "From the lines", mobileLabel: "From the lines", numeric: true, cell: (row) => amount(row.recomputedTotal, row.currency) },
    {
      key: "difference",
      header: "Difference",
      mobileLabel: "Difference",
      numeric: true,
      cell: (row) => (
        <span className="flex flex-col items-end gap-0.5">
          {amount(row.difference, row.currency)}
          <span className="t-caption lk-tnum text-ink-3">{row.discrepant === 1 ? "1 quotation differs" : `${formatCount(row.discrepant, locale)} quotations differ`}</span>
        </span>
      ),
    },
  ];
}

const discrepancyColumns: Column<Discrepancy>[] = [
  { key: "quote", header: "Quotation", primary: true, cell: (row) => <Mono>{row.quoteNumber ?? row.key}</Mono> },
  { key: "currency", header: "Currency", mobileLabel: "Currency", cell: (row) => <Mono>{row.currency}</Mono> },
  { key: "legacy", header: "Old total", mobileLabel: "Old total", numeric: true, cell: (row) => amount(row.legacy, row.currency) },
  { key: "lines", header: "From the lines", mobileLabel: "From the lines", numeric: true, cell: (row) => amount(row.lines, row.currency) },
  { key: "difference", header: "Difference", mobileLabel: "Difference", numeric: true, cell: (row) => amount(row.difference, row.currency) },
];

function linkColumns(locale: string): Column<LinkRow>[] {
  const n = (value: number | null) => (value === null ? none : <span className="lk-tnum">{formatCount(value, locale)}</span>);
  return [
    { key: "link", header: "Link", primary: true, cell: (row) => <Mono>{row.link.replace("->", " → ")}</Mono> },
    { key: "linked", header: "Linked", mobileLabel: "Linked", numeric: true, cell: (row) => n(row.linked) },
    { key: "orphans", header: "Orphans", mobileLabel: "Orphans", numeric: true, cell: (row) => n(row.orphans) },
    { key: "unresolved", header: "Unresolved", mobileLabel: "Unresolved", numeric: true, cell: (row) => n(row.unresolved) },
  ];
}

function Reconciliation({ report }: { report: RunReport }) {
  const { zone } = useSession();
  return (
    <div className="stack">
      <GlassPanel as="section" padding="none" className="rise" title="Rows by collection" titleAs="h2" eyebrow="Every source row has exactly one outcome">
        <DataTable label="Rows per legacy collection" columns={entityColumns(zone.locale)} rows={report.entities} rowKey={(row) => row.entity} empty={<EmptyState compact icon="database" title="No collection in this report" text="The export held nothing this run could read." />} />
      </GlassPanel>
      {report.totals.length > 0 ? (
        <GlassPanel as="section" padding="none" className="rise" title="Quotation totals by currency" titleAs="h2" eyebrow="Issued quotations are kept exactly as exported">
          <div className="flex min-w-0 flex-col gap-5">
            <p className="t-body-sm px-6 text-ink-2">Old totals are compared with their lines. A difference is reported, never rewritten.</p>
            <DataTable label="Old quotation totals by currency" columns={totalsColumns(zone.locale)} rows={report.totals} rowKey={(row) => row.currency} />
          </div>
        </GlassPanel>
      ) : null}
      {report.discrepancies.length > 0 ? (
        <GlassPanel as="section" padding="none" className="rise" title="Quotations whose old total differs from their lines" titleAs="h2">
          <DataTable label="Old total discrepancies" columns={discrepancyColumns} rows={report.discrepancies} rowKey={(row) => row.key} />
        </GlassPanel>
      ) : null}
      {report.links.length > 0 ? (
        <GlassPanel as="section" padding="none" className="rise" title="Links between collections" titleAs="h2">
          <DataTable label="Links between collections" columns={linkColumns(zone.locale)} rows={report.links} rowKey={(row) => row.link} />
        </GlassPanel>
      ) : null}
    </div>
  );
}

// ---- files ----

function fileColumns(locale: string): Column<FileRow>[] {
  return [
    { key: "file", header: "File", primary: true, cell: (row) => <Mono>{row.file}</Mono> },
    { key: "collection", header: "Collection", mobileLabel: "Collection", cell: (row) => entityLabel(row.entity) },
    { key: "format", header: "Format", mobileLabel: "Format", cell: (row) => row.format.toUpperCase() },
    { key: "rows", header: "Rows", mobileLabel: "Rows", numeric: true, cell: (row) => <span className="lk-tnum">{formatCount(row.rows, locale)}</span> },
    { key: "sha", header: "SHA-256", mobileLabel: "SHA-256", cell: (row) => <Mono title={row.sha256} className="select-all">{shortSha(row.sha256) ?? ""}</Mono> },
  ];
}

const mediaColumns: Column<{ key: string; location: string; reason: string }>[] = [
  { key: "key", header: "Media", primary: true, cell: (row) => <Mono>{row.key}</Mono> },
  { key: "location", header: "Location", mobileLabel: "Location", cell: (row) => <Mono>{row.location}</Mono> },
  { key: "reason", header: "Reason", mobileLabel: "Reason", cell: (row) => row.reason },
];

function Files({ report }: { report: RunReport }) {
  const { zone } = useSession();
  const n = (value: number) => <span className="lk-tnum">{formatCount(value, zone.locale)}</span>;
  return (
    <div className="stack">
      <GlassPanel as="section" padding="none" className="rise" title="Files and checksums" titleAs="h2">
        <div className="flex min-w-0 flex-col gap-4">
          {report.ignored.length ? <p className="t-body-sm px-6 text-ink-2">Not read, because they are not collections from the old system: {report.ignored.join(", ")}.</p> : null}
          <DataTable label="Source files with their SHA-256" columns={fileColumns(zone.locale)} rows={report.files} rowKey={(row) => row.file} empty={<EmptyState compact icon="file" title="No file was read" text="The export folder held no file this run recognised." />} />
        </div>
      </GlassPanel>
      {report.media ? (
        <GlassPanel as="section" padding="lg" className="rise" title="Media" titleAs="h2">
          <div className="flex min-w-0 flex-col gap-5">
            <KeyValue
              columns={3}
              items={[
                { label: "Files hashed", value: n(report.media.accessible) },
                { label: "Remote links not downloaded", value: n(report.media.notFetched) },
                { label: "Links that could not be read", value: n(report.media.inaccessible.length) },
              ]}
            />
            {report.media.inaccessible.length > 0 ? (
              <GlassPanel variant="outline" padding="none">
                <DataTable label="Media that could not be read" columns={mediaColumns} rows={report.media.inaccessible} rowKey={(row) => `${row.key}|${row.location}`} />
              </GlassPanel>
            ) : null}
          </div>
        </GlassPanel>
      ) : null}
    </div>
  );
}

// ---- issues ----

function rowReference(issue: Issue): string {
  return [issue.source_file, issue.row_number !== null ? `row ${issue.row_number}` : null, issue.source_key].filter(Boolean).join(" · ");
}

const issueColumns: Column<Issue>[] = [
  {
    key: "reference",
    header: "Row",
    primary: true,
    width: "28%",
    cell: (issue) => (
      <span className="flex min-w-0 flex-col gap-0.5">
        <span className="t-label text-ink">{entityLabel(issue.entity)}</span>
        <Mono className="text-ink-3">{rowReference(issue) || "No row reference"}</Mono>
      </span>
    ),
  },
  { key: "severity", header: "Kind", mobileLabel: "Kind", cell: (issue) => <SeverityBadge severity={issue.severity} /> },
  { key: "code", header: "Code", mobileLabel: "Code", cell: (issue) => <Mono>{issue.code}</Mono> },
  {
    key: "message",
    header: "What was found",
    mobileLabel: "What was found",
    cell: (issue) => (
      <span className="flex min-w-0 flex-col gap-1">
        <span className="t-body-sm">{issue.message}</span>
        {issue.raw_value ? <Mono className="text-ink-3">{issue.raw_value}</Mono> : null}
        {issue.raw ? (
          <details className="t-body-sm">
            <summary className="cursor-pointer text-gold-strong">Values as exported</summary>
            <dl className="mt-2 flex flex-col gap-1">
              {Object.entries(issue.raw).map(([key, value]) => (
                <div key={key} className="flex min-w-0 flex-wrap gap-x-2">
                  <dt className="t-code-sm lk-mono text-ink-3">{key}</dt>
                  <dd className="t-code-sm lk-mono min-w-0 [overflow-wrap:anywhere]">{typeof value === "string" ? value : JSON.stringify(value)}</dd>
                </div>
              ))}
            </dl>
          </details>
        ) : null}
      </span>
    ),
  },
];

const ANY = "any";

function Issues({ run, filters }: { run: RunDetail; filters: IssueFilters }) {
  const router = useRouter();
  const [draft, setDraft] = useState(filters);
  const facets = useRunIssueFacets(run.id);
  const issues = useRunIssues(run.id, filters);
  const go = (next: IssueFilters) => router.push(runHref(run.id, "issues", next));
  const option = (value: string, count: number, label: string) => ({ value, label: `${label} (${count})` });
  const filtered = Boolean(filters.severity || filters.entity || filters.code);

  return (
    <div className="stack">
      <form
        className="grid min-w-0 grid-cols-1 gap-4 md:grid-cols-[repeat(3,minmax(0,1fr))_auto] md:items-end"
        onSubmit={(event) => {
          event.preventDefault();
          go({ ...draft, offset: 0 });
        }}
      >
        <Select
          label="Kind"
          options={[{ value: ANY, label: "Every kind" }, ...(facets.data?.severity ?? []).map((facet) => option(facet.value, facet.count, SEVERITY_LABEL[facet.value] ?? facet.value))]}
          value={draft.severity ?? ANY}
          onChange={(value) => setDraft((current) => ({ ...current, severity: (ISSUE_SEVERITIES.find((severity) => severity === value) ?? null) as IssueSeverity | null }))}
        />
        <Select
          label="Collection"
          options={[{ value: ANY, label: "Every collection" }, ...(facets.data?.entity ?? []).map((facet) => option(facet.value, facet.count, entityLabel(facet.value)))]}
          value={draft.entity ?? ANY}
          onChange={(value) => setDraft((current) => ({ ...current, entity: value === ANY ? null : value }))}
        />
        <Select
          label="Code"
          options={[{ value: ANY, label: "Every code" }, ...(facets.data?.code ?? []).map((facet) => option(facet.value, facet.count, facet.value))]}
          value={draft.code ?? ANY}
          onChange={(value) => setDraft((current) => ({ ...current, code: value === ANY ? null : value }))}
        />
        <div className="flex gap-2">
          <Button type="submit" variant="inverse">
            Show issues
          </Button>
          {filtered ? (
            <Button
              variant="ghost"
              onPress={() => {
                setDraft(CLEARED);
                go(CLEARED);
              }}
            >
              Clear
            </Button>
          ) : null}
        </div>
      </form>
      {issues.isError && !issues.data ? (
        <ProtectedReadProblem error={issues.error} what="The issues" reason={STEP_UP_REASON} retry={() => fetchIssues(run.id, filters).then(() => issues.refetch())} />
      ) : (
        <GlassPanel padding="none">
          <DataTable
            label="Issues of this run"
            columns={issueColumns}
            rows={issues.data?.items ?? []}
            rowKey={(issue) => issue.id}
            loading={issues.isPending}
            skeletonRows={6}
            empty={
              filtered ? (
                <EmptyState
                  compact
                  icon="search"
                  title="No issue matches these filters"
                  text="Choose every kind, collection and code to see the rest."
                  actions={
                    <ButtonLink href={runHref(run.id, "issues", CLEARED)} variant="secondary" size="sm">
                      Clear the filters
                    </ButtonLink>
                  }
                />
              ) : (
                <EmptyState compact icon="checkCircle" title="This run found no issue" text="Every row in the export was read without a problem." />
              )
            }
          />
        </GlassPanel>
      )}
      {issues.data ? <OffsetPager data={issues.data} noun="issues" label="Issue pages" fallbackLimit={PAGE_SIZE} hrefFor={(offset) => runHref(run.id, "issues", { ...filters, offset })} /> : null}
    </div>
  );
}

// ---- the screen ----

export function MigrationRun({ runId, view, filters }: { runId: string | null; view: RunView; filters: IssueFilters }) {
  const { permissionKeys, zone } = useSession();
  const allowed = permissionKeys.has(MIGRATION_READ);
  const query = useMigrationRun(runId, allowed);

  const plainHeader = <PageHeader breadcrumb={MIGRATION_CRUMBS} title="Migration run" />;
  if (!allowed) {
    return (
      <Page>
        {plainHeader}
        <NotPermitted what="Migration" icon="database" />
      </Page>
    );
  }
  if (runId === null || (query.isError && isProblemError(query.error) && query.error.status === 404)) {
    return (
      <Page>
        {plainHeader}
        <GlassPanel padding="lg">
          <EmptyState
            icon="search"
            title="This run is not here"
            text="It does not exist, or it belongs to another company."
            actions={
              <ButtonLink href="/settings/migration" variant="secondary">
                See every run
              </ButtonLink>
            }
          />
        </GlassPanel>
      </Page>
    );
  }
  if (query.isPending) {
    return (
      <Page>
        <LoadingBlock lines={10} label="Loading the run" />
      </Page>
    );
  }
  if (query.isError) {
    return (
      <Page>
        {plainHeader}
        <ProtectedReadProblem error={query.error} what="This run" reason={STEP_UP_REASON} retry={() => fetchRun(runId).then(() => query.refetch())} />
      </Page>
    );
  }

  const run = query.data;
  const report = readReport(run.report);
  const hasReport = run.status === "completed" || run.kind === "apply";
  const selected: RunView = !hasReport && (view === "reconciliation" || view === "files") ? "overview" : view;
  const tabs = [
    { id: "overview", label: "Overview", href: runHref(run.id, "overview") },
    ...(hasReport
      ? [
          { id: "reconciliation", label: "Reconciliation", href: runHref(run.id, "reconciliation") },
          { id: "files", label: "Files", count: report.files.length, href: runHref(run.id, "files") },
        ]
      : []),
    { id: "issues", label: "Issues", count: run.issue_count, href: runHref(run.id, "issues", CLEARED) },
  ];

  return (
    <Page>
      <RecordHeader
        breadcrumb={MIGRATION_CRUMBS}
        code={`${RUN_KIND[run.kind] ?? run.kind} · migration run`}
        title={<span className="[overflow-wrap:anywhere]">Run over {run.source_label}</span>}
        status={<RunStatus status={run.status} />}
        facts={
          <FactStrip
            items={[
              { label: "Started", value: <DateText value={run.started_at} style="dayTime" /> },
              { label: "Issues", value: <span className="lk-tnum">{formatCount(run.issue_count, zone.locale)}</span> },
              { label: "Held back", value: <span className="lk-tnum">{formatCount(run.quarantined_count, zone.locale)}</span> },
              { label: "Rows accounted for", value: report.reconciled ? "Every one" : "Not all" },
            ]}
          />
        }
        actions={
          <ButtonLink external href={issuesCsvHref(run.id)} download variant="secondary" iconLeft="download">
            Download issues
          </ButtonLink>
        }
      >
        <Tabs label="Views of this run" selectedKey={selected} tabs={tabs} />
      </RecordHeader>

      {selected === "reconciliation" ? (
        <Reconciliation report={report} />
      ) : selected === "files" ? (
        <Files report={report} />
      ) : selected === "issues" ? (
        <Issues key={JSON.stringify(filters)} run={run} filters={filters} />
      ) : (
        <Overview run={run} report={report} />
      )}
    </Page>
  );
}
