"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { AreaNav } from "@/components/shell/area-nav";
import { StatusPill } from "@/components/ui/badge";
import { Button, unavailableWhen } from "@/components/ui/button";
import { DataTable, type DataTableColumn } from "@/components/ui/data-table";
import { LocalDateTime, Quantity } from "@/components/ui/format";
import { Link } from "@/components/ui/link";
import { NumberField } from "@/components/ui/number-field";
import { PageHeader } from "@/components/ui/page-header";
import { ReasonDialog } from "@/components/ui/reason-dialog";
import { MetaDot, RecordHeader } from "@/components/ui/record-header";
import { SectionCard } from "@/components/ui/section-card";
import { Select } from "@/components/ui/select";
import { EmptyState, ErrorState, Loading, NotAvailable, PermissionDenied } from "@/components/ui/states";
import { ProblemError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { useSession } from "@/lib/session/context";
import { inventoryMessages as m } from "@/messages/inventory";
import {
  approveCount,
  confirmPick,
  countAction,
  createCount,
  documentAction,
  enterCounts,
  fetchCount,
  fetchDocument,
  fetchDocuments,
  fetchPickList,
  fetchWarehouses,
  pickListAction,
  pickListChallan,
  type CountRead,
  type DocumentAction,
  type DocumentKind,
  type DocumentRead,
  type DocumentSummary,
  type PickListRead,
} from "./api";
import { InventoryTabs, OPERATIONS_LEADING } from "./stock-screens";
import { useCommand } from "./use-command";

function q(value: string | null | undefined, uom: string) {
  return value != null ? <Quantity value={{ value, uom }} /> : <span className="text-ink-muted">—</span>;
}

function failure(error: unknown, what: string, retry: () => void) {
  if (error instanceof ProblemError && error.status === 404) return <NotAvailable />;
  if (error instanceof ProblemError && error.status === 403) return <PermissionDenied area={what} />;
  return <ErrorState error={error} what={what} onRetry={retry} />;
}

// =====================================================================================================
// /operations/inventory/stock-takes
// =====================================================================================================
export function StockTakesScreen() {
  const router = useRouter();
  const { permissionKeys } = useSession();
  const c = m.counts;
  const listKey = useMemo(() => queryKeys.inventory.documents("stock_count"), []);
  const query = useQuery({ queryKey: listKey, queryFn: ({ signal }) => fetchDocuments("stock_count", signal) });
  const warehouses = useQuery({ queryKey: queryKeys.inventory.warehouses(), queryFn: ({ signal }) => fetchWarehouses(signal) });
  const [warehouse, setWarehouse] = useState<string | null>(null);
  const { run, pending } = useCommand<null>(listKey);
  const canCreate = permissionKeys.has("inventory.stock_count.create");
  const columns: DataTableColumn<DocumentSummary>[] = [
    { id: "number", header: c.columns.number, isRowHeader: true, mobile: "title", cell: (d) => <Link href={d.path} className="font-mono">{d.number}</Link>, mobileCell: (d) => d.number },
    { id: "warehouse", header: c.columns.warehouse, cell: (d) => d.warehouse.code },
    { id: "status", header: c.columns.status, mobile: "status", cell: (d) => <StatusPill tone={d.status === "posted" ? "success" : "info"}>{c.statuses[d.status] ?? d.status}</StatusPill> },
    { id: "lines", header: c.columns.lines, numeric: true, cell: (d) => d.line_count },
    { id: "created", header: c.columns.created, mobile: "meta", cell: (d) => <LocalDateTime value={d.created_at} /> },
  ];
  const chosen = warehouse ?? warehouses.data?.[0]?.id ?? null;
  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={c.title} intro={c.intro} nav={<AreaNav area="operations" label={m.area} leading={OPERATIONS_LEADING} />} />
      <InventoryTabs current="stockTakes" />
      {canCreate && (warehouses.data?.length ?? 0) > 0 ? (
        <div className="flex flex-wrap items-end gap-3">
          <Select label={c.warehouse} className="min-w-56" options={(warehouses.data ?? []).map((wh) => ({ id: wh.id, label: `${wh.code} · ${wh.name}` }))} value={chosen ?? ""} onChange={setWarehouse} />
          <Button
            variant="primary"
            isPending={pending === "create"}
            onPress={() =>
              chosen
                ? void run("create", (k) => createCount(chosen, k), { done: c.created, failed: c.detail.failed }).then((r) => {
                    if (r) router.push(`/operations/inventory/stock-takes/${r.id}` as Parameters<typeof router.push>[0]);
                  })
                : undefined
            }
          >
            {c.newCount}
          </Button>
        </div>
      ) : null}
      {query.isPending ? (
        <Loading label={c.loading} />
      ) : query.isError ? (
        <ErrorState error={query.error} what={c.loading} onRetry={() => void query.refetch()} />
      ) : (
        <DataTable caption={c.caption} hideCaption columns={columns} rows={query.data} rowId={(d) => d.id} rowHref={(d) => d.path} empty={<EmptyState title={c.emptyTitle}>{c.empty}</EmptyState>} />
      )}
    </div>
  );
}

export function StockTakeScreen({ countId }: { countId: string }) {
  const query = useQuery({ queryKey: queryKeys.inventory.count(countId), queryFn: ({ signal }) => fetchCount(countId, signal) });
  if (query.isPending) return <Loading label={m.counts.detail.loading} variant="detail" />;
  if (query.isError) return failure(query.error, m.counts.title, () => void query.refetch());
  return <StockTake count={query.data} key={query.data.version} />;
}

function StockTake({ count }: { count: CountRead }) {
  const d = m.counts.detail;
  const key = useMemo(() => queryKeys.inventory.count(count.id), [count.id]);
  const { run, pending, offline } = useCommand<CountRead>(key);
  const [entries, setEntries] = useState<Record<string, string>>(() =>
    Object.fromEntries(count.lines.map((l) => [l.id, l.counted_quantity ?? l.system_quantity])),
  );
  const caps = count.capabilities;
  const write = (r: CountRead) => r;
  const lines = count.lines;
  const columns: DataTableColumn<(typeof lines)[number]>[] = [
    { id: "product", header: d.columns.product, isRowHeader: true, mobile: "title", cell: (l) => <span className="font-mono">{l.product.product_key}</span>, mobileCell: (l) => l.product.product_key },
    { id: "location", header: d.columns.location, cell: (l) => [l.location.code, l.lot?.lot_code].filter(Boolean).join(" · ") },
    { id: "system", header: d.columns.system, numeric: true, cell: (l) => q(l.system_quantity, l.unit) },
    {
      id: "counted",
      header: d.columns.counted,
      numeric: true,
      mobile: "amount",
      cell: (l) =>
        caps.enter?.allowed ? (
          <NumberField
            label={d.countedLabel(l.product.product_key)}
            className="w-32"
            uom={l.unit}
            value={entries[l.id] ?? null}
            onChange={(value) => setEntries((prev) => ({ ...prev, [l.id]: value ?? "" }))}
          />
        ) : (
          q(l.counted_quantity, l.unit)
        ),
    },
    { id: "variance", header: d.columns.variance, numeric: true, cell: (l) => q(l.variance, l.unit) },
  ];
  const saveEntries = () =>
    run("save", (k) => enterCounts(count, Object.entries(entries).map(([line_id, counted_quantity]) => ({ line_id, counted_quantity })), k), { done: d.saved, failed: d.failed, write });
  return (
    <div className="flex flex-col gap-6">
      <RecordHeader
        back={{ href: "/operations/inventory/stock-takes", label: d.back }}
        recordKey={count.number}
        title={`${count.warehouse.code} · ${count.warehouse.name}`}
        status={<StatusPill tone={count.status === "posted" ? "success" : "info"}>{m.counts.statuses[count.status] ?? count.status}</StatusPill>}
        meta={
          <>
            <span>{d.variance(count.variance_lines)}</span>
            {count.frozen_at ? (
              <>
                <MetaDot />
                <LocalDateTime value={count.frozen_at} />
              </>
            ) : null}
          </>
        }
        actions={
          <>
            {caps.freeze?.allowed ? (
              <Button variant="primary" isPending={pending === "freeze"} onPress={() => void run("freeze", (k) => countAction(count, "freeze", k), { done: d.frozen, failed: d.failed, write })}>
                {d.freeze}
              </Button>
            ) : null}
            {caps.enter?.allowed ? (
              <Button isPending={pending === "save"} onPress={() => void saveEntries()} {...unavailableWhen(offline)}>
                {d.save}
              </Button>
            ) : null}
            {caps.submit?.allowed ? (
              <Button
                variant="primary"
                isPending={pending === "submit"}
                onPress={async () => {
                  const saved = await saveEntries();
                  if (saved) await run("submit", (k) => countAction(saved, "submit", k), { done: d.submitted, failed: d.failed, write });
                }}
              >
                {d.submit}
              </Button>
            ) : null}
            {caps.approve?.allowed ? (
              <Button variant="primary" isPending={pending === "approve"} onPress={() => void run("approve", (k) => approveCount(count, k), { done: d.posted, failed: d.failed, write })}>
                {d.approve}
              </Button>
            ) : null}
            {caps.cancel?.allowed ? (
              <Button variant="quiet" isPending={pending === "cancel"} onPress={() => void run("cancel", (k) => countAction(count, "cancel", k), { done: d.cancelled, failed: d.failed, write })}>
                {d.cancel}
              </Button>
            ) : null}
          </>
        }
      />
      {count.posting_id ? (
        <p className="text-sm">
          <Link href="/operations/inventory/movements">{m.document.viewMovements}</Link>
        </p>
      ) : null}
      <SectionCard title={d.linesCaption}>
        <DataTable caption={d.linesCaption} hideCaption columns={columns} rows={lines} rowId={(l) => l.id} empty={<EmptyState title={d.linesCaption}>{d.noLines}</EmptyState>} />
      </SectionCard>
    </div>
  );
}

// =====================================================================================================
// /operations/inventory/pick-lists/[pickListId]
// =====================================================================================================
export function PickListScreen({ pickListId }: { pickListId: string }) {
  const query = useQuery({ queryKey: queryKeys.inventory.pickList(pickListId), queryFn: ({ signal }) => fetchPickList(pickListId, signal) });
  if (query.isPending) return <Loading label={m.pickList.loading} variant="detail" />;
  if (query.isError) return failure(query.error, m.pickList.loading, () => void query.refetch());
  return <PickList pl={query.data} key={query.data.version} />;
}

function PickList({ pl }: { pl: PickListRead }) {
  const p = m.pickList;
  const key = useMemo(() => queryKeys.inventory.pickList(pl.id), [pl.id]);
  const { run, pending } = useCommand<PickListRead>(key);
  const [picked, setPicked] = useState<Record<string, string>>(() => Object.fromEntries(pl.lines.map((l) => [l.id, l.picked ?? l.requested])));
  const caps = pl.capabilities;
  const write = (r: PickListRead) => r;
  const columns: DataTableColumn<PickListRead["lines"][number]>[] = [
    { id: "product", header: p.columns.product, isRowHeader: true, mobile: "title", cell: (l) => <span className="font-mono">{l.product.product_key}</span>, mobileCell: (l) => l.product.product_key },
    { id: "location", header: p.columns.location, cell: (l) => [l.location.code, l.lot?.lot_code].filter(Boolean).join(" · ") },
    { id: "requested", header: p.columns.requested, numeric: true, cell: (l) => q(l.requested, l.unit) },
    {
      id: "picked",
      header: p.columns.picked,
      numeric: true,
      mobile: "amount",
      cell: (l) =>
        caps.pick?.allowed ? (
          <NumberField label={p.pickedLabel(l.product.product_key)} className="w-32" uom={l.unit} value={picked[l.id] ?? null} onChange={(value) => setPicked((prev) => ({ ...prev, [l.id]: value ?? "" }))} />
        ) : (
          q(l.picked, l.unit)
        ),
    },
    { id: "status", header: p.columns.status, mobile: "status", cell: (l) => l.status },
  ];
  return (
    <div className="flex flex-col gap-6">
      <RecordHeader
        back={{ href: `/sales/orders/${pl.order_id}`, label: `${p.back} ${pl.order_number}` }}
        recordKey={pl.number}
        title={`${pl.order_number} · ${pl.warehouse.code}`}
        status={<StatusPill tone={pl.status === "picked" ? "success" : "info"}>{p.statuses[pl.status] ?? pl.status}</StatusPill>}
        meta={pl.assignee?.display_name ? <span>{pl.assignee.display_name}</span> : undefined}
        actions={
          <>
            {caps.release?.allowed ? (
              <Button variant="primary" isPending={pending === "release"} onPress={() => void run("release", (k) => pickListAction(pl, "release", k), { done: p.released, failed: p.failed, write })}>
                {p.release}
              </Button>
            ) : null}
            {caps.pick?.allowed ? (
              <Button
                variant="primary"
                isPending={pending === "pick"}
                onPress={() => void run("pick", (k) => confirmPick(pl, Object.entries(picked).map(([line_id, picked_quantity]) => ({ line_id, picked_quantity })), k), { done: p.picked, failed: p.failed, write })}
              >
                {p.confirm}
              </Button>
            ) : null}
            {caps.create_challan?.allowed ? (
              <Button variant="primary" isPending={pending === "challan"} onPress={() => void run("challan", (k) => pickListChallan(pl.id, k), { done: p.challanCreated, failed: p.failed, write })}>
                {p.challan}
              </Button>
            ) : null}
            {caps.cancel?.allowed ? (
              <Button variant="quiet" isPending={pending === "cancel"} onPress={() => void run("cancel", (k) => pickListAction(pl, "cancel", k), { done: p.cancelled, failed: p.failed, write })}>
                {p.cancel}
              </Button>
            ) : null}
          </>
        }
      />
      <p className="text-sm text-ink-muted">{p.noMovement}</p>
      {pl.challan_id ? (
        <p className="text-sm">
          <Link href={`/operations/challans/${pl.challan_id}`} className="font-mono">
            {pl.challan_number ?? pl.challan_id}
          </Link>
        </p>
      ) : null}
      <SectionCard title={p.linesCaption}>
        <DataTable caption={p.linesCaption} hideCaption columns={columns} rows={pl.lines} rowId={(l) => l.id} />
      </SectionCard>
    </div>
  );
}

// =====================================================================================================
// adjustments, opening batches, transfers
// =====================================================================================================
export function DocumentScreen({ kind, id }: { kind: DocumentKind; id: string }) {
  const query = useQuery({ queryKey: queryKeys.inventory.document(kind, id), queryFn: ({ signal }) => fetchDocument(kind, id, signal) });
  if (query.isPending) return <Loading label={m.document.loading} variant="detail" />;
  if (query.isError) return failure(query.error, m.document.kinds[kind] ?? kind, () => void query.refetch());
  return <InventoryDocument doc={query.data} />;
}

function InventoryDocument({ doc }: { doc: DocumentRead }) {
  const t = m.document;
  const key = useMemo(() => queryKeys.inventory.document(doc.kind, doc.id), [doc.kind, doc.id]);
  const { run, pending, offline } = useCommand<DocumentRead>(key);
  const [rejecting, setRejecting] = useState(false);
  const act = (action: DocumentAction, note: string | null = null) => void run(action, (k) => documentAction(doc, action, k, note), { done: t.done, failed: t.failed, write: (r) => r });
  const labels: Record<string, string> = { submit: t.submit, approve: t.approve, reject: t.reject, dispatch: t.dispatch, receive: t.receive, cancel: t.cancel };
  const columns: DataTableColumn<DocumentRead["lines"][number]>[] = [
    { id: "product", header: t.columns.product, isRowHeader: true, mobile: "title", cell: (l) => <span className="font-mono">{l.product.product_key}</span>, mobileCell: (l) => l.product.product_key },
    { id: "location", header: t.columns.location, cell: (l) => l.location?.code ?? "—" },
    { id: "lot", header: t.columns.lot, cell: (l) => l.lot?.lot_code ?? l.lot_code ?? "—" },
    { id: "direction", header: t.columns.direction, cell: (l) => (l.direction ? (t.directions[l.direction] ?? l.direction) : "—") },
    { id: "quantity", header: t.columns.quantity, numeric: true, mobile: "amount", cell: (l) => q(l.quantity, l.unit) },
  ];
  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={t.kinds[doc.kind] ?? doc.kind} nav={<AreaNav area="operations" label={m.area} leading={OPERATIONS_LEADING} />} />
      <RecordHeader
        recordKey={doc.number}
        title={doc.to_warehouse ? `${doc.warehouse.code} → ${doc.to_warehouse.code}` : `${doc.warehouse.code} · ${doc.warehouse.name}`}
        status={<StatusPill tone={doc.status === "posted" || doc.status === "received" ? "success" : "info"}>{t.statuses[doc.status] ?? doc.status}</StatusPill>}
        meta={
          <>
            {doc.created_by?.display_name ? <span>{t.createdBy(doc.created_by.display_name)}</span> : null}
            {doc.decided_by?.display_name ? (
              <>
                <MetaDot />
                <span>{t.decidedBy(doc.decided_by.display_name)}</span>
              </>
            ) : null}
          </>
        }
        actions={Object.entries(doc.capabilities)
          .filter(([, c]) => c.allowed)
          .map(([action]) =>
            action === "reject" ? (
              <Button key={action} variant="quiet" onPress={() => setRejecting(true)}>
                {labels[action]}
              </Button>
            ) : (
              <Button key={action} variant={action === "cancel" ? "quiet" : "primary"} isPending={pending === action} {...unavailableWhen(offline)} onPress={() => act(action as DocumentAction)}>
                {labels[action] ?? action}
              </Button>
            ),
          )}
      />
      {doc.capabilities.approve?.reason_code === "approver_is_creator" ? <p className="text-sm text-ink-muted">{t.secondPerson}</p> : null}
      {doc.posting_id ? (
        <p className="text-sm">
          <Link href="/operations/inventory/movements">{t.viewMovements}</Link>
        </p>
      ) : null}
      <SectionCard title={t.linesCaption}>
        <DataTable caption={t.linesCaption} hideCaption columns={columns} rows={doc.lines} rowId={(l) => l.id} />
      </SectionCard>
      <ReasonDialog
        title={t.rejectTitle}
        description={doc.number}
        requireNote
        confirmLabel={t.reject}
        isOpen={rejecting}
        disabledReason={offline}
        onOpenChange={setRejecting}
        onConfirm={(_, note) => {
          setRejecting(false);
          act("reject", note);
        }}
      />
    </div>
  );
}
