"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchWorkCentres, type WorkCenterSummary } from "@/features/production/api";
import { queryKeys } from "@/lib/api/query-keys";
import { asRoute, WORK_CENTRE_KIND } from "~/data/production";
import { Page, PageHeader } from "~/shell/page";
import { ErrorBlock } from "~/shell/states";
import { Badge, Code, DataTable, EmptyState, GlassPanel, Money, PageSummary, type Column } from "~/ui";
import { Minutes, PATHS, Percent, ProductionNav, stagger } from "./parts";

/** The rate, or why it is not shown: hidden from people without the costing permission. */
export function RateText({ centre }: { centre: Pick<WorkCenterSummary, "rate_per_hour" | "redacted_fields"> }) {
  if (centre.rate_per_hour) return <Money value={centre.rate_per_hour} />;
  if (centre.redacted_fields?.includes("rate_per_hour")) return <span className="text-ink-3">Hidden</span>;
  return <span className="text-ink-3">Not set</span>;
}

const COLUMNS: Column<WorkCenterSummary>[] = [
  {
    key: "centre",
    header: "Work centre",
    primary: true,
    cell: (centre) => (
      <span className="flex min-w-0 flex-col gap-0.5">
        <span className="flex min-w-0 flex-wrap items-center gap-2">
          <span className="t-label text-ink">{centre.name}</span>
          {centre.is_active ? null : (
            <Badge size="sm" outline>
              Inactive
            </Badge>
          )}
        </span>
        <Code className="t-code-sm text-ink-3">{centre.code}</Code>
      </span>
    ),
  },
  { key: "kind", header: "Run by", cell: (centre) => WORK_CENTRE_KIND[centre.kind] ?? centre.kind },
  { key: "machines", header: "Machines", numeric: true, cell: (centre) => <span className="lk-tnum">{centre.machine_count}</span> },
  { key: "efficiency", header: "Efficiency", numeric: true, cell: (centre) => <Percent value={centre.efficiency_pct} /> },
  { key: "day", header: "Standard day", numeric: true, cell: (centre) => <Minutes value={centre.standard_day_minutes} className="t-label text-ink" /> },
  { key: "rate", header: "Rate per hour", numeric: true, hideOnMobile: true, cell: (centre) => <RateText centre={centre} /> },
];

/** Work centres: where the work happens and how much a day holds. */
export function WorkCentreList() {
  const query = useQuery({ queryKey: queryKeys.production.workCentres(), queryFn: ({ signal }) => fetchWorkCentres(signal) });
  const total = query.data?.length ?? 0;
  return (
    <Page>
      <PageHeader
        eyebrow="Production"
        title="Work centres"
        lead="Where the work happens. A day holds shifts × machines × efficiency, unless that day has its own capacity set."
      />
      <ProductionNav current="workCentres" />

      {query.isError ? (
        <ErrorBlock error={query.error} what="Work centres" onRetry={() => void query.refetch()} />
      ) : (
        <GlassPanel padding="none" className="rise min-w-0" style={stagger(1)}>
          <DataTable
            label="Work centres"
            columns={COLUMNS}
            rows={query.data ?? []}
            rowKey={(centre) => centre.id}
            rowHref={(centre) => asRoute(`${PATHS.workCentres}/${centre.id}`)}
            loading={query.isPending}
            skeletonRows={6}
            empty={<EmptyState icon="factory" title="No work centres yet" text="No work centre has been set up in this workspace. Routings and capacity planning use them once they exist." />}
          />
        </GlassPanel>
      )}

      {query.data && total > 0 ? <PageSummary from={1} to={total} total={total} noun="work centres" /> : null}
    </Page>
  );
}
