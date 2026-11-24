"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useCommand } from "@/features/inventory/use-command";
import { fetchPurchaseOrder, poAction, type PoAction, type PoDetail } from "@/features/procurement/api";
import { queryKeys } from "@/lib/api/query-keys";
import { isPositiveDecimalStr } from "@/lib/format/decimal";
import { Steps, type StepItem } from "~/screens/sales/quotations/parts";
import { Page, RecordHeader, Split } from "~/shell/page";
import {
  Badge,
  Banner,
  Button,
  ButtonLink,
  Code,
  ConfirmDialog,
  DateText,
  EmptyState,
  FactStrip,
  GlassPanel,
  KeyValue,
  Menu,
  Money,
  ReasonDialog,
  Tabs,
  TextLink,
  type IconName,
  type MenuItem,
} from "~/ui";
import { count, FAILED, poStatus, receiptStatus } from "./labels";
import { must, OfflineBanner, RecordFailure, RecordLoading, stagger, StatusBadge } from "./parts";
import { BillsView } from "./po-bills";
import { PoLinesView } from "./po-lines";
import { ReceiveDrawer } from "./po-receive";
import { asRoute, viewHref, type PoView } from "./views";

/** A purchase order: where it stands with the vendor, its lines, what arrived and what was billed. */
export function PurchaseOrderRecord({ poId, view }: { poId: string; view: PoView }) {
  const query = useQuery({
    queryKey: queryKeys.procurement.order(poId),
    queryFn: ({ signal }) => fetchPurchaseOrder(poId, signal),
  });
  if (query.isPending) return <RecordLoading label="Loading the purchase order" />;
  if (query.isError) {
    return (
      <RecordFailure error={query.error} what="This purchase order" retry={() => void query.refetch()} backHref="/operations/purchasing/orders" backLabel="All purchase orders" />
    );
  }
  return <Loaded po={query.data} view={view} />;
}

type Step = {
  id: string;
  label: string;
  icon: IconName;
  pendingName: string;
  run: () => void;
};

const DONE: Record<PoAction, string> = {
  submit: "Submitted for approval",
  approve: "Purchase order approved",
  reject: "Sent back to draft",
  issue: "Marked as sent to the vendor",
  close: "Purchase order closed",
  cancel: "Purchase order cancelled",
};

function Loaded({ po, view }: { po: PoDetail; view: PoView }) {
  const router = useRouter();
  const key = useMemo(() => queryKeys.procurement.order(po.id), [po.id]);
  const { run, pending, offline } = useCommand<PoDetail>(key);
  const [dialog, setDialog] = useState<null | "reject" | "cancel" | "close" | "closeShort">(null);
  const [receiving, setReceiving] = useState(false);
  const [receiveAttempt, setReceiveAttempt] = useState(0);
  const caps = po.capabilities;
  const path = `/operations/purchasing/orders/${po.id}`;
  const outstanding = po.lines.filter((line) => isPositiveDecimalStr(line.qty_outstanding));
  const late = po.lines.filter((line) => line.is_overdue);
  const billsHidden = caps.bill?.reason_code === "permission_denied" && po.bills.length === 0;
  const shown: PoView = view === "bills" && billsHidden ? "overview" : view;

  // Links to a bill arrive as "…/orders/{id}#bill-{billId}": the bill lives in the Bills view.
  useEffect(() => {
    const hash = window.location.hash;
    if (hash.startsWith("#bill-") && view !== "bills" && !billsHidden) router.replace(asRoute(`${path}?view=bills${hash}`));
  }, [view, billsHidden, path, router]);

  const act = (action: PoAction, reason?: string) =>
    run(action, (k) => poAction(po, action, k, reason), {
      done: DONE[action],
      failed: FAILED,
      write: (next) => next,
    });
  const startReceiving = () => {
    setReceiveAttempt((n) => n + 1);
    setReceiving(true);
  };

  // The forward steps in the order they happen; the first one available leads.
  const steps: Step[] = [];
  if (caps.submit?.allowed)
    steps.push({
      id: "submit",
      label: "Submit for approval",
      icon: "send",
      pendingName: "submit",
      run: () => void act("submit"),
    });
  if (caps.approve?.allowed)
    steps.push({
      id: "approve",
      label: "Approve",
      icon: "check",
      pendingName: "approve",
      run: () => void act("approve"),
    });
  if (caps.issue?.allowed)
    steps.push({
      id: "issue",
      label: "Mark sent to vendor",
      icon: "truck",
      pendingName: "issue",
      run: () => void act("issue"),
    });
  if (caps.receive?.allowed)
    steps.push({
      id: "receive",
      label: "Receive goods",
      icon: "packageOpen",
      pendingName: "receive",
      run: startReceiving,
    });
  const [lead, second, ...others] = steps;

  const menu: MenuItem[] = others.map((step) => ({
    id: step.id,
    label: step.label,
    icon: step.icon,
    isDisabled: Boolean(offline),
    onAction: step.run,
  }));
  if (caps.reject?.allowed) {
    menu.push({
      id: "reject",
      label: "Send back to draft",
      icon: "undo",
      description: "Returns it to the buyer with your reason",
      isDisabled: Boolean(offline),
      onAction: () => setDialog("reject"),
    });
  }
  if (caps.close?.allowed) {
    menu.push({
      id: "close",
      label: "Close purchase order",
      icon: "archive",
      description: outstanding.length > 0 ? "Stops receiving what has not arrived" : "Nothing more is expected",
      isDisabled: Boolean(offline),
      onAction: () => setDialog(outstanding.length > 0 ? "closeShort" : "close"),
    });
  }
  if (caps.cancel?.allowed) {
    if (menu.length > 0) menu.push({ id: "sep", separator: true });
    menu.push({
      id: "cancel",
      label: "Cancel purchase order",
      icon: "xCircle",
      tone: "danger",
      isDisabled: Boolean(offline),
      onAction: () => setDialog("cancel"),
    });
  }

  const tabs = [
    { id: "overview", label: "Overview", href: viewHref(path, "overview") },
    {
      id: "lines",
      label: "Lines",
      count: po.lines.length,
      href: viewHref(path, "lines"),
    },
    {
      id: "receipts",
      label: "Receipts",
      count: po.receipts.length || undefined,
      href: viewHref(path, "receipts"),
    },
    ...(billsHidden
      ? []
      : [
          {
            id: "bills",
            label: "Vendor bills",
            count: po.bills.length || undefined,
            href: viewHref(path, "bills"),
          },
        ]),
  ];

  return (
    <Page>
      <RecordHeader
        breadcrumb={[{ label: "Operations", href: "/operations" }, { label: "Purchase orders", href: "/operations/purchasing/orders" }, { label: po.po_number }]}
        code={po.po_number}
        title={po.vendor.display_name}
        status={
          <>
            <StatusBadge look={poStatus(po.status)} />
            {po.is_overdue ? (
              <Badge tone="ember" icon="clock">
                Overdue
              </Badge>
            ) : null}
          </>
        }
        lead={
          <>
            Ordered <DateText value={po.order_date} style="business" />
            {po.requisition ? (
              <>
                {" "}
                from requisition <TextLink href={asRoute(po.requisition.path)}>{po.requisition.number}</TextLink>
              </>
            ) : null}
            {po.vendor_reference ? ` · their ref. ${po.vendor_reference}` : ""}
          </>
        }
        facts={
          <FactStrip
            items={[
              {
                label: "Total",
                icon: "banknote",
                value: <Money value={{ amount: po.total_amount, currency: po.currency }} className="t-stat-sm" />,
              },
              {
                label: "Next delivery",
                icon: "calendar",
                value: po.next_expected_date ? <DateText value={po.next_expected_date} style="business" /> : null,
              },
              {
                label: "Deliver to",
                icon: "warehouse",
                value: po.warehouse.name,
              },
              { label: "Buyer", icon: "user", value: po.owner.display_name },
              {
                label: "Approved by",
                icon: "badgeCheck",
                value: po.approved_by?.display_name,
              },
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
                label="More purchase order actions"
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
        <Tabs label="Views of this purchase order" selectedKey={shown} tabs={tabs} />
      </RecordHeader>

      {offline ? <OfflineBanner what="this purchase order" /> : null}
      {caps.approve?.reason_code === "approver_is_submitter" ? (
        <Banner tone="cobalt" icon="users" title="You cannot approve an order you submitted.">
          Someone else approves it or sends it back.
        </Banner>
      ) : null}
      {po.status_reason ? (
        <Banner
          tone={po.status === "cancelled" ? "neutral" : "amber"}
          icon={po.status === "cancelled" ? "xCircle" : "info"}
          title={`${poStatus(po.status).label}, with this reason:`}
        >
          {po.status_reason}
        </Banner>
      ) : null}
      {late.length > 0 && shown !== "lines" ? (
        <Banner
          tone="amber"
          icon="clock"
          title={`${count(late.length, "line is", "lines are")} past the expected date.`}
          action={
            <ButtonLink href={viewHref(path, "lines")} variant="secondary" size="sm">
              See the lines
            </ButtonLink>
          }
        >
          Chase the vendor, or move the date once they give you a new one.
        </Banner>
      ) : null}

      {shown === "overview" ? <Overview po={po} outstanding={outstanding.length} leadLabel={lead?.label ?? null} billsHidden={billsHidden} /> : null}
      {shown === "lines" ? <PoLinesView po={po} /> : null}
      {shown === "receipts" ? <ReceiptsView po={po} onReceive={caps.receive?.allowed && !offline ? startReceiving : null} /> : null}
      {shown === "bills" ? <BillsView po={po} /> : null}

      <ReasonDialog
        isOpen={dialog === "reject"}
        onOpenChange={(open) => (open ? undefined : setDialog(null))}
        title="Send this purchase order back to draft"
        description="The buyer can change it and submit it again. They see your reason."
        reasonLabel="What needs to change"
        confirmLabel="Send back"
        cancelLabel="Keep it here"
        onConfirm={(reason) => must(act("reject", reason))}
      />
      <ReasonDialog
        isOpen={dialog === "cancel"}
        onOpenChange={(open) => (open ? undefined : setDialog(null))}
        title="Cancel this purchase order"
        description="Nothing more can be received or billed against it. It stays on record as cancelled."
        reasonLabel="Why it is cancelled"
        confirmLabel="Cancel purchase order"
        cancelLabel="Keep it open"
        tone="danger"
        onConfirm={(reason) => must(act("cancel", reason))}
      />
      <ReasonDialog
        isOpen={dialog === "closeShort"}
        onOpenChange={(open) => (open ? undefined : setDialog(null))}
        title="Close with goods still to come"
        description={`${count(outstanding.length, "line has", "lines have")} not fully arrived. Closing means nothing more is received against this order.`}
        reasonLabel="Why it is closed short"
        confirmLabel="Close purchase order"
        cancelLabel="Keep it open"
        onConfirm={(reason) => must(act("close", reason))}
      />
      <ConfirmDialog
        isOpen={dialog === "close"}
        onOpenChange={(open) => (open ? undefined : setDialog(null))}
        title="Close this purchase order"
        description="Everything ordered has arrived. Closing ends receiving against it."
        confirmLabel="Close purchase order"
        cancelLabel="Keep it open"
        onConfirm={() => must(act("close"))}
      />
      <ReceiveDrawer key={receiveAttempt} po={po} isOpen={receiving} onClose={() => setReceiving(false)} />
    </Page>
  );
}

// ---------------------------------------------------------------------------------------------
// Overview: from draft to goods on the floor

function progressOf(po: PoDetail): StepItem[] {
  const cancelled = po.status === "cancelled";
  const past = (statuses: string[]) => statuses.includes(po.status);
  const approved = po.approved_at !== null || past(["approved", "issued", "partially_received", "received"]);
  const sent = po.issued_at !== null || past(["issued", "partially_received", "received"]);
  const received = po.status === "received" || (po.status === "closed" && !po.lines.some((line) => isPositiveDecimalStr(line.qty_outstanding)));
  const raw: { id: string; label: string; hint: ReactNode; done: boolean }[] = [
    {
      id: "drafted",
      label: "Drafted",
      hint: <DateText value={po.order_date} style="business" />,
      done: true,
    },
    {
      id: "approved",
      label: "Approved",
      hint: po.approved_at ? <DateText value={po.approved_at} style="date" /> : po.status === "pending_approval" ? "Waiting for approval" : "By someone else",
      done: approved,
    },
    {
      id: "sent",
      label: "Sent to vendor",
      hint: po.issued_at ? <DateText value={po.issued_at} style="date" /> : "Marked once it has gone",
      done: sent,
    },
    {
      id: "received",
      label: "Received",
      hint: po.receipts.length > 0 ? count(po.receipts.length, "receipt", "receipts") : "Goods on the floor",
      done: received,
    },
  ];
  const stopped = cancelled || po.status === "closed";
  const current = stopped ? -1 : raw.findIndex((step) => !step.done);
  return raw.map((step, index) => ({
    id: step.id,
    label: step.label,
    hint: step.hint,
    state: step.done ? "done" : index === current ? "current" : "todo",
  }));
}

function standingOf(po: PoDetail, outstanding: number, leadLabel: string | null): { headline: ReactNode; body: ReactNode } {
  const next = leadLabel ? ` Next: ${leadLabel.toLowerCase()}.` : "";
  switch (po.status) {
    case "draft":
      return {
        headline: (
          <>
            A draft, not yet <em>submitted</em>
          </>
        ),
        body: `Check the lines and prices, then send it for approval.${next}`,
      };
    case "pending_approval":
      return {
        headline: (
          <>
            Waiting for <em>approval</em>
          </>
        ),
        body: `${po.submitted_by?.display_name ? `${po.submitted_by.display_name} submitted it. ` : ""}The person who submits a purchase order never approves it.${next}`,
      };
    case "approved":
      return {
        headline: (
          <>
            Approved. Now <em>send</em> it
          </>
        ),
        body: `Send the order to ${po.vendor.display_name}, then mark it as sent so receiving can begin.`,
      };
    case "issued":
      return {
        headline: (
          <>
            With the <em>vendor</em>
          </>
        ),
        body: po.next_expected_date ? (
          <>
            Nothing has arrived yet. The next delivery is due <DateText value={po.next_expected_date} style="business" />.
          </>
        ) : (
          "Nothing has arrived yet."
        ),
      };
    case "partially_received":
      return {
        headline: (
          <>
            Partly <em>received</em>
          </>
        ),
        body: `${count(outstanding, "line still has", "lines still have")} goods to come. The Lines view shows what is outstanding.${next}`,
      };
    case "received":
      return {
        headline: (
          <>
            Received in <em>full</em>
          </>
        ),
        body: "Everything ordered has arrived. Record the vendor's bill, then close the order.",
      };
    case "closed":
      return {
        headline: "Closed",
        body:
          outstanding > 0
            ? `Closed with ${count(outstanding, "line", "lines")} not fully received. Nothing more will arrive against it.`
            : "Nothing more will be received against this order.",
      };
    case "cancelled":
      return {
        headline: "Cancelled",
        body: "Nothing will be received or billed against this order.",
      };
    default:
      return { headline: poStatus(po.status).label, body: next.trim() };
  }
}

function Overview({ po, outstanding, leadLabel, billsHidden }: { po: PoDetail; outstanding: number; leadLabel: string | null; billsHidden: boolean }) {
  const standing = standingOf(po, outstanding, leadLabel);
  const inQc = po.lines.filter((line) => isPositiveDecimalStr(line.qty_pending_qc)).length;
  return (
    <Split
      main={
        <>
          <GlassPanel padding="lg" className="rise flex flex-col gap-6" eyebrow="Where it stands">
            <Steps label="Progress of this purchase order" steps={progressOf(po)} />
            <div className="flex max-w-prose flex-col gap-2">
              <h2 className="t-display-sm text-ink">{standing.headline}</h2>
              <p className="t-body text-ink-2">{standing.body}</p>
            </div>
          </GlassPanel>
          <section aria-label="Order value" className="lk-glass lk-glass-inverse rise flex min-w-0 flex-col gap-5 rounded-xl p-6">
            <div className="flex items-center justify-between gap-3">
              <h2 className="t-overline opacity-70">Order value</h2>
              <span className="t-caption lk-tnum opacity-70">
                {po.currency} · {count(po.lines.length, "line", "lines")}
              </span>
            </div>
            <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-1">
              <span className="t-label">Total</span>
              <span className="t-stat-xl ml-auto text-right">
                <Money value={{ amount: po.total_amount, currency: po.currency }} />
              </span>
            </div>
            <dl className="flex flex-wrap gap-x-8 gap-y-3 border-t border-on-inverse/20 pt-5">
              <div className="flex flex-col gap-0.5">
                <dt className="t-caption opacity-70">Still to arrive</dt>
                <dd className="t-label lk-tnum">{count(outstanding, "line", "lines")}</dd>
              </div>
              <div className="flex flex-col gap-0.5">
                <dt className="t-caption opacity-70">Waiting in QC</dt>
                <dd className="t-label lk-tnum">{count(inQc, "line", "lines")}</dd>
              </div>
              <div className="flex flex-col gap-0.5">
                <dt className="t-caption opacity-70">Receipts</dt>
                <dd className="t-label lk-tnum">{po.receipts.length}</dd>
              </div>
            </dl>
          </section>
        </>
      }
      aside={
        <>
          <GlassPanel padding="md" className="rise" title="Linked records" titleAs="h2">
            {!po.requisition && po.receipts.length === 0 && (billsHidden || po.bills.length === 0) ? (
              <p className="t-body-sm text-ink-3">Not raised from a requisition. Goods receipts and vendor bills are listed here as they come in.</p>
            ) : (
              <KeyValue
                rows
                items={[
                  {
                    label: "Requisition",
                    value: po.requisition ? (
                      <TextLink href={asRoute(po.requisition.path)}>
                        <Code>{po.requisition.number}</Code>
                      </TextLink>
                    ) : null,
                  },
                  ...po.receipts.map((receipt) => ({
                    label: "Goods receipt",
                    value: (
                      <TextLink href={asRoute(receipt.path)}>
                        <Code>{receipt.number}</Code>
                      </TextLink>
                    ),
                  })),
                  ...(billsHidden
                    ? []
                    : po.bills.map((bill) => ({
                        label: "Vendor bill",
                        value: (
                          <TextLink href={asRoute(`/operations/purchasing/orders/${po.id}?view=bills#bill-${bill.id}`)}>
                            <Code>{bill.number}</Code>
                          </TextLink>
                        ),
                      }))),
                ]}
              />
            )}
          </GlassPanel>
          <GlassPanel padding="md" className="rise" title="Details" titleAs="h2">
            <KeyValue
              rows
              items={[
                { label: "Vendor", value: po.vendor.display_name },
                { label: "Vendor reference", value: po.vendor_reference },
                {
                  label: "Deliver to",
                  value: `${po.warehouse.code} · ${po.warehouse.name}`,
                },
                { label: "Buyer", value: po.owner.display_name },
                { label: "Submitted by", value: po.submitted_by?.display_name },
                { label: "Approved by", value: po.approved_by?.display_name },
                { label: "Notes", value: po.notes },
              ]}
            />
          </GlassPanel>
        </>
      }
    />
  );
}

// ---------------------------------------------------------------------------------------------
// Receipts against this order

function ReceiptsView({ po, onReceive }: { po: PoDetail; onReceive: (() => void) | null }) {
  return (
    <div className="stack">
      <div className="flex min-w-0 flex-wrap items-end justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-1">
          <h2 className="t-h3">Goods receipts</h2>
          <p className="t-body-sm text-ink-3">Each delivery against this order. Open one for its lots, locations and inspections.</p>
        </div>
      </div>
      <GlassPanel padding={po.receipts.length === 0 ? "md" : "none"} className="rise min-w-0">
        {po.receipts.length === 0 ? (
          <EmptyState
            compact
            icon="packageOpen"
            title="Nothing received yet"
            text={onReceive ? "When the goods arrive, record what came in and it is added to stock." : "A receipt is listed here each time goods arrive against this order."}
            actions={
              onReceive ? (
                <Button variant="inverse" iconLeft="packageOpen" onPress={onReceive}>
                  Receive goods
                </Button>
              ) : null
            }
          />
        ) : (
          <ul className="flex flex-col">
            {po.receipts.map((receipt, index) => (
              <li
                key={receipt.id}
                className="rise-plain relative flex min-w-0 flex-wrap items-center justify-between gap-3 border-t border-line px-5 py-4 first:border-t-0"
                style={stagger(index)}
              >
                <TextLink href={asRoute(receipt.path)} className="stretched">
                  <Code>{receipt.number}</Code>
                </TextLink>
                <StatusBadge look={receiptStatus(receipt.status)} size="sm" />
              </li>
            ))}
          </ul>
        )}
      </GlassPanel>
    </div>
  );
}
