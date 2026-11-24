"use client";

import type { Currency, MyCalendar, Uom } from "@/features/settings/types";
import { formatCount } from "@/lib/format/money";
import { useSession } from "@/lib/session/context";
import { CALENDAR_READ, useCurrencies, useMyCalendar, useUoms } from "~/data/settings-data";
import { Page, PageHeader, Split } from "~/shell/page";
import { ErrorBlock, LoadingBlock } from "~/shell/states";
import { Badge, Code, DataTable, DateText, EmptyState, GlassPanel, KeyValue, Tabs, type Column } from "~/ui";
import { asRoute, Mono, Quiet, SETTINGS_CRUMBS } from "./shared";

/**
 * The shared lists every screen leans on: currencies, units of measure and the person's work
 * calendar. Read-only here (they are managed on the server); one view each, chosen with `?view=`.
 */

export type ReferenceView = "currencies" | "units" | "calendar";

const none = <Quiet>None</Quiet>;

const currencyColumns: Column<Currency>[] = [
  { key: "code", header: "Code", primary: true, cell: (row) => <Code>{row.code}</Code> },
  { key: "name", header: "Currency", mobileLabel: "Currency", cell: (row) => row.name },
  { key: "symbol", header: "Symbol", mobileLabel: "Symbol", cell: (row) => row.symbol || none },
  { key: "exponent", header: "Decimal places", mobileLabel: "Decimal places", numeric: true, cell: (row) => <span className="lk-tnum">{row.exponent}</span> },
];

/** "1 kg = 1000 g" for each generic conversion; the factor is shown exactly as the server holds it. */
function conversionText(uom: Pick<Uom, "conversions">): string[] {
  return uom.conversions.map((conversion) => `1 ${conversion.from_code} = ${conversion.factor} ${conversion.to_code}`);
}

const uomColumns: Column<Uom>[] = [
  { key: "code", header: "Code", primary: true, cell: (row) => <Code>{row.code}</Code> },
  { key: "name", header: "Unit", mobileLabel: "Unit", cell: (row) => row.name },
  { key: "dimension", header: "Measures", mobileLabel: "Measures", cell: (row) => row.dimension || none },
  {
    key: "precision",
    header: "Precision",
    mobileLabel: "Precision",
    cell: (row) => (row.is_integer ? "Whole numbers only" : row.max_decimal_places === 1 ? "Up to 1 decimal place" : `Up to ${row.max_decimal_places} decimal places`),
  },
  { key: "aliases", header: "Also written", mobileLabel: "Also written", hideOnMobile: true, cell: (row) => (row.aliases.length ? row.aliases.join(", ") : none) },
  {
    key: "conversions",
    header: "Conversions",
    mobileLabel: "Conversions",
    hideOnMobile: true,
    cell: (row) => {
      const lines = conversionText(row);
      return lines.length ? (
        <ul className="lk-tnum flex list-none flex-col gap-0.5">
          {lines.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      ) : (
        none
      );
    },
  },
];

function Currencies() {
  const query = useCurrencies();
  if (query.isError && !query.data) return <ErrorBlock error={query.error} what="Currencies" onRetry={() => void query.refetch()} />;
  return (
    <GlassPanel padding="none" className="rise">
      <DataTable
        label="Currencies"
        columns={currencyColumns}
        rows={query.data ?? []}
        rowKey={(row) => row.code}
        loading={query.isPending}
        skeletonRows={4}
        empty={<EmptyState compact icon="banknote" title="No currency is set up" text="Currencies are added on the server. Ask whoever runs your installation." />}
      />
    </GlassPanel>
  );
}

function Units() {
  const query = useUoms();
  if (query.isError && !query.data) return <ErrorBlock error={query.error} what="Units of measure" onRetry={() => void query.refetch()} />;
  return (
    <GlassPanel padding="none" className="rise">
      <DataTable
        label="Units of measure"
        columns={uomColumns}
        rows={query.data ?? []}
        rowKey={(row) => row.code}
        loading={query.isPending}
        skeletonRows={6}
        empty={<EmptyState compact icon="ruler" title="No unit is set up" text="Units are added on the server. Ask whoever runs your installation." />}
      />
    </GlassPanel>
  );
}

const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const SOURCE: Record<MyCalendar["source"], string> = { assignment: "Assigned to you", company_default: "The company default", built_in: "The built-in default" };
const DAY_TYPE: Record<MyCalendar["day_type"], { label: string; tone: "leaf" | "neutral" | "cobalt" }> = {
  working: { label: "A working day", tone: "leaf" },
  non_working: { label: "A day off", tone: "neutral" },
  holiday: { label: "A holiday", tone: "cobalt" },
};

/** `HH:MM:SS` becomes `HH:MM`. */
const localTime = (value: string) => value.replace(/^(\d{2}:\d{2})(:\d{2}(\.\d+)?)?$/, "$1");

function WorkCalendar() {
  const { zone } = useSession();
  const query = useMyCalendar();
  if (query.isPending) return <LoadingBlock lines={8} label="Loading your work calendar" />;
  if (query.isError || !query.data) return <ErrorBlock error={query.error} what="Your work calendar" onRetry={() => void query.refetch()} />;
  const calendar = query.data;
  const shift = calendar.shift;
  const hours = shift.start_local && shift.end_local ? `${localTime(shift.start_local)} to ${localTime(shift.end_local)}` : null;
  const day = DAY_TYPE[calendar.day_type];

  return (
    <Split
      main={
        <GlassPanel padding="lg" className="rise" title={calendar.calendar_name ?? calendar.calendar_code ?? "Built-in calendar"} titleAs="h2" eyebrow={SOURCE[calendar.source]} action={<Badge tone={day.tone} dot>{day.label}</Badge>}>
          <KeyValue
            rows
            items={[
              { label: "Work date", value: <DateText value={calendar.work_date} style="business" /> },
              { label: "Shift", value: [shift.name ?? shift.code, hours].filter(Boolean).join(", ") || null },
              { label: "Working days", value: calendar.workweek.map((weekday) => WEEKDAYS[weekday - 1]).filter(Boolean).join(", ") || null },
              { label: "The day rolls over at", value: calendar.rollover_local ? <span className="lk-tnum">{localTime(calendar.rollover_local)}</span> : null },
              { label: "Next working day", value: calendar.next_working_day ? <DateText value={calendar.next_working_day} style="business" /> : null },
              { label: "Time zone", value: <Mono>{calendar.time_zone}</Mono> },
            ]}
          />
        </GlassPanel>
      }
      aside={
        <GlassPanel title="Upcoming holidays" titleAs="h2">
          {calendar.upcoming_holidays.length === 0 ? (
            <p className="t-body-sm text-ink-3">No holidays in the coming weeks.</p>
          ) : (
            <ul className="flex list-none flex-col">
              {calendar.upcoming_holidays.map((holiday) => (
                <li key={`${holiday.date}:${holiday.name}`} className="hairline-top flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 py-3 first:border-t-0 first:pt-0">
                  <span className="t-label text-ink">{holiday.name}</span>
                  <span className="t-caption text-ink-3">
                    <DateText value={holiday.date} style="business" />
                    {holiday.kind ? ` · ${holiday.kind.replace(/_/g, " ")}` : ""}
                  </span>
                </li>
              ))}
            </ul>
          )}
          <p className="t-caption mt-3 text-ink-3">Shown in {zone.timeZone} time.</p>
        </GlassPanel>
      }
    />
  );
}

export function ReferenceData({ view }: { view: ReferenceView }) {
  const { permissionKeys, zone } = useSession();
  const canSeeCalendar = permissionKeys.has(CALENDAR_READ);
  const selected: ReferenceView = view === "calendar" && !canSeeCalendar ? "currencies" : view;
  const currencies = useCurrencies();
  const units = useUoms();

  const tabs = [
    { id: "currencies", label: "Currencies", href: asRoute("/settings/reference"), count: currencies.data?.length },
    { id: "units", label: "Units of measure", href: asRoute("/settings/reference?view=units"), count: units.data?.length },
    ...(canSeeCalendar ? [{ id: "calendar", label: "My work calendar", href: asRoute("/settings/reference?view=calendar") }] : []),
  ];
  const lead =
    selected === "currencies"
      ? "The currencies quotations and price lists can use."
      : selected === "units"
        ? "The units quantities are counted in, how precise each one is, and how they convert."
        : "The calendar behind your work date, your shift and your days off.";

  return (
    <Page>
      <PageHeader
        breadcrumb={SETTINGS_CRUMBS}
        title="Reference data"
        lead={`${lead} Managed on the server; shown here to look up.`}
        meta={selected === "currencies" && currencies.data ? <span className="lk-sr-only">{formatCount(currencies.data.length, zone.locale)} currencies</span> : undefined}
      />
      <Tabs label="Reference data views" selectedKey={selected} tabs={tabs} />
      {selected === "currencies" ? <Currencies /> : selected === "units" ? <Units /> : <WorkCalendar />}
    </Page>
  );
}
