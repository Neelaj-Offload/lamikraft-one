"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { AreaNav } from "@/components/shell/area-nav";
import { StatusPill } from "@/components/ui/badge";
import { Button, unavailableWhen } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/choice";
import { DataTable, OffsetPagination, type DataTableColumn } from "@/components/ui/data-table";
import { DatePicker } from "@/components/ui/date-picker";
import { Dialog } from "@/components/ui/dialog";
import { LocalDate } from "@/components/ui/format";
import { KeyValueGrid, type KeyValue } from "@/components/ui/key-value-grid";
import { Link } from "@/components/ui/link";
import { NumberField } from "@/components/ui/number-field";
import { PageHeader } from "@/components/ui/page-header";
import { ReasonDialog } from "@/components/ui/reason-dialog";
import { MetaDot, RecordHeader } from "@/components/ui/record-header";
import { SearchField } from "@/components/ui/search-field";
import { SectionCard } from "@/components/ui/section-card";
import { Select } from "@/components/ui/select";
import { EmptyState, ErrorState, Loading } from "@/components/ui/states";
import { TextField } from "@/components/ui/text-field";
import { useCommand } from "@/features/inventory/use-command";
import { queryKeys } from "@/lib/api/query-keys";
import { procurementMessages as m } from "@/messages/procurement";
import {
  billAction,
  createBill,
  fetchBills,
  fetchPurchaseOrder,
  fetchPurchaseOrders,
  moveExpectedDate,
  PAGE_SIZE,
  PO_STATUSES,
  poAction,
  receiveGoods,
  type BillRead,
  type PoAction,
  type PoDetail,
  type PoLine,
  type PoSummary,
} from "./api";
import { poListHref, type PoListState } from "./list-state";
import { dash, failure, MatchStatusPill, money, OPERATIONS_LEADING, PoStatusPill, positive, PurchasingTabs, qty } from "./shared";

type Push = Parameters<ReturnType<typeof useRouter>["push"]>[0];
const o = m.order;

// =====================================================================================================
// /operations/purchasing/orders
// =====================================================================================================
export function PurchaseOrdersScreen({ state }: { state: PoListState }) {
  const router = useRouter();
  const l = m.orders;
  const query = useQuery({
    queryKey: queryKeys.procurement.orders({ q: state.q, status: state.status, overdue: state.overdue, offset: state.offset }),
    queryFn: ({ signal }) => fetchPurchaseOrders(state, signal),
  });
  const go = (next: Partial<PoListState>) => router.push(poListHref({ ...state, offset: 0, ...next }) as Push);
  const columns: DataTableColumn<PoSummary>[] = [
    { id: "number", header: l.columns.number, isRowHeader: true, mobile: "title", mobileCell: (p) => `${p.po_number} · ${p.vendor.display_name}`, cell: (p) => <Link href={p.path} className="font-mono">{p.po_number}</Link> },
    { id: "vendor", header: l.columns.vendor, cell: (p) => p.vendor.display_name },
    { id: "warehouse", header: l.columns.warehouse, cell: (p) => p.warehouse.code },
    {
      id: "status",
      header: l.columns.status,
      mobile: "status",
      cell: (p) => (
        <span className="flex flex-wrap gap-1">
          <PoStatusPill status={p.status} />
          {p.is_overdue ? <StatusPill tone="danger">{l.overdue}</StatusPill> : null}
        </span>
      ),
    },
    { id: "expected", header: l.columns.expected, mobile: "meta", cell: (p) => (p.next_expected_date ? <LocalDate value={p.next_expected_date} /> : dash) },
    { id: "total", header: l.columns.total, numeric: true, mobile: "amount", cell: (p) => money(p.total_amount, p.currency) },
    { id: "owner", header: l.columns.owner, cell: (p) => p.owner.display_name ?? dash },
  ];
  const filtered = Boolean(state.q.trim() || state.status || state.overdue);
  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={l.title} intro={l.intro} nav={<AreaNav area="operations" label={m.area} leading={OPERATIONS_LEADING} />} />
      <PurchasingTabs current="orders" />
      <div className="grid grid-cols-1 gap-4 md:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_auto] md:items-end">
        <SearchField label={l.search} placeholder={l.searchPlaceholder} defaultValue={state.q} onSubmit={(q) => go({ q })} onClear={() => go({ q: "" })} />
        <Select
          label={l.status}
          options={[{ id: "", label: l.anyStatus }, ...PO_STATUSES.map((s) => ({ id: s, label: m.poStatus[s] ?? s }))]}
          value={state.status ?? ""}
          onChange={(value) => go({ status: PO_STATUSES.find((s) => s === value) ?? null })}
        />
        <Checkbox isSelected={state.overdue} onChange={(overdue) => go({ overdue })}>
          {l.overdueOnly}
        </Checkbox>
      </div>
      {query.isPending ? (
        <Loading label={l.loading} />
      ) : query.isError ? (
        <ErrorState error={query.error} what={l.loading} onRetry={() => void query.refetch()} />
      ) : (
        <DataTable
          caption={l.caption}
          hideCaption
          columns={columns}
          rows={query.data.items}
          rowId={(p) => p.id}
          rowHref={(p) => p.path}
          empty={<EmptyState title={l.emptyTitle}>{filtered ? l.empty : l.emptyStart}</EmptyState>}
          footer={
            <OffsetPagination
              label={l.pages}
              total={query.data.total}
              limit={query.data.limit || PAGE_SIZE}
              offset={query.data.offset}
              shown={query.data.items.length}
              control={(offset) => ({ href: poListHref({ ...state, offset }) })}
            />
          }
        />
      )}
    </div>
  );
}

// =====================================================================================================
// /operations/purchasing/orders/[poId]
// =====================================================================================================
export function PurchaseOrderScreen({ poId }: { poId: string }) {
  const query = useQuery({ queryKey: queryKeys.procurement.order(poId), queryFn: ({ signal }) => fetchPurchaseOrder(poId, signal) });
  if (query.isPending) return <Loading label={o.loading} variant="detail" />;
  if (query.isError) return failure(query.error, o.permissionArea, o.loading, () => void query.refetch());
  return <PurchaseOrder po={query.data} key={query.data.version} />;
}

const REASON_ACTIONS = new Set<PoAction>(["reject", "cancel"]);
const ACTION_ORDER: PoAction[] = ["submit", "approve", "issue", "reject", "close", "cancel"];

function PurchaseOrder({ po }: { po: PoDetail }) {
  const key = useMemo(() => queryKeys.procurement.order(po.id), [po.id]);
  const { run, pending, offline } = useCommand<PoDetail>(key);
  const [reasonFor, setReasonFor] = useState<PoAction | null>(null);
  const [moving, setMoving] = useState<PoLine | null>(null);
  const [receiving, setReceiving] = useState(false);
  const caps = po.capabilities;
  const outstanding = po.lines.some((l) => positive(l.qty_outstanding));
  const act = (action: PoAction, reason?: string) =>
    void run(action, (k) => poAction(po, action, k, reason), { done: o.done[action], failed: m.failed, write: (x) => x });

  const actions = (
    <>
      {ACTION_ORDER.filter((a) => caps[a]?.allowed).map((a) => (
        <Button
          key={a}
          variant={a === "submit" || a === "approve" || a === "issue" ? "primary" : a === "cancel" ? "quiet" : "secondary"}
          isPending={pending === a}
          onPress={() => (REASON_ACTIONS.has(a) || (a === "close" && outstanding) ? setReasonFor(a) : act(a))}
          {...unavailableWhen(offline)}
        >
          {o.actions[a]}
        </Button>
      ))}
      {caps.receive?.allowed ? (
        <Button variant="primary" onPress={() => setReceiving(true)} {...unavailableWhen(offline)}>
          {o.receive}
        </Button>
      ) : null}
    </>
  );
  const facts: KeyValue[] = [
    { term: o.facts.vendor, description: po.vendor.display_name },
    { term: o.facts.warehouse, description: `${po.warehouse.code} · ${po.warehouse.name}` },
    { term: o.facts.total, description: money(po.total_amount, po.currency), numeric: true },
    { term: o.facts.requisition, description: po.requisition ? <Link href={po.requisition.path}>{po.requisition.number}</Link> : "—" },
    { term: o.facts.approvedBy, description: po.approved_by?.display_name ?? "—" },
    { term: o.facts.vendorRef, description: po.vendor_reference ?? "—" },
  ];
  const c = o.columns;
  const columns: DataTableColumn<PoLine>[] = [
    { id: "no", header: c.line, numeric: true, cell: (l) => l.line_no },
    { id: "product", header: c.product, isRowHeader: true, mobile: "title", cell: (l) => `${l.product.product_key} · ${l.product.name}` },
    { id: "ordered", header: c.ordered, numeric: true, mobile: "amount", cell: (l) => qty(l.quantity, l.unit) },
    { id: "price", header: c.price, numeric: true, cell: (l) => money(l.unit_price, po.currency) },
    { id: "amount", header: c.amount, numeric: true, cell: (l) => money(l.line_amount, po.currency) },
    {
      id: "expected",
      header: c.expected,
      mobile: "meta",
      cell: (l) => (
        <span className="flex flex-wrap items-center gap-2">
          <LocalDate value={l.expected_date} />
          {l.is_overdue ? <StatusPill tone="danger">{o.late}</StatusPill> : null}
          {caps.change_expected_date?.allowed && positive(l.qty_outstanding) ? (
            <Button size="sm" variant="quiet" onPress={() => setMoving(l)}>
              {o.moveDate}
            </Button>
          ) : null}
        </span>
      ),
    },
    { id: "received", header: c.received, numeric: true, cell: (l) => qty(l.qty_received, l.unit) },
    { id: "accepted", header: c.accepted, numeric: true, cell: (l) => qty(l.qty_accepted, l.unit) },
    { id: "rejected", header: c.rejected, numeric: true, cell: (l) => qty(l.qty_rejected, l.unit) },
    { id: "qc", header: c.pendingQc, numeric: true, cell: (l) => qty(l.qty_pending_qc, l.unit) },
    { id: "outstanding", header: c.outstanding, numeric: true, mobile: "key", cell: (l) => qty(l.qty_outstanding, l.unit) },
  ];
  return (
    <div className="flex flex-col gap-6">
      <RecordHeader
        back={{ href: "/operations/purchasing/orders", label: o.back }}
        recordKey={po.po_number}
        title={po.vendor.display_name}
        status={
          <span className="flex flex-wrap gap-1">
            <PoStatusPill status={po.status} />
            {po.is_overdue ? <StatusPill tone="danger">{m.orders.overdue}</StatusPill> : null}
          </span>
        }
        meta={
          <>
            <LocalDate value={po.order_date} />
            <MetaDot />
            <span>{po.owner.display_name}</span>
          </>
        }
        actions={actions}
      />
      {caps.approve?.reason_code === "approver_is_submitter" ? <p className="text-sm text-ink-muted">{o.approverNote}</p> : null}
      <KeyValueGrid items={facts} />
      <SectionCard title={o.linesHeading}>
        <DataTable caption={o.linesHeading} hideCaption columns={columns} rows={po.lines} rowId={(l) => l.id} />
      </SectionCard>
      {receiving ? <ReceivePanel po={po} onClose={() => setReceiving(false)} /> : null}
      <SectionCard title={o.receipts}>
        {po.receipts.length ? (
          <ul className="flex flex-col gap-1">
            {po.receipts.map((r) => (
              <li key={r.id}>
                <Link href={r.path} className="font-mono">
                  {r.number}
                </Link>{" "}
                <span className="text-sm text-ink-muted">{m.grnStatus[r.status] ?? r.status}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-ink-muted">{o.noReceipts}</p>
        )}
      </SectionCard>
      <BillsSection po={po} />
      <ReasonDialog
        title={o.reasonTitle(reasonFor ? (o.actions[reasonFor] ?? reasonFor) : "")}
        requireNote
        noteLabel={o.reasonLabel}
        confirmLabel={reasonFor ? (o.actions[reasonFor] ?? reasonFor) : ""}
        isOpen={reasonFor !== null}
        isPending={pending === reasonFor}
        disabledReason={offline}
        onOpenChange={(open) => (open ? undefined : setReasonFor(null))}
        onConfirm={(_code, note) => {
          const which = reasonFor;
          setReasonFor(null);
          if (which) act(which, note);
        }}
      />
      {moving ? <MoveDateDialog po={po} line={moving} onClose={() => setMoving(null)} /> : null}
    </div>
  );
}

function MoveDateDialog({ po, line, onClose }: { po: PoDetail; line: PoLine; onClose: () => void }) {
  const key = useMemo(() => queryKeys.procurement.order(po.id), [po.id]);
  const { run, pending, offline } = useCommand<PoDetail>(key);
  const [date, setDate] = useState<string | null>(line.expected_date);
  return (
    <Dialog
      title={o.moveDateTitle(line.line_no)}
      isOpen
      onOpenChange={(open) => (open ? undefined : onClose())}
      footer={(close) => (
        <>
          <Button variant="quiet" onPress={close}>
            {m.requisition.cancel}
          </Button>
          <Button
            variant="primary"
            isPending={pending === "move"}
            {...unavailableWhen(offline ?? (date ? null : o.newDate))}
            onPress={() =>
              date ? void run("move", (k) => moveExpectedDate(po.id, line, date, k), { done: o.dateMoved, failed: m.failed, write: (x) => x }).then(close) : undefined
            }
          >
            {o.moveDate}
          </Button>
        </>
      )}
    >
      <DatePicker label={o.newDate} value={date} onChange={setDate} />
    </Dialog>
  );
}

function ReceivePanel({ po, onClose }: { po: PoDetail; onClose: () => void }) {
  const router = useRouter();
  const key = useMemo(() => queryKeys.procurement.order(po.id), [po.id]);
  const { run, pending, offline } = useCommand<null>(key);
  const open = po.lines.filter((l) => positive(l.qty_receivable));
  const [values, setValues] = useState<Record<string, { qty: string | null; lot: string }>>(
    Object.fromEntries(open.map((l) => [l.id, { qty: l.qty_outstanding, lot: "" }])),
  );
  const [challan, setChallan] = useState("");
  const lines = open.filter((l) => positive(values[l.id]?.qty));
  const missingLot = lines.some((l) => l.product.track_lots && !values[l.id]?.lot.trim());
  return (
    <SectionCard title={o.receiveTitle} description={o.receiveIntro}>
      <div className="flex flex-col gap-4">
        {open.map((l) => (
          <div key={l.id} className="grid grid-cols-1 gap-3 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)] sm:items-end">
            <p className="text-sm text-ink">{o.receiveQty(l.line_no, `${l.product.product_key} · ${l.product.name}`)}</p>
            <NumberField
              label={m.requisitions.quantity}
              value={values[l.id]?.qty ?? null}
              uom={l.unit}
              onChange={(value) => setValues((all) => ({ ...all, [l.id]: { qty: value, lot: all[l.id]?.lot ?? "" } }))}
            />
            {l.product.track_lots ? (
              <TextField
                label={o.lotRequired}
                value={values[l.id]?.lot ?? ""}
                maxLength={60}
                onChange={(lot) => setValues((all) => ({ ...all, [l.id]: { qty: all[l.id]?.qty ?? null, lot } }))}
              />
            ) : (
              <span />
            )}
          </div>
        ))}
        <TextField label={o.vendorChallan} value={challan} onChange={setChallan} maxLength={80} />
        <div className="flex gap-3">
          <Button
            variant="primary"
            isPending={pending === "receive"}
            {...unavailableWhen(offline ?? (lines.length === 0 ? m.requisitions.noLines : missingLot ? o.lotRequired : null))}
            onPress={() =>
              void run(
                "receive",
                (k) =>
                  receiveGoods(
                    po.id,
                    lines.map((l) => ({ po_line_id: l.id, quantity: values[l.id]!.qty!, lot_code: values[l.id]!.lot || null })),
                    challan,
                    k,
                  ),
                { done: o.received, failed: m.failed },
              ).then((grn) => {
                if (grn) router.push(grn.path as Push);
              })
            }
          >
            {o.receive}
          </Button>
          <Button variant="quiet" onPress={onClose}>
            {m.requisition.cancel}
          </Button>
        </div>
      </div>
    </SectionCard>
  );
}

function BillsSection({ po }: { po: PoDetail }) {
  const key = useMemo(() => queryKeys.procurement.bills(po.id), [po.id]);
  const bills = useQuery({ queryKey: key, queryFn: ({ signal }) => fetchBills(po.id, signal), enabled: po.capabilities.bill?.reason_code !== "permission_denied" });
  const [adding, setAdding] = useState(false);
  if (po.capabilities.bill?.reason_code === "permission_denied" && !po.bills.length) return null;
  return (
    <SectionCard
      title={o.bills}
      actions={
        po.capabilities.bill?.allowed && !adding ? (
          <Button size="sm" onPress={() => setAdding(true)}>
            {o.newBill}
          </Button>
        ) : null
      }
    >
      <div className="flex flex-col gap-4">
        {adding ? <BillForm po={po} onDone={() => setAdding(false)} /> : null}
        {bills.isPending ? (
          <Loading label={o.bills} />
        ) : bills.isError ? (
          <ErrorState error={bills.error} what={o.bills} onRetry={() => void bills.refetch()} />
        ) : bills.data.items.length === 0 ? (
          <p className="text-sm text-ink-muted">{o.noBills}</p>
        ) : (
          bills.data.items.map((b) => <Bill key={b.id} bill={b} poId={po.id} />)
        )}
      </div>
    </SectionCard>
  );
}

function Bill({ bill, poId }: { bill: BillRead; poId: string }) {
  const key = useMemo(() => queryKeys.procurement.bills(poId), [poId]);
  const { run, pending, offline } = useCommand<null>(key);
  return (
    <article id={`bill-${bill.id}`} className="flex flex-col gap-2 rounded-md border p-3">
      <header className="flex flex-wrap items-center gap-2">
        <span className="font-mono">{bill.bill_number}</span>
        <LocalDate value={bill.bill_date} />
        <MatchStatusPill status={bill.match_status} />
        <span className="text-sm text-ink-muted">{m.billStatus[bill.status] ?? bill.status}</span>
      </header>
      <p className="text-sm">
        {o.subtotal}: {money(bill.subtotal_amount, bill.currency)} · {o.computed}: {money(bill.computed_subtotal, bill.currency)}
      </p>
      {bill.match_exceptions.length ? (
        <ul className="list-disc ps-5 text-sm text-danger-text">
          {bill.match_exceptions.map((e, i) => (
            <li key={`${e.code}-${i}`}>
              {m.exceptionCodes[e.code] ?? e.code}
              {e.line_no ? ` · ${m.requisition.columns.line} ${e.line_no}` : ""}
              {e.expected != null ? ` (${e.expected} / ${e.actual})` : ""}
            </li>
          ))}
        </ul>
      ) : null}
      <div className="flex gap-2">
        {bill.capabilities.match?.allowed ? (
          <Button size="sm" isPending={pending === "match"} {...unavailableWhen(offline)} onPress={() => void run("match", (k) => billAction(bill, "match", k), { failed: m.failed })}>
            {o.rematch}
          </Button>
        ) : null}
        {bill.capabilities.hand_off?.allowed ? (
          <Button
            size="sm"
            variant="primary"
            isPending={pending === "hand"}
            {...unavailableWhen(offline)}
            onPress={() => void run("hand", (k) => billAction(bill, "hand-off", k), { done: o.handedOff, failed: m.failed })}
          >
            {o.handOff}
          </Button>
        ) : null}
      </div>
    </article>
  );
}

function BillForm({ po, onDone }: { po: PoDetail; onDone: () => void }) {
  const key = useMemo(() => queryKeys.procurement.bills(po.id), [po.id]);
  const { run, pending, offline } = useCommand<null>(key);
  const billable = po.lines.filter((l) => positive(l.qty_billable));
  const [number, setNumber] = useState("");
  const [date, setDate] = useState<string | null>(null);
  const [subtotal, setSubtotal] = useState<string | null>(null);
  const [tax, setTax] = useState<string | null>("0");
  const [total, setTotal] = useState<string | null>(null);
  const [lines, setLines] = useState<Record<string, { qty: string | null; price: string | null }>>(
    Object.fromEntries(billable.map((l) => [l.id, { qty: l.qty_billable, price: l.unit_price }])),
  );
  const chosen = billable.filter((l) => lines[l.id]?.qty && lines[l.id]?.price);
  const missing = !number.trim() || !date || !subtotal || !total || chosen.length === 0;
  return (
    <div className="flex flex-col gap-3 rounded-md border p-3">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <TextField label={o.billNumber} value={number} onChange={setNumber} maxLength={80} />
        <DatePicker label={o.billDate} value={date} onChange={setDate} />
        <span />
        <NumberField label={o.subtotal} value={subtotal} onChange={setSubtotal} currency={po.currency} />
        <NumberField label={o.tax} value={tax} onChange={setTax} currency={po.currency} />
        <NumberField label={o.total} value={total} onChange={setTotal} currency={po.currency} />
        {billable.map((l) => (
          <div key={l.id} className="contents">
            <NumberField label={o.billQty(l.line_no)} value={lines[l.id]?.qty ?? null} uom={l.unit} onChange={(v) => setLines((a) => ({ ...a, [l.id]: { qty: v, price: a[l.id]?.price ?? null } }))} />
            <NumberField label={o.billPrice(l.line_no)} value={lines[l.id]?.price ?? null} currency={po.currency} onChange={(v) => setLines((a) => ({ ...a, [l.id]: { qty: a[l.id]?.qty ?? null, price: v } }))} />
            <span />
          </div>
        ))}
      </div>
      <div className="flex gap-3">
        <Button
          variant="primary"
          isPending={pending === "bill"}
          {...unavailableWhen(offline ?? (missing ? o.billNumber : null))}
          onPress={() =>
            void run(
              "bill",
              (k) =>
                createBill(
                  po.id,
                  {
                    bill_number: number.trim(),
                    bill_date: date!,
                    subtotal_amount: subtotal!,
                    tax_amount: tax ?? "0",
                    total_amount: total!,
                    lines: chosen.map((l) => ({ po_line_id: l.id, quantity: lines[l.id]!.qty!, unit_price: lines[l.id]!.price! })),
                  },
                  k,
                ),
              { done: o.billCreated, failed: m.failed },
            ).then((b) => {
              if (b) onDone();
            })
          }
        >
          {o.newBill}
        </Button>
        <Button variant="quiet" onPress={onDone}>
          {m.requisition.cancel}
        </Button>
      </div>
    </div>
  );
}

