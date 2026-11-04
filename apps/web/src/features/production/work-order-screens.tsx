"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { AreaNav } from "@/components/shell/area-nav";
import { Badge, StatusPill } from "@/components/ui/badge";
import { Button, unavailableWhen } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/choice";
import { DataTable, OffsetPagination, type DataTableColumn } from "@/components/ui/data-table";
import { DatePicker } from "@/components/ui/date-picker";
import { Dialog } from "@/components/ui/dialog";
import { InfoIcon } from "@/components/ui/icons";
import { LocalDate, LocalDateTime } from "@/components/ui/format";
import { Link } from "@/components/ui/link";
import { NumberField } from "@/components/ui/number-field";
import { PageHeader } from "@/components/ui/page-header";
import { ReasonDialog } from "@/components/ui/reason-dialog";
import { MetaDot, RecordHeader } from "@/components/ui/record-header";
import { SearchField } from "@/components/ui/search-field";
import { SectionCard } from "@/components/ui/section-card";
import { Select } from "@/components/ui/select";
import { EmptyState, ErrorState, Loading, StateView } from "@/components/ui/states";
import { TextArea } from "@/components/ui/text-field";
import { fetchPlans } from "@/features/cutting/api";
import { fetchWarehouses } from "@/features/inventory/api";
import { queryKeys } from "@/lib/api/query-keys";
import { productionMessages as m } from "@/messages/production";
import {
  completeOperation,
  createWorkOrder,
  fetchBoms,
  fetchPosition,
  fetchWorkOrder,
  fetchWorkOrders,
  issueMaterials,
  linkCutPlan,
  moveFromWip,
  PAGE_SIZE,
  recheckWorkOrder,
  recordOffcut,
  reportOutput,
  transitionWorkOrder,
  type CancelReason,
  type MaterialRead,
  type OperationRead,
  type WorkOrderRead,
  type WorkOrderSummary,
} from "./api";
import { OPERATIONS_LEADING, ProductionTabs, WorkOrderStatus, dash, failure, qty, useProductionCommand } from "./common";
import { workOrdersHref, type WorkOrderListState } from "./list-state";
import { isPositiveDecimalStr, subtractDecimalStr } from "@/lib/format/decimal";

const d = m.detail;

// =====================================================================================================
// /operations/production/work-orders
// =====================================================================================================
export function WorkOrdersScreen({ state }: { state: WorkOrderListState }) {
  const router = useRouter();
  const query = useQuery({
    queryKey: queryKeys.production.workOrders({ ...state }),
    queryFn: ({ signal }) => fetchWorkOrders({ q: state.q, status: state.status as WorkOrderSummary["status"] | null, blocked: state.blocked, offset: state.offset }, signal),
  });
  const go = (next: Partial<WorkOrderListState>) => router.push(workOrdersHref({ ...state, offset: 0, ...next }) as Parameters<typeof router.push>[0]);
  const w = m.workOrders;
  const columns: DataTableColumn<WorkOrderSummary>[] = [
    { id: "number", header: w.columns.number, isRowHeader: true, mobile: "title", cell: (r) => <Link href={`/operations/production/work-orders/${r.id}`} className="font-mono">{r.wo_number}</Link>, mobileCell: (r) => r.wo_number },
    { id: "product", header: w.columns.product, mobile: "key", cell: (r) => <span><span className="font-mono">{r.product.product_key}</span> <span className="text-ink-muted">{r.product.name}</span></span>, mobileCell: (r) => r.product.product_key },
    { id: "qty", header: w.columns.quantity, numeric: true, mobile: "amount", cell: (r) => qty(r.qty_planned, r.uom_code) },
    { id: "status", header: w.columns.status, mobile: "status", cell: (r) => <WorkOrderStatus status={r.status} blocked={r.is_blocked} /> },
    { id: "start", header: w.columns.start, cell: (r) => (r.planned_start_date ? <LocalDate value={r.planned_start_date} /> : dash) },
    { id: "due", header: w.columns.due, mobile: "meta", cell: (r) => (r.due_date ? <LocalDate value={r.due_date} /> : dash) },
    { id: "order", header: w.columns.order, cell: (r) => (r.sales_order ? <Link href={r.sales_order.path}>{r.sales_order.order_number}</Link> : dash), mobileCell: (r) => r.sales_order?.order_number ?? "" },
  ];
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={w.title}
        intro={w.intro}
        nav={<AreaNav area="operations" label={m.area} leading={OPERATIONS_LEADING} />}
        actions={<Link href="/operations/production/work-orders/new">{w.newTitle}</Link>}
      />
      <ProductionTabs current="workOrders" />
      <div className="grid grid-cols-1 gap-4 md:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_auto] md:items-end">
        <SearchField label={w.search} placeholder={w.searchPlaceholder} defaultValue={state.q} onSubmit={(q) => go({ q })} onClear={() => go({ q: "" })} />
        <Select
          label={w.status}
          options={[{ id: "", label: w.anyStatus }, ...Object.entries(m.statuses).map(([id, label]) => ({ id, label }))]}
          value={state.status ?? ""}
          onChange={(value) => go({ status: value || null })}
        />
        <Checkbox isSelected={state.blocked} onChange={(blocked) => go({ blocked })}>
          {w.blockedOnly}
        </Checkbox>
      </div>
      {query.isPending ? (
        <Loading label={w.loading} />
      ) : query.isError ? (
        <ErrorState error={query.error} what={w.loading} onRetry={() => void query.refetch()} />
      ) : (
        <DataTable
          caption={w.caption}
          hideCaption
          columns={columns}
          rows={query.data.items}
          rowId={(r) => r.id}
          rowHref={(r) => `/operations/production/work-orders/${r.id}`}
          empty={<EmptyState title={w.emptyTitle}>{w.empty}</EmptyState>}
          footer={
            query.data.total > PAGE_SIZE ? (
              <OffsetPagination total={query.data.total} limit={query.data.limit} offset={query.data.offset} shown={query.data.items.length} control={(offset) => ({ href: workOrdersHref({ ...state, offset }) })} />
            ) : null
          }
        />
      )}
    </div>
  );
}

// =====================================================================================================
// /operations/production/work-orders/new
// =====================================================================================================
export function NewWorkOrderScreen() {
  const router = useRouter();
  const w = m.workOrders;
  const boms = useQuery({ queryKey: queryKeys.production.boms({ status: "approved" }), queryFn: ({ signal }) => fetchBoms({}, signal) });
  const warehouses = useQuery({ queryKey: queryKeys.inventory.warehouses(), queryFn: ({ signal }) => fetchWarehouses(signal) });
  const listKey = useMemo(() => queryKeys.production.workOrders({}), []);
  const { run, pending } = useProductionCommand<null>(listKey);
  const products = useMemo(() => {
    const seen = new Map<string, { id: string; label: string; uom: string | null }>();
    for (const b of boms.data?.items ?? []) {
      if (b.status === "approved") seen.set(b.product.id, { id: b.product.id, label: `${b.product.product_key} · ${b.product.name}`, uom: b.product.stock_uom_code });
    }
    return [...seen.values()];
  }, [boms.data]);
  const [product, setProduct] = useState<string | null>(null);
  const [quantity, setQuantity] = useState<string | null>(null);
  const [warehouse, setWarehouse] = useState<string | null>(null);
  const [start, setStart] = useState<string | null>(null);
  const [due, setDue] = useState<string | null>(null);
  const [notes, setNotes] = useState("");
  const chosen = products.find((p) => p.id === product) ?? null;
  const submit = () =>
    product && quantity
      ? void run("create", (k) => createWorkOrder({ product_id: product, quantity, warehouse_id: warehouse, planned_start_date: start, due_date: due, notes: notes || null }, k), {
          done: w.created,
          failed: w.createFailed,
        }).then((r) => {
          if (r) router.push(`/operations/production/work-orders/${r.id}` as Parameters<typeof router.push>[0]);
        })
      : undefined;
  return (
    <div className="flex max-w-2xl flex-col gap-6">
      <PageHeader title={w.newTitle} intro={w.newIntro} nav={<AreaNav area="operations" label={m.area} leading={OPERATIONS_LEADING} />} />
      {boms.isPending ? (
        <Loading label={m.masters.loading} />
      ) : boms.isError ? (
        <ErrorState error={boms.error} what={m.masters.loading} onRetry={() => void boms.refetch()} />
      ) : products.length === 0 ? (
        <EmptyState title={w.newTitle}>{w.noProducts}</EmptyState>
      ) : (
        <SectionCard title={w.newTitle} headingLevel={2}>
          <div className="flex flex-col gap-4">
            <Select label={w.product} placeholder={w.productPlaceholder} options={products} value={product} onChange={setProduct} isRequired />
            <NumberField label={w.quantity} value={quantity} onChange={setQuantity} uom={chosen?.uom ?? undefined} isRequired />
            <Select
              label={w.warehouse}
              options={(warehouses.data ?? []).map((wh) => ({ id: wh.id, label: `${wh.code} · ${wh.name}` }))}
              value={warehouse ?? warehouses.data?.[0]?.id ?? null}
              onChange={setWarehouse}
            />
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <DatePicker label={w.plannedStart} value={start} onChange={setStart} />
              <DatePicker label={w.due} value={due} onChange={setDue} />
            </div>
            <TextArea label={w.notes} value={notes} onChange={setNotes} />
            <div>
              <Button variant="primary" isPending={pending === "create"} {...unavailableWhen((!product || !quantity) ? m.fillIn : null)} onPress={submit}>
                {w.create}
              </Button>
            </div>
          </div>
        </SectionCard>
      )}
    </div>
  );
}

// =====================================================================================================
// /operations/production/work-orders/[workOrderId]
// =====================================================================================================
export function WorkOrderScreen({ workOrderId }: { workOrderId: string }) {
  const query = useQuery({ queryKey: queryKeys.production.workOrder(workOrderId), queryFn: ({ signal }) => fetchWorkOrder(workOrderId, signal) });
  if (query.isPending) return <Loading label={d.loading} variant="detail" />;
  if (query.isError) return failure(query.error, m.workOrders.title, () => void query.refetch());
  return <WorkOrder wo={query.data} key={query.data.version} />;
}

type DialogKind = "issue" | "consume" | "return" | "output" | "cancel" | "offcut" | "plan" | null;

function WorkOrder({ wo }: { wo: WorkOrderRead }) {
  const key = useMemo(() => queryKeys.production.workOrder(wo.id), [wo.id]);
  const { run, pending, offline } = useProductionCommand<WorkOrderRead>(key);
  const [open, setOpen] = useState<DialogKind>(null);
  const [planOp, setPlanOp] = useState<OperationRead | null>(null);
  const caps = wo.capabilities;
  const write = (r: WorkOrderRead) => r;
  const act = (action: "release" | "complete" | "close", done: string) =>
    void run(action, (k) => transitionWorkOrder(wo, action, k), { done, failed: d.failed, write });
  const can = (name: string) => Boolean(caps[name]?.allowed);
  return (
    <div className="flex flex-col gap-6">
      <RecordHeader
        back={{ href: "/operations/production/work-orders", label: d.back }}
        recordKey={wo.wo_number}
        title={`${wo.product.product_key} · ${wo.product.name}`}
        status={<WorkOrderStatus status={wo.status} blocked={wo.is_blocked} />}
        meta={
          <>
            <span>{d.planned(`${wo.qty_planned} ${wo.uom_code}`)}</span>
            <MetaDot />
            <span>{d.good(`${wo.qty_good} ${wo.uom_code}`)}</span>
            <MetaDot />
            <span>{wo.warehouse.code}</span>
            {wo.sales_order ? (
              <>
                <MetaDot />
                <Link href={wo.sales_order.path}>{d.orderLink(wo.sales_order.order_number)}</Link>
              </>
            ) : null}
            <MetaDot />
            <Link href={`/operations/production/boms/${wo.bom.id}`}>{d.bomVersion(wo.bom.version_no)}</Link>
            <MetaDot />
            <Link href={`/operations/production/routings/${wo.routing.id}`}>{d.routingVersion(wo.routing.version_no)}</Link>
          </>
        }
        actions={
          <>
            {can("release") ? (
              <Button variant="primary" isPending={pending === "release"} onPress={() => act("release", d.released)}>
                {d.release}
              </Button>
            ) : null}
            {can("issue") ? <Button onPress={() => setOpen("issue")}>{d.issue}</Button> : null}
            {can("consume") ? <Button onPress={() => setOpen("consume")}>{d.consume}</Button> : null}
            {can("return") ? <Button onPress={() => setOpen("return")}>{d.returnMaterial}</Button> : null}
            {can("output") ? <Button onPress={() => setOpen("output")}>{d.reportOutput}</Button> : null}
            {can("complete") ? (
              <Button variant="primary" isPending={pending === "complete"} onPress={() => act("complete", d.completed)}>
                {d.complete}
              </Button>
            ) : null}
            {can("close") ? (
              <Button isPending={pending === "close"} onPress={() => act("close", d.closed)}>
                {d.close}
              </Button>
            ) : null}
            {can("cancel") ? (
              <Button variant="quiet" onPress={() => setOpen("cancel")}>
                {d.cancel}
              </Button>
            ) : null}
          </>
        }
      />
      {wo.is_blocked ? (
        <StateView
          icon={<InfoIcon />}
          title={d.blockedTitle}
          headingLevel={2}
          actions={
            can("recheck") ? (
              <Button isPending={pending === "recheck"} onPress={() => void run("recheck", (k) => recheckWorkOrder(wo, k), { done: d.rechecked, failed: d.failed, write })}>
                {d.recheck}
              </Button>
            ) : undefined
          }
        >
          <p>{d.blockedBody}</p>
          <ul className="mt-2 flex flex-col gap-1">
            {wo.blocked_causes.map((c) => (
              <li key={c.id}>{c.path ? <Link href={c.path}>{c.label ?? c.type}</Link> : (c.label ?? c.type)}</li>
            ))}
          </ul>
        </StateView>
      ) : null}
      <Materials wo={wo} />
      <Operations
        wo={wo}
        pending={pending}
        onComplete={(op) => void run(`op-${op.id}`, (k) => completeOperation(wo, op.id, k), { done: d.opCompleted, failed: d.failed, write })}
        onLinkPlan={(op) => {
          setPlanOp(op);
          setOpen("plan");
        }}
        onOffcut={() => setOpen("offcut")}
      />
      <Transactions wo={wo} />
      {open === "issue" ? <IssueDialog wo={wo} onClose={() => setOpen(null)} run={run} pending={pending} write={write} /> : null}
      {open === "consume" || open === "return" ? <WipDialog kind={open} wo={wo} onClose={() => setOpen(null)} run={run} pending={pending} write={write} /> : null}
      {open === "output" ? <OutputDialog wo={wo} onClose={() => setOpen(null)} run={run} pending={pending} write={write} /> : null}
      {open === "offcut" ? <OffcutDialog wo={wo} onClose={() => setOpen(null)} run={run} pending={pending} write={write} /> : null}
      {open === "plan" && planOp ? <PlanDialog wo={wo} op={planOp} onClose={() => setOpen(null)} run={run} pending={pending} write={write} /> : null}
      <ReasonDialog
        title={d.cancelTitle}
        description={d.cancelBody}
        reasons={Object.entries(d.reasons).map(([id, label]) => ({ id, label }))}
        noteLabel={d.cancelReason}
        confirmLabel={d.cancel}
        isOpen={open === "cancel"}
        isPending={pending === "cancel"}
        disabledReason={offline}
        onOpenChange={(o) => setOpen(o ? "cancel" : null)}
        onConfirm={(reasonCode, note) =>
          void run("cancel", (k) => transitionWorkOrder(wo, "cancel", k, { reason_code: (reasonCode ?? "other") as CancelReason, reason: note || undefined }), {
            done: d.cancelled,
            failed: d.failed,
            write,
          }).then((r) => {
            if (r) setOpen(null);
          })
        }
      />
    </div>
  );
}

function Materials({ wo }: { wo: WorkOrderRead }) {
  const c = d.materialColumns;
  const columns: DataTableColumn<MaterialRead>[] = [
    {
      id: "component",
      header: c.component,
      isRowHeader: true,
      mobile: "title",
      cell: (r) => (
        <span className="flex flex-col">
          <span>
            <span className="font-mono">{r.component.product_key}</span> <span className="text-ink-muted">{r.component.name}</span>
          </span>
          {r.alternates.length ? <span className="text-xs text-ink-muted">{d.alternates(r.alternates.map((a) => a.product_key).join(", "))}</span> : null}
        </span>
      ),
      mobileCell: (r) => r.component.product_key,
    },
    { id: "source", header: c.source, cell: (r) => (r.requirement_source === "cut_plan" ? <Badge tone="info">{d.fromCutPlan}</Badge> : d.fromBom) },
    { id: "required", header: c.required, numeric: true, mobile: "amount", cell: (r) => qty(r.qty_required, r.uom_code) },
    { id: "reserved", header: c.reserved, numeric: true, cell: (r) => (r.short ? <StatusPill tone="warning">{qty(r.qty_reserved, r.uom_code)}</StatusPill> : qty(r.qty_reserved, r.uom_code)) },
    { id: "issued", header: c.issued, numeric: true, cell: (r) => qty(r.qty_issued, r.uom_code) },
    { id: "wip", header: c.inWip, numeric: true, cell: (r) => qty(r.qty_in_wip, r.uom_code) },
    { id: "consumed", header: c.consumed, numeric: true, cell: (r) => qty(r.qty_consumed, r.uom_code) },
    { id: "free", header: c.free, numeric: true, mobile: "meta", cell: (r) => qty(r.qty_free, r.uom_code) },
  ];
  return (
    <SectionCard title={d.materials}>
      <DataTable caption={d.materialsCaption} hideCaption columns={columns} rows={wo.materials} rowId={(r) => r.id} />
    </SectionCard>
  );
}

function Operations({ wo, pending, onComplete, onLinkPlan, onOffcut }: { wo: WorkOrderRead; pending: string | null; onComplete: (op: OperationRead) => void; onLinkPlan: (op: OperationRead) => void; onOffcut: () => void }) {
  const c = d.operationColumns;
  const canDo = (name: string) => Boolean(wo.capabilities[name]?.allowed);
  const columns: DataTableColumn<OperationRead>[] = [
    { id: "seq", header: c.seq, numeric: true, cell: (o) => o.seq },
    {
      id: "name",
      header: c.name,
      isRowHeader: true,
      mobile: "title",
      cell: (o) => (
        <span className="flex flex-col gap-1">
          <span>{o.name}</span>
          {o.cut_plan ? (
            <span className="flex flex-wrap items-center gap-2 text-sm">
              <Link href={o.cut_plan.path} className="font-mono">{o.cut_plan.plan_number}</Link>
              {o.cut_plan.boards != null ? <span className="text-ink-muted">{d.planBoards(o.cut_plan.boards)}</span> : null}
              {o.cut_plan.ready ? <Badge tone="success">{d.planReady}</Badge> : <Badge tone="warning">{d.planNotReady(o.cut_plan.reason_code ?? "")}</Badge>}
            </span>
          ) : null}
        </span>
      ),
      mobileCell: (o) => `${o.seq} ${o.name}`,
    },
    { id: "centre", header: c.centre, mobile: "key", cell: (o) => <Link href={`/operations/production/work-centres/${o.work_center.id}`}>{o.work_center.code}</Link>, mobileCell: (o) => o.work_center.code },
    { id: "minutes", header: c.minutes, numeric: true, cell: (o) => m.minutes(o.planned_minutes) },
    { id: "day", header: c.day, cell: (o) => (o.planned_date ? <LocalDate value={o.planned_date} /> : dash) },
    { id: "status", header: c.status, mobile: "status", cell: (o) => (o.status === "done" ? <StatusPill tone="success">{d.opDone}</StatusPill> : <StatusPill>{d.opPending}</StatusPill>) },
    {
      id: "actions",
      header: "",
      cell: (o) => (
        <span className="flex flex-wrap justify-end gap-2">
          {o.is_board_cutting && o.status === "pending" && canDo("link_cut_plan") ? (
            <Button size="sm" onPress={() => onLinkPlan(o)}>
              {d.linkPlan}
            </Button>
          ) : null}
          {o.is_board_cutting && canDo("record_offcut") ? (
            <Button size="sm" onPress={onOffcut}>
              {d.recordOffcut}
            </Button>
          ) : null}
          {o.status === "pending" && canDo("complete_operation") && wo.status !== "draft" ? (
            <Button size="sm" isPending={pending === `op-${o.id}`} onPress={() => onComplete(o)}>
              {d.completeOp(o.seq)}
            </Button>
          ) : null}
        </span>
      ),
    },
  ];
  return (
    <SectionCard title={d.operations}>
      <DataTable caption={d.operationsCaption} hideCaption columns={columns} rows={wo.operations} rowId={(o) => o.id} empty={<EmptyState title={d.operations}>{d.noOperations}</EmptyState>} />
    </SectionCard>
  );
}

function Transactions({ wo }: { wo: WorkOrderRead }) {
  type Row = WorkOrderRead["transactions"][number];
  const columns: DataTableColumn<Row>[] = [
    { id: "kind", header: "", isRowHeader: true, mobile: "title", cell: (t) => d.transactionKinds[t.kind] ?? t.kind },
    {
      id: "lines",
      header: d.materialColumns.component,
      mobile: "meta",
      cell: (t) => (
        <ul className="flex flex-col">
          {t.lines.map((ln, i) => (
            <li key={`${t.id}-${i}`}>
              <span className="font-mono">{ln.product.product_key}</span> {qty(ln.quantity, ln.uom_code)}
              {ln.lot_code ? <span className="text-ink-muted"> · {ln.lot_code}</span> : null}
              <span className="text-ink-muted"> · {ln.from_location ?? "?"} → {ln.to_location ?? "?"}</span>
            </li>
          ))}
        </ul>
      ),
    },
    { id: "by", header: "", cell: (t) => t.created_by?.display_name ?? dash },
    { id: "at", header: "", mobile: "status", cell: (t) => <LocalDateTime value={t.created_at} /> },
  ];
  return (
    <SectionCard title={d.transactions} actions={wo.transactions.length ? <Link href="/operations/inventory/movements">{d.viewMovements}</Link> : undefined}>
      <DataTable caption={d.transactionsCaption} hideCaption columns={columns} rows={wo.transactions} rowId={(t) => t.id} empty={<EmptyState title={d.transactions}>{d.noTransactions}</EmptyState>} />
    </SectionCard>
  );
}

type RunFn = ReturnType<typeof useProductionCommand<WorkOrderRead>>["run"];
interface DialogProps {
  wo: WorkOrderRead;
  onClose: () => void;
  run: RunFn;
  pending: string | null;
  write: (r: WorkOrderRead) => WorkOrderRead;
}

function IssueDialog({ wo, onClose, run, pending, write }: DialogProps) {
  const open = wo.materials.filter((x) => isPositiveDecimalStr(x.qty_to_issue));
  const [materialId, setMaterialId] = useState<string | null>(open[0]?.id ?? null);
  const material = wo.materials.find((x) => x.id === materialId) ?? null;
  const [quantity, setQuantity] = useState<string | null>(material?.qty_to_issue ?? null);
  const [source, setSource] = useState<string | null>(null);
  const position = useQuery({
    queryKey: ["production", "position", material?.component.id ?? ""],
    queryFn: ({ signal }) => fetchPosition(material!.component.id, signal),
    enabled: Boolean(material),
  });
  const sources = (position.data?.balances ?? [])
    .filter((b) => b.location.warehouse_id === wo.warehouse.id && b.location.location_type === "internal" && isPositiveDecimalStr(b.quantity) && b.lot?.lot_kind !== "offcut")
    .map((b) => ({ id: `${b.location.id}|${b.lot?.id ?? ""}`, label: `${b.location.code}${b.lot ? ` · ${b.lot.lot_code}` : ""} (${b.quantity})` }));
  const chosen = source ?? sources[0]?.id ?? null;
  const [locationId, lotId] = chosen ? chosen.split("|") : [null, null];
  return (
    <Dialog
      title={d.issueTitle}
      isOpen
      onOpenChange={(o) => (o ? undefined : onClose())}
      footer={(close) => (
        <>
          <Button variant="quiet" onPress={close}>
            {d.cancel}
          </Button>
          <Button
            variant="primary"
            isPending={pending === "issue"}
            {...unavailableWhen((!material || !quantity) ? m.fillIn : null)}
            onPress={() =>
              material && quantity
                ? void run("issue", (k) => issueMaterials(wo, [{ material_id: material.id, quantity, lot_id: lotId || null, from_location_id: locationId || null }], k), { done: d.issued, failed: d.failed, write }).then((r) => {
                    if (r) close();
                  })
                : undefined
            }
          >
            {d.issue}
          </Button>
        </>
      )}
    >
      <div className="flex flex-col gap-4">
        <Select label={d.materialColumns.component} options={open.map((x) => ({ id: x.id, label: `${x.component.product_key} · ${x.qty_to_issue} ${x.uom_code}` }))} value={materialId} onChange={(v) => { setMaterialId(v); setSource(null); setQuantity(wo.materials.find((x) => x.id === v)?.qty_to_issue ?? null); }} />
        <Select label={d.fromBin} options={sources} value={chosen} onChange={setSource} placeholder={d.lotPlaceholder} />
        <NumberField label={d.quantityOf(material?.component.product_key ?? "")} value={quantity} onChange={setQuantity} uom={material?.uom_code} isRequired />
      </div>
    </Dialog>
  );
}

function WipDialog({ kind, wo, onClose, run, pending, write }: DialogProps & { kind: "consume" | "return" }) {
  const inWip = wo.materials.filter((x) => isPositiveDecimalStr(x.qty_in_wip));
  const [materialId, setMaterialId] = useState<string | null>(inWip[0]?.id ?? null);
  const material = wo.materials.find((x) => x.id === materialId) ?? null;
  const [quantity, setQuantity] = useState<string | null>(material?.qty_in_wip ?? null);
  const title = kind === "consume" ? d.consume : d.returnTitle;
  return (
    <Dialog
      title={title}
      isOpen
      onOpenChange={(o) => (o ? undefined : onClose())}
      footer={(close) => (
        <>
          <Button variant="quiet" onPress={close}>
            {d.cancel}
          </Button>
          <Button
            variant="primary"
            isPending={pending === kind}
            {...unavailableWhen((!material || !quantity) ? m.fillIn : null)}
            onPress={() =>
              material && quantity
                ? void run(kind, (k) => moveFromWip(wo, kind, [{ material_id: material.id, quantity }], k), { done: kind === "consume" ? d.consumed : d.returned, failed: d.failed, write }).then((r) => {
                    if (r) close();
                  })
                : undefined
            }
          >
            {kind === "consume" ? d.consume : d.returnMaterial}
          </Button>
        </>
      )}
    >
      <div className="flex flex-col gap-4">
        <Select label={d.materialColumns.component} options={inWip.map((x) => ({ id: x.id, label: `${x.component.product_key} · ${x.qty_in_wip} ${x.uom_code}` }))} value={materialId} onChange={(v) => { setMaterialId(v); setQuantity(wo.materials.find((x) => x.id === v)?.qty_in_wip ?? null); }} />
        <NumberField label={d.quantityOf(material?.component.product_key ?? "")} value={quantity} onChange={setQuantity} uom={material?.uom_code} isRequired />
      </div>
    </Dialog>
  );
}

function OutputDialog({ wo, onClose, run, pending, write }: DialogProps) {
  const remaining = (() => { const left = subtractDecimalStr(wo.qty_planned, wo.qty_good); return isPositiveDecimalStr(left) ? left : "0"; })();
  const [good, setGood] = useState<string | null>(remaining);
  const [scrap, setScrap] = useState<string | null>("0");
  return (
    <Dialog
      title={d.outputTitle}
      isOpen
      onOpenChange={(o) => (o ? undefined : onClose())}
      footer={(close) => (
        <>
          <Button variant="quiet" onPress={close}>
            {d.cancel}
          </Button>
          <Button
            variant="primary"
            isPending={pending === "output"}
            {...unavailableWhen((!good) ? m.fillIn : null)}
            onPress={() =>
              good
                ? void run("output", (k) => reportOutput(wo, { qty_good: good, qty_scrap: scrap || "0" }, k), { done: d.outputPosted, failed: d.failed, write }).then((r) => {
                    if (r) close();
                  })
                : undefined
            }
          >
            {d.reportOutput}
          </Button>
        </>
      )}
    >
      <div className="flex flex-col gap-4">
        <NumberField label={d.goodQty} value={good} onChange={setGood} uom={wo.uom_code} isRequired />
        <NumberField label={d.scrapQty} value={scrap} onChange={setScrap} uom={wo.uom_code} />
      </div>
    </Dialog>
  );
}

function OffcutDialog({ wo, onClose, run, pending, write }: DialogProps) {
  const sheets = wo.materials.filter((x) => x.is_sheet_material);
  const board = wo.operations.find((o) => o.is_board_cutting) ?? null;
  const predicted = board?.predicted_offcuts ?? [];
  const [materialId, setMaterialId] = useState<string | null>(sheets[0]?.id ?? null);
  const [predictedId, setPredictedId] = useState<string | null>(null);
  const [length, setLength] = useState<string | null>(null);
  const [width, setWidth] = useState<string | null>(null);
  const [thickness, setThickness] = useState<string | null>(null);
  return (
    <Dialog
      title={d.offcutTitle}
      description={d.offcutIntro}
      isOpen
      onOpenChange={(o) => (o ? undefined : onClose())}
      footer={(close) => (
        <>
          <Button variant="quiet" onPress={close}>
            {d.cancel}
          </Button>
          <Button
            variant="primary"
            isPending={pending === "offcut"}
            {...unavailableWhen((!materialId || !length || !width) ? m.fillIn : null)}
            onPress={() =>
              materialId && length && width
                ? void run("offcut", (k) => recordOffcut(wo, { material_id: materialId, operation_id: board?.id ?? null, length_mm: length, width_mm: width, thickness_mm: thickness, predicted_offcut_id: predictedId }, k), { done: d.offcutRecorded, failed: d.failed, write }).then((r) => {
                    if (r) close();
                  })
                : undefined
            }
          >
            {d.recordOffcut}
          </Button>
        </>
      )}
    >
      <div className="flex flex-col gap-4">
        <Select label={d.materialColumns.component} options={sheets.map((x) => ({ id: x.id, label: x.component.product_key }))} value={materialId} onChange={setMaterialId} />
        {predicted.length ? (
          <Select
            label={d.usePredicted}
            options={[{ id: "", label: d.none }, ...predicted.map((p) => ({ id: p.id, label: d.predicted(p.length_mm, p.width_mm) }))]}
            value={predictedId ?? ""}
            onChange={(v) => {
              setPredictedId(v || null);
              const p = predicted.find((x) => x.id === v);
              if (p) {
                setLength(p.length_mm);
                setWidth(p.width_mm);
              }
            }}
          />
        ) : null}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <NumberField label={d.length} value={length} onChange={setLength} isRequired maxFractionDigits={1} />
          <NumberField label={d.width} value={width} onChange={setWidth} isRequired maxFractionDigits={1} />
          <NumberField label={d.thickness} value={thickness} onChange={setThickness} maxFractionDigits={1} />
        </div>
      </div>
    </Dialog>
  );
}

function PlanDialog({ wo, op, onClose, run, pending, write }: DialogProps & { op: OperationRead }) {
  const plans = useQuery({ queryKey: queryKeys.cutting.plans({ status: "calculated" }), queryFn: ({ signal }) => fetchPlans({ status: "calculated" }, signal) });
  const [planId, setPlanId] = useState<string | null>(op.cut_plan?.id ?? null);
  return (
    <Dialog
      title={d.linkPlan}
      isOpen
      onOpenChange={(o) => (o ? undefined : onClose())}
      footer={(close) => (
        <>
          <Button variant="quiet" onPress={close}>
            {d.cancel}
          </Button>
          <Button
            variant="primary"
            isPending={pending === "plan"}
            {...unavailableWhen((!planId) ? m.fillIn : null)}
            onPress={() =>
              planId
                ? void run("plan", (k) => linkCutPlan(wo, op.id, planId, k), { done: d.cutPlanLinked, failed: d.failed, write }).then((r) => {
                    if (r) close();
                  })
                : undefined
            }
          >
            {d.linkPlan}
          </Button>
        </>
      )}
    >
      {plans.isPending ? (
        <Loading label={d.planPlaceholder} />
      ) : plans.isError ? (
        <ErrorState error={plans.error} what={d.planNumber} onRetry={() => void plans.refetch()} />
      ) : (
        <Select
          label={d.planNumber}
          placeholder={d.planPlaceholder}
          options={plans.data.items.map((p) => ({ id: p.id, label: `${p.plan_number} · ${p.name}${p.boards != null ? ` · ${d.planBoards(p.boards)}` : ""}` }))}
          value={planId}
          onChange={setPlanId}
        />
      )}
    </Dialog>
  );
}
