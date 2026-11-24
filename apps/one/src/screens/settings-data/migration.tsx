"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import {
  CANDIDATE_STATUSES,
  decideCandidate,
  fetchCandidates,
  fetchOpeningBatches,
  fetchRuns,
  type Candidate,
  type CandidateDecision,
  type CandidateStatus,
  type OpeningBatch,
  type Page as ResultPage,
  type RunSummary,
} from "@/features/migration/api";
import { ProblemError } from "@/lib/api/errors";
import { formatCount } from "@/lib/format/money";
import { useSession } from "@/lib/session/context";
import { CANDIDATE_UPDATE, MIGRATION_READ, useCandidates, useMigrationRuns, useOpeningBatches } from "~/data/settings-data";
import { Page, PageHeader } from "~/shell/page";
import { LoadingBlock, NotPermitted } from "~/shell/states";
import {
  Banner,
  Button,
  DataTable,
  DateText,
  EmptyState,
  GlassPanel,
  SegmentedControl,
  StatRow,
  StatTile,
  Tabs,
  TextLink,
  toast,
  type Column,
} from "~/ui";
import { migrationHref, RUN_KIND, runHref, RunStatus, type MigrationView } from "./migration-shared";
import { asRoute, Mono, OffsetPager, Quiet, ServerCommand, SETTINGS_CRUMBS, StatusBadge, type StatusLook } from "./shared";
import { ProtectedReadProblem } from "./step-up";

/**
 * Bringing the old system's data across: dry runs and their reports, the legacy customer names
 * waiting for a decision, and the opening stock batches. Runs start on the server; this screen reads
 * them and records the customer decisions. Migration reports are protected reads (second factor).
 */

const PAGE_SIZE = 25;
const STEP_UP_REASON = "Migration reports hold company data. Confirm with your authenticator to see them.";

// ---- runs ----

function runColumns(locale: string): Column<RunSummary>[] {
  return [
    { key: "started", header: "Started", primary: true, cell: (run) => <DateText value={run.started_at} style="dayTime" /> },
    { key: "kind", header: "Kind", mobileLabel: "Kind", cell: (run) => RUN_KIND[run.kind] ?? run.kind },
    { key: "export", header: "Export", mobileLabel: "Export", cell: (run) => <Mono>{run.source_label}</Mono> },
    { key: "status", header: "Status", mobileLabel: "Status", cell: (run) => <RunStatus status={run.status} size="sm" /> },
    {
      key: "issues",
      header: "Issues",
      mobileLabel: "Issues",
      numeric: true,
      cell: (run) => (
        <span className="flex flex-col items-end gap-0.5">
          <span className="lk-tnum">{formatCount(run.issue_count, locale)}</span>
          {run.quarantined_count > 0 ? <span className="t-caption lk-tnum text-ink-3">{formatCount(run.quarantined_count, locale)} held back</span> : null}
        </span>
      ),
    },
    { key: "by", header: "Run by", mobileLabel: "Run by", hideOnMobile: true, cell: (run) => run.started_by_name || <Quiet>Unknown</Quiet> },
  ];
}

function LatestRun({ run }: { run: RunSummary }) {
  const { zone } = useSession();
  const none = { severity: null, entity: null, code: null, offset: 0 } as const;
  return (
    <GlassPanel
      as="section"
      padding="lg"
      className="rise"
      eyebrow="Latest run"
      title={<DateText value={run.started_at} style="dayTime" />}
      titleAs="h2"
      action={<RunStatus status={run.status} />}
    >
      <StatRow>
        <StatTile label="Issues" value={<span className="lk-tnum">{formatCount(run.issue_count, zone.locale)}</span>} href={runHref(run.id, "issues", none)} foot="Open the report" />
        <StatTile
          label="Held back"
          value={<span className="lk-tnum">{formatCount(run.quarantined_count, zone.locale)}</span>}
          href={runHref(run.id, "issues", { ...none, severity: "quarantine" })}
          foot="Rows kept aside for a look"
        />
        <StatTile
          label="Rejected"
          value={<span className="lk-tnum">{formatCount(run.error_count, zone.locale)}</span>}
          href={runHref(run.id, "issues", { ...none, severity: "error" })}
          foot="Rows that cannot be brought over"
        />
      </StatRow>
    </GlassPanel>
  );
}

function Runs({ offset }: { offset: number }) {
  const { zone } = useSession();
  const runs = useMigrationRuns(offset);
  if (runs.isPending) return <LoadingBlock lines={8} label="Loading the migration runs" />;
  if (runs.isError) return <ProtectedReadProblem error={runs.error} what="The migration runs" reason={STEP_UP_REASON} retry={() => fetchRuns(offset).then(() => runs.refetch())} />;
  const page: ResultPage<RunSummary> = runs.data;
  const latest = offset === 0 ? page.items[0] : undefined;
  return (
    <div className="stack">
      {latest ? <LatestRun run={latest} /> : null}
      <GlassPanel as="section" padding="none" className="rise" title="Run history" titleAs="h2">
        <DataTable
          label="Migration runs, newest first"
          columns={runColumns(zone.locale)}
          rows={page.items}
          rowKey={(run) => run.id}
          rowHref={(run) => runHref(run.id, "overview")}
          empty={
            <EmptyState
              icon="database"
              title="Run the first dry run"
              text="A dry run reads the old system's export and writes nothing but its report. Start it on the server; the report appears here."
              actions={<ServerCommand>lk migration dry-run --source &lt;export folder&gt;</ServerCommand>}
            />
          }
        />
      </GlassPanel>
      <OffsetPager data={page} noun="runs" label="Run pages" fallbackLimit={PAGE_SIZE} hrefFor={(next) => migrationHref("runs", next)} />
      {page.items.length > 0 ? (
        <div className="flex min-w-0 flex-wrap items-center gap-3">
          <span className="t-body-sm text-ink-2">Start another dry run on the server:</span>
          <ServerCommand>lk migration dry-run --source &lt;export folder&gt;</ServerCommand>
        </div>
      ) : null}
    </div>
  );
}

// ---- legacy customer names ----

const CANDIDATE_STATUS: Record<string, StatusLook> = {
  proposed: { label: "To review", tone: "amber" },
  linked: { label: "Linked", tone: "leaf" },
  new_party: { label: "New customer", tone: "cobalt" },
  rejected: { label: "Not a customer", tone: "neutral" },
};
const MATCH: Record<string, string> = { exact_name: "same name", name_tokens: "similar name", ambiguous: "several match", none: "no match" };
const ANY = "any";

function CandidateActions({ candidate }: { candidate: Candidate }) {
  const queryClient = useQueryClient();
  const decide = useMutation({
    mutationFn: ({ decision, partyId }: { decision: CandidateDecision; partyId: string | null }) => decideCandidate(candidate, decision, partyId),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["migration", "candidates"] }),
    onError: (error) =>
      toast.error("The decision was not saved", {
        description: error instanceof ProblemError ? (error.detail ?? error.title) : "Check your connection and try again.",
      }),
  });
  const open = candidate.capabilities.decide?.allowed ?? false;
  const busy = decide.isPending;
  const run = (decision: CandidateDecision, partyId: string | null = null) => decide.mutate({ decision, partyId });
  if (!open) {
    return (
      <Button size="sm" variant="ghost" iconLeft="undo" loading={busy} onPress={() => run("reopen")} aria-label={`Reopen ${candidate.legacy_name}`}>
        Reopen
      </Button>
    );
  }
  const suggested = candidate.suggested_party;
  return (
    <div className="flex flex-wrap gap-2">
      {suggested ? (
        <Button size="sm" variant="inverse" iconLeft="link" isDisabled={busy} onPress={() => run("link", suggested.id)}>
          Link to {suggested.display_name}
        </Button>
      ) : null}
      <Button size="sm" variant="secondary" isDisabled={busy} onPress={() => run("new_party")} aria-label={`Make ${candidate.legacy_name} a new customer`}>
        New customer
      </Button>
      <Button size="sm" variant="ghost" isDisabled={busy} onPress={() => run("reject")} aria-label={`${candidate.legacy_name} is not a customer`}>
        Not a customer
      </Button>
    </div>
  );
}

function candidateColumns(locale: string, canDecide: boolean): Column<Candidate>[] {
  const columns: Column<Candidate>[] = [
    {
      key: "name",
      header: "Name in the old system",
      primary: true,
      cell: (row) => (
        <span className="flex min-w-0 flex-col gap-0.5">
          <span className="t-label text-ink [overflow-wrap:anywhere]">{row.legacy_name}</span>
          <span className="t-caption text-ink-3">
            {row.variants.length === 1 ? "1 spelling" : `${row.variants.length} spellings`}
            {row.legacy_country || row.country_key ? ` · ${row.legacy_country || row.country_key}` : ""}
          </span>
        </span>
      ),
    },
    { key: "seen", header: "Seen", mobileLabel: "Seen", numeric: true, cell: (row) => <span className="lk-tnum">{formatCount(row.occurrences, locale)}</span> },
    {
      key: "match",
      header: "Matching customer",
      mobileLabel: "Matching customer",
      cell: (row) => {
        const party = row.linked_party ?? row.suggested_party;
        if (!party) return <Quiet>{row.match_kind === "ambiguous" ? "Several match" : "No suggestion"}</Quiet>;
        return (
          <span className="flex min-w-0 flex-col gap-0.5">
            <TextLink href={asRoute(party.path)}>{party.display_name}</TextLink>
            <span className="t-caption text-ink-3">
              <Mono>{party.party_number}</Mono> · {MATCH[row.match_kind] ?? row.match_kind}
            </span>
          </span>
        );
      },
    },
    { key: "status", header: "Status", mobileLabel: "Status", cell: (row) => <StatusBadge look={CANDIDATE_STATUS[row.status] ?? { label: row.status, tone: "neutral" }} size="sm" /> },
  ];
  if (canDecide) columns.push({ key: "decide", header: "Decision", mobileLabel: "Decision", cell: (row) => <CandidateActions candidate={row} /> });
  return columns;
}

function CustomerNames() {
  const { permissionKeys, zone } = useSession();
  const [status, setStatus] = useState<CandidateStatus | null>("proposed");
  const [offset, setOffset] = useState(0);
  const query = useCandidates(status, offset);
  return (
    <div className="stack">
      <p className="t-body max-w-[68ch] text-ink-2">
        Old quotations name customers as free text. Similar spellings are grouped and a matching customer is suggested. Nothing is merged until someone decides.
      </p>
      <SegmentedControl
        label="Status"
        value={status ?? ANY}
        onChange={(value) => {
          setOffset(0);
          setStatus(CANDIDATE_STATUSES.find((candidate) => candidate === value) ?? null);
        }}
        options={[...CANDIDATE_STATUSES.map((value) => ({ value, label: CANDIDATE_STATUS[value]?.label ?? value })), { value: ANY, label: "All" }]}
      />
      {query.isError && !query.data ? (
        <ProtectedReadProblem error={query.error} what="The legacy customer names" reason={STEP_UP_REASON} retry={() => fetchCandidates(status, offset).then(() => query.refetch())} />
      ) : (
        <GlassPanel padding="none">
          <DataTable
            label="Legacy customer names to review"
            columns={candidateColumns(zone.locale, permissionKeys.has(CANDIDATE_UPDATE))}
            rows={query.data?.items ?? []}
            rowKey={(row) => row.id}
            loading={query.isPending}
            skeletonRows={5}
            empty={
              <EmptyState
                compact
                icon="users"
                title={status === "proposed" ? "No name is waiting for a decision" : "No name here yet"}
                text={status === "proposed" ? "Every legacy customer name from the dry runs has been decided." : "Legacy names appear here after a dry run reads the old quotations."}
              />
            }
          />
        </GlassPanel>
      )}
      {query.data ? <OffsetPager data={query.data} noun="names" label="Customer name pages" fallbackLimit={PAGE_SIZE} onOffset={setOffset} /> : null}
    </div>
  );
}

// ---- opening balances ----

const OPENING_STATUS: Record<string, StatusLook> = {
  staged: { label: "Staged", tone: "amber" },
  approved: { label: "Approved", tone: "cobalt" },
  posted: { label: "Posted", tone: "leaf" },
  rejected: { label: "Rejected", tone: "neutral" },
};

function openingColumns(locale: string): Column<OpeningBatch>[] {
  return [
    { key: "staged", header: "Staged", primary: true, cell: (row) => <DateText value={row.created_at} style="dayTime" /> },
    { key: "status", header: "Status", mobileLabel: "Status", cell: (row) => <StatusBadge look={OPENING_STATUS[row.status] ?? { label: row.status, tone: "neutral" }} size="sm" /> },
    { key: "lines", header: "Lines", mobileLabel: "Lines", numeric: true, cell: (row) => <span className="lk-tnum">{formatCount(row.line_count, locale)}</span> },
    { key: "held", header: "Held back", mobileLabel: "Held back", numeric: true, cell: (row) => <span className="lk-tnum">{formatCount(row.quarantined_count, locale)}</span> },
    {
      key: "totals",
      header: "Quantity by unit",
      mobileLabel: "Quantity by unit",
      cell: (row) => {
        const entries = Object.entries(row.totals);
        return entries.length ? <span className="lk-tnum">{entries.map(([uom, qty]) => `${String(qty)} ${uom}`).join(", ")}</span> : <Quiet>None</Quiet>;
      },
    },
    { key: "approved", header: "Approved by", mobileLabel: "Approved by", cell: (row) => row.approved_by_name ?? <Quiet>Not yet</Quiet> },
  ];
}

function OpeningBalances() {
  const { zone } = useSession();
  const query = useOpeningBatches();
  const posterMissing = query.data?.items.some((batch) => !batch.poster_available);
  return (
    <div className="stack">
      <p className="t-body max-w-[68ch] text-ink-2">
        Stock starts from an authorised count, staged as its own batch and approved by a second person. Challans from the old system never create stock.
      </p>
      {query.isError && !query.data ? (
        <ProtectedReadProblem error={query.error} what="The opening balances" reason={STEP_UP_REASON} retry={() => fetchOpeningBatches().then(() => query.refetch())} />
      ) : (
        <GlassPanel padding="none">
          <DataTable
            label="Opening balance batches"
            columns={openingColumns(zone.locale)}
            rows={query.data?.items ?? []}
            rowKey={(row) => row.id}
            loading={query.isPending}
            skeletonRows={3}
            empty={<EmptyState compact icon="boxes" title="No opening batch staged" text="A migration run stages the counted opening stock here for a second person to approve." />}
          />
        </GlassPanel>
      )}
      {posterMissing ? (
        <Banner tone="amber" title="These lines are not posted to stock yet.">
          Record opening stock as a stock opening batch under Operations.
        </Banner>
      ) : null}
    </div>
  );
}

// ---- the screen ----

export function Migration({ view, offset }: { view: MigrationView; offset: number }) {
  const { permissionKeys } = useSession();
  const allowed = permissionKeys.has(MIGRATION_READ);

  const header = (
    <PageHeader
      breadcrumb={SETTINGS_CRUMBS}
      title="Migration"
      lead="Bring the old system's data across safely. Dry runs read an authorised export and change nothing; the apply runs on the server and needs a fresh, rehearsed backup."
    />
  );

  if (!allowed) {
    return (
      <Page>
        {header}
        <NotPermitted what="Migration" icon="database" />
      </Page>
    );
  }

  return (
    <Page>
      {header}
      <Tabs
        label="Migration views"
        selectedKey={view}
        tabs={[
          { id: "runs", label: "Runs", href: migrationHref("runs") },
          { id: "customers", label: "Customer names", href: migrationHref("customers") },
          { id: "opening", label: "Opening balances", href: migrationHref("opening") },
        ]}
      />
      {view === "customers" ? <CustomerNames /> : view === "opening" ? <OpeningBalances /> : <Runs offset={offset} />}
    </Page>
  );
}
