"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useMemo, useState, type ReactNode } from "react";
import { useCommand } from "@/features/inventory/use-command";
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
} from "@/features/orders/api";
import { queryKeys } from "@/lib/api/query-keys";
import { isPositiveDecimalStr } from "@/lib/format/decimal";
import { asRoute, humanise, orderStatus } from "~/data/sales-deals";
import { Page, RecordHeader, Split } from "~/shell/page";
import { ErrorBlock, LoadingBlock } from "~/shell/states";
import {
  Banner,
  Button,
  ButtonLink,
  Code,
  DataTable,
  DateText,
  Drawer,
  EmptyState,
  FactStrip,
  GlassPanel,
  KeyValue,
  Menu,
  Modal,
  Money,
  Qty,
  Select,
  Skeleton,
  SkeletonText,
  Tabs,
  Textarea,
  TextLink,
  Timeline,
  toast,
  type Column,
  type IconName,
  type MenuItem,
  type TimelineItem,
} from "~/ui";
import { StatusBadge, Steps, type StepItem } from "../quotations/parts";
import { viewHref, type OrderView } from "../quotations/views";
import { FulfilmentView } from "./fulfilment-view";
import { FulfilmentBadge } from "./order-list";

const HOLD_REASONS = [
  { id: "credit", label: "Credit or payment" },
  { id: "customer_request", label: "The customer asked to wait" },
  { id: "stock", label: "Stock" },
  { id: "quality", label: "Quality" },
  { id: "other", label: "Something else" },
];
const CANCEL_REASONS = [
  { id: "customer_cancelled", label: "The customer cancelled" },
  { id: "duplicate", label: "Duplicate order" },
  { id: "price", label: "Price" },
  { id: "stock_unavailable", label: "Stock is not available" },
  { id: "other", label: "Something else" },
];
const MODE: Record<string, string> = { stock: "From stock", make_to_order: "Made to order", non_stock: "Not stocked" };
const FAILED = "That did not go through";
const reasonLabel = (list: typeof HOLD_REASONS, code: string | null) => list.find((reason) => reason.id === code)?.label ?? (code ? humanise(code) : null);

/** An order: its progress from confirmation to delivery, its lines, its fulfilment records and its history. */
export function OrderRecord({ orderId, view }: { orderId: string; view: OrderView }) {
  const query = useQuery({ queryKey: queryKeys.orders.order(orderId), queryFn: ({ signal }) => fetchOrder(orderId, signal) });
  if (query.isPending) {
    return (
      <Page>
        <div className="lk-glass record-head" role="status" aria-label="Loading the order">
          <Skeleton width="160px" height={14} />
          <Skeleton width="45%" height={32} />
          <SkeletonText lines={2} />
        </div>
        <LoadingBlock lines={6} label="Loading the order" />
      </Page>
    );
  }
  if (query.isError) {
    return (
      <Page>
        <ErrorBlock error={query.error} what="This order" onRetry={() => void query.refetch()} />
        <div>
          <ButtonLink href="/sales/orders" variant="secondary" iconLeft="arrowLeft">
            All orders
          </ButtonLink>
        </div>
      </Page>
    );
  }
  return <Loaded order={query.data} view={view} />;
}

type Step = { id: string; label: string; icon: IconName; run: () => void; pendingName: string };

function Loaded({ order, view }: { order: OrderDetail; view: OrderView }) {
  const router = useRouter();
  const key = useMemo(() => queryKeys.orders.order(order.id), [order.id]);
  const { run, pending, offline } = useCommand<OrderDetail>(key);
  const [dialog, setDialog] = useState<null | "hold" | "cancel">(null);
  const [openLineId, setOpenLineId] = useState<string | null>(null);
  const [cancelLineId, setCancelLineId] = useState<string | null>(null);
  const caps = order.capabilities;
  const allowed = new Set(order.allowed_transitions.map((t) => t.action));
  const path = `/sales/orders/${order.id}`;
  const openLine = order.lines.find((line) => line.id === openLineId) ?? null;
  const lineToCancel = order.lines.find((line) => line.id === cancelLineId) ?? null;

  const transition = (action: OrderAction, done: string, reason?: { code: string | null; note: string | null }) =>
    run(action, (k) => transitionOrder(order, action, k, reason ? { code: reason.code, note: reason.note } : {}), { done, failed: FAILED, write: (r) => r });

  // The forward steps in the order they usually happen; the first one available leads.
  const steps: Step[] = [];
  if (allowed.has("confirm")) steps.push({ id: "confirm", label: "Confirm order", icon: "check", pendingName: "confirm", run: () => void transition("confirm", "Order confirmed") });
  if (allowed.has("release_hold")) steps.push({ id: "release_hold", label: "Release hold", icon: "play", pendingName: "release_hold", run: () => void transition("release_hold", "Hold released") });
  if (caps.reserve?.allowed) {
    steps.push({
      id: "reserve",
      label: "Reserve stock",
      icon: "bookmark",
      pendingName: "reserve",
      run: () =>
        void run("reserve", (k) => reserveOrder(order.id, k), {
          failed: FAILED,
          write: (r) => {
            const short = r.outcomes.filter((o) => isPositiveDecimalStr(o.shortfall)).length;
            if (short > 0) toast.warning("Reserved what was available", { description: short === 1 ? "1 line is still short." : `${short} lines are still short.` });
            else toast.success(r.outcomes.length === 1 ? "Reserved 1 line" : `Reserved ${r.outcomes.length} lines`);
            return r.order;
          },
        }),
    });
  }
  if (caps.create_pick_list?.allowed) {
    steps.push({
      id: "pick",
      label: "Create pick list",
      icon: "clipboard",
      pendingName: "pick",
      run: () =>
        void run("pick", (k) => createPickList(order.id, k), { done: "Pick list created", failed: FAILED }).then((r) => {
          if (r) router.push(asRoute(`/operations/inventory/pick-lists/${r.id}`));
        }),
    });
  }
  if (caps.create_challan?.allowed) {
    steps.push({
      id: "challan",
      label: "Create delivery challan",
      icon: "truck",
      pendingName: "challan",
      run: () =>
        void run("challan", (k) => createOrderChallan(order.id, k), { done: "Draft challan created", failed: FAILED }).then((r) => {
          if (r) router.push(asRoute(r.path));
        }),
    });
  }
  const [lead, second, ...others] = steps;

  const menu: MenuItem[] = others.map((step) => ({ id: step.id, label: step.label, icon: step.icon, isDisabled: Boolean(offline), onAction: step.run }));
  if (caps.release_reservations?.allowed) {
    menu.push({
      id: "release",
      label: "Release reservations",
      icon: "undo",
      description: "Frees the stock held for this order",
      isDisabled: Boolean(offline),
      onAction: () => void run("release", (k) => releaseReservations(order.id, k), { done: "Reservations released", failed: FAILED, write: (r) => r }),
    });
  }
  if (allowed.has("hold")) menu.push({ id: "hold", label: "Put on hold", icon: "pause", isDisabled: Boolean(offline), onAction: () => setDialog("hold") });
  if (allowed.has("cancel")) {
    if (menu.length > 0) menu.push({ id: "sep", separator: true });
    menu.push({ id: "cancel", label: "Cancel order", icon: "xCircle", tone: "danger", isDisabled: Boolean(offline), onAction: () => setDialog("cancel") });
  }

  const wanted = order.requested_delivery_date ?? order.promised_date;

  return (
    <Page>
      <RecordHeader
        breadcrumb={[{ label: "Sales", href: "/sales" }, { label: "Orders", href: "/sales/orders" }, { label: order.order_number }]}
        code={order.order_number}
        title={order.party.display_name}
        status={
          <>
            <StatusBadge look={orderStatus(order.status)} />
            {order.status === "cancelled" ? null : <FulfilmentBadge state={order.fulfilment_state} />}
          </>
        }
        lead={
          <>
            From quotation{" "}
            <TextLink href={asRoute(`/sales/quotes/${order.quote.id}`)}>{order.quote.quote_number}</TextLink>, revision {order.quote.revision_no}
            {order.customer_reference ? ` · their ref. ${order.customer_reference}` : ""}
          </>
        }
        facts={
          <FactStrip
            items={[
              { label: "Total", icon: "banknote", value: <Money value={order.total} className="t-stat-sm" /> },
              { label: "Ordered", icon: "calendar", value: <DateText value={order.order_date} style="business" /> },
              { label: order.promised_date && !order.requested_delivery_date ? "Promised for" : "Wanted by", icon: "clock", value: wanted ? <DateText value={wanted} style="business" /> : null },
              { label: "Warehouse", icon: "warehouse", value: order.default_warehouse ? order.default_warehouse.name : null },
              { label: "Owner", icon: "user", value: order.owner.display_name },
            ]}
          />
        }
        actions={
          <>
            {lead ? (
              <Button iconLeft={lead.icon} loading={pending === lead.pendingName} isDisabled={Boolean(offline)} onPress={lead.run}>
                {lead.label}
              </Button>
            ) : null}
            {second ? (
              <Button variant="secondary" iconLeft={second.icon} loading={pending === second.pendingName} isDisabled={Boolean(offline)} onPress={second.run}>
                {second.label}
              </Button>
            ) : null}
            {menu.length > 0 ? (
              <Menu
                label="More order actions"
                items={menu}
                placement="bottom end"
                trigger={
                  <Button variant="secondary" iconRight="chevronDown">
                    More
                  </Button>
                }
              />
            ) : null}
          </>
        }
      >
        <Tabs
          label="Views of this order"
          selectedKey={view}
          tabs={[
            { id: "overview", label: "Overview", href: asRoute(path) },
            { id: "lines", label: "Lines", count: order.lines.length, href: asRoute(viewHref(path, "lines")) },
            { id: "fulfilment", label: "Stock and dispatch", count: order.documents.length || undefined, href: asRoute(viewHref(path, "fulfilment")) },
            { id: "activity", label: "Activity", href: asRoute(viewHref(path, "activity")) },
          ]}
        />
      </RecordHeader>

      {offline ? (
        <Banner tone="amber" title="You are offline.">
          You can read this order. Actions work again once the connection is back.
        </Banner>
      ) : null}
      {order.status === "on_hold" || order.hold_reason_code ? (
        <Banner tone="amber" icon="pause" title={`On hold: ${reasonLabel(HOLD_REASONS, order.hold_reason_code) ?? "no reason recorded"}.`}>
          {order.hold_reason ?? "Nothing is reserved or dispatched until the hold is released."}
        </Banner>
      ) : null}
      {order.status === "cancelled" ? (
        <Banner tone="neutral" icon="xCircle" title={`Cancelled${order.cancel_reason_code ? `: ${(reasonLabel(CANCEL_REASONS, order.cancel_reason_code) ?? "").toLowerCase()}` : ""}.`}>
          {order.cancel_reason ?? "Any stock held for it has been released."}
        </Banner>
      ) : null}

      {view === "overview" ? <Overview order={order} leadLabel={lead?.label ?? null} /> : null}
      {view === "lines" ? <LinesView order={order} onOpen={setOpenLineId} selected={openLineId} /> : null}
      {view === "fulfilment" ? <FulfilmentView order={order} /> : null}
      {view === "activity" ? <ActivityView order={order} /> : null}

      <LineDrawer
        order={order}
        line={openLine}
        canCancel={Boolean(caps.cancel_line?.allowed) && !offline}
        onClose={() => setOpenLineId(null)}
        onCancelRemaining={(line) => {
          setOpenLineId(null);
          setCancelLineId(line.id);
        }}
      />

      <CodeReasonDialog
        isOpen={dialog === "hold"}
        onClose={() => setDialog(null)}
        title="Put this order on hold"
        description="Nothing is reserved or dispatched while it is held. Release the hold to carry on."
        reasons={HOLD_REASONS}
        confirmLabel="Put on hold"
        onConfirm={async (code, note) => Boolean(await transition("hold", "Order on hold", { code, note }))}
      />
      <CodeReasonDialog
        isOpen={dialog === "cancel"}
        onClose={() => setDialog(null)}
        tone="danger"
        title="Cancel this order"
        description="What is still open is cancelled and the stock held for it is released. Deliveries already made stay on record."
        reasons={CANCEL_REASONS}
        confirmLabel="Cancel order"
        onConfirm={async (code, note) => Boolean(await transition("cancel", "Order cancelled", { code, note }))}
      />
      <CodeReasonDialog
        isOpen={lineToCancel !== null}
        onClose={() => setCancelLineId(null)}
        tone="danger"
        title={lineToCancel ? `Cancel what remains of line ${lineToCancel.line_no}` : ""}
        description={lineToCancel ? `${lineToCancel.description}: the undelivered quantity is cancelled. What was delivered stays.` : undefined}
        reasons={CANCEL_REASONS}
        confirmLabel="Cancel remaining"
        onConfirm={async (code, note) =>
          lineToCancel
            ? Boolean(await run("cancel_line", (k) => cancelLine(order.id, lineToCancel, code, note, k), { done: "Remaining quantity cancelled", failed: FAILED, write: (r) => r }))
            : false
        }
      />
    </Page>
  );
}

// ---------------------------------------------------------------------------------------------
// Overview: progress from confirmation to delivery

function progressOf(order: OrderDetail): StepItem[] {
  const cancelled = order.status === "cancelled";
  const stockLines = order.lines.some((line) => line.fulfilment_mode === "stock" && line.line_kind !== "charge");
  const challans = order.documents.filter((doc) => doc.kind === "challan");
  const picks = order.documents.filter((doc) => doc.kind === "pick_list");
  const confirmed = order.confirmed_at !== null || order.status === "confirmed" || order.status === "completed";
  const reserved = order.reservations.length > 0 || order.lines.some((line) => isPositiveDecimalStr(line.qty_reserved));
  const moving = order.fulfilment_state !== "none";
  const dispatched = challans.length > 0 || moving;
  const delivered = order.fulfilment_state === "complete" || order.status === "completed";
  const raw: { id: string; label: string; hint: ReactNode; done: boolean }[] = [
    { id: "confirmed", label: "Confirmed", hint: order.confirmed_at ? <DateText value={order.confirmed_at} style="date" /> : "Tells operations it is real", done: confirmed },
    ...(stockLines ? [{ id: "reserved", label: "Stock reserved", hint: reserved ? (order.reservations.length === 1 ? "1 reservation" : `${order.reservations.length} reservations`) : "Held in the warehouse", done: reserved || dispatched }] : []),
    {
      id: "dispatch",
      label: "Dispatched",
      hint: challans.length > 0 ? (challans.length === 1 ? "1 challan" : `${challans.length} challans`) : picks.length > 0 ? (picks.length === 1 ? "1 pick list" : `${picks.length} pick lists`) : "Pick list, then challan",
      done: dispatched,
    },
    { id: "delivered", label: "Delivered", hint: order.completed_at ? <DateText value={order.completed_at} style="date" /> : order.fulfilment_state === "partial" ? "Partly delivered" : "In full", done: delivered },
  ];
  const current = cancelled ? -1 : raw.findIndex((step) => !step.done);
  return raw.map((step, index) => ({ id: step.id, label: step.label, hint: step.hint, state: step.done && !cancelled ? "done" : index === current ? "current" : "todo" }));
}

function standingOf(order: OrderDetail, leadLabel: string | null): { headline: ReactNode; body: string } {
  const next = leadLabel ? ` Next: ${leadLabel.toLowerCase()}.` : "";
  if (order.status === "cancelled") return { headline: "Cancelled", body: "Nothing more will be reserved or dispatched for this order." };
  if (order.status === "completed" || order.fulfilment_state === "complete") {
    return { headline: <>Delivered in <em>full</em></>, body: "Every line has reached the customer. Invoices and receipts continue in Finance." };
  }
  if (order.status === "on_hold") return { headline: <>On <em>hold</em></>, body: `Reserving and dispatching wait until the hold is released.${next}` };
  if (order.status === "draft") return { headline: <>Waiting to be <em>confirmed</em></>, body: "Confirming tells operations the order is real. Stock can be reserved and dispatch planned from then on." };
  if (order.fulfilment_state === "partial") return { headline: <>Partly <em>delivered</em></>, body: `Some of it has reached the customer. The Lines view shows what is still to go.${next}` };
  const reserved = order.reservations.length > 0;
  const docs = order.documents.length > 0;
  if (docs) return { headline: <>On its way to <em>dispatch</em></>, body: `Its delivery documents are under Stock and dispatch. Delivery is recorded on the challan.${next}` };
  if (reserved) return { headline: <>Stock is <em>held</em></>, body: `The warehouse is holding stock for this order.${next || " Create a pick list or a delivery challan to send it."}` };
  return { headline: <>Confirmed. Now the <em>stock</em></>, body: `Nothing is held for this order yet.${next}` };
}

function Overview({ order, leadLabel }: { order: OrderDetail; leadLabel: string | null }) {
  const standing = standingOf(order, leadLabel);
  const terms = order.terms as Record<string, unknown>;
  const term = (name: string) => (typeof terms[name] === "string" && terms[name] ? (terms[name] as string) : null);
  return (
    <Split
      main={
        <>
          <GlassPanel padding="lg" className="rise flex flex-col gap-6" eyebrow="Where it stands">
            <Steps label="Progress of this order" steps={progressOf(order)} />
            <div className="flex max-w-prose flex-col gap-2">
              <h2 className="t-display-sm text-ink">{standing.headline}</h2>
              <p className="t-body text-ink-2">{standing.body}</p>
            </div>
          </GlassPanel>
          <section aria-label="Totals" className="lk-glass lk-glass-inverse rise flex min-w-0 flex-col gap-5 rounded-xl p-6">
            <div className="flex items-center justify-between gap-3">
              <h2 className="t-overline opacity-70">Totals</h2>
              <span className="t-caption lk-tnum opacity-70">
                {order.currency} · {order.line_count === 1 ? "1 line" : `${order.line_count} lines`}
              </span>
            </div>
            <dl className="flex flex-col gap-2">
              <div className="flex items-baseline justify-between gap-4">
                <dt className="t-body-sm opacity-70">Subtotal</dt>
                <dd className="t-body lk-tnum">
                  <Money value={order.subtotal} />
                </dd>
              </div>
              <div className="flex items-baseline justify-between gap-4">
                <dt className="t-body-sm opacity-70">Surcharge</dt>
                <dd className="t-body lk-tnum">
                  <Money value={order.surcharge} />
                </dd>
              </div>
            </dl>
            <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-1 border-t border-on-inverse/20 pt-5">
              <span className="t-label">Total</span>
              <span className="t-stat-xl ml-auto text-right">
                <Money value={order.total} />
              </span>
            </div>
            <p className="t-body-sm opacity-80">Prices and quantities come from the accepted quotation revision. They never change on the order.</p>
          </section>
        </>
      }
      aside={
        <>
          <GlassPanel padding="md" className="rise" title="Linked records" titleAs="h2">
            <KeyValue
              rows
              items={[
                { label: "Quotation", value: <TextLink href={asRoute(`/sales/quotes/${order.quote.id}`)}>{order.quote.quote_number}</TextLink> },
                { label: "Customer", value: <TextLink href={asRoute(`/sales/parties/${order.party.id}`)}>{order.party.display_name}</TextLink> },
                { label: "Warehouse", value: order.default_warehouse ? `${order.default_warehouse.code} · ${order.default_warehouse.name}` : null },
                ...order.documents.map((doc) => ({
                  label: doc.kind === "challan" ? "Delivery challan" : "Pick list",
                  value: (
                    <TextLink href={asRoute(doc.path)}>
                      <Code>{doc.number}</Code>
                    </TextLink>
                  ),
                })),
              ]}
            />
          </GlassPanel>
          <GlassPanel padding="md" className="rise" title="Terms from the quotation" titleAs="h2">
            <KeyValue
              rows
              items={[
                { label: "Incoterm", value: [term("incoterm"), term("incoterm_place")].filter(Boolean).join(" · ") },
                { label: "Payment terms", value: term("payment_terms") },
                { label: "Their reference", value: order.customer_reference },
                { label: "Ship to", value: order.ship_to },
              ]}
            />
          </GlassPanel>
        </>
      }
    />
  );
}

// ---------------------------------------------------------------------------------------------
// Lines

function LinesView({ order, onOpen, selected }: { order: OrderDetail; onOpen: (lineId: string) => void; selected: string | null }) {
  const qty = (value: string, unit: string) => <Qty value={{ value, uom: unit }} />;
  const columns: Column<OrderLine>[] = [
    {
      key: "item",
      header: "Line",
      primary: true,
      cell: (line) => (
        <span className="flex min-w-0 items-start gap-3">
          <span className="t-caption lk-tnum mt-0.5 w-5 flex-none text-right text-ink-3">{line.line_no}</span>
          <span className="flex min-w-0 flex-col gap-0.5">
            <span className="t-label text-ink">{line.description}</span>
            <span className="t-caption text-ink-3">{[line.product_key, MODE[line.fulfilment_mode]].filter(Boolean).join(" · ")}</span>
          </span>
        </span>
      ),
    },
    { key: "ordered", header: "Ordered", numeric: true, cell: (line) => qty(line.qty_ordered, line.unit) },
    { key: "reserved", header: "Reserved", numeric: true, hideOnMobile: true, cell: (line) => qty(line.qty_reserved, line.unit) },
    { key: "delivered", header: "Delivered", numeric: true, cell: (line) => qty(line.qty_delivered, line.unit) },
    {
      key: "remaining",
      header: "Still to go",
      numeric: true,
      cell: (line) => <span className={isPositiveDecimalStr(line.qty_remaining) ? "t-label text-ink" : "text-ink-3"}>{qty(line.qty_remaining, line.unit)}</span>,
    },
    { key: "total", header: "Line total", numeric: true, hideOnMobile: true, cell: (line) => <Money value={line.line_total} /> },
  ];
  return (
    <div className="stack">
      <div className="flex min-w-0 flex-col gap-1">
        <h2 className="t-h3">Lines</h2>
        <p className="t-body-sm text-ink-3">Open a line for its full count: reserved, delivered, returned and cancelled.</p>
      </div>
      <GlassPanel padding="none" className="rise min-w-0">
        <DataTable
          label={`Lines of ${order.order_number}`}
          columns={columns}
          rows={order.lines}
          rowKey={(line) => line.id}
          onRowAction={(line) => onOpen(line.id)}
          selectedKey={selected ?? undefined}
          empty={<EmptyState compact icon="list" title="This order has no lines" text="It was converted from a quotation without lines." />}
        />
      </GlassPanel>
    </div>
  );
}

function LineDrawer({
  order,
  line,
  canCancel,
  onClose,
  onCancelRemaining,
}: {
  order: OrderDetail;
  line: OrderLine | null;
  canCancel: boolean;
  onClose: () => void;
  onCancelRemaining: (line: OrderLine) => void;
}) {
  const cancellable = line !== null && canCancel && isPositiveDecimalStr(line.qty_remaining) && line.line_kind !== "charge";
  const qty = (value: string) => (line ? <Qty value={{ value, uom: line.unit }} /> : null);
  return (
    <Drawer
      isOpen={line !== null}
      onOpenChange={(open) => (open ? undefined : onClose())}
      title={line ? `Line ${line.line_no}` : ""}
      description={line ? [line.description, line.product_key].filter(Boolean).join(" · ") : undefined}
      footer={
        <>
          {cancellable && line ? (
            <Button variant="danger" className="mr-auto" onPress={() => onCancelRemaining(line)}>
              Cancel remaining
            </Button>
          ) : null}
          <Button variant="ghost" onPress={onClose}>
            Close
          </Button>
        </>
      }
    >
      {line ? (
        <div className="flex flex-col gap-5">
          <div className="flex items-end justify-between gap-4 rounded-md border border-line bg-surface p-4">
            <div className="flex flex-col gap-0.5">
              <span className="t-overline text-ink-3">Still to go</span>
              <span className="t-stat text-ink">{qty(line.qty_remaining)}</span>
            </div>
            <span className="t-caption text-ink-3">{MODE[line.fulfilment_mode] ?? line.fulfilment_mode}</span>
          </div>
          <KeyValue
            rows
            items={[
              { label: "Ordered", value: qty(line.qty_ordered) },
              { label: "Reserved", value: qty(line.qty_reserved) },
              { label: "Not yet reserved", value: qty(line.qty_unreserved) },
              { label: "Delivered", value: qty(line.qty_delivered) },
              { label: "Returned", value: qty(line.qty_returned) },
              { label: "Cancelled", value: qty(line.qty_cancelled) },
              { label: "Unit price", value: <Money value={line.unit_price} /> },
              { label: "Line total", value: <Money value={line.line_total} />, total: true },
            ]}
          />
          {line.cancel_reason_code ? <p className="t-body-sm text-ink-3">Cancelled because: {(reasonLabel(CANCEL_REASONS, line.cancel_reason_code) ?? "").toLowerCase()}.</p> : null}
          <p className="t-caption text-ink-3">Order {order.order_number}. Quantities and prices come from the accepted quotation revision.</p>
        </div>
      ) : null}
    </Drawer>
  );
}

// ---------------------------------------------------------------------------------------------
// Activity

const DID: Record<string, string> = {
  create: "created the order from the quotation",
  confirm: "confirmed the order",
  hold: "put it on hold",
  release_hold: "released the hold",
  cancel: "cancelled the order",
  complete: "completed the order",
  cancel_line: "cancelled the rest of a line",
  deliver: "recorded a delivery",
  return: "recorded a return",
  reverse_delivery: "reversed a delivery",
};
const DID_ICON: Record<string, IconName> = { create: "filePlus", confirm: "check", hold: "pause", release_hold: "play", cancel: "xCircle", complete: "checkCircle", deliver: "truck", return: "undo" };

function ActivityView({ order }: { order: OrderDetail }) {
  const items: TimelineItem[] = [...order.history]
    .sort((a, b) => b.occurred_at.localeCompare(a.occurred_at))
    .map((entry, index) => ({
      id: `${entry.occurred_at}-${index}`,
      title: `${entry.actor?.display_name ?? "Lamikraft One"} ${DID[entry.action] ?? humanise(entry.action).toLowerCase()}`,
      meta: (
        <>
          <DateText value={entry.occurred_at} style="dayTime" />
          {entry.reference ? (
            <>
              {" · "}
              <Code>{entry.reference}</Code>
            </>
          ) : null}
        </>
      ),
      body: [reasonLabel([...HOLD_REASONS, ...CANCEL_REASONS], entry.reason_code), entry.reason].filter(Boolean).join(": ") || undefined,
      icon: DID_ICON[entry.action],
      tone: orderStatus(entry.to_status).tone,
    }));
  return (
    <GlassPanel padding="lg" title="Activity" titleAs="h2" className="rise">
      {items.length === 0 ? <EmptyState compact icon="history" title="Nothing has happened yet" text="Confirmations, holds, deliveries and returns are listed here." /> : <Timeline label="Order activity" items={items} />}
    </GlassPanel>
  );
}

// ---------------------------------------------------------------------------------------------

/** A confirmation that takes one of the order's reason codes and an optional note. */
function CodeReasonDialog({
  isOpen,
  onClose,
  title,
  description,
  reasons,
  confirmLabel,
  tone = "default",
  onConfirm,
}: {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  reasons: readonly { id: string; label: string }[];
  confirmLabel: string;
  tone?: "default" | "danger";
  onConfirm: (code: string, note: string | null) => Promise<boolean>;
}) {
  const [code, setCode] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [error, setError] = useState(false);
  const [busy, setBusy] = useState(false);
  const close = () => {
    if (busy) return;
    setCode(null);
    setNote("");
    setError(false);
    onClose();
  };
  const confirm = async () => {
    if (!code) {
      setError(true);
      return;
    }
    setBusy(true);
    try {
      if (await onConfirm(code, note.trim() || null)) {
        setCode(null);
        setNote("");
        onClose();
      }
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      isOpen={isOpen}
      onOpenChange={(open) => (open ? undefined : close())}
      size="sm"
      title={title}
      description={description}
      actions={
        <>
          <Button variant="ghost" onPress={close} isDisabled={busy}>
            Keep as it is
          </Button>
          <Button variant={tone === "danger" ? "danger" : "inverse"} loading={busy} onPress={() => void confirm()}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <Select
          label="Reason"
          placeholder="Choose a reason"
          options={reasons.map((reason) => ({ value: reason.id, label: reason.label }))}
          value={code}
          onChange={(value) => {
            setCode(value);
            setError(false);
          }}
          isRequired
          error={error ? "Choose the reason. It is kept in the order's history." : undefined}
        />
        <Textarea label="Note" optional rows={2} maxLength={500} value={note} onChange={setNote} />
      </div>
    </Modal>
  );
}
