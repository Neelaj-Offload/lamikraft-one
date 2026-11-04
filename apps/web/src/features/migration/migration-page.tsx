"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link as RacLink } from "react-aria-components";
import { StatusPill } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DataTable, OffsetPagination, type DataTableColumn } from "@/components/ui/data-table";
import { FactStrip } from "@/components/ui/fact-strip";
import { LocalDateTime } from "@/components/ui/format";
import { PageHeader } from "@/components/ui/page-header";
import { SectionCard } from "@/components/ui/section-card";
import { Select } from "@/components/ui/select";
import { EmptyState, ErrorState, Loading, PermissionDenied } from "@/components/ui/states";
import { SettingsAreaNav } from "@/features/settings/settings-hub";
import { queryKeys } from "@/lib/api/query-keys";
import { formatCount } from "@/lib/format/money";
import { useSession, useZone } from "@/lib/session/context";
import { migrationMessages as m } from "@/messages/migration";
import { settingsMessages } from "@/messages/settings";
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
  type Page,
  type RunSummary,
} from "./api";
import { CANDIDATE_TONE, QueryProblem, RunStatusPill } from "./shared";

export const RUN_READ = "migration.run.read";
export const CANDIDATE_UPDATE = "migration.party_candidate.update";

function runColumns(locale: string): DataTableColumn<RunSummary>[] {
  const c = m.runs.columns;
  return [
    {
      id: "started",
      header: c.started,
      isRowHeader: true,
      mobile: "title",
      cell: (row) => (
        <RacLink href={row.path} className="font-semibold text-ink underline-offset-2 hover:underline">
          <LocalDateTime value={row.started_at} />
        </RacLink>
      ),
      mobileCell: (row) => <LocalDateTime value={row.started_at} />,
    },
    { id: "kind", header: c.kind, mobile: "meta", cell: (row) => m.runs.kinds[row.kind] ?? row.kind },
    { id: "source", header: c.source, cell: (row) => <span className="font-mono text-xs [overflow-wrap:anywhere]">{row.source_label}</span> },
    { id: "status", header: c.status, mobile: "status", cell: (row) => <RunStatusPill status={row.status} /> },
    {
      id: "issues",
      header: c.issues,
      numeric: true,
      mobile: "amount",
      cell: (row) => `${formatCount(row.issue_count, locale)} (${formatCount(row.quarantined_count, locale)})`,
    },
    { id: "by", header: c.by, cell: (row) => row.started_by_name || "—" },
  ];
}

function LatestRun({ run }: { run: RunSummary }) {
  const { locale } = useZone();
  return (
    <SectionCard title={m.latest} description={<LocalDateTime value={run.started_at} />} actions={<RunStatusPill status={run.status} />}>
      <FactStrip
        label={m.latestFacts}
        facts={[
          { label: m.facts.issues, value: formatCount(run.issue_count, locale), href: run.path },
          { label: m.facts.quarantined, value: formatCount(run.quarantined_count, locale), href: `${run.path}?severity=quarantine#issues` },
          { label: m.facts.rejected, value: formatCount(run.error_count, locale), href: `${run.path}?severity=error#issues` },
        ]}
      />
    </SectionCard>
  );
}

function RunHistory({ page, offset }: { page: Page<RunSummary>; offset: number }) {
  const { locale } = useZone();
  return (
    <div className="flex flex-col gap-6">
      {page.items[0] && offset === 0 ? <LatestRun run={page.items[0]} /> : null}
      <SectionCard
        title={m.runs.title}
        description={
          <>
            {m.cli} <code className="font-mono text-xs text-ink">{m.cliCommand}</code>
          </>
        }
      >
        <DataTable
          caption={m.runs.caption}
          hideCaption
          columns={runColumns(locale)}
          rows={page.items}
          rowId={(row) => row.id}
          rowHref={(row) => row.path}
          empty={<EmptyState title={m.runs.empty}>{m.runs.emptyBody}</EmptyState>}
          footer={
            page.total > page.limit ? (
              <OffsetPagination
                label={m.runs.pages}
                total={page.total}
                limit={page.limit}
                offset={page.offset}
                shown={page.items.length}
                control={(next) => ({ href: next ? `/settings/migration?offset=${next}` : "/settings/migration" })}
              />
            ) : null
          }
        />
      </SectionCard>
    </div>
  );
}

function CandidateActions({ candidate, canDecide }: { candidate: Candidate; canDecide: boolean }) {
  const client = useQueryClient();
  const mutation = useMutation({
    mutationFn: ({ decision, partyId }: { decision: CandidateDecision; partyId: string | null }) =>
      decideCandidate(candidate, decision, partyId),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["migration", "candidates"] }),
  });
  if (!canDecide) return <span className="text-sm text-ink-muted">{m.candidates.statuses[candidate.status]}</span>;
  const open = candidate.capabilities.decide?.allowed ?? false;
  const pending = mutation.isPending;
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap gap-2">
        {open ? (
          <>
            {candidate.suggested_party ? (
              <Button
                size="sm"
                variant="primary"
                isPending={pending}
                onPress={() => mutation.mutate({ decision: "link", partyId: candidate.suggested_party!.id })}
              >
                {m.candidates.link(candidate.suggested_party.display_name)}
              </Button>
            ) : null}
            <Button size="sm" isPending={pending} onPress={() => mutation.mutate({ decision: "new_party", partyId: null })}>
              {m.candidates.newParty}
            </Button>
            <Button size="sm" variant="quiet" isPending={pending} onPress={() => mutation.mutate({ decision: "reject", partyId: null })}>
              {m.candidates.reject}
            </Button>
          </>
        ) : (
          <Button size="sm" variant="quiet" isPending={pending} onPress={() => mutation.mutate({ decision: "reopen", partyId: null })}>
            {m.candidates.reopen}
          </Button>
        )}
      </div>
      {mutation.isError ? <ErrorState error={mutation.error} what={m.candidates.what} compact /> : null}
    </div>
  );
}

function candidateColumns(locale: string, canDecide: boolean): DataTableColumn<Candidate>[] {
  const c = m.candidates.columns;
  return [
    {
      id: "name",
      header: c.name,
      isRowHeader: true,
      mobile: "title",
      cell: (row) => (
        <span className="flex flex-col gap-0.5">
          <span className="font-semibold text-ink">{row.legacy_name}</span>
          <span className="text-xs text-ink-muted">{m.candidates.variants(row.variants.length)}</span>
        </span>
      ),
    },
    { id: "country", header: c.country, mobile: "meta", cell: (row) => row.legacy_country || row.country_key || "—" },
    { id: "seen", header: c.seen, numeric: true, cell: (row) => formatCount(row.occurrences, locale) },
    {
      id: "suggestion",
      header: c.suggestion,
      mobile: "meta",
      cell: (row) =>
        row.linked_party ?? row.suggested_party ? (
          <span className="flex flex-col gap-0.5">
            <RacLink href={(row.linked_party ?? row.suggested_party)!.path} className="text-ink underline underline-offset-2">
              {(row.linked_party ?? row.suggested_party)!.display_name}
            </RacLink>
            <span className="font-mono text-xs text-ink-muted">
              {(row.linked_party ?? row.suggested_party)!.party_number} · {m.candidates.matches[row.match_kind] ?? row.match_kind}
            </span>
          </span>
        ) : (
          <span className="text-ink-muted">{row.match_kind === "ambiguous" ? m.candidates.matches.ambiguous : m.candidates.noSuggestion}</span>
        ),
    },
    {
      id: "status",
      header: c.status,
      mobile: "status",
      cell: (row) => <StatusPill tone={CANDIDATE_TONE[row.status] ?? "neutral"}>{m.candidates.statuses[row.status] ?? row.status}</StatusPill>,
    },
    { id: "decide", header: c.decide, mobile: "meta", cell: (row) => <CandidateActions candidate={row} canDecide={canDecide} /> },
  ];
}

function Candidates() {
  const { locale } = useZone();
  const { permissionKeys } = useSession();
  const [status, setStatus] = useState<CandidateStatus | null>("proposed");
  const [offset, setOffset] = useState(0);
  const query = useQuery({
    queryKey: queryKeys.migration.candidates({ status, offset }),
    queryFn: ({ signal }) => fetchCandidates(status, offset, signal),
  });
  return (
    <SectionCard
      title={m.candidates.title}
      description={m.candidates.description}
      actions={
        <Select
          label={m.candidates.filters.status}
          options={[{ id: "", label: m.candidates.filters.any }, ...CANDIDATE_STATUSES.map((s) => ({ id: s, label: m.candidates.statuses[s] ?? s }))]}
          value={status ?? ""}
          onChange={(value) => {
            setOffset(0);
            setStatus((CANDIDATE_STATUSES.find((s) => s === value) ?? null) as CandidateStatus | null);
          }}
        />
      }
    >
      {query.isPending ? (
        <Loading label={m.candidates.what} />
      ) : query.isError ? (
        <QueryProblem error={query.error} what={m.candidates.what} retry={() => fetchCandidates(status, offset).then(() => query.refetch())} />
      ) : (
        <DataTable
          caption={m.candidates.caption}
          hideCaption
          columns={candidateColumns(locale, permissionKeys.has(CANDIDATE_UPDATE))}
          rows={query.data.items}
          rowId={(row) => row.id}
          empty={<EmptyState title={m.candidates.empty} />}
          footer={
            query.data.total > query.data.limit ? (
              <OffsetPagination
                label={m.candidates.pages}
                total={query.data.total}
                limit={query.data.limit}
                offset={query.data.offset}
                shown={query.data.items.length}
                control={(next) => ({ onPress: () => setOffset(next) })}
              />
            ) : null
          }
        />
      )}
    </SectionCard>
  );
}

function openingColumns(locale: string): DataTableColumn<OpeningBatch>[] {
  const c = m.opening.columns;
  return [
    { id: "staged", header: c.staged, isRowHeader: true, mobile: "title", cell: (row) => <LocalDateTime value={row.created_at} /> },
    { id: "status", header: c.status, mobile: "status", cell: (row) => m.opening.statuses[row.status] ?? row.status },
    { id: "lines", header: c.lines, numeric: true, cell: (row) => formatCount(row.line_count, locale) },
    { id: "quarantined", header: c.quarantined, numeric: true, cell: (row) => formatCount(row.quarantined_count, locale) },
    {
      id: "totals",
      header: c.totals,
      cell: (row) =>
        Object.entries(row.totals)
          .map(([uom, qty]) => `${String(qty)} ${uom}`)
          .join(", ") || "—",
    },
    { id: "approved", header: c.approved, cell: (row) => row.approved_by_name ?? "—" },
  ];
}

function OpeningBatches() {
  const { locale } = useZone();
  const query = useQuery({ queryKey: queryKeys.migration.opening(), queryFn: ({ signal }) => fetchOpeningBatches(signal) });
  const posterMissing = query.data?.items.some((b) => !b.poster_available);
  return (
    <SectionCard title={m.opening.title} description={m.opening.description}>
      {query.isPending ? (
        <Loading label={m.opening.title} variant="inline" />
      ) : query.isError ? (
        <QueryProblem error={query.error} what={m.opening.title} retry={() => fetchOpeningBatches().then(() => query.refetch())} />
      ) : (
        <>
          <DataTable
            caption={m.opening.caption}
            hideCaption
            columns={openingColumns(locale)}
            rows={query.data.items}
            rowId={(row) => row.id}
            empty={<EmptyState title={m.opening.empty} />}
          />
          {posterMissing ? <p className="text-sm text-ink-muted">{m.opening.posterMissing}</p> : null}
        </>
      )}
    </SectionCard>
  );
}

/**
 * Settings › Migration: run history and the latest run, candidate customer links, opening-balance batches. The run
 * list is read first: when it asks for the authenticator (MFA-flagged reads), one confirmation unlocks the page.
 */
export function MigrationPage({ offset }: { offset: number }) {
  const { permissionKeys } = useSession();
  const allowed = permissionKeys.has(RUN_READ);
  const runs = useQuery({ queryKey: queryKeys.migration.runs(offset), queryFn: ({ signal }) => fetchRuns(offset, signal), enabled: allowed });
  if (!allowed) return <PermissionDenied area={m.area} />;
  return (
    <div className="flex flex-col gap-8">
      <PageHeader title={m.title} intro={m.intro} eyebrow={settingsMessages.hub.title} nav={<SettingsAreaNav currentId="settings-migration" />} />
      {runs.isPending ? (
        <Loading label={m.what} />
      ) : runs.isError ? (
        <QueryProblem error={runs.error} what={m.what} retry={() => fetchRuns(offset).then(() => runs.refetch())} />
      ) : (
        <>
          <RunHistory page={runs.data} offset={offset} />
          <Candidates />
          <OpeningBatches />
        </>
      )}
    </div>
  );
}
