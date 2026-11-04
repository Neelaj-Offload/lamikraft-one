"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { AreaNav } from "@/components/shell/area-nav";
import { StatusPill } from "@/components/ui/badge";
import { Button, unavailableWhen } from "@/components/ui/button";
import { DataTable, OffsetPagination, type DataTableColumn } from "@/components/ui/data-table";
import { DatePicker } from "@/components/ui/date-picker";
import { Dialog } from "@/components/ui/dialog";
import { LocalDate, LocalDateTime } from "@/components/ui/format";
import { KeyValueGrid, type KeyValue } from "@/components/ui/key-value-grid";
import { Link } from "@/components/ui/link";
import { PageHeader } from "@/components/ui/page-header";
import { ReasonDialog } from "@/components/ui/reason-dialog";
import { MetaDot, RecordHeader } from "@/components/ui/record-header";
import { SearchField } from "@/components/ui/search-field";
import { SectionCard } from "@/components/ui/section-card";
import { Select } from "@/components/ui/select";
import { EmptyState, Loading } from "@/components/ui/states";
import { TextArea, TextField } from "@/components/ui/text-field";
import { useCommand } from "@/features/inventory/use-command";
import { fetchOrder } from "@/features/orders/api";
import { failure, OPERATIONS_LEADING } from "@/features/procurement/shared";
import { queryKeys } from "@/lib/api/query-keys";
import { useSession } from "@/lib/session/context";
import { logisticsMessages as m } from "@/messages/logistics";
import {
  addTrackingRef,
  fetchPackingLists,
  fetchShipment,
  fetchShipments,
  linkShipment,
  PAGE_SIZE,
  planShipment,
  SHIPMENT_MODES,
  SHIPMENT_STATUSES,
  TRACKING_TYPES,
  transitionShipment,
  type EvidenceKind,
  type ExceptionCode,
  type ShipmentAction,
  type ShipmentDetail,
  type ShipmentMode,
  type ShipmentSummary,
  type TrackingRefType,
} from "./api";
import { shipmentListHref, type ShipmentListState } from "./list-state";
import { DispatchTabs, OrderPicker, ShipmentStatusPill, type OrderOption } from "./shared";

type Push = Parameters<ReturnType<typeof useRouter>["push"]>[0];
const TIME = /^([01]\d|2[0-3]):[0-5]\d$/;

function Cutoff({ s }: { s: Pick<ShipmentSummary, "cutoff_at" | "is_past_cutoff" | "status"> }) {
  if (!s.cutoff_at) return <span className="text-ink-muted">{m.shipments.noCutoff}</span>;
  return (
    <span className="flex flex-wrap items-center gap-2">
      <LocalDateTime value={s.cutoff_at} />
      {s.is_past_cutoff && (s.status === "planned" || s.status === "booked") ? <StatusPill tone="danger">{m.shipments.pastCutoff}</StatusPill> : null}
    </span>
  );
}

// =====================================================================================================
// /operations/dispatch
// =====================================================================================================
export function ShipmentsScreen({ state }: { state: ShipmentListState }) {
  const router = useRouter();
  const { permissionKeys } = useSession();
  const l = m.shipments;
  const query = useQuery({
    queryKey: queryKeys.logistics.shipments({ q: state.q, status: state.status, offset: state.offset }),
    queryFn: ({ signal }) => fetchShipments(state, signal),
  });
  const go = (next: Partial<ShipmentListState>) => router.push(shipmentListHref({ ...state, offset: 0, ...next }) as Push);
  const columns: DataTableColumn<ShipmentSummary>[] = [
    {
      id: "number",
      header: l.columns.number,
      isRowHeader: true,
      mobile: "title",
      mobileCell: (s) => `${s.shipment_number} · ${s.party_name}`,
      cell: (s) => (
        <Link href={s.path} className="font-mono">
          {s.shipment_number}
        </Link>
      ),
    },
    { id: "party", header: l.columns.party, cell: (s) => s.party_name },
    { id: "order", header: l.columns.order, cell: (s) => (s.order ? <Link href={s.order.path} className="font-mono">{s.order.number}</Link> : "—") },
    { id: "challan", header: l.columns.challan, cell: (s) => (s.challan ? <Link href={s.challan.path} className="font-mono">{s.challan.number}</Link> : "—") },
    { id: "mode", header: l.columns.mode, cell: (s) => m.modes[s.mode] ?? s.mode },
    { id: "cutoff", header: l.columns.cutoff, mobile: "meta", cell: (s) => <Cutoff s={s} /> },
    { id: "status", header: l.columns.status, mobile: "status", cell: (s) => <ShipmentStatusPill status={s.status} /> },
  ];
  const filtered = Boolean(state.q.trim() || state.status);
  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={l.title} intro={l.intro} nav={<AreaNav area="operations" label={m.area} leading={OPERATIONS_LEADING} />} />
      <DispatchTabs current="shipments" />
      {permissionKeys.has("logistics.shipment.create") ? <PlanShipment /> : null}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-[minmax(0,2fr)_minmax(0,1fr)] md:items-end">
        <SearchField label={l.search} placeholder={l.searchPlaceholder} defaultValue={state.q} onSubmit={(q) => go({ q })} onClear={() => go({ q: "" })} />
        <Select
          label={l.status}
          options={[{ id: "", label: l.anyStatus }, ...SHIPMENT_STATUSES.map((s) => ({ id: s, label: m.shipmentStatus[s] ?? s }))]}
          value={state.status ?? ""}
          onChange={(value) => go({ status: SHIPMENT_STATUSES.find((s) => s === value) ?? null })}
        />
      </div>
      {query.isPending ? (
        <Loading label={l.loading} />
      ) : query.isError ? (
        failure(query.error, l.title, l.loading, () => void query.refetch())
      ) : (
        <DataTable
          caption={l.caption}
          hideCaption
          columns={columns}
          rows={query.data.items}
          rowId={(s) => s.id}
          rowHref={(s) => s.path}
          empty={<EmptyState title={l.emptyTitle}>{filtered ? l.emptyFiltered : l.empty}</EmptyState>}
          footer={
            <OffsetPagination
              label={l.pages}
              total={query.data.total}
              limit={query.data.limit || PAGE_SIZE}
              offset={query.data.offset}
              shown={query.data.items.length}
              control={(offset) => ({ href: shipmentListHref({ ...state, offset }) })}
            />
          }
        />
      )}
    </div>
  );
}

function PlanShipment() {
  const router = useRouter();
  const p = m.planShipment;
  const key = useMemo(() => queryKeys.logistics.all(), []);
  const { run, pending, offline } = useCommand<null>(key);
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [order, setOrder] = useState<OrderOption | null>(null);
  const [mode, setMode] = useState<ShipmentMode>("road");
  const [transporter, setTransporter] = useState("");
  const [cutoffDate, setCutoffDate] = useState<string | null>(null);
  const [cutoffTime, setCutoffTime] = useState("");
  const badTime = cutoffTime.trim() !== "" && !TIME.test(cutoffTime.trim());
  if (!open) {
    return (
      <div>
        <Button variant="primary" onPress={() => setOpen(true)}>
          {p.title}
        </Button>
      </div>
    );
  }
  return (
    <SectionCard title={p.title} description={p.intro}>
      <div className="flex flex-col gap-4">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <OrderPicker text={text} onText={setText} value={order} onChange={setOrder} />
          <Select label={p.mode} options={SHIPMENT_MODES.map((x) => ({ id: x, label: m.modes[x] ?? x }))} value={mode} onChange={(v) => setMode(SHIPMENT_MODES.find((x) => x === v) ?? "road")} />
          <TextField label={p.transporter} value={transporter} onChange={setTransporter} maxLength={200} />
          <DatePicker label={p.cutoffDate} value={cutoffDate} onChange={setCutoffDate} />
          <TextField
            label={p.cutoffTime}
            description={p.cutoffHint}
            placeholder="17:30"
            value={cutoffTime}
            onChange={setCutoffTime}
            maxLength={5}
            errorMessage={badTime ? p.badTime : undefined}
          />
        </div>
        <div className="flex flex-wrap gap-3">
          <Button
            variant="primary"
            isPending={pending === "plan"}
            {...unavailableWhen(offline ?? (!order ? p.orderNeeded : badTime ? p.badTime : null))}
            onPress={() =>
              order
                ? void run(
                    "plan",
                    (k) => planShipment({ sales_order_id: order.id, mode, transporter_name: transporter, cutoff_date: cutoffDate, cutoff_time: cutoffTime.trim() || null }, k),
                    { done: p.created, failed: m.failed },
                  ).then((sh) => {
                    if (sh) router.push(sh.path as Push);
                  })
                : undefined
            }
          >
            {p.create}
          </Button>
          <Button variant="quiet" onPress={() => setOpen(false)}>
            {p.close}
          </Button>
        </div>
      </div>
    </SectionCard>
  );
}

// =====================================================================================================
// /operations/dispatch/shipments/[shipmentId]
// =====================================================================================================
export function ShipmentScreen({ shipmentId }: { shipmentId: string }) {
  const d = m.shipment;
  const query = useQuery({ queryKey: queryKeys.logistics.shipment(shipmentId), queryFn: ({ signal }) => fetchShipment(shipmentId, signal) });
  if (query.isPending) return <Loading label={d.loading} variant="detail" />;
  if (query.isError) return failure(query.error, d.permissionArea, d.loading, () => void query.refetch());
  return <Shipment sh={query.data} key={query.data.version} />;
}

const ACTION_ORDER: ShipmentAction[] = ["book", "dispatch", "in_transit", "deliver", "record_exception", "resolve_exception", "cancel"];
const PRIMARY = new Set<ShipmentAction>(["dispatch", "deliver"]);

function Shipment({ sh }: { sh: ShipmentDetail }) {
  const d = m.shipment;
  const key = useMemo(() => queryKeys.logistics.shipment(sh.id), [sh.id]);
  const { run, pending, offline } = useCommand<ShipmentDetail>(key);
  const [dialog, setDialog] = useState<null | "deliver" | "record_exception" | "cancel">(null);
  const caps = sh.capabilities;
  const act = (action: ShipmentAction, extras = {}) =>
    void run(action, (k) => transitionShipment(sh, action, extras, k), { done: d.done[action], failed: m.failed, write: (x) => x });
  const actions = ACTION_ORDER.filter((a) => caps[a]?.allowed).map((a) => (
    <Button
      key={a}
      variant={PRIMARY.has(a) ? "primary" : a === "cancel" ? "quiet" : "secondary"}
      isPending={pending === a}
      {...unavailableWhen(offline)}
      onPress={() => (a === "deliver" || a === "record_exception" || a === "cancel" ? setDialog(a) : act(a))}
    >
      {d.actions[a] ?? a}
    </Button>
  ));
  const facts: KeyValue[] = [
    { term: d.facts.party, description: sh.party_name },
    { term: d.facts.order, description: sh.order ? <Link href={sh.order.path}>{sh.order.number}</Link> : "—" },
    { term: d.facts.challan, description: sh.challan ? <Link href={sh.challan.path}>{`${sh.challan.number} · ${sh.challan.status}`}</Link> : "—" },
    { term: d.facts.packingList, description: sh.packing_list ? <Link href={sh.packing_list.path}>{sh.packing_list.number}</Link> : "—" },
    { term: d.facts.mode, description: m.modes[sh.mode] ?? sh.mode },
    { term: d.facts.transporter, description: sh.transporter_name ?? "—" },
    { term: d.facts.cutoff, description: <Cutoff s={sh} /> },
    { term: d.facts.planned, description: sh.planned_dispatch_date ? <LocalDate value={sh.planned_dispatch_date} /> : "—" },
    { term: d.facts.dispatched, description: sh.dispatched_at ? <LocalDateTime value={sh.dispatched_at} /> : "—" },
    { term: d.facts.delivered, description: sh.delivered_at ? <LocalDateTime value={sh.delivered_at} /> : "—" },
    {
      term: d.facts.evidence,
      description: sh.evidence_kind ? `${m.evidenceKinds.find((e) => e.id === sh.evidence_kind)?.label ?? sh.evidence_kind}${sh.evidence_note ? ` · ${sh.evidence_note}` : ""}` : "—",
    },
  ];
  return (
    <div className="flex flex-col gap-6">
      <RecordHeader
        back={{ href: "/operations/dispatch", label: d.back }}
        recordKey={sh.shipment_number}
        title={sh.party_name}
        status={<ShipmentStatusPill status={sh.status} />}
        meta={
          <>
            <span>{m.modes[sh.mode] ?? sh.mode}</span>
            {sh.cutoff_local ? (
              <>
                <MetaDot />
                <span>{d.cutoffMeta(sh.cutoff_local)}</span>
              </>
            ) : null}
          </>
        }
        actions={<>{actions}</>}
      />
      {caps.dispatch?.reason_code === "challan_required" ? <p className="text-sm text-ink-muted">{d.noChallan}</p> : null}
      {sh.is_past_cutoff && (sh.status === "planned" || sh.status === "booked") ? <p className="text-sm text-danger-text">{d.pastCutoff}</p> : null}
      {sh.exception_code ? (
        <p className="text-sm text-danger-text">
          {d.exceptionLine(m.exceptionCodes.find((e) => e.id === sh.exception_code)?.label ?? sh.exception_code, sh.exception_note)}
        </p>
      ) : null}
      <KeyValueGrid items={facts} />
      {caps.update?.allowed && sh.order ? <LinkDocuments sh={sh} orderId={sh.order.id} /> : null}
      <Tracking sh={sh} />
      <DeliverDialog sh={sh} isOpen={dialog === "deliver"} onClose={() => setDialog(null)} />
      <ExceptionDialog sh={sh} isOpen={dialog === "record_exception"} onClose={() => setDialog(null)} />
      <ReasonDialog
        title={d.cancelTitle}
        requireNote
        noteLabel={d.reason}
        confirmLabel={d.actions.cancel ?? "cancel"}
        isOpen={dialog === "cancel"}
        isPending={pending === "cancel"}
        disabledReason={offline}
        onOpenChange={(o) => (o ? undefined : setDialog(null))}
        onConfirm={(_code, note) => {
          setDialog(null);
          act("cancel", { reason: note });
        }}
      />
    </div>
  );
}

function LinkDocuments({ sh, orderId }: { sh: ShipmentDetail; orderId: string }) {
  const d = m.shipment;
  const key = useMemo(() => queryKeys.logistics.shipment(sh.id), [sh.id]);
  const { run, pending, offline } = useCommand<ShipmentDetail>(key);
  const order = useQuery({ queryKey: queryKeys.orders.order(orderId), queryFn: ({ signal }) => fetchOrder(orderId, signal) });
  const lists = useQuery({
    queryKey: queryKeys.logistics.packingLists({ sales_order_id: orderId }),
    queryFn: ({ signal }) => fetchPackingLists({ salesOrderId: orderId }, signal),
  });
  const challans = (order.data?.documents ?? []).filter((x) => x.kind === "challan" && x.status !== "cancelled");
  const packing = (lists.data?.items ?? []).filter((x) => x.status !== "cancelled");
  const [challan, setChallan] = useState<string | null>(sh.challan?.id ?? null);
  const [packingList, setPackingList] = useState<string | null>(sh.packing_list?.id ?? null);
  const changed = (challan && challan !== sh.challan?.id) || (packingList && packingList !== sh.packing_list?.id);
  return (
    <SectionCard title={d.linkHeading} description={d.linkIntro}>
      <div className="flex flex-col gap-4">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {order.isError ? (
            <p className="text-sm text-ink-muted">{d.orderUnavailable}</p>
          ) : (
            <Select
              label={d.facts.challan}
              placeholder={challans.length ? d.choose : d.noChallans}
              options={challans.map((c) => ({ id: c.id, label: c.number, detail: c.status }))}
              value={challan}
              onChange={setChallan}
              isDisabled={challans.length === 0}
            />
          )}
          <Select
            label={d.facts.packingList}
            placeholder={packing.length ? d.choose : d.noPackingLists}
            options={packing.map((p) => ({ id: p.id, label: p.packing_list_number, detail: m.packingStatus[p.status] ?? p.status }))}
            value={packingList}
            onChange={setPackingList}
            isDisabled={packing.length === 0}
          />
        </div>
        <div>
          <Button
            isPending={pending === "link"}
            {...unavailableWhen(offline ?? (changed ? null : d.nothingChanged))}
            onPress={() =>
              void run(
                "link",
                (k) =>
                  linkShipment(
                    sh,
                    {
                      ...(challan && challan !== sh.challan?.id ? { challan_id: challan } : {}),
                      ...(packingList && packingList !== sh.packing_list?.id ? { packing_list_id: packingList } : {}),
                    },
                    k,
                  ),
                { done: d.linked, failed: m.failed, write: (x) => x },
              )
            }
          >
            {d.link}
          </Button>
        </div>
      </div>
    </SectionCard>
  );
}

function Tracking({ sh }: { sh: ShipmentDetail }) {
  const d = m.shipment;
  const key = useMemo(() => queryKeys.logistics.shipment(sh.id), [sh.id]);
  const { run, pending, offline } = useCommand<ShipmentDetail>(key);
  const [type, setType] = useState<TrackingRefType>("lr");
  const [value, setValue] = useState("");
  return (
    <SectionCard title={d.tracking}>
      <div className="flex flex-col gap-4">
        {sh.tracking_refs.length ? (
          <ul className="flex flex-col gap-1 text-sm">
            {sh.tracking_refs.map((r) => (
              <li key={r.id}>
                <span className="text-ink-muted">{d.trackingTypes[r.ref_type] ?? r.ref_type}</span> <span className="font-mono">{r.value}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-ink-muted">{d.noTracking}</p>
        )}
        {sh.capabilities.add_tracking_ref?.allowed ? (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,2fr)_auto] sm:items-end">
            <Select label={d.trackingType} options={TRACKING_TYPES.map((t) => ({ id: t, label: d.trackingTypes[t] ?? t }))} value={type} onChange={(v) => setType(TRACKING_TYPES.find((t) => t === v) ?? "other")} />
            <TextField label={d.trackingValue} value={value} onChange={setValue} maxLength={80} />
            <Button
              isPending={pending === "track"}
              {...unavailableWhen(offline ?? (value.trim() ? null : d.trackingValue))}
              onPress={() =>
                void run("track", (k) => addTrackingRef(sh.id, type, value, k), { done: d.trackingAdded, failed: m.failed, write: (x) => x }).then((x) => {
                  if (x) setValue("");
                })
              }
            >
              {d.addTracking}
            </Button>
          </div>
        ) : null}
      </div>
    </SectionCard>
  );
}

function DeliverDialog({ sh, isOpen, onClose }: { sh: ShipmentDetail; isOpen: boolean; onClose: () => void }) {
  const d = m.shipment;
  const key = useMemo(() => queryKeys.logistics.shipment(sh.id), [sh.id]);
  const { run, pending, offline } = useCommand<ShipmentDetail>(key);
  const [kind, setKind] = useState<string | null>(null);
  const [note, setNote] = useState("");
  return (
    <Dialog
      title={d.deliverTitle}
      description={d.deliverIntro}
      isOpen={isOpen}
      onOpenChange={(o) => (o ? undefined : onClose())}
      footer={(close) => (
        <>
          <Button variant="quiet" onPress={close}>
            {d.close}
          </Button>
          <Button
            variant="primary"
            isPending={pending === "deliver"}
            {...unavailableWhen(offline ?? (kind ? null : d.evidenceNeeded))}
            onPress={() =>
              void run("deliver", (k) => transitionShipment(sh, "deliver", { evidence_kind: kind as EvidenceKind, evidence_note: note }, k), {
                done: d.done.deliver,
                failed: m.failed,
                write: (x) => x,
              }).then((x) => {
                if (x) close();
              })
            }
          >
            {d.actions.deliver}
          </Button>
        </>
      )}
    >
      <div className="flex flex-col gap-3">
        <Select label={d.evidenceKind} placeholder={d.choose} options={m.evidenceKinds} value={kind} onChange={setKind} />
        <TextArea label={d.evidenceNote} value={note} onChange={setNote} maxLength={1000} />
      </div>
    </Dialog>
  );
}

function ExceptionDialog({ sh, isOpen, onClose }: { sh: ShipmentDetail; isOpen: boolean; onClose: () => void }) {
  const d = m.shipment;
  const key = useMemo(() => queryKeys.logistics.shipment(sh.id), [sh.id]);
  const { run, pending, offline } = useCommand<ShipmentDetail>(key);
  const [code, setCode] = useState<string | null>(null);
  const [note, setNote] = useState("");
  return (
    <Dialog
      title={d.exceptionTitle}
      isOpen={isOpen}
      onOpenChange={(o) => (o ? undefined : onClose())}
      footer={(close) => (
        <>
          <Button variant="quiet" onPress={close}>
            {d.close}
          </Button>
          <Button
            variant="primary"
            isPending={pending === "record_exception"}
            {...unavailableWhen(offline ?? (code ? null : d.exceptionCode))}
            onPress={() =>
              void run("record_exception", (k) => transitionShipment(sh, "record_exception", { exception_code: code as ExceptionCode, note }, k), {
                done: d.done.record_exception,
                failed: m.failed,
                write: (x) => x,
              }).then((x) => {
                if (x) close();
              })
            }
          >
            {d.actions.record_exception}
          </Button>
        </>
      )}
    >
      <div className="flex flex-col gap-3">
        <Select label={d.exceptionCode} placeholder={d.choose} options={m.exceptionCodes} value={code} onChange={setCode} />
        <TextArea label={d.note} value={note} onChange={setNote} maxLength={1000} />
      </div>
    </Dialog>
  );
}
