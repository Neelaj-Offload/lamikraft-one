"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { AreaNav } from "@/components/shell/area-nav";
import { StatusPill } from "@/components/ui/badge";
import { Button, unavailableWhen } from "@/components/ui/button";
import { DataTable, OffsetPagination, type DataTableColumn } from "@/components/ui/data-table";
import { Dialog } from "@/components/ui/dialog";
import { LocalDateTime } from "@/components/ui/format";
import { FactStrip } from "@/components/ui/fact-strip";
import { Link } from "@/components/ui/link";
import { NumberField } from "@/components/ui/number-field";
import { PageHeader } from "@/components/ui/page-header";
import { MetaDot, RecordHeader } from "@/components/ui/record-header";
import { SectionCard } from "@/components/ui/section-card";
import { Select } from "@/components/ui/select";
import { EmptyState, ErrorState, Loading } from "@/components/ui/states";
import { TextArea } from "@/components/ui/text-field";
import { toast } from "@/components/ui/toast";
import { useCommand } from "@/features/inventory/use-command";
import { failure, OPERATIONS_LEADING, qty } from "@/features/procurement/shared";
import { problemDescription } from "@/features/sales/use-quote-command";
import { queryKeys } from "@/lib/api/query-keys";
import { useSession } from "@/lib/session/context";
import { logisticsMessages as m } from "@/messages/logistics";
import {
  createPackingList,
  fetchContainerProfiles,
  fetchPackingList,
  fetchPackingLists,
  overrideLine,
  PACKING_STATUSES,
  packingListAction,
  PAGE_SIZE,
  suggestLoad,
  type LoadSuggestion,
  type PackingLine,
  type PackingListDetail,
  type PackingListSummary,
} from "./api";
import { packingListHref, type PackingListState } from "./list-state";
import { DecimalText, DispatchTabs, OrderPicker, PackingStatusPill, type OrderOption } from "./shared";

type Push = Parameters<ReturnType<typeof useRouter>["push"]>[0];

const dec = (value: string | null | undefined) => (value != null ? <DecimalText value={value} /> : <span className="text-ink-muted">—</span>);

// =====================================================================================================
// /operations/dispatch/packing-lists
// =====================================================================================================
export function PackingListsScreen({ state }: { state: PackingListState }) {
  const router = useRouter();
  const { permissionKeys } = useSession();
  const l = m.packingLists;
  const query = useQuery({
    queryKey: queryKeys.logistics.packingLists({ status: state.status, offset: state.offset }),
    queryFn: ({ signal }) => fetchPackingLists(state, signal),
  });
  const columns: DataTableColumn<PackingListSummary>[] = [
    {
      id: "number",
      header: l.columns.number,
      isRowHeader: true,
      mobile: "title",
      mobileCell: (p) => `${p.packing_list_number} · ${p.party_name}`,
      cell: (p) => (
        <Link href={p.path} className="font-mono">
          {p.packing_list_number}
        </Link>
      ),
    },
    { id: "order", header: l.columns.order, cell: (p) => <Link href={p.order.path} className="font-mono">{p.order.number}</Link> },
    { id: "party", header: l.columns.party, cell: (p) => p.party_name },
    { id: "cartons", header: l.columns.cartons, numeric: true, cell: (p) => p.total_cartons },
    { id: "cbm", header: l.columns.cbm, numeric: true, mobile: "amount", cell: (p) => dec(p.total_cbm) },
    { id: "gross", header: l.columns.gross, numeric: true, cell: (p) => dec(p.total_gross_kg) },
    {
      id: "status",
      header: l.columns.status,
      mobile: "status",
      cell: (p) => (
        <span className="flex flex-wrap gap-1">
          <PackingStatusPill status={p.status} />
          {p.is_stale ? <StatusPill tone="warning">{l.stale}</StatusPill> : null}
          {p.totals_partial ? <StatusPill tone="warning">{l.partial}</StatusPill> : null}
        </span>
      ),
    },
  ];
  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={l.title} intro={l.intro} nav={<AreaNav area="operations" label={m.area} leading={OPERATIONS_LEADING} />} />
      <DispatchTabs current="packing-lists" />
      {permissionKeys.has("logistics.packing_list.create") ? <NewPackingList /> : null}
      <div className="flex flex-wrap items-end gap-3">
        <Select
          label={l.status}
          className="min-w-56"
          options={[{ id: "", label: l.anyStatus }, ...PACKING_STATUSES.map((s) => ({ id: s, label: m.packingStatus[s] ?? s }))]}
          value={state.status ?? ""}
          onChange={(value) => router.push(packingListHref({ status: PACKING_STATUSES.find((s) => s === value) ?? null, offset: 0 }) as Push)}
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
          rowId={(p) => p.id}
          rowHref={(p) => p.path}
          empty={<EmptyState title={l.emptyTitle}>{state.status ? l.emptyFiltered : l.empty}</EmptyState>}
          footer={
            <OffsetPagination
              label={l.pages}
              total={query.data.total}
              limit={query.data.limit || PAGE_SIZE}
              offset={query.data.offset}
              shown={query.data.items.length}
              control={(offset) => ({ href: packingListHref({ ...state, offset }) })}
            />
          }
        />
      )}
    </div>
  );
}

function NewPackingList() {
  const router = useRouter();
  const p = m.planShipment;
  const key = useMemo(() => queryKeys.logistics.all(), []);
  const { run, pending, offline } = useCommand<null>(key);
  const [text, setText] = useState("");
  const [order, setOrder] = useState<OrderOption | null>(null);
  return (
    <SectionCard title={p.pack} description={m.packingLists.newIntro}>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-[minmax(0,2fr)_auto] sm:items-end">
        <OrderPicker text={text} onText={setText} value={order} onChange={setOrder} />
        <Button
          variant="primary"
          isPending={pending === "pack"}
          {...unavailableWhen(offline ?? (order ? null : p.orderNeeded))}
          onPress={() =>
            order
              ? void run("pack", (k) => createPackingList(order.id, k), { done: p.packed, failed: m.failed }).then((pl) => {
                  if (pl) router.push(pl.path as Push);
                })
              : undefined
          }
        >
          {p.pack}
        </Button>
      </div>
    </SectionCard>
  );
}

// =====================================================================================================
// /operations/dispatch/packing-lists/[packingListId]
// =====================================================================================================
export function PackingListScreen({ packingListId }: { packingListId: string }) {
  const d = m.packingList;
  const query = useQuery({ queryKey: queryKeys.logistics.packingList(packingListId), queryFn: ({ signal }) => fetchPackingList(packingListId, signal) });
  if (query.isPending) return <Loading label={d.loading} variant="detail" />;
  if (query.isError) return failure(query.error, d.permissionArea, d.loading, () => void query.refetch());
  return <PackingList pl={query.data} key={query.data.version} />;
}

function PackingList({ pl }: { pl: PackingListDetail }) {
  const d = m.packingList;
  const { permissionKeys } = useSession();
  const key = useMemo(() => queryKeys.logistics.packingList(pl.id), [pl.id]);
  const { run, pending, offline } = useCommand<PackingListDetail>(key);
  const [overriding, setOverriding] = useState<PackingLine | null>(null);
  const caps = pl.capabilities;
  const act = (action: "refresh" | "finalise" | "cancel", done: string) =>
    void run(action, (k) => packingListAction(pl, action, k), { done, failed: m.failed, write: (x) => x });
  const c = d.columns;
  const columns: DataTableColumn<PackingLine>[] = [
    { id: "no", header: c.line, numeric: true, cell: (x) => x.line_no },
    { id: "product", header: c.product, isRowHeader: true, mobile: "title", cell: (x) => `${x.product_key} · ${x.description}` },
    { id: "qty", header: c.quantity, numeric: true, mobile: "amount", cell: (x) => qty(x.quantity, x.unit) },
    { id: "cartons", header: c.cartons, numeric: true, cell: (x) => x.cartons ?? "—" },
    { id: "inner", header: c.inner, numeric: true, cell: (x) => x.inner_packs ?? "—" },
    { id: "cbm", header: c.cbm, numeric: true, cell: (x) => dec(x.cbm) },
    { id: "net", header: c.net, numeric: true, cell: (x) => dec(x.net_kg) },
    { id: "gross", header: c.gross, numeric: true, cell: (x) => dec(x.gross_kg) },
    {
      id: "flags",
      header: c.flags,
      mobile: "meta",
      cell: (x) => (
        <span className="flex flex-wrap items-center gap-1">
          {x.is_part_carton ? <StatusPill tone="neutral">{d.partCarton}</StatusPill> : null}
          {x.is_estimate ? <StatusPill tone="warning">{d.estimate}</StatusPill> : null}
          {x.is_fragile ? <StatusPill tone="warning">{d.fragile}</StatusPill> : null}
          {x.incomplete_reasons.map((r) => (
            <StatusPill key={r} tone="danger">
              {m.reasons[r] ?? r}
            </StatusPill>
          ))}
          {x.override_reason ? <span className="text-sm text-ink-muted">{d.entered(x.override_reason)}</span> : null}
          {caps.override?.allowed && x.incomplete_reasons.length ? (
            <Button size="sm" variant="quiet" onPress={() => setOverriding(x)}>
              {d.enterValues}
            </Button>
          ) : null}
        </span>
      ),
    },
  ];
  return (
    <div className="flex flex-col gap-6">
      <RecordHeader
        back={{ href: "/operations/dispatch/packing-lists", label: d.back }}
        recordKey={pl.packing_list_number}
        title={pl.party_name}
        status={
          <span className="flex flex-wrap gap-1">
            <PackingStatusPill status={pl.status} />
            {pl.is_stale ? <StatusPill tone="warning">{m.packingLists.stale}</StatusPill> : null}
          </span>
        }
        meta={
          <>
            <Link href={pl.order.path}>{pl.order.number}</Link>
            <MetaDot />
            <LocalDateTime value={pl.created_at} />
            {pl.challan ? (
              <>
                <MetaDot />
                <Link href={pl.challan.path}>{pl.challan.number}</Link>
              </>
            ) : null}
          </>
        }
        actions={
          <>
            {caps.refresh?.allowed ? (
              <Button variant={pl.is_stale ? "primary" : "secondary"} isPending={pending === "refresh"} {...unavailableWhen(offline)} onPress={() => act("refresh", d.refreshed)}>
                {d.refresh}
              </Button>
            ) : null}
            {caps.finalise?.allowed ? (
              <Button variant="primary" isPending={pending === "finalise"} {...unavailableWhen(offline)} onPress={() => act("finalise", d.finalised)}>
                {d.finalise}
              </Button>
            ) : null}
            {caps.cancel?.allowed ? (
              <Button variant="quiet" isPending={pending === "cancel"} {...unavailableWhen(offline)} onPress={() => act("cancel", d.cancelled)}>
                {d.cancel}
              </Button>
            ) : null}
          </>
        }
      />
      {pl.is_stale ? <p className="text-sm text-warning-text">{d.staleNote}</p> : null}
      {pl.totals_partial ? <p className="text-sm text-warning-text">{d.partialNote}</p> : null}
      {pl.has_estimates ? <p className="text-sm text-ink-muted">{d.estimateNote}</p> : null}
      {caps.finalise && !caps.finalise.allowed && caps.finalise.reason_code && pl.status === "draft" ? (
        <p className="text-sm text-ink-muted">{d.finaliseBlocked[caps.finalise.reason_code] ?? d.finaliseBlocked.default}</p>
      ) : null}
      <FactStrip
        label={d.totalsLabel}
        facts={[
          { label: d.totals.cartons, value: pl.total_cartons },
          { label: d.totals.cbm, value: <DecimalText value={pl.total_cbm} /> },
          { label: d.totals.net, value: <DecimalText value={pl.total_net_kg} /> },
          { label: d.totals.gross, value: <DecimalText value={pl.total_gross_kg} /> },
        ]}
      />
      <SectionCard title={d.linesHeading}>
        <DataTable caption={d.linesHeading} hideCaption columns={columns} rows={pl.lines} rowId={(x) => x.id} />
      </SectionCard>
      {permissionKeys.has("logistics.load_plan.run") && pl.status !== "cancelled" ? <LoadPlan pl={pl} /> : null}
      {overriding ? <OverrideDialog pl={pl} line={overriding} onClose={() => setOverriding(null)} /> : null}
    </div>
  );
}

function OverrideDialog({ pl, line, onClose }: { pl: PackingListDetail; line: PackingLine; onClose: () => void }) {
  const d = m.packingList;
  const key = useMemo(() => queryKeys.logistics.packingList(pl.id), [pl.id]);
  const { run, pending, offline } = useCommand<PackingListDetail>(key);
  const [cbm, setCbm] = useState<string | null>(line.cbm);
  const [net, setNet] = useState<string | null>(line.net_kg);
  const [gross, setGross] = useState<string | null>(line.gross_kg);
  const [reason, setReason] = useState("");
  return (
    <Dialog
      title={d.overrideTitle(line.line_no)}
      description={`${line.product_key} · ${line.description}`}
      isOpen
      onOpenChange={(o) => (o ? undefined : onClose())}
      footer={(close) => (
        <>
          <Button variant="quiet" onPress={close}>
            {m.shipment.close}
          </Button>
          <Button
            variant="primary"
            isPending={pending === "override"}
            {...unavailableWhen(offline ?? (reason.trim() ? null : d.overrideReason))}
            onPress={() =>
              void run("override", (k) => overrideLine(pl, line.id, { cbm, net_kg: net, gross_kg: gross, reason }, k), {
                done: d.overrideSaved,
                failed: m.failed,
                write: (x) => x,
              }).then((x) => {
                if (x) close();
              })
            }
          >
            {d.overrideSave}
          </Button>
        </>
      )}
    >
      <div className="flex flex-col gap-3">
        <NumberField label={d.overrideCbm} value={cbm} onChange={setCbm} maxFractionDigits={6} />
        <NumberField label={d.overrideNet} value={net} onChange={setNet} maxFractionDigits={3} />
        <NumberField label={d.overrideGross} value={gross} onChange={setGross} maxFractionDigits={3} />
        <TextArea label={d.overrideReason} value={reason} onChange={setReason} maxLength={500} />
      </div>
    </Dialog>
  );
}

function LoadPlan({ pl }: { pl: PackingListDetail }) {
  const d = m.packingList;
  const profiles = useQuery({ queryKey: queryKeys.logistics.containers(), queryFn: ({ signal }) => fetchContainerProfiles(signal) });
  const active = (profiles.data?.items ?? []).filter((p) => p.is_active);
  const [profile, setProfile] = useState<string | null>(null);
  const chosen = profile ?? active[0]?.id ?? null;
  const suggestion = useMutation({
    mutationFn: (containerId: string) => suggestLoad(pl.id, containerId),
    onError: (error) => toast.error(m.failed, { description: problemDescription(error) }),
  });
  return (
    <SectionCard title={d.loadHeading} description={d.loadIntro}>
      <div className="flex flex-col gap-4">
        {profiles.isPending ? (
          <Loading label={d.container} />
        ) : profiles.isError ? (
          <ErrorState error={profiles.error} what={d.container} onRetry={() => void profiles.refetch()} />
        ) : active.length === 0 ? (
          <p className="text-sm text-ink-muted">{d.noContainers}</p>
        ) : (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-[minmax(0,2fr)_auto] sm:items-end">
            <Select
              label={d.container}
              options={active.map((p) => ({ id: p.id, label: `${p.code} · ${p.name}`, detail: d.containerDetail(p.internal_volume_m3, p.max_payload_kg) }))}
              value={chosen}
              onChange={setProfile}
            />
            <Button isPending={suggestion.isPending} {...unavailableWhen(chosen ? null : d.container)} onPress={() => (chosen ? suggestion.mutate(chosen) : undefined)}>
              {d.suggest}
            </Button>
          </div>
        )}
        {suggestion.data ? <Suggestion s={suggestion.data} /> : null}
      </div>
    </SectionCard>
  );
}

function Suggestion({ s }: { s: LoadSuggestion }) {
  const d = m.packingList;
  return (
    <div className="flex flex-col gap-3" aria-live="polite">
      <p className="text-sm text-ink">
        <StatusPill tone="info">{s.label}</StatusPill> {d.containers(s.container_count)} · {s.container.code}
      </p>
      {s.totals_partial ? <p className="text-sm text-warning-text">{d.partialNote}</p> : null}
      <ol className="flex flex-col gap-2">
        {s.loads.map((load) => (
          <li key={load.index} className="rounded-md border p-3 text-sm">
            <p className="font-[650] text-ink">
              {d.loadNo(load.index)} · {d.binding[load.binding_constraint] ?? load.binding_constraint}
            </p>
            <p className="text-ink-muted">{d.utilisation(load.volume_utilisation_pct, load.payload_utilisation_pct)}</p>
            <ul className="mt-1 flex flex-col">
              {load.allocations.map((a) => (
                <li key={`${load.index}-${a.line_no}`}>{d.allocation(a.line_no, a.product_key, a.cartons)}</li>
              ))}
            </ul>
          </li>
        ))}
      </ol>
      {s.unplanned.length ? (
        <div className="text-sm">
          <p className="font-[650] text-ink">{d.unplanned}</p>
          <ul className="list-disc ps-5 text-ink-muted">
            {s.unplanned.map((u) => (
              <li key={u.line_no}>{d.unplannedLine(u.line_no, m.reasons[u.reason] ?? u.reason)}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {s.manual_review_line_nos.length ? <p className="text-sm text-ink-muted">{d.manualLines(s.manual_review_line_nos.join(", "))}</p> : null}
    </div>
  );
}
