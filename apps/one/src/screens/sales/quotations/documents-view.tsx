"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { compareRevisions, fetchQuoteRevisions, quoteLinesCsvHref, type RevisionCompare } from "@/features/sales/api";
import type { QuoteDetail, QuoteRevision } from "@/features/sales/types";
import { queryKeys } from "@/lib/api/query-keys";
import { humanise, useRestoreRevision } from "~/data/sales-deals";
import { ErrorBlock, LoadingBlock } from "~/shell/states";
import { Badge, Button, ButtonLink, DateText, EmptyState, GlassPanel, Icon, Select, SkeletonText, type Tone } from "~/ui";
import { ReasonModal, stagger } from "./parts";

const WORKING = "working";
const CHANGE: Record<string, { label: string; tone: Tone }> = {
  added: { label: "Added", tone: "leaf" },
  removed: { label: "Removed", tone: "ember" },
  changed: { label: "Changed", tone: "amber" },
  moved: { label: "Moved", tone: "cobalt" },
};
const FIELD: Record<string, string> = {
  price_type: "Price type",
  incoterm: "Incoterm",
  incoterm_place: "Incoterm place",
  payment_terms: "Payment terms",
  validity_days: "Valid for (days)",
  customer_reference: "Their reference",
  remarks: "Remarks",
  apply_minimum_surcharge: "Minimum order surcharge",
};
const shown = (value: unknown) => (value === null || value === undefined || value === "" ? "nothing" : String(value));

/** Issued revisions with their PDFs, a comparison between any two, and the line export. */
export function DocumentsView({ quote }: { quote: QuoteDetail }) {
  const query = useQuery({ queryKey: queryKeys.sales.quoteRevisions(quote.id), queryFn: ({ signal }) => fetchQuoteRevisions(quote.id, signal) });
  const restorer = useRestoreRevision(quote);
  const [restoring, setRestoring] = useState<QuoteRevision | null>(null);
  const canRestore = quote.capabilities.restore?.allowed === true;
  const canExport = quote.capabilities.export_lines?.allowed === true;

  if (query.isPending) return <LoadingBlock label="Loading revisions" lines={5} />;
  if (query.isError) return <ErrorBlock error={query.error} what="The issued revisions" onRetry={() => void query.refetch()} />;
  const revisions = query.data;

  return (
    <div className="stack">
      <GlassPanel
        padding="lg"
        title="Issued revisions"
        titleAs="h2"
        className="rise"
        action={
          canExport ? (
            <ButtonLink external href={quoteLinesCsvHref(quote.id)} download variant="ghost" size="sm" iconLeft="download">
              Lines as CSV
            </ButtonLink>
          ) : undefined
        }
      >
        {revisions.length === 0 ? (
          <EmptyState
            compact
            icon="fileText"
            title="Nothing issued yet"
            text="Marking the quotation as sent issues revision 1 and its PDF. Every later send adds the next revision; earlier ones never change."
          />
        ) : (
          <ol className="flex flex-col">
            {revisions.map((revision, index) => (
              <li key={revision.id} className="rise-plain hairline-top flex flex-wrap items-center justify-between gap-x-6 gap-y-3 py-4 first:border-t-0 first:pt-0 last:pb-0" style={stagger(index)}>
                <div className="flex min-w-0 items-center gap-4">
                  <span className="t-stat-sm lk-tnum flex h-11 w-11 flex-none items-center justify-center rounded-md border border-line bg-surface text-ink" aria-hidden="true">
                    {revision.revision_no}
                  </span>
                  <div className="flex min-w-0 flex-col gap-0.5">
                    <span className="t-label flex flex-wrap items-center gap-2 text-ink">
                      Revision {revision.revision_no}
                      {index === 0 ? (
                        <Badge tone="cobalt" size="sm">
                          Latest
                        </Badge>
                      ) : null}
                    </span>
                    <span className="t-caption text-ink-3">
                      Issued <DateText value={revision.issued_at} style="dayTime" />
                      {revision.issued_by?.display_name ? ` by ${revision.issued_by.display_name}` : ""}
                      {revision.valid_until ? (
                        <>
                          {" · valid until "}
                          <DateText value={revision.valid_until} style="business" />
                        </>
                      ) : null}
                    </span>
                  </div>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  {canRestore ? (
                    <Button variant="ghost" size="sm" iconLeft="undo" onPress={() => setRestoring(revision)}>
                      Restore
                    </Button>
                  ) : null}
                  {/* The PDF streams from the API (inline, same origin): a real link, so it opens, prints and downloads like any PDF. */}
                  <ButtonLink external href={revision.document_path} target="_blank" type="application/pdf" variant="secondary" size="sm" iconLeft="fileText">
                    Open PDF
                  </ButtonLink>
                </div>
              </li>
            ))}
          </ol>
        )}
      </GlassPanel>

      {revisions.length > 0 ? <Compare quote={quote} revisions={revisions.map((revision) => revision.revision_no)} /> : null}

      <ReasonModal
        isOpen={restoring !== null}
        onOpenChange={(open) => (open ? undefined : setRestoring(null))}
        title={restoring ? `Restore revision ${restoring.revision_no}` : ""}
        description="Its lines and terms come back into the working copy. The issued revisions stay as they are; a sent quotation is revised first, and the next send issues a new revision."
        confirmLabel={restoring ? `Restore revision ${restoring.revision_no}` : "Restore"}
        reason="optional"
        reasonHelp="Kept in the quotation's history."
        onConfirm={async (reason) => {
          if (restoring && (await restorer.restore(restoring.revision_no, reason))) setRestoring(null);
        }}
      />
    </div>
  );
}

function Compare({ quote, revisions }: { quote: QuoteDetail; revisions: number[] }) {
  const [from, setFrom] = useState<number>(revisions[0] ?? 1);
  const [to, setTo] = useState<number | null>(null);
  const [run, setRun] = useState(false);
  const query = useQuery({
    queryKey: queryKeys.sales.quoteCompare(quote.id, from, to),
    queryFn: ({ signal }) => compareRevisions(quote.id, from, to, signal),
    enabled: run,
  });
  const options = revisions.map((n) => ({ value: String(n), label: `Revision ${n}` }));
  return (
    <GlassPanel padding="lg" title="What changed between two versions" titleAs="h2" className="rise" style={stagger(1)}>
      <div className="flex flex-col gap-5">
        <div className="grid grid-cols-1 items-end gap-4 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]">
          <Select
            label="From"
            options={options}
            value={String(from)}
            onChange={(value) => {
              setFrom(Number.parseInt(value, 10));
              setRun(false);
            }}
          />
          <Select
            label="To"
            options={[{ value: WORKING, label: "Working copy", description: "The quotation as it stands now" }, ...options]}
            value={to === null ? WORKING : String(to)}
            onChange={(value) => {
              setTo(value === WORKING ? null : Number.parseInt(value, 10));
              setRun(false);
            }}
          />
          <Button variant="secondary" iconLeft="split" onPress={() => setRun(true)}>
            Compare
          </Button>
        </div>
        {!run ? null : query.isPending ? (
          <SkeletonText lines={4} />
        ) : query.isError ? (
          <ErrorBlock error={query.error} what="The comparison" onRetry={() => void query.refetch()} />
        ) : (
          <CompareResult data={query.data} />
        )}
      </div>
    </GlassPanel>
  );
}

function CompareResult({ data }: { data: RevisionCompare }) {
  const lines = data.lines.filter((line) => line.change !== "unchanged");
  const totals = data.totals.filter((total) => total.delta !== null && total.delta !== "0.00");
  const nothing = data.header.length === 0 && lines.length === 0 && totals.length === 0;
  return (
    <div className="hairline-top flex flex-col gap-5 pt-5" aria-live="polite">
      <p className="t-h4 flex items-start gap-2 text-ink">
        <Icon name={nothing ? "checkCircle" : "split"} size={18} className="mt-0.5 flex-none text-ink-3" />
        {data.summary || (nothing ? "No differences." : "Differences found.")}
      </p>
      {data.header.length > 0 ? (
        <div className="flex flex-col gap-2">
          <h3 className="t-overline text-ink-3">Terms</h3>
          <ul className="flex flex-col gap-1.5">
            {data.header.map((change) => (
              <li key={change.field} className="t-body-sm text-ink-2">
                <span className="text-ink">{FIELD[change.field] ?? humanise(change.field)}</span>: {shown(change.before)} became {shown(change.after)}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {lines.length > 0 ? (
        <div className="flex flex-col gap-2">
          <h3 className="t-overline text-ink-3">Lines</h3>
          <ul className="flex flex-col">
            {lines.map((line) => (
              <li key={line.line_key} className="hairline-top flex flex-col gap-1 py-3 first:border-t-0 first:pt-0">
                <span className="flex flex-wrap items-center gap-2">
                  <Badge tone={CHANGE[line.change]?.tone ?? "neutral"} size="sm">
                    {CHANGE[line.change]?.label ?? humanise(line.change)}
                  </Badge>
                  <span className="t-label text-ink">{line.description}</span>
                </span>
                {line.changes.length > 0 ? (
                  <span className="t-caption text-ink-3">
                    {line.changes.map((c) => `${humanise(c.field)}: ${shown(c.before)} became ${shown(c.after)}`).join(" · ")}
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {totals.length > 0 ? (
        <div className="flex flex-col gap-2">
          <h3 className="t-overline text-ink-3">Totals, {data.currency_after}</h3>
          <dl className="flex flex-col gap-1.5">
            {totals.map((total) => (
              <div key={total.field} className="flex flex-wrap items-baseline justify-between gap-x-6">
                <dt className="t-body-sm text-ink-2">{humanise(total.field)}</dt>
                <dd className="t-body-sm lk-tnum text-ink">
                  {total.before ?? "none"} <span aria-hidden="true">→</span>
                  <span className="sr-only">became</span> {total.after ?? "none"} <span className="text-ink-3">({total.delta})</span>
                </dd>
              </div>
            ))}
          </dl>
        </div>
      ) : null}
    </div>
  );
}
