"use client";

import { useQuery } from "@tanstack/react-query";
import { useMemo, useState, type FormEvent } from "react";
import { deleteCapacityException, fetchWorkCentre, setCapacityException, type WorkCenterRead } from "@/features/production/api";
import { queryKeys } from "@/lib/api/query-keys";
import { CALENDAR_SOURCE, humanise, useProductionCommand, WORK_CENTRE_KIND } from "~/data/production";
import { Page, RecordHeader, Split } from "~/shell/page";
import { Badge, Banner, Button, DataTable, DatePicker, DateText, EmptyState, FactStrip, GlassPanel, IntegerField, KeyValue, TextField, type Column } from "~/ui";
import { Minutes, OPERATIONS_CRUMB, PATHS, Percent, RecordFailed, RecordLoading, stagger, ViewHeading } from "./parts";
import { RateText } from "./work-centre-list";

const FAILED = "That did not go through";

/** A work centre: what a day holds, the calendar behind it, and the days that differ. */
export function WorkCentreRecord({ workCenterId }: { workCenterId: string }) {
  const query = useQuery({ queryKey: queryKeys.production.workCentre(workCenterId), queryFn: ({ signal }) => fetchWorkCentre(workCenterId, signal) });
  if (query.isPending) return <RecordLoading label="Loading the work centre" />;
  if (query.isError) return <RecordFailed error={query.error} what="This work centre" onRetry={() => void query.refetch()} backHref={PATHS.workCentres} backLabel="All work centres" />;
  return <Loaded wc={query.data} />;
}

type Exception = WorkCenterRead["exceptions"][number];

function Loaded({ wc }: { wc: WorkCenterRead }) {
  const key = useMemo(() => queryKeys.production.workCentre(wc.id), [wc.id]);
  const { run, pending, offline } = useProductionCommand<WorkCenterRead>(key);
  const canManage = Boolean(wc.capabilities.manage_exceptions?.allowed);
  const write = (record: WorkCenterRead) => record;
  const exceptions = [...wc.exceptions].sort((a, b) => a.exception_date.localeCompare(b.exception_date));

  const columns: Column<Exception>[] = [
    { key: "day", header: "Day", primary: true, cell: (exception) => <DateText value={exception.exception_date} style="business" className="t-label text-ink" /> },
    { key: "minutes", header: "Available", numeric: true, cell: (exception) => (exception.available_minutes === 0 ? <span className="text-ink-2">Closed</span> : <Minutes value={exception.available_minutes} />) },
    { key: "reason", header: "Reason", cell: (exception) => <span className="text-ink-2">{exception.reason}</span> },
    ...(canManage
      ? [
          {
            key: "remove",
            header: <span className="sr-only">Remove</span>,
            mobileLabel: "Remove",
            width: "120px",
            cell: (exception: Exception) => (
              <Button
                variant="ghost"
                size="sm"
                iconLeft="trash"
                aria-label={`Remove the capacity set for ${exception.exception_date}`}
                loading={pending === `rm-${exception.id}`}
                isDisabled={Boolean(offline)}
                onPress={() => void run(`rm-${exception.id}`, () => deleteCapacityException(wc.id, exception.id), { done: "That day follows the calendar again", failed: FAILED, write })}
              >
                Remove
              </Button>
            ),
          } satisfies Column<Exception>,
        ]
      : []),
  ];

  return (
    <Page>
      <RecordHeader
        breadcrumb={[OPERATIONS_CRUMB, { label: "Work centres", href: PATHS.workCentres }, { label: wc.code }]}
        code={wc.code}
        title={wc.name}
        status={
          wc.is_active ? (
            <Badge tone="leaf" dot>
              Active
            </Badge>
          ) : (
            <Badge outline>Inactive</Badge>
          )
        }
        lead={wc.notes || undefined}
        facts={
          <FactStrip
            items={[
              { label: "Standard day", icon: "clock", value: <Minutes value={wc.standard_day_minutes} /> },
              { label: "Machines", icon: "factory", value: String(wc.machine_count) },
              { label: "Efficiency", icon: "gauge", value: <Percent value={wc.efficiency_pct} /> },
              { label: "Rate per hour", icon: "banknote", value: <RateText centre={wc} /> },
              { label: "Run by", icon: "users", value: WORK_CENTRE_KIND[wc.kind] ?? wc.kind },
            ]}
          />
        }
      />

      {offline ? (
        <Banner tone="amber" title="You are offline.">
          You can read this work centre. Changes work again once the connection is back.
        </Banner>
      ) : null}

      <Split
        main={
          <div className="stack">
            <ViewHeading title="Days that differ" text="A day listed here holds the minutes shown instead of what the calendar gives it. Capacity planning uses these first." />
            <GlassPanel padding="none" className="rise min-w-0">
              <DataTable
                label={`Capacity exceptions of ${wc.code}`}
                columns={columns}
                rows={exceptions}
                rowKey={(exception) => exception.id}
                empty={<EmptyState compact icon="calendar" title="Every working day follows the calendar" text={canManage ? "Set a day below when a machine is down or an extra shift runs." : "No day has its own capacity set."} />}
              />
            </GlassPanel>
            {canManage ? <ExceptionForm wc={wc} run={run} pending={pending} offline={Boolean(offline)} /> : null}
          </div>
        }
        aside={
          <>
            <GlassPanel padding="md" className="rise" style={stagger(1)} title="Calendar" titleAs="h2">
              <KeyValue
                rows
                items={[
                  { label: "Follows", value: wc.calendar.name },
                  { label: "Source", value: humanise(CALENDAR_SOURCE[wc.calendar.source] ?? wc.calendar.source) },
                ]}
              />
            </GlassPanel>
            <GlassPanel padding="md" className="rise" style={stagger(2)} title="Shifts" titleAs="h2">
              {wc.shifts.length === 0 ? (
                <p className="t-body-sm text-ink-2">The calendar names no shifts.</p>
              ) : (
                <ul className="flex flex-col">
                  {wc.shifts.map((shift, index) => (
                    <li key={shift.code} className={`flex min-w-0 items-baseline justify-between gap-3 py-2.5 ${index > 0 ? "border-t border-line" : ""}`}>
                      <span className="flex min-w-0 flex-col gap-0.5">
                        <span className="t-label text-ink">{shift.name}</span>
                        <span className="t-caption lk-tnum text-ink-3">
                          {shift.start} to {shift.end}
                        </span>
                      </span>
                      <Minutes value={shift.minutes} className="t-body-sm text-ink-2" />
                    </li>
                  ))}
                </ul>
              )}
            </GlassPanel>
          </>
        }
      />
    </Page>
  );
}

function ExceptionForm({
  wc,
  run,
  pending,
  offline,
}: {
  wc: WorkCenterRead;
  run: ReturnType<typeof useProductionCommand<WorkCenterRead>>["run"];
  pending: string | null;
  offline: boolean;
}) {
  const [day, setDay] = useState<string | null>(null);
  const [minutes, setMinutes] = useState<number | null>(null);
  const [reason, setReason] = useState("");
  const [errors, setErrors] = useState<{ day?: string; minutes?: string; reason?: string }>({});

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const found: typeof errors = {};
    if (!day) found.day = "Choose the day.";
    if (minutes === null) found.minutes = "Say how many minutes the day holds. Use 0 if it is closed.";
    else if (minutes < 0) found.minutes = "Use 0 or more minutes.";
    if (!reason.trim()) found.reason = "Say why, so planners know.";
    setErrors(found);
    if (!day || minutes === null || minutes < 0 || !reason.trim()) return;
    void run("exception", (key) => setCapacityException(wc.id, { exception_date: day, available_minutes: minutes, reason: reason.trim() }, key), {
      done: "Capacity set for that day",
      failed: FAILED,
      write: (record) => record,
    }).then((result) => {
      if (!result) return;
      setDay(null);
      setMinutes(null);
      setReason("");
    });
  };

  return (
    <GlassPanel padding="lg" className="rise" title="Set capacity for a day" titleAs="h3">
      <form onSubmit={submit} noValidate className="flex flex-col gap-5">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <DatePicker
          label="Day"
          value={day}
          onChange={(value) => {
            setDay(value);
            setErrors((current) => ({ ...current, day: undefined }));
          }}
          isRequired
          error={errors.day}
        />
        <IntegerField
          label="Minutes available"
          value={minutes}
          minValue={0}
          step={30}
          onChange={(value) => {
            setMinutes(value);
            setErrors((current) => ({ ...current, minutes: undefined }));
          }}
          isRequired
          help={
            <>
              A standard day here is <Minutes value={wc.standard_day_minutes} />.
            </>
          }
          error={errors.minutes}
        />
        <TextField
          className="sm:col-span-2"
          label="Reason"
          value={reason}
          onChange={(value) => {
            setReason(value);
            setErrors((current) => ({ ...current, reason: undefined }));
          }}
          placeholder="Machine down for maintenance"
          isRequired
          error={errors.reason}
        />
      </div>
      <div className="flex justify-end">
        <Button type="submit" variant="inverse" iconLeft="calendar" loading={pending === "exception"} isDisabled={offline}>
          Set capacity
        </Button>
      </div>
      </form>
    </GlassPanel>
  );
}
