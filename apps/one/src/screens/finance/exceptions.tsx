"use client";

import type { ExceptionsRead } from "@/features/finance/api";
import { asRoute, EXCEPTION_KINDS, exceptionCodeText, exceptionKind, serverPath, useFinanceExceptions } from "~/data/finance";
import { Page, PageHeader } from "~/shell/page";
import { ErrorBlock } from "~/shell/states";
import { ButtonLink, ChipGroup, ChipLink, Code, Dash, DataTable, DateText, EmptyState, GlassPanel, Icon, SegmentedLinks, type Column } from "~/ui";
import { Percent, stagger } from "./parts";
import type { ExceptionKindFilter, ExceptionView } from "./views";

type Item = ExceptionsRead["items"][number];
type Margin = ExceptionsRead["margin"][number];

const BASE = "/finance/exceptions";

function href(view: ExceptionView, kind: ExceptionKindFilter = null) {
  const search = new URLSearchParams();
  if (view !== "documents") search.set("view", view);
  if (kind) search.set("kind", kind);
  const text = search.toString();
  return asRoute(text ? `${BASE}?${text}` : BASE);
}

const ITEM_COLUMNS: Column<Item>[] = [
  {
    key: "record",
    header: "Record",
    primary: true,
    cell: (item) => {
      const look = exceptionKind(item.kind);
      return (
        <span className="flex min-w-0 items-start gap-3">
          <span className={`mt-0.5 flex-none ${look.tone === "ember" ? "text-ember-text" : look.tone === "amber" ? "text-amber-text" : "text-ink-3"}`}>
            <Icon name={look.icon} size={16} />
          </span>
          <span className="flex min-w-0 flex-col gap-0.5">
            <Code>{item.ref.number}</Code>
            <span className="t-caption text-ink-3">{look.label}</span>
          </span>
        </span>
      );
    },
  },
  {
    key: "customer",
    header: "Customer",
    cell: (item) =>
      item.party_name ? (
        <span className="block truncate text-ink" title={item.party_name}>
          {item.party_name}
        </span>
      ) : (
        <Dash />
      ),
  },
  {
    key: "what",
    header: "What is wrong",
    cell: (item) => <span className="t-body-sm text-ink-2">{item.codes.length ? item.codes.map(exceptionCodeText).join(" ") : exceptionKind(item.kind).label}</span>,
  },
  { key: "since", header: "Since", hideOnMobile: true, cell: (item) => (item.since ? <DateText value={item.since} style="relative" /> : <Dash />) },
];

const MARGIN_COLUMNS: Column<Margin>[] = [
  {
    key: "quotation",
    header: "Quotation",
    primary: true,
    cell: (row) => (
      <span className="flex min-w-0 flex-col gap-0.5">
        <Code>{row.quote_number}</Code>
        <span className="t-caption text-ink-3">
          Revision {row.revision_no} · flagged <DateText value={row.detected_at} style="relative" />
        </span>
      </span>
    ),
  },
  {
    key: "customer",
    header: "Customer",
    cell: (row) => (
      <span className="flex min-w-0 flex-col gap-0.5">
        <span className="truncate text-ink" title={row.party_name}>
          {row.party_name}
        </span>
        {row.owner?.display_name ? <span className="t-caption text-ink-3">Owner: {row.owner.display_name}</span> : null}
      </span>
    ),
  },
  {
    key: "margin",
    header: "Margin",
    numeric: true,
    cell: (row) => (row.margin_percent != null ? <Percent value={row.margin_percent} maxFractionDigits={1} className="t-label text-ember-text" /> : <span className="t-caption text-ink-3">Needs cost access</span>),
  },
  { key: "policy", header: "Policy", numeric: true, cell: (row) => <Percent value={row.threshold_percent} maxFractionDigits={1} /> },
  {
    key: "missing",
    header: "Lines without cost",
    mobileLabel: "Without cost",
    numeric: true,
    cell: (row) => <span className={`lk-tnum ${row.lines_without_cost > 0 ? "t-label text-amber-text" : "text-ink-3"}`}>{row.lines_without_cost}</span>,
  },
];

/** What finance has to look at: blocked issues, overdue invoices, loose receipts, failed exports, and quotations under the margin policy. */
export function Exceptions({ view, kind }: { view: ExceptionView; kind: ExceptionKindFilter }) {
  const query = useFinanceExceptions();
  const data = query.data;
  const items = data?.items ?? [];
  const shown = kind ? items.filter((item) => item.kind === kind) : items;
  const countOf = (k: string) => items.filter((item) => item.kind === k).length;

  return (
    <Page>
      <PageHeader eyebrow="Finance" title="Exceptions" lead="Everything in finance that is stuck, late or out of line. Each line opens the record that fixes it." />

      <div className="rise flex min-w-0 flex-col gap-3" style={stagger(1)}>
        <SegmentedLinks
          className="self-start"
          label="Kind of exception"
          value={view}
          options={[
            { value: "documents", label: data ? `Documents · ${items.length}` : "Documents", href: href("documents") },
            { value: "margin", label: data ? `Margin · ${data.margin.length}` : "Margin", href: href("margin") },
          ]}
        />
        {view === "documents" ? (
          <ChipGroup label="Filter by kind">
            <ChipLink href={href("documents")} selected={kind === null} scroll={false}>
              All
            </ChipLink>
            {EXCEPTION_KINDS.map((k) => (
              <ChipLink key={k} href={href("documents", k)} selected={kind === k} count={data ? countOf(k) : undefined} scroll={false}>
                {exceptionKind(k).plural}
              </ChipLink>
            ))}
          </ChipGroup>
        ) : null}
      </div>

      {query.isError ? (
        <ErrorBlock error={query.error} what="Finance exceptions" onRetry={() => void query.refetch()} />
      ) : view === "documents" ? (
        <GlassPanel padding="none" className="rise min-w-0" style={stagger(2)}>
          <DataTable
            label={kind ? exceptionKind(kind).plural : "Finance exceptions"}
            columns={ITEM_COLUMNS}
            rows={shown}
            rowKey={(item) => `${item.kind}:${item.ref.id}`}
            rowHref={(item) => serverPath(item.ref.path)}
            loading={query.isPending}
            skeletonRows={6}
            empty={
              kind ? (
                <EmptyState
                  compact
                  icon="checkCircle"
                  title={`No ${exceptionKind(kind).plural.toLowerCase()} right now`}
                  text="This kind is clear. Other kinds may still need you."
                  actions={
                    <ButtonLink href={href("documents")} variant="secondary" size="sm">
                      See every exception
                    </ButtonLink>
                  }
                />
              ) : (
                <EmptyState
                  icon="checkCircle"
                  title="Nothing in finance needs attention"
                  text="No blocked issue, overdue invoice, loose receipt or failed export. New ones are listed here first."
                  actions={
                    <ButtonLink href="/finance" variant="secondary" iconRight="arrowRight">
                      Back to finance
                    </ButtonLink>
                  }
                />
              )
            }
          />
        </GlassPanel>
      ) : (
        <div className="stack">
          <p className="t-body-sm max-w-prose text-ink-3">
            Quotations issued to customers at a margin below the agreed policy. Open one to see its lines and costs.
            {data?.margin.some((row) => row.margin_percent == null) ? " Your role cannot see costs, so some margins are hidden." : ""}
          </p>
          <GlassPanel padding="none" className="rise min-w-0" style={stagger(2)}>
            <DataTable
              label="Quotations below the margin policy"
              columns={MARGIN_COLUMNS}
              rows={data?.margin ?? []}
              rowKey={(row) => row.id}
              rowHref={(row) => asRoute(`/sales/quotes/${row.quote_id}`)}
              loading={query.isPending}
              skeletonRows={4}
              empty={<EmptyState compact icon="percent" title="Every issued quotation meets the margin policy" text="A quotation issued below the threshold is listed here, with its owner." />}
            />
          </GlassPanel>
        </div>
      )}
    </Page>
  );
}
