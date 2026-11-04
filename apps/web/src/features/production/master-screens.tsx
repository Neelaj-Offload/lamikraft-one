"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { AreaNav } from "@/components/shell/area-nav";
import { Badge, StatusPill } from "@/components/ui/badge";
import { Button, unavailableWhen } from "@/components/ui/button";
import { DataTable, type DataTableColumn } from "@/components/ui/data-table";
import { DatePicker } from "@/components/ui/date-picker";
import { LocalDate, LocalDateTime, Money } from "@/components/ui/format";
import { KeyValueGrid } from "@/components/ui/key-value-grid";
import { Link } from "@/components/ui/link";
import { NumberField } from "@/components/ui/number-field";
import { PageHeader } from "@/components/ui/page-header";
import { ReasonDialog } from "@/components/ui/reason-dialog";
import { MetaDot, RecordHeader } from "@/components/ui/record-header";
import { SearchField } from "@/components/ui/search-field";
import { SectionCard } from "@/components/ui/section-card";
import { EmptyState, ErrorState, Loading } from "@/components/ui/states";
import { TextField } from "@/components/ui/text-field";
import { queryKeys } from "@/lib/api/query-keys";
import { useSession } from "@/lib/session/context";
import { productionMessages as m } from "@/messages/production";
import {
  bomAction,
  copyBom,
  copyRouting,
  deleteCapacityException,
  fetchBom,
  fetchBoms,
  fetchCapacity,
  fetchCostRollups,
  fetchRouting,
  fetchRoutings,
  fetchWorkCentre,
  fetchWorkCentres,
  routingAction,
  runCostRollup,
  setCapacityException,
  type BomRead,
  type CapacityRead,
  type CostRollupRead,
  type MasterSummary,
  type RoutingRead,
  type WorkCenterRead,
  type WorkCenterSummary,
} from "./api";
import { MasterStatus, OPERATIONS_LEADING, ProductionTabs, dash, failure, qty, useProductionCommand } from "./common";

const ms = m.masters;

// =====================================================================================================
// BOM and routing lists
// =====================================================================================================
function MastersList({ kind }: { kind: "boms" | "routings" }) {
  const [q, setQ] = useState("");
  const query = useQuery({
    queryKey: kind === "boms" ? queryKeys.production.boms({ q }) : queryKeys.production.routings({ q }),
    queryFn: ({ signal }) => (kind === "boms" ? fetchBoms({ q }, signal) : fetchRoutings({ q }, signal)),
  });
  const base = kind === "boms" ? "/operations/production/boms" : "/operations/production/routings";
  const c = ms.columns;
  const columns: DataTableColumn<MasterSummary>[] = [
    { id: "product", header: c.product, isRowHeader: true, mobile: "title", cell: (r) => <Link href={`${base}/${r.id}`}><span className="font-mono">{r.product.product_key}</span> {r.product.name}</Link>, mobileCell: (r) => r.product.product_key },
    { id: "version", header: c.version, mobile: "key", cell: (r) => m.version(r.version_no) },
    { id: "status", header: c.status, mobile: "status", cell: (r) => <MasterStatus status={r.status} /> },
    { id: "lines", header: c.lines, numeric: true, cell: (r) => r.line_count },
    { id: "author", header: c.author, cell: (r) => r.author?.display_name ?? dash },
    { id: "approved", header: c.approvedBy, cell: (r) => r.approved_by?.display_name ?? dash },
    { id: "updated", header: c.updated, mobile: "meta", cell: (r) => <LocalDateTime value={r.updated_at} /> },
  ];
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={kind === "boms" ? ms.bomsTitle : ms.routingsTitle}
        intro={kind === "boms" ? ms.bomsIntro : ms.routingsIntro}
        nav={<AreaNav area="operations" label={m.area} leading={OPERATIONS_LEADING} />}
      />
      <ProductionTabs current={kind} />
      <SearchField label={m.workOrders.product} defaultValue={q} onSubmit={setQ} onClear={() => setQ("")} className="max-w-md" />
      {query.isPending ? (
        <Loading label={ms.loading} />
      ) : query.isError ? (
        <ErrorState error={query.error} what={ms.loading} onRetry={() => void query.refetch()} />
      ) : (
        <DataTable caption={ms.caption} hideCaption columns={columns} rows={query.data.items} rowId={(r) => r.id} rowHref={(r) => `${base}/${r.id}`} empty={<EmptyState title={ms.emptyTitle}>{ms.empty}</EmptyState>} />
      )}
    </div>
  );
}

export function BomsScreen() {
  return <MastersList kind="boms" />;
}

export function RoutingsScreen() {
  return <MastersList kind="routings" />;
}

// =====================================================================================================
// version detail (shared header and actions)
// =====================================================================================================
function VersionHeader<T extends BomRead | RoutingRead>({ record, back, onAction, pending, onCopy }: { record: T; back: { href: string; label: string }; onAction: (a: "approve" | "retire", reason?: string) => void; onCopy: () => void; pending: string | null }) {
  const [retiring, setRetiring] = useState(false);
  const caps = record.capabilities;
  return (
    <>
      <RecordHeader
        back={back}
        recordKey={m.version(record.version_no)}
        title={`${record.product.product_key} · ${record.product.name}`}
        status={<MasterStatus status={record.status} />}
        meta={
          <>
            <span>{record.author?.display_name ?? dash}</span>
            {record.approved_by ? (
              <>
                <MetaDot />
                <span>
                  {ms.columns.approvedBy}: {record.approved_by.display_name}
                </span>
              </>
            ) : null}
            <MetaDot />
            <LocalDateTime value={record.updated_at} />
          </>
        }
        actions={
          <>
            {caps.approve?.allowed ? (
              <Button variant="primary" isPending={pending === "approve"} onPress={() => onAction("approve")}>
                {ms.approve}
              </Button>
            ) : null}
            {caps.retire?.allowed ? <Button onPress={() => setRetiring(true)}>{ms.retire}</Button> : null}
            {caps.new_version?.allowed ? (
              <Button variant="quiet" isPending={pending === "copy"} onPress={onCopy}>
                {ms.newVersion}
              </Button>
            ) : null}
          </>
        }
      />
      {caps.approve?.reason_code === "separation_of_duties" ? <p className="text-sm text-ink-muted">{ms.separation}</p> : null}
      <ReasonDialog
        title={ms.retireTitle}
        description={ms.retireBody}
        requireNote
        noteLabel={ms.retireReason}
        confirmLabel={ms.retire}
        isOpen={retiring}
        isPending={pending === "retire"}
        onOpenChange={setRetiring}
        onConfirm={(_code, note) => {
          onAction("retire", note);
          setRetiring(false);
        }}
      />
    </>
  );
}

export function BomScreen({ bomId }: { bomId: string }) {
  const query = useQuery({ queryKey: queryKeys.production.bom(bomId), queryFn: ({ signal }) => fetchBom(bomId, signal) });
  if (query.isPending) return <Loading label={ms.loading} variant="detail" />;
  if (query.isError) return failure(query.error, ms.bomsTitle, () => void query.refetch());
  return <Bom bom={query.data} key={query.data.version} />;
}

function Bom({ bom }: { bom: BomRead }) {
  const router = useRouter();
  const key = useMemo(() => queryKeys.production.bom(bom.id), [bom.id]);
  const { run, pending } = useProductionCommand<BomRead>(key);
  const c = ms.lineColumns;
  type Line = BomRead["lines"][number];
  const columns: DataTableColumn<Line>[] = [
    { id: "line", header: c.line, numeric: true, cell: (l) => l.line_no },
    { id: "component", header: c.component, isRowHeader: true, mobile: "title", cell: (l) => <span><span className="font-mono">{l.component.product_key}</span> {l.component.name}</span>, mobileCell: (l) => l.component.product_key },
    { id: "qty", header: c.qty, numeric: true, mobile: "amount", cell: (l) => qty(l.qty_per, l.uom_code) },
    { id: "scrap", header: c.scrap, numeric: true, cell: (l) => `${l.scrap_pct} %` },
    {
      id: "flags",
      header: c.flags,
      mobile: "meta",
      cell: (l) => (
        <span className="flex flex-wrap gap-1.5">
          {l.is_sheet_material ? <Badge tone="info">{ms.sheet}</Badge> : null}
          {l.alternate_for_line_no ? <Badge>{ms.alternateFor(l.alternate_for_line_no)}</Badge> : null}
          {l.has_approved_bom ? <Badge>{ms.subBom}</Badge> : null}
        </span>
      ),
    },
  ];
  return (
    <div className="flex flex-col gap-6">
      <VersionHeader
        record={bom}
        back={{ href: "/operations/production/boms", label: ms.bomsTitle }}
        pending={pending}
        onAction={(a, reason) => void run(a, (k) => bomAction(bom, a, k, reason), { done: a === "approve" ? ms.approved : ms.retired, failed: ms.failed, write: (r) => r })}
        onCopy={() =>
          void run("copy", (k) => copyBom(bom, k), { done: ms.newVersionCreated, failed: ms.failed }).then((r) => {
            if (r) router.push(`/operations/production/boms/${r.id}` as Parameters<typeof router.push>[0]);
          })
        }
      />
      {bom.notes ? <p className="max-w-3xl text-ink-muted">{bom.notes}</p> : null}
      <SectionCard title={ms.lines}>
        <DataTable caption={ms.linesCaption} hideCaption columns={columns} rows={bom.lines} rowId={(l) => l.id} />
      </SectionCard>
      <CostRollup productId={bom.product.id} />
    </div>
  );
}

function CostRollup({ productId }: { productId: string }) {
  const { permissionKeys } = useSession();
  const key = useMemo(() => queryKeys.production.costRollups(productId), [productId]);
  const latest = useQuery({ queryKey: key, queryFn: ({ signal }) => fetchCostRollups(productId, signal) });
  const { run, pending } = useProductionCommand<null>(key);
  const [shown, setShown] = useState<CostRollupRead | null>(null);
  const rollup = shown ?? latest.data?.items[0] ?? null;
  const canRun = permissionKeys.has("production.cost_rollup.run");
  const c = ms.costColumns;
  type Line = NonNullable<CostRollupRead["lines"]>[number];
  const columns: DataTableColumn<Line>[] = [
    { id: "path", header: c.path, mobile: "meta", cell: (l) => <span className="font-mono text-sm">{l.path}</span> },
    { id: "label", header: c.label, isRowHeader: true, mobile: "title", cell: (l) => l.label },
    { id: "qty", header: c.qty, numeric: true, cell: (l) => qty(l.quantity, l.uom_code) },
    { id: "unit", header: c.unit, numeric: true, cell: (l) => <Money value={l.unit_cost} maxFractionDigits={4} /> },
    { id: "amount", header: c.amount, numeric: true, mobile: "amount", cell: (l) => <Money value={l.amount} maxFractionDigits={4} /> },
  ];
  return (
    <SectionCard
      title={ms.costTitle}
      description={ms.costIntro}
      actions={
        canRun ? (
          <Button
            isPending={pending === "rollup"}
            onPress={() =>
              void run("rollup", (k) => runCostRollup(productId, k), { failed: ms.failed }).then((r) => {
                if (r) setShown(r);
              })
            }
          >
            {ms.runRollup}
          </Button>
        ) : undefined
      }
    >
      {latest.isPending ? (
        <Loading label={ms.costTitle} />
      ) : latest.isError ? (
        <ErrorState error={latest.error} what={ms.costTitle} onRetry={() => void latest.refetch()} />
      ) : !rollup ? (
        <p className="text-ink-muted">{ms.costIntro}</p>
      ) : (
        <div className="flex flex-col gap-4">
          <div className="flex flex-wrap items-center gap-2">
            {rollup.status === "complete" ? <StatusPill tone="success">{ms.complete}</StatusPill> : <StatusPill tone="warning">{ms.partial}</StatusPill>}
            {rollup.reused ? <Badge>{ms.reused}</Badge> : null}
            <span className="text-sm text-ink-muted">
              <LocalDate value={rollup.as_of} /> · {rollup.currency}
            </span>
          </div>
          {rollup.total ? (
            <KeyValueGrid
              items={[
                { term: ms.total, description: <Money value={rollup.total} maxFractionDigits={4} />, numeric: true },
                { term: ms.materialTotal, description: <Money value={rollup.material_total} maxFractionDigits={4} />, numeric: true },
                { term: ms.operationTotal, description: <Money value={rollup.operation_total} maxFractionDigits={4} />, numeric: true },
              ]}
            />
          ) : (
            <p className="text-sm text-ink-muted">{ms.redacted}</p>
          )}
          {rollup.missing_inputs.length ? (
            <div>
              <h3 className="text-sm font-semibold">{ms.missing}</h3>
              <ul className="mt-1 list-disc ps-5 text-sm">
                {rollup.missing_inputs.map((x) => (
                  <li key={`${x.kind}-${x.ref_id ?? x.label}`}>{x.label}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {rollup.lines ? <DataTable caption={ms.costTitle} hideCaption columns={columns} rows={rollup.lines} rowId={(l) => `${l.path}-${l.label}`} /> : null}
        </div>
      )}
    </SectionCard>
  );
}

export function RoutingScreen({ routingId }: { routingId: string }) {
  const query = useQuery({ queryKey: queryKeys.production.routing(routingId), queryFn: ({ signal }) => fetchRouting(routingId, signal) });
  if (query.isPending) return <Loading label={ms.loading} variant="detail" />;
  if (query.isError) return failure(query.error, ms.routingsTitle, () => void query.refetch());
  return <Routing routing={query.data} key={query.data.version} />;
}

function Routing({ routing }: { routing: RoutingRead }) {
  const router = useRouter();
  const key = useMemo(() => queryKeys.production.routing(routing.id), [routing.id]);
  const { run, pending } = useProductionCommand<RoutingRead>(key);
  const c = ms.opColumns;
  type Op = RoutingRead["operations"][number];
  const columns: DataTableColumn<Op>[] = [
    { id: "seq", header: c.seq, numeric: true, cell: (o) => o.seq },
    { id: "name", header: c.name, isRowHeader: true, mobile: "title", cell: (o) => o.name },
    { id: "centre", header: c.centre, mobile: "key", cell: (o) => <Link href={`/operations/production/work-centres/${o.work_center.id}`}>{o.work_center.code}</Link>, mobileCell: (o) => o.work_center.code },
    { id: "setup", header: c.setup, numeric: true, cell: (o) => m.minutes(o.setup_minutes) },
    { id: "run", header: c.run, numeric: true, mobile: "amount", cell: (o) => m.minutes(o.run_minutes_per_unit) },
    { id: "flags", header: c.flags, mobile: "meta", cell: (o) => <span className="flex flex-wrap gap-1.5">{o.is_board_cutting ? <Badge tone="info">{ms.boardOp}</Badge> : null}{o.is_job_work ? <Badge>{ms.jobWork}</Badge> : null}</span> },
  ];
  return (
    <div className="flex flex-col gap-6">
      <VersionHeader
        record={routing}
        back={{ href: "/operations/production/routings", label: ms.routingsTitle }}
        pending={pending}
        onAction={(a, reason) => void run(a, (k) => routingAction(routing, a, k, reason), { done: a === "approve" ? ms.approved : ms.retired, failed: ms.failed, write: (r) => r })}
        onCopy={() =>
          void run("copy", (k) => copyRouting(routing, k), { done: ms.newVersionCreated, failed: ms.failed }).then((r) => {
            if (r) router.push(`/operations/production/routings/${r.id}` as Parameters<typeof router.push>[0]);
          })
        }
      />
      <p className="text-sm text-ink-muted">{ms.batch(`${routing.standard_batch_qty} ${routing.product.stock_uom_code ?? ""}`.trim())}</p>
      <SectionCard title={ms.operations}>
        <DataTable caption={ms.operationsCaption} hideCaption columns={columns} rows={routing.operations} rowId={(o) => o.id} />
      </SectionCard>
    </div>
  );
}

// =====================================================================================================
// work centres
// =====================================================================================================
export function WorkCentresScreen() {
  const query = useQuery({ queryKey: queryKeys.production.workCentres(), queryFn: ({ signal }) => fetchWorkCentres(signal) });
  const w = m.workCentres;
  const c = w.columns;
  const columns: DataTableColumn<WorkCenterSummary>[] = [
    { id: "code", header: c.code, isRowHeader: true, mobile: "title", cell: (r) => <Link href={`/operations/production/work-centres/${r.id}`} className="font-mono">{r.code}</Link>, mobileCell: (r) => r.code },
    { id: "name", header: c.name, mobile: "key", cell: (r) => r.name },
    { id: "kind", header: c.kind, cell: (r) => w.kinds[r.kind] ?? r.kind },
    { id: "machines", header: c.machines, numeric: true, cell: (r) => r.machine_count },
    { id: "eff", header: c.efficiency, numeric: true, cell: (r) => `${Number(r.efficiency_pct)} %` },
    { id: "day", header: c.day, numeric: true, mobile: "amount", cell: (r) => m.minutes(String(Number(r.standard_day_minutes))) },
    { id: "rate", header: c.rate, numeric: true, cell: (r) => (r.rate_per_hour ? <Money value={r.rate_per_hour} /> : r.redacted_fields?.includes("rate_per_hour") ? <span className="text-ink-muted">{w.rateHidden}</span> : dash) },
  ];
  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={w.title} intro={w.intro} nav={<AreaNav area="operations" label={m.area} leading={OPERATIONS_LEADING} />} />
      <ProductionTabs current="workCentres" />
      {query.isPending ? (
        <Loading label={w.loading} />
      ) : query.isError ? (
        <ErrorState error={query.error} what={w.loading} onRetry={() => void query.refetch()} />
      ) : (
        <DataTable caption={w.caption} hideCaption columns={columns} rows={query.data} rowId={(r) => r.id} rowHref={(r) => `/operations/production/work-centres/${r.id}`} empty={<EmptyState title={w.emptyTitle}>{w.empty}</EmptyState>} />
      )}
    </div>
  );
}

export function WorkCentreScreen({ workCenterId }: { workCenterId: string }) {
  const query = useQuery({ queryKey: queryKeys.production.workCentre(workCenterId), queryFn: ({ signal }) => fetchWorkCentre(workCenterId, signal) });
  if (query.isPending) return <Loading label={m.workCentres.loading} variant="detail" />;
  if (query.isError) return failure(query.error, m.workCentres.title, () => void query.refetch());
  return <WorkCentre wc={query.data} key={query.data.version + query.data.exceptions.length} />;
}

function WorkCentre({ wc }: { wc: WorkCenterRead }) {
  const w = m.workCentres;
  const key = useMemo(() => queryKeys.production.workCentre(wc.id), [wc.id]);
  const { run, pending } = useProductionCommand<WorkCenterRead>(key);
  const [day, setDay] = useState<string | null>(null);
  const [minutes, setMinutes] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const canManage = Boolean(wc.capabilities.manage_exceptions?.allowed);
  type Exc = WorkCenterRead["exceptions"][number];
  const columns: DataTableColumn<Exc>[] = [
    { id: "day", header: w.exceptionColumns.day, isRowHeader: true, mobile: "title", cell: (e) => <LocalDate value={e.exception_date} /> },
    { id: "minutes", header: w.exceptionColumns.minutes, numeric: true, mobile: "amount", cell: (e) => m.minutes(String(e.available_minutes)) },
    { id: "reason", header: w.exceptionColumns.reason, mobile: "meta", cell: (e) => e.reason },
    {
      id: "remove",
      header: "",
      cell: (e) =>
        canManage ? (
          <Button size="sm" variant="quiet" isPending={pending === `rm-${e.id}`} onPress={() => void run(`rm-${e.id}`, () => deleteCapacityException(wc.id, e.id), { done: w.removed, failed: w.failed, write: (r) => r })}>
            {w.remove}
          </Button>
        ) : null,
    },
  ];
  return (
    <div className="flex flex-col gap-6">
      <RecordHeader back={{ href: "/operations/production/work-centres", label: w.back }} recordKey={wc.code} title={wc.name} status={wc.is_active ? null : <StatusPill>{"Inactive"}</StatusPill>} />
      <KeyValueGrid
        items={[
          { term: w.columns.machines, description: String(wc.machine_count), numeric: true },
          { term: w.columns.efficiency, description: `${Number(wc.efficiency_pct)} %`, numeric: true },
          { term: w.columns.day, description: m.minutes(String(Number(wc.standard_day_minutes))), numeric: true },
          { term: w.calendar, description: `${wc.calendar.name} (${w.sources[wc.calendar.source] ?? wc.calendar.source})` },
          { term: w.shifts, description: wc.shifts.map((s) => `${s.name} ${s.start}–${s.end}`).join(", ") || dash },
          { term: w.columns.rate, description: wc.rate_per_hour ? <Money value={wc.rate_per_hour} /> : wc.redacted_fields?.includes("rate_per_hour") ? w.rateHidden : dash },
        ]}
      />
      <SectionCard title={w.exceptions}>
        <DataTable caption={w.exceptionsCaption} hideCaption columns={columns} rows={wc.exceptions} rowId={(e) => e.id} empty={<p className="text-ink-muted">{w.noExceptions}</p>} />
        {canManage ? (
          <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-[auto_auto_minmax(0,1fr)_auto] md:items-end">
            <DatePicker label={w.exceptionDay} value={day} onChange={setDay} />
            <NumberField label={w.exceptionMinutes} value={minutes} onChange={setMinutes} maxFractionDigits={0} />
            <TextField label={w.exceptionReason} value={reason} onChange={setReason} />
            <Button
              isPending={pending === "exception"}
              {...unavailableWhen((!day || minutes == null || !reason.trim()) ? m.fillIn : null)}
              onPress={() =>
                day && minutes != null
                  ? void run("exception", (k) => setCapacityException(wc.id, { exception_date: day, available_minutes: Number(minutes), reason: reason.trim() }, k), { done: w.saved, failed: w.failed, write: (r) => r })
                  : undefined
              }
            >
              {w.setException}
            </Button>
          </div>
        ) : null}
      </SectionCard>
    </div>
  );
}

// =====================================================================================================
// capacity
// =====================================================================================================
export function CapacityScreen({ state }: { state: { from: string | null; to: string | null } }) {
  const router = useRouter();
  const c = m.capacity;
  const query = useQuery({ queryKey: queryKeys.production.capacity(state), queryFn: ({ signal }) => fetchCapacity(state, signal) });
  const go = (next: { from?: string | null; to?: string | null }) => {
    const s = new URLSearchParams();
    const f = next.from !== undefined ? next.from : state.from;
    const t = next.to !== undefined ? next.to : state.to;
    if (f) s.set("from", f);
    if (t) s.set("to", t);
    router.push(`/operations/production/capacity${s.toString() ? `?${s}` : ""}` as Parameters<typeof router.push>[0]);
  };
  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={c.title} intro={c.intro} nav={<AreaNav area="operations" label={m.area} leading={OPERATIONS_LEADING} />} />
      <ProductionTabs current="capacity" />
      <div className="flex flex-wrap items-end gap-4">
        <DatePicker label={c.from} value={state.from ?? query.data?.date_from ?? null} onChange={(v) => go({ from: v })} />
        <DatePicker label={c.to} value={state.to ?? query.data?.date_to ?? null} onChange={(v) => go({ to: v })} />
        {query.data ? <span className="pb-2 text-sm text-ink-muted">{c.overloadedDays(query.data.overloaded_days)}</span> : null}
      </div>
      {query.isPending ? (
        <Loading label={c.loading} />
      ) : query.isError ? (
        <ErrorState error={query.error} what={c.loading} onRetry={() => void query.refetch()} />
      ) : query.data.rows.length === 0 ? (
        <EmptyState title={c.emptyTitle}>{c.empty}</EmptyState>
      ) : (
        query.data.rows.map((row) => <CapacityTable key={row.work_center.id} row={row} />)
      )}
    </div>
  );
}

function CapacityTable({ row }: { row: CapacityRead["rows"][number] }) {
  const c = m.capacity;
  type Day = (typeof row.days)[number];
  const columns: DataTableColumn<Day>[] = [
    { id: "day", header: c.columns.day, isRowHeader: true, mobile: "title", cell: (x) => <LocalDate value={x.day} /> },
    { id: "capacity", header: c.columns.capacity, numeric: true, cell: (x) => (x.day_type === "working" || Number(x.capacity_minutes) > 0 ? m.minutes(String(Number(x.capacity_minutes))) : x.day_type === "holiday" ? c.holiday : c.nonWorking) },
    { id: "load", header: c.columns.load, numeric: true, mobile: "amount", cell: (x) => m.minutes(String(Number(x.load_minutes))) },
    { id: "use", header: c.columns.use, numeric: true, mobile: "status", cell: (x) => (x.overloaded ? <StatusPill tone="danger">{c.overloaded}</StatusPill> : x.utilisation_pct != null ? `${Number(x.utilisation_pct)} %` : dash) },
    { id: "orders", header: c.columns.orders, mobile: "meta", cell: (x) => (x.work_orders.length ? x.work_orders.join(", ") : dash) },
  ];
  return (
    <SectionCard title={`${row.work_center.code} · ${row.work_center.name}`} description={Number(row.unscheduled_minutes) > 0 ? c.unscheduled(String(Number(row.unscheduled_minutes))) : undefined}>
      <DataTable caption={c.caption(row.work_center.code)} hideCaption columns={columns} rows={row.days} rowId={(x) => x.day} />
    </SectionCard>
  );
}
