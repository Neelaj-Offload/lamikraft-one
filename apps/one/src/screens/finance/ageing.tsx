"use client";

import { useRouter } from "next/navigation";
import type { AgeingReport } from "@/features/finance/api";
import { isPositiveDecimalStr } from "@/lib/format/decimal";
import { asRoute, useAgeing } from "~/data/finance";
import { Page, PageHeader, PageSection } from "~/shell/page";
import { ErrorBlock } from "~/shell/states";
import {
  Banner,
  ButtonLink,
  Code,
  DataTable,
  DatePicker,
  EmptyState,
  GlassPanel,
  Money,
  Skeleton,
  TextLink,
  type Column,
} from "~/ui";
import { stagger } from "./parts";

type Row = AgeingReport["rows"][number];
type Buckets = AgeingReport["totals"][number];
type BucketKey = Exclude<keyof Buckets, "total">;

/** The five age bands in the order money gets older. */
const BANDS: { key: BucketKey; label: string; late: boolean }[] = [
  { key: "current", label: "Not yet due", late: false },
  { key: "days_1_30", label: "1 to 30 days", late: true },
  { key: "days_31_60", label: "31 to 60 days", late: true },
  { key: "days_61_90", label: "61 to 90 days", late: true },
  { key: "days_over_90", label: "Over 90 days", late: true },
];

const plural = (count: number, one: string, many: string) =>
  count === 1 ? `1 ${one}` : `${count} ${many}`;

const COLUMNS: Column<Row>[] = [
  {
    key: "customer",
    header: "Customer",
    primary: true,
    cell: (row) => (
      <span className="flex min-w-0 flex-col gap-0.5">
        <span
          className="t-label truncate text-ink"
          title={row.party.display_name}
        >
          {row.party.display_name}
        </span>
        <span className="t-caption text-ink-3">
          {row.currency} · {plural(row.invoice_count, "invoice", "invoices")}
          {row.no_due_date_count > 0
            ? ` · ${row.no_due_date_count} without a due date`
            : ""}
        </span>
        {isPositiveDecimalStr(row.unallocated_receipts.amount) ? (
          <span className="t-caption text-ink-3">
            <Money value={row.unallocated_receipts} /> received, not yet
            allocated
          </span>
        ) : null}
      </span>
    ),
  },
  ...BANDS.map<Column<Row>>((band) => ({
    key: band.key,
    header: band.label,
    numeric: true,
    cell: (row) => {
      const value = row.buckets[band.key];
      const owed = isPositiveDecimalStr(value.amount);
      return (
        <Money
          value={value}
          className={
            owed
              ? band.key === "days_over_90"
                ? "t-label text-ember-text"
                : "text-ink"
              : "text-ink-3"
          }
        />
      );
    },
  })),
  {
    key: "total",
    header: "Total",
    numeric: true,
    cell: (row) => (
      <Money value={row.buckets.total} className="t-label text-ink" />
    ),
  },
];

/** Receivables by age: what each customer owes, per currency, by how long it has been past due. */
export function Ageing({ asOf }: { asOf: string | null }) {
  const router = useRouter();
  const query = useAgeing(asOf);
  const report = query.data;
  const shownDate = asOf ?? report?.as_of ?? null;

  return (
    <Page>
      <PageHeader
        eyebrow="Finance"
        title="Ageing"
        lead={`What each customer still owes, by how long it has been past due. Days are counted in company time${report ? ` (${report.time_zone})` : ""}.`}
      />

      <div
        className="rise flex min-w-0 flex-wrap items-end gap-3"
        style={stagger(1)}
      >
        <DatePicker
          className="w-full sm:w-64"
          label="As of"
          value={shownDate}
          onChange={(value) =>
            router.push(
              asRoute(
                value ? `/finance/ageing?as_of=${value}` : "/finance/ageing",
              ),
            )
          }
        />
        {asOf ? (
          <ButtonLink href="/finance/ageing" variant="ghost" iconLeft="undo">
            Back to today
          </ButtonLink>
        ) : null}
      </div>

      {query.isError ? (
        <ErrorBlock
          error={query.error}
          what="The ageing report"
          onRetry={() => void query.refetch()}
        />
      ) : (
        <>
          {report && report.totals.length === 0 ? (
            <GlassPanel padding="lg" className="rise">
              <EmptyState
                compact
                icon="checkCircle"
                title="Nothing is owed on this date"
                text="No issued invoice had anything outstanding. Pick another date, or see what was invoiced."
                actions={
                  <ButtonLink
                    href="/finance/invoices?status=issued"
                    variant="secondary"
                    size="sm"
                    iconRight="arrowRight"
                  >
                    See issued invoices
                  </ButtonLink>
                }
              />
            </GlassPanel>
          ) : (
            <PageSection
              title="Totals by currency"
              description="Each currency stands alone. Amounts are never added across currencies."
              index={1}
            >
              {!report ? (
                <div
                  className="tiles"
                  role="status"
                  aria-label="Loading the totals"
                >
                  {[0, 1].map((tile) => (
                    <GlassPanel
                      key={tile}
                      padding="lg"
                      className="flex flex-col gap-4"
                    >
                      <Skeleton width="30%" height={14} />
                      <Skeleton width="55%" height={32} />
                      <Skeleton width="100%" height={40} />
                    </GlassPanel>
                  ))}
                </div>
              ) : (
                <ul className="tiles m-0 list-none p-0" data-min="lg">
                  {report.totals.map((total, index) => (
                    <CurrencyTotal
                      key={total.total.currency}
                      total={total}
                      index={index}
                    />
                  ))}
                </ul>
              )}
            </PageSection>
          )}

          {report && report.no_due_date_invoices.length > 0 ? (
            <Banner
              tone="cobalt"
              title={`${plural(report.no_due_date_invoices.length, "invoice has", "invoices have")} no due date, so they count as not yet due.`}
            >
              <span className="inline-flex flex-wrap gap-x-3 gap-y-1">
                {report.no_due_date_invoices.map((invoice) => (
                  <TextLink
                    key={invoice.id}
                    href={asRoute(`/finance/invoices/${invoice.id}`)}
                  >
                    <Code>{invoice.document_number}</Code>
                  </TextLink>
                ))}
              </span>
            </Banner>
          ) : null}

          {report && report.rows.length === 0 ? null : (
            <PageSection
              title="By customer"
              description="One line per customer and currency. Open a customer to see their invoices."
              index={2}
            >
              <GlassPanel padding="none" className="min-w-0">
                <DataTable
                  label="Ageing by customer"
                  columns={COLUMNS}
                  rows={report?.rows ?? []}
                  rowKey={(row) => `${row.party.id}:${row.currency}`}
                  rowHref={(row) => asRoute(`/sales/parties/${row.party.id}`)}
                  loading={!report}
                  skeletonRows={6}
                />
              </GlassPanel>
            </PageSection>
          )}
        </>
      )}
    </Page>
  );
}

function CurrencyTotal({ total, index }: { total: Buckets; index: number }) {
  return (
    <GlassPanel
      as="li"
      padding="lg"
      className="rise-plain flex min-w-0 flex-col gap-5"
      style={stagger(index)}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <span className="t-overline text-ink-3">
          {total.total.currency} outstanding
        </span>
        <span className="t-stat ml-auto text-right text-ink">
          <Money value={total.total} />
        </span>
      </div>
      <dl className="m-0 grid grid-cols-[repeat(auto-fit,minmax(108px,1fr))] gap-x-4 gap-y-3 border-t border-line pt-4">
        {BANDS.map((band) => {
          const value = total[band.key];
          const owed = isPositiveDecimalStr(value.amount);
          return (
            <div key={band.key} className="flex min-w-0 flex-col gap-0.5">
              <dt className="t-caption text-ink-3">{band.label}</dt>
              <dd
                className={`lk-tnum m-0 ${owed && band.late ? (band.key === "days_over_90" ? "t-label text-ember-text" : "t-label text-ink") : "t-body text-ink-2"}`}
              >
                <Money value={value} />
              </dd>
            </div>
          );
        })}
      </dl>
    </GlassPanel>
  );
}
