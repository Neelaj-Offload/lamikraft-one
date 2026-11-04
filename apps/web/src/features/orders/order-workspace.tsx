"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { Button, unavailableWhen } from "@/components/ui/button";
import { DataTable, type DataTableColumn } from "@/components/ui/data-table";
import { LocalDate, LocalDateTime, Money, Quantity } from "@/components/ui/format";
import { KeyValueGrid, type KeyValue } from "@/components/ui/key-value-grid";
import { Link } from "@/components/ui/link";
import { MetaDot, RecordHeader } from "@/components/ui/record-header";
import { ReasonDialog } from "@/components/ui/reason-dialog";
import { SectionCard } from "@/components/ui/section-card";
import { ErrorState, Loading, NotAvailable, PermissionDenied } from "@/components/ui/states";
import { toast } from "@/components/ui/toast";
import { useScreenContribution } from "@/features/assistant/screen-context-store";
import { useCommand } from "@/features/inventory/use-command";
import { OrderFeasibilityPanel } from "@/features/production/feasibility-panel";
import { ProblemError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { ordersMessages as m } from "@/messages/orders";
import {
  cancelLine,
  createOrderChallan,
  createPickList,
  fetchOrder,
  releaseReservations,
  reserveOrder,
  transitionOrder,
  type OrderAction,
  type OrderDetail,
  type OrderLine,
} from "./api";
import { OrderStatusPill } from "./order-list";
import { isPositiveDecimalStr } from "@/lib/format/decimal";

const w = m.workspace;

/** The sales order workspace. 404 and out-of-scope orders are the same "not available" state on purpose. */
export function OrderWorkspace({ orderId }: { orderId: string }) {
  const query = useQuery({ queryKey: queryKeys.orders.order(orderId), queryFn: ({ signal }) => fetchOrder(orderId, signal) });
  if (query.isPending) return <Loading label={w.loading} variant="detail" />;
  if (query.isError) {
    const error = query.error;
    if (error instanceof ProblemError && error.status === 404) return <NotAvailable />;
    if (error instanceof ProblemError && error.status === 403) return <PermissionDenied area={w.permissionArea} />;
    return <ErrorState error={error} what={w.loading} onRetry={() => void query.refetch()} />;
  }
  return <Workspace order={query.data} />;
}

function qty(value: string, uom: string) {
  return <Quantity value={{ value, uom }} />;
}

function Workspace({ order }: { order: OrderDetail }) {
  const router = useRouter();
  const key = useMemo(() => queryKeys.orders.order(order.id), [order.id]);
  const { run, pending, offline } = useCommand<OrderDetail>(key);
  const [dialog, setDialog] = useState<null | "hold" | "cancel" | { line: OrderLine }>(null);
  const caps = order.capabilities;
  const allowed = new Set(order.allowed_transitions.map((t) => t.action));

  useScreenContribution({ focus: { type: "orders.sales_order", id: order.id, version: order.version } });

  const transition = (action: OrderAction, done: string, reason?: { code: string | null; note: string }) =>
    void run(action, (k) => transitionOrder(order, action, k, reason ? { code: reason.code, note: reason.note } : {}), { done, failed: w.failed, write: (r) => r });

  const actions = (
    <>
      {allowed.has("confirm") ? (
        <Button variant="primary" isPending={pending === "confirm"} onPress={() => transition("confirm", w.confirmed)} {...unavailableWhen(offline)}>
          {w.confirm}
        </Button>
      ) : null}
      {caps.reserve?.allowed ? (
        <Button
          variant="primary"
          isPending={pending === "reserve"}
          onPress={() =>
            void run("reserve", (k) => reserveOrder(order.id, k), {
              failed: w.failed,
              write: (r) => {
                const short = r.outcomes.filter((o) => isPositiveDecimalStr(o.shortfall)).length;
                (short ? toastWarn : toastOk)(w.reserved(r.outcomes.length, short));
                return r.order;
              },
            })
          }
        >
          {w.reserve}
        </Button>
      ) : null}
      {caps.create_challan?.allowed ? (
        <Button
          isPending={pending === "challan"}
          onPress={() =>
            void run("challan", (k) => createOrderChallan(order.id, k), { done: w.challanCreated, failed: w.failed }).then((r) => {
              if (r) router.push(r.path as Parameters<typeof router.push>[0]);
            })
          }
        >
          {w.createChallan}
        </Button>
      ) : null}
      {caps.create_pick_list?.allowed ? (
        <Button
          isPending={pending === "pick"}
          onPress={() =>
            void run("pick", (k) => createPickList(order.id, k), { done: w.pickListCreated, failed: w.failed }).then((r) => {
              if (r) router.push(`/operations/inventory/pick-lists/${r.id}` as Parameters<typeof router.push>[0]);
            })
          }
        >
          {w.createPickList}
        </Button>
      ) : null}
      {caps.release_reservations?.allowed ? (
        <Button isPending={pending === "release"} onPress={() => void run("release", (k) => releaseReservations(order.id, k), { done: w.reservationsReleased, failed: w.failed, write: (r) => r })}>
          {w.release}
        </Button>
      ) : null}
      {allowed.has("hold") ? <Button onPress={() => setDialog("hold")}>{w.hold}</Button> : null}
      {allowed.has("release_hold") ? (
        <Button isPending={pending === "release_hold"} onPress={() => transition("release_hold", w.released)}>
          {w.releaseHold}
        </Button>
      ) : null}
      {allowed.has("cancel") ? (
        <Button variant="quiet" onPress={() => setDialog("cancel")}>
          {w.cancel}
        </Button>
      ) : null}
    </>
  );

  const facts: KeyValue[] = [
    { term: w.subtotal, description: <Money value={order.subtotal} />, numeric: true },
    { term: w.surcharge, description: <Money value={order.surcharge} />, numeric: true },
    { term: w.total, description: order.total ? <Money value={order.total} /> : "—", numeric: true },
    { term: w.warehouse, description: order.default_warehouse ? `${order.default_warehouse.code} · ${order.default_warehouse.name}` : w.noWarehouse },
  ];

  const lineColumns: DataTableColumn<OrderLine>[] = [
    { id: "no", header: w.columns.line, numeric: true, cell: (l) => l.line_no },
    {
      id: "item",
      header: w.columns.item,
      isRowHeader: true,
      mobile: "title",
      cell: (l) => (
        <span className="flex flex-col">
          <span>{l.description}</span>
          <span className="text-xs text-ink-muted">{[l.product_key, m.modes[l.fulfilment_mode]].filter(Boolean).join(" · ")}</span>
        </span>
      ),
    },
    { id: "ordered", header: w.columns.ordered, numeric: true, mobile: "amount", cell: (l) => qty(l.qty_ordered, l.unit) },
    { id: "reserved", header: w.columns.reserved, numeric: true, cell: (l) => qty(l.qty_reserved, l.unit) },
    { id: "delivered", header: w.columns.delivered, numeric: true, cell: (l) => qty(l.qty_delivered, l.unit) },
    { id: "returned", header: w.columns.returned, numeric: true, cell: (l) => qty(l.qty_returned, l.unit) },
    { id: "cancelled", header: w.columns.cancelled, numeric: true, cell: (l) => qty(l.qty_cancelled, l.unit) },
    { id: "remaining", header: w.columns.remaining, numeric: true, mobile: "key", cell: (l) => qty(l.qty_remaining, l.unit) },
    { id: "total", header: w.columns.total, numeric: true, cell: (l) => (l.line_total ? <Money value={l.line_total} /> : "—") },
    {
      id: "actions",
      header: "",
      cell: (l) =>
        caps.cancel_line?.allowed && isPositiveDecimalStr(l.qty_remaining) && l.line_kind !== "charge" ? (
          <Button size="sm" variant="quiet" onPress={() => setDialog({ line: l })}>
            {w.cancelLine}
          </Button>
        ) : null,
    },
  ];

  return (
    <div className="flex flex-col gap-6">
      <RecordHeader
        back={{ href: "/sales/orders", label: w.back }}
        recordKey={order.order_number}
        title={order.party.display_name}
        status={<OrderStatusPill status={order.status} />}
        meta={
          <>
            <span>{w.fromQuote(order.quote.quote_number, order.quote.revision_no)}</span>
            <MetaDot />
            <span>{m.fulfilment[order.fulfilment_state]}</span>
            <MetaDot />
            <LocalDate value={order.order_date} />
            {order.owner.display_name ? (
              <>
                <MetaDot />
                <span>{order.owner.display_name}</span>
              </>
            ) : null}
          </>
        }
        actions={actions}
      />
      {order.hold_reason_code ? (
        <p className="rounded-md border border-warning-text/40 bg-warning-bg p-3 text-sm text-warning-text">
          {m.workspace.held}: {m.holdReasons.find((r) => r.id === order.hold_reason_code)?.label ?? order.hold_reason_code}
          {order.hold_reason ? ` — ${order.hold_reason}` : ""}
        </p>
      ) : null}
      <SectionCard title={w.totals} description={w.commercialLocked}>
        <KeyValueGrid items={facts} columns={2} />
      </SectionCard>
      <SectionCard title={w.lines}>
        <DataTable caption={w.linesCaption} hideCaption columns={lineColumns} rows={order.lines} rowId={(l) => l.id} />
      </SectionCard>
      <OrderFeasibilityPanel lines={order.lines} requestedDate={order.requested_delivery_date ?? order.promised_date ?? null} />
      <SectionCard title={w.reservations}>
        {order.reservations.length === 0 ? (
          <p className="text-sm text-ink-muted">{w.reservationsEmpty}</p>
        ) : (
          <ul className="flex flex-col divide-y">
            {order.reservations.map((r) => (
              <li key={r.id} className="flex flex-wrap items-baseline justify-between gap-2 py-2 text-sm">
                <span>
                  {w.reservationColumns.line} {order.lines.find((l) => l.id === r.line_id)?.line_no ?? "?"} · {r.warehouse.code}
                </span>
                <span className="tabular">
                  {qty(r.remaining, r.unit)} <span className="text-ink-muted">/ {qty(r.quantity, r.unit)}</span> · {r.status}
                </span>
              </li>
            ))}
          </ul>
        )}
      </SectionCard>
      <SectionCard title={w.documents}>
        {order.documents.length === 0 ? (
          <p className="text-sm text-ink-muted">{w.documentsEmpty}</p>
        ) : (
          <ul className="flex flex-col gap-1">
            {order.documents.map((d) => (
              <li key={d.id} className="text-sm">
                <Link href={d.path} className="font-mono">
                  {d.number}
                </Link>{" "}
                <span className="text-ink-muted">· {d.status}</span>
              </li>
            ))}
          </ul>
        )}
      </SectionCard>
      <SectionCard title={w.history}>
        <ol className="flex flex-col gap-2 text-sm">
          {order.history.map((h, i) => (
            <li key={`${h.occurred_at}-${i}`} className="flex flex-wrap gap-x-2">
              <LocalDateTime value={h.occurred_at} />
              <span>{w.actions[h.action] ?? h.action}</span>
              {h.reference ? <span className="font-mono text-ink-muted">{h.reference}</span> : null}
              {h.actor?.display_name ? <span className="text-ink-muted">· {h.actor.display_name}</span> : null}
              {h.reason ? <span className="text-ink-muted">· {h.reason}</span> : null}
            </li>
          ))}
        </ol>
      </SectionCard>
      <ReasonDialog
        title={w.holdTitle}
        reasons={m.holdReasons}
        noteLabel={w.reasonNote}
        confirmLabel={w.hold}
        isOpen={dialog === "hold"}
        isPending={pending === "hold"}
        disabledReason={offline}
        onOpenChange={(open) => (open ? null : setDialog(null))}
        onConfirm={(code, note) => {
          setDialog(null);
          transition("hold", w.held, { code, note });
        }}
      />
      <ReasonDialog
        title={w.cancelTitle}
        reasons={m.cancelReasons}
        noteLabel={w.reasonNote}
        confirmLabel={w.cancel}
        isOpen={dialog === "cancel"}
        isPending={pending === "cancel"}
        disabledReason={offline}
        onOpenChange={(open) => (open ? null : setDialog(null))}
        onConfirm={(code, note) => {
          setDialog(null);
          transition("cancel", w.cancelled, { code, note });
        }}
      />
      <ReasonDialog
        title={typeof dialog === "object" && dialog ? w.cancelLineTitle(dialog.line.line_no) : w.cancelLine}
        reasons={m.cancelReasons}
        noteLabel={w.reasonNote}
        confirmLabel={w.cancelLine}
        isOpen={typeof dialog === "object" && dialog !== null}
        disabledReason={offline}
        onOpenChange={(open) => (open ? null : setDialog(null))}
        onConfirm={(code, note) => {
          const line = typeof dialog === "object" && dialog ? dialog.line : null;
          setDialog(null);
          if (line && code) void run("cancel_line", (k) => cancelLine(order.id, line, code, note, k), { done: w.lineCancelled, failed: w.failed, write: (r) => r });
        }}
      />
    </div>
  );
}

function toastOk(text: string) {
  toast.success(text);
}

function toastWarn(text: string) {
  toast.warning(text);
}
