"use client";

import { useQuery } from "@tanstack/react-query";
import { DataTable, type DataTableColumn } from "@/components/ui/data-table";
import { LocalDate } from "@/components/ui/format";
import { KeyValueGrid, type KeyValue } from "@/components/ui/key-value-grid";
import { PageHeader } from "@/components/ui/page-header";
import { SectionCard } from "@/components/ui/section-card";
import { EmptyState, ErrorState, Loading } from "@/components/ui/states";
import { queryKeys } from "@/lib/api/query-keys";
import { useSession } from "@/lib/session/context";
import { settingsMessages } from "@/messages/settings";
import { fetchCurrencies, fetchMyCalendar, fetchUoms } from "./api";
import { SettingsAreaNav } from "./settings-hub";
import type { Currency, MyCalendar, Uom } from "./types";

const m = settingsMessages.reference;

const yesNo = (value: boolean) => (value ? settingsMessages.company.yes : settingsMessages.company.no);

export function currencyColumns(): DataTableColumn<Currency>[] {
  const c = m.currencies.columns;
  return [
    { id: "code", header: c.code, isRowHeader: true, mobile: "title", cell: (row) => <span className="font-mono">{row.code}</span> },
    { id: "name", header: c.name, mobile: "key", cell: (row) => row.name },
    { id: "symbol", header: c.symbol, mobile: "meta", cell: (row) => row.symbol || <span className="text-ink-muted">{m.uoms.none}</span> },
    { id: "exponent", header: c.exponent, numeric: true, mobile: "amount", cell: (row) => row.exponent },
  ];
}

/** "1 kg = 1000 g" for each generic conversion. */
export function conversionText(uom: Pick<Uom, "conversions">): string[] {
  return uom.conversions.map((conversion) => `1 ${conversion.from_code} = ${conversion.factor} ${conversion.to_code}`);
}

export function uomColumns(): DataTableColumn<Uom>[] {
  const c = m.uoms.columns;
  const none = <span className="text-ink-muted">{m.uoms.none}</span>;
  return [
    { id: "code", header: c.code, isRowHeader: true, mobile: "title", cell: (row) => <span className="font-mono">{row.code}</span> },
    { id: "name", header: c.name, mobile: "key", cell: (row) => row.name },
    { id: "dimension", header: c.dimension, mobile: "meta", cell: (row) => row.dimension || none },
    { id: "integer", header: c.integer, cell: (row) => yesNo(row.is_integer) },
    { id: "decimals", header: c.decimals, numeric: true, mobile: "amount", cell: (row) => row.max_decimal_places },
    { id: "aliases", header: c.aliases, cell: (row) => (row.aliases.length ? row.aliases.join(", ") : none) },
    {
      id: "conversions",
      header: c.conversions,
      cell: (row) => {
        const lines = conversionText(row);
        return lines.length ? (
          <ul className="flex flex-col gap-0.5 tabular">
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
}

const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

/** `HH:MM:SS` → `HH:MM`. */
const localTime = (value: string) => value.replace(/^(\d{2}:\d{2})(:\d{2}(\.\d+)?)?$/, "$1");

export function calendarItems(calendar: MyCalendar): KeyValue[] {
  const f = m.calendar.fields;
  const shift = calendar.shift;
  const shiftLabel = [shift.name ?? shift.code, `${localTime(shift.start_local)}–${localTime(shift.end_local)}`].filter(Boolean).join(", ");
  return [
    { term: f.calendar, description: calendar.calendar_name ?? calendar.calendar_code ?? m.calendar.builtIn },
    { term: f.source, description: m.calendar.sources[calendar.source] ?? calendar.source },
    { term: f.timeZone, description: calendar.time_zone, mono: true },
    { term: f.workDate, description: <LocalDate value={calendar.work_date} /> },
    { term: f.dayType, description: m.calendar.dayTypes[calendar.day_type] ?? calendar.day_type },
    { term: f.shift, description: shiftLabel, numeric: true },
    { term: f.rollover, description: localTime(calendar.rollover_local), numeric: true },
    { term: f.workweek, description: calendar.workweek.map((day) => WEEKDAYS[day - 1]).filter(Boolean).join(", ") },
    { term: f.nextWorkingDay, description: <LocalDate value={calendar.next_working_day} /> },
  ];
}

function Currencies() {
  const query = useQuery({ queryKey: queryKeys.org.currencies(), queryFn: ({ signal }) => fetchCurrencies(signal) });
  return (
    <SectionCard title={m.currencies.title} description={m.currencies.intro}>
      {query.isPending ? (
        <Loading label={m.currencies.what} rows={3} />
      ) : query.isError ? (
        <ErrorState error={query.error} what={m.currencies.what} onRetry={() => void query.refetch()} headingLevel={3} compact backToToday={false} />
      ) : (
        <DataTable caption={m.currencies.title} hideCaption columns={currencyColumns()} rows={query.data} rowId={(row) => row.code} empty={<EmptyState title={m.currencies.empty} headingLevel={3} />} />
      )}
    </SectionCard>
  );
}

function Uoms() {
  const query = useQuery({ queryKey: queryKeys.org.uoms(), queryFn: ({ signal }) => fetchUoms(signal) });
  return (
    <SectionCard title={m.uoms.title} description={m.uoms.intro}>
      {query.isPending ? (
        <Loading label={m.uoms.what} rows={3} />
      ) : query.isError ? (
        <ErrorState error={query.error} what={m.uoms.what} onRetry={() => void query.refetch()} headingLevel={3} compact backToToday={false} />
      ) : (
        <DataTable caption={m.uoms.title} hideCaption columns={uomColumns()} rows={query.data} rowId={(row) => row.code} empty={<EmptyState title={m.uoms.empty} headingLevel={3} />} />
      )}
    </SectionCard>
  );
}

function WorkCalendar() {
  const query = useQuery({ queryKey: queryKeys.org.calendar(), queryFn: ({ signal }) => fetchMyCalendar(signal) });
  return (
    <SectionCard title={m.calendar.title} description={m.calendar.intro}>
      {query.isPending ? (
        <Loading label={m.calendar.what} variant="detail" />
      ) : query.isError ? (
        <ErrorState error={query.error} what={m.calendar.what} onRetry={() => void query.refetch()} headingLevel={3} compact backToToday={false} />
      ) : (
        <>
          <KeyValueGrid items={calendarItems(query.data)} />
          <div className="flex flex-col gap-1">
            <h3 className="text-sm text-ink-muted">{m.calendar.fields.holidays}</h3>
            {query.data.upcoming_holidays.length === 0 ? (
              <p className="text-ink-muted">{m.calendar.noHolidays}</p>
            ) : (
              <ul className="flex flex-col divide-y">
                {query.data.upcoming_holidays.map((holiday) => (
                  <li key={`${holiday.date}:${holiday.name}`} className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 py-2">
                    <span className="text-ink">{holiday.name}</span>
                    <span className="text-sm text-ink-muted">
                      <LocalDate value={holiday.date} />
                      {holiday.kind ? ` · ${holiday.kind}` : ""}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      )}
    </SectionCard>
  );
}

export function ReferenceData() {
  const { permissionKeys } = useSession();
  return (
    <div className="flex max-w-5xl flex-col gap-6">
      <PageHeader title={m.title} intro={m.intro} eyebrow={settingsMessages.hub.title} nav={<SettingsAreaNav />} />
      <Currencies />
      <Uoms />
      {permissionKeys.has("org.calendar.read") ? <WorkCalendar /> : null}
    </div>
  );
}
