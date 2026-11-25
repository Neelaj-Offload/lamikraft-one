"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { fetchCapacity, type CapacityRead } from "@/features/production/api";
import { queryKeys } from "@/lib/api/query-keys";
import { isPositiveDecimalStr } from "@/lib/format/decimal";
import { asRoute } from "~/data/production";
import { Page, PageHeader } from "~/shell/page";
import { ErrorBlock, LoadingBlock } from "~/shell/states";
import { Badge, Code, DataTable, DateRangePicker, DateText, EmptyState, GlassPanel, ProgressBar, TextLink, type Column } from "~/ui";
import { Minutes, PATHS, Percent, ProductionNav, stagger, useCanOpen } from "./parts";

type Window = { from: string | null; to: string | null };
type Row = CapacityRead["rows"][number];
type Day = Row["days"][number];

function capacityHref(next: Window): string {
  const search = new URLSearchParams();
  if (next.from) search.set("from", next.from);
  if (next.to) search.set("to", next.to);
  const text = search.toString();
  return text ? `${PATHS.capacity}?${text}` : PATHS.capacity;
}

/** A width for the day's bar. The server already worked out the percentage; this only draws it. */
function barValue(pct: string | null): number {
  const value = pct === null ? 0 : Number.parseFloat(pct);
  return Number.isFinite(value) ? Math.min(Math.max(value, 0), 100) : 0;
}

const DAY_COLUMNS: Column<Day>[] = [
  {
    key: "day",
    header: "Day",
    primary: true,
    cell: (day) => (
      <span className="flex min-w-0 flex-col gap-0.5">
        <DateText value={day.day} style="business" className="t-label text-ink" />
        {day.exception_reason ? <span className="t-caption text-ink-3">{day.exception_reason}</span> : null}
      </span>
    ),
  },
  {
    key: "capacity",
    header: "Capacity",
    numeric: true,
    cell: (day) =>
      day.day_type === "working" || isPositiveDecimalStr(day.capacity_minutes) ? (
        <Minutes value={day.capacity_minutes} />
      ) : (
        <span className="text-ink-3">{day.day_type === "holiday" ? "Holiday" : "Not a working day"}</span>
      ),
  },
  { key: "load", header: "Booked", numeric: true, cell: (day) => <Minutes value={day.load_minutes} className="t-label text-ink" /> },
  {
    key: "use",
    header: "Use",
    width: "200px",
    cell: (day) =>
      day.overloaded ? (
        <span className="flex min-w-0 items-center gap-2">
          <Badge tone="ember" icon="alert" size="sm">
            Overloaded
          </Badge>
          {day.utilisation_pct ? <Percent value={day.utilisation_pct} className="t-caption text-ink-2" /> : null}
        </span>
      ) : day.utilisation_pct !== null ? (
        <span className="flex min-w-0 items-center gap-3">
          <ProgressBar label={`Use on ${day.day}`} hideLabel value={barValue(day.utilisation_pct)} tone="ink" className="min-w-16 flex-1" />
          <Percent value={day.utilisation_pct} className="t-caption w-12 text-right text-ink-2" />
        </span>
      ) : (
        <span className="text-ink-3">Nothing booked</span>
      ),
  },
  {
    key: "orders",
    header: "Work orders",
    cell: (day) =>
      day.work_orders.length > 0 ? (
        <span className="flex flex-wrap gap-x-2 gap-y-1">
          {day.work_orders.map((number) => (
            <Code key={number} className="t-code-sm">
              {number}
            </Code>
          ))}
        </span>
      ) : (
        <span className="text-ink-3">None</span>
      ),
  },
];

/** Capacity: the load each work centre carries, day by day, against what its calendar gives it. The window lives in the URL. */
export function Capacity({ state }: { state: Window }) {
  const router = useRouter();
  const query = useQuery({ queryKey: queryKeys.production.capacity(state), queryFn: ({ signal }) => fetchCapacity(state, signal) });
  const from = state.from ?? query.data?.date_from ?? null;
  const to = state.to ?? query.data?.date_to ?? null;
  const overloaded = query.data?.overloaded_days ?? 0;

  return (
    <Page>
      <PageHeader
        eyebrow="Production"
        title="Capacity"
        lead="What released work orders ask of each work centre, day by day, against what its calendar gives. An overloaded day is raised as a task."
      />
      <ProductionNav current="capacity" />

      <div className="rise flex min-w-0 flex-col gap-3 md:flex-row md:items-end md:justify-between" style={stagger(1)}>
        <DateRangePicker
          className="min-w-0 md:w-96"
          label="Days shown"
          value={from && to ? { start: from, end: to } : null}
          onChange={(range) => router.push(asRoute(capacityHref({ from: range?.start ?? null, to: range?.end ?? null })), { scroll: false })}
        />
        {query.data ? (
          overloaded > 0 ? (
            <Badge tone="ember" icon="alert">
              {overloaded === 1 ? "1 overloaded day" : `${overloaded} overloaded days`}
            </Badge>
          ) : (
            <Badge tone="leaf" icon="check">
              No day is overloaded
            </Badge>
          )
        ) : null}
      </div>

      {query.isPending ? (
        <LoadingBlock lines={8} label="Loading capacity" />
      ) : query.isError ? (
        <ErrorBlock error={query.error} what="Capacity" onRetry={() => void query.refetch()} />
      ) : query.data.rows.length === 0 ? (
        <GlassPanel padding="lg" className="rise">
          <EmptyState icon="gauge" title="No work centres to plan against" text="Capacity is worked out per work centre. Once one is set up, its days show here." />
        </GlassPanel>
      ) : (
        <div className="flex min-w-0 flex-col gap-6">
          {query.data.rows.map((row, index) => (
            <CentreCapacity key={row.work_center.id} row={row} index={index} />
          ))}
        </div>
      )}
    </Page>
  );
}

function CentreCapacity({ row, index }: { row: Row; index: number }) {
  const canOpen = useCanOpen();
  const path = `${PATHS.workCentres}/${row.work_center.id}`;
  const overloaded = row.days.filter((day) => day.overloaded).length;
  return (
    <section aria-labelledby={`centre-${row.work_center.id}`} className="rise flex min-w-0 flex-col gap-3" style={stagger(index + 2)}>
      <div className="flex min-w-0 flex-wrap items-end justify-between gap-x-6 gap-y-2">
        <div className="flex min-w-0 flex-col gap-1">
          <h2 id={`centre-${row.work_center.id}`} className="t-h3 flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
            {canOpen(path) ? <TextLink href={asRoute(path)}>{row.work_center.name}</TextLink> : row.work_center.name}
            <Code className="t-code-sm text-ink-3">{row.work_center.code}</Code>
            {overloaded > 0 ? (
              <Badge tone="ember" size="sm" icon="alert">
                {overloaded === 1 ? "1 day over" : `${overloaded} days over`}
              </Badge>
            ) : null}
          </h2>
          {isPositiveDecimalStr(row.unscheduled_minutes) ? (
            <p className="t-body-sm text-ink-2">
              <Minutes value={row.unscheduled_minutes} /> of work is not yet on a day.
            </p>
          ) : null}
        </div>
        <p className="t-body-sm text-ink-2">
          <Minutes value={row.total_load_minutes} className="t-label text-ink" /> booked of <Minutes value={row.total_capacity_minutes} />
        </p>
      </div>
      <GlassPanel padding="none" className="min-w-0">
        <DataTable label={`Capacity of ${row.work_center.code}, day by day`} columns={DAY_COLUMNS} rows={row.days} rowKey={(day) => day.day} dense />
      </GlassPanel>
    </section>
  );
}
