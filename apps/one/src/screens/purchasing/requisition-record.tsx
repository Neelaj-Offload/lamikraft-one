"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useMemo, useState, type ReactNode } from "react";
import { useRolePartySearch } from "@/features/challans/pickers";
import { useCommand } from "@/features/inventory/use-command";
import { convertRequisition, fetchRequisition, requisitionAction, type RequisitionAction, type RequisitionDetail } from "@/features/procurement/api";
import { queryKeys } from "@/lib/api/query-keys";
import { isPositiveDecimalStr } from "@/lib/format/decimal";
import { Steps, type StepItem } from "~/screens/sales/quotations/parts";
import { Page, RecordHeader, Split } from "~/shell/page";
import {
  Banner,
  Button,
  Code,
  ComboBox,
  DataTable,
  DateText,
  DecimalField,
  EmptyState,
  FactStrip,
  GlassPanel,
  KeyValue,
  Menu,
  Modal,
  Qty,
  ReasonDialog,
  Tabs,
  TextLink,
  type Column,
  type IconName,
  type MenuItem,
} from "~/ui";
import { count, FAILED, poStatus, requisitionStatus } from "./labels";
import { LineName, must, OfflineBanner, RecordFailure, RecordLoading, StatusBadge } from "./parts";
import { asRoute, viewHref, type RequisitionView } from "./views";

type Line = RequisitionDetail["lines"][number];

/** A requisition: where it stands on the way to a purchase order, and its lines. */
export function RequisitionRecord({ requisitionId, view }: { requisitionId: string; view: RequisitionView }) {
  const query = useQuery({ queryKey: queryKeys.procurement.requisition(requisitionId), queryFn: ({ signal }) => fetchRequisition(requisitionId, signal) });
  if (query.isPending) return <RecordLoading label="Loading the requisition" />;
  if (query.isError) {
    return <RecordFailure error={query.error} what="This requisition" retry={() => void query.refetch()} backHref="/operations/purchasing/requisitions" backLabel="All requisitions" />;
  }
  return <Loaded r={query.data} view={view} />;
}

type Step = { id: string; label: string; icon: IconName; pendingName: string; run: () => void };

function Loaded({ r, view }: { r: RequisitionDetail; view: RequisitionView }) {
  const router = useRouter();
  const key = useMemo(() => queryKeys.procurement.requisition(r.id), [r.id]);
  const { run, pending, offline } = useCommand<RequisitionDetail>(key);
  const [dialog, setDialog] = useState<null | "reject" | "cancel">(null);
  const [converting, setConverting] = useState(false);
  const [convertAttempt, setConvertAttempt] = useState(0);
  const caps = r.capabilities;
  const path = `/operations/purchasing/requisitions/${r.id}`;
  const openLines = r.lines.filter((line) => isPositiveDecimalStr(line.qty_remaining));

  const act = (action: RequisitionAction, done: string, note?: string) =>
    run(action, (k) => requisitionAction(r, action, k, note), { done, failed: FAILED, write: (next) => next });

  // The forward steps in the order they happen; the first one available leads.
  const steps: Step[] = [];
  if (caps.submit?.allowed) steps.push({ id: "submit", label: "Submit for approval", icon: "send", pendingName: "submit", run: () => void act("submit", "Submitted for approval") });
  if (caps.approve?.allowed) steps.push({ id: "approve", label: "Approve", icon: "check", pendingName: "approve", run: () => void act("approve", "Requisition approved") });
  if (caps.convert?.allowed) {
    steps.push({
      id: "convert",
      label: "Create purchase order",
      icon: "filePlus",
      pendingName: "convert",
      run: () => {
        setConvertAttempt((n) => n + 1);
        setConverting(true);
      },
    });
  }
  const [lead, ...others] = steps;

  const menu: MenuItem[] = others.map((step) => ({ id: step.id, label: step.label, icon: step.icon, isDisabled: Boolean(offline), onAction: step.run }));
  if (caps.cancel?.allowed) {
    if (menu.length > 0) menu.push({ id: "sep", separator: true });
    menu.push({ id: "cancel", label: "Cancel requisition", icon: "xCircle", tone: "danger", isDisabled: Boolean(offline), onAction: () => setDialog("cancel") });
  }

  return (
    <Page>
      <RecordHeader
        breadcrumb={[{ label: "Operations", href: "/operations" }, { label: "Requisitions", href: "/operations/purchasing/requisitions" }, { label: r.requisition_number }]}
        code={r.requisition_number}
        title={`For ${r.warehouse.name}`}
        status={<StatusBadge look={requisitionStatus(r.status)} />}
        lead={
          <>
            Raised by {r.owner.display_name ?? "someone no longer listed"} on <DateText value={r.created_at} style="date" />.
          </>
        }
        facts={
          <FactStrip
            items={[
              { label: "Needed by", icon: "calendar", value: r.required_by ? <DateText value={r.required_by} style="business" /> : null },
              { label: "Lines", icon: "list", value: r.line_count },
              { label: "Still to order", icon: "cart", value: count(openLines.length, "line", "lines") },
              { label: "Deliver to", icon: "warehouse", value: r.warehouse.code },
              { label: "Decided by", icon: "user", value: r.decided_by?.display_name },
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
            {caps.reject?.allowed ? (
              <Button variant="secondary" iconLeft="thumbsDown" isDisabled={Boolean(offline)} onPress={() => setDialog("reject")}>
                Reject
              </Button>
            ) : null}
            {menu.length > 0 ? (
              <Menu
                label="More requisition actions"
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
          label="Views of this requisition"
          selectedKey={view}
          tabs={[
            { id: "overview", label: "Overview", href: viewHref(path, "overview") },
            { id: "lines", label: "Lines", count: r.lines.length, href: viewHref(path, "lines") },
          ]}
        />
      </RecordHeader>

      {offline ? <OfflineBanner what="this requisition" /> : null}
      {caps.approve?.reason_code === "approver_is_requester" ? (
        <Banner tone="cobalt" icon="users" title="You cannot decide your own request.">
          Someone other than the person who raised or submitted this requisition approves or rejects it.
        </Banner>
      ) : null}
      {(r.status === "rejected" || r.status === "cancelled") && r.decision_note ? (
        <Banner tone={r.status === "rejected" ? "ember" : "neutral"} icon="xCircle" title={`${r.status === "rejected" ? "Rejected" : "Cancelled"}${r.decided_by?.display_name ? ` by ${r.decided_by.display_name}` : ""}.`}>
          {r.decision_note}
        </Banner>
      ) : null}

      {view === "overview" ? <Overview r={r} openLines={openLines.length} leadLabel={lead?.label ?? null} /> : null}
      {view === "lines" ? <LinesView r={r} /> : null}

      <ReasonDialog
        isOpen={dialog === "reject"}
        onOpenChange={(open) => (open ? undefined : setDialog(null))}
        title="Reject this requisition"
        description="Nothing is ordered. The person who raised it sees your reason."
        reasonLabel="Why it is rejected"
        confirmLabel="Reject requisition"
        cancelLabel="Keep it open"
        tone="danger"
        onConfirm={(reason) => must(act("reject", "Requisition rejected", reason))}
      />
      <ReasonDialog
        isOpen={dialog === "cancel"}
        onOpenChange={(open) => (open ? undefined : setDialog(null))}
        title="Cancel this requisition"
        description="It stays on record as cancelled and can no longer become a purchase order."
        reasonLabel="Why it is cancelled"
        confirmLabel="Cancel requisition"
        cancelLabel="Keep it open"
        tone="danger"
        onConfirm={(reason) => must(act("cancel", "Requisition cancelled", reason))}
      />
      <ConvertDialog
        key={convertAttempt}
        r={r}
        openLines={openLines}
        isOpen={converting}
        onClose={() => setConverting(false)}
        onConvert={async (vendorId, prices) => {
          const po = await run("convert", (k) => convertRequisition(r, vendorId, prices, k), { done: "Draft purchase order created", failed: FAILED });
          if (po) router.push(asRoute(po.path));
          return po !== null;
        }}
      />
    </Page>
  );
}

// ---------------------------------------------------------------------------------------------
// Overview: from request to purchase order

function progressOf(r: RequisitionDetail): StepItem[] {
  const stopped = r.status === "rejected" || r.status === "cancelled";
  const submitted = r.submitted_at !== null || r.status === "submitted" || r.status === "approved" || r.status === "closed" || r.status === "rejected";
  const approved = r.status === "approved" || r.status === "closed";
  const ordered = r.status === "closed";
  const orders = r.purchase_orders.length;
  const raw: { id: string; label: string; hint: ReactNode; done: boolean }[] = [
    { id: "raised", label: "Raised", hint: <DateText value={r.created_at} style="date" />, done: true },
    { id: "submitted", label: "Submitted", hint: r.submitted_at ? <DateText value={r.submitted_at} style="date" /> : "Sent for approval", done: submitted },
    { id: "approved", label: "Approved", hint: approved && r.decided_at ? <DateText value={r.decided_at} style="date" /> : "By someone else", done: approved },
    { id: "ordered", label: "Ordered", hint: orders > 0 ? count(orders, "purchase order", "purchase orders") : "On a purchase order", done: ordered },
  ];
  const current = stopped ? -1 : raw.findIndex((step) => !step.done);
  return raw.map((step, index) => ({ id: step.id, label: step.label, hint: step.hint, state: step.done ? "done" : index === current ? "current" : "todo" }));
}

function standingOf(r: RequisitionDetail, openLines: number, leadLabel: string | null): { headline: ReactNode; body: string } {
  const next = leadLabel ? ` Next: ${leadLabel.toLowerCase()}.` : "";
  switch (r.status) {
    case "draft":
      return { headline: <>Not yet <em>submitted</em></>, body: `Check the lines, then send it for approval. Nothing is ordered until someone approves it.${next}` };
    case "submitted":
      return { headline: <>Waiting for <em>approval</em></>, body: `${r.submitted_by?.display_name ? `${r.submitted_by.display_name} submitted it. ` : ""}Someone other than the requester decides it.${next}` };
    case "approved":
      return openLines > 0
        ? { headline: <>Approved. Now <em>order</em> it</>, body: `${count(openLines, "line still needs", "lines still need")} a purchase order. Choose the vendor and a draft order is made from them.` }
        : { headline: <>Approved and <em>ordered</em></>, body: "Every line is on a purchase order." };
    case "closed":
      return { headline: <>Fully <em>ordered</em></>, body: "Every line is on a purchase order. Follow the delivery there." };
    case "rejected":
      return { headline: "Rejected", body: "Nothing was ordered. Raise a new requisition if the material is still needed." };
    case "cancelled":
      return { headline: "Cancelled", body: "Nothing more will be ordered from this requisition." };
    default:
      return { headline: requisitionStatus(r.status).label, body: next.trim() };
  }
}

function Overview({ r, openLines, leadLabel }: { r: RequisitionDetail; openLines: number; leadLabel: string | null }) {
  const standing = standingOf(r, openLines, leadLabel);
  return (
    <Split
      main={
        <>
          <GlassPanel padding="lg" className="rise flex flex-col gap-6" eyebrow="Where it stands">
            <Steps label="Progress of this requisition" steps={progressOf(r)} />
            <div className="flex max-w-prose flex-col gap-2">
              <h2 className="t-display-sm text-ink">{standing.headline}</h2>
              <p className="t-body text-ink-2">{standing.body}</p>
            </div>
          </GlassPanel>
          <GlassPanel padding="md" className="rise" title="Purchase orders made from it" titleAs="h2">
            {r.purchase_orders.length === 0 ? (
              <p className="t-body-sm text-ink-3">None yet. A purchase order appears here once the requisition is approved and ordered.</p>
            ) : (
              <ul className="flex flex-col">
                {r.purchase_orders.map((po) => (
                  <li key={po.id} className="flex min-w-0 flex-wrap items-center justify-between gap-3 border-t border-line py-3 first:border-t-0 first:pt-0 last:pb-0">
                    <TextLink href={asRoute(po.path)}>
                      <Code>{po.number}</Code>
                    </TextLink>
                    <StatusBadge look={poStatus(po.status)} size="sm" />
                  </li>
                ))}
              </ul>
            )}
          </GlassPanel>
        </>
      }
      aside={
        <GlassPanel padding="md" className="rise" title="Details" titleAs="h2">
          <KeyValue
            rows
            items={[
              { label: "Deliver to", value: `${r.warehouse.code} · ${r.warehouse.name}` },
              { label: "Needed by", value: r.required_by ? <DateText value={r.required_by} style="business" /> : null },
              { label: "Raised by", value: r.owner.display_name },
              { label: "Submitted by", value: r.submitted_by?.display_name },
              { label: "Decided by", value: r.decided_by?.display_name },
              { label: "Decision note", value: r.decision_note },
              { label: "Notes", value: r.notes },
            ]}
          />
        </GlassPanel>
      }
    />
  );
}

// ---------------------------------------------------------------------------------------------
// Lines

function LinesView({ r }: { r: RequisitionDetail }) {
  const qty = (value: string, unit: string) => <Qty value={{ value, uom: unit }} />;
  const columns: Column<Line>[] = [
    { key: "item", header: "Line", primary: true, cell: (line) => <LineName lineNo={line.line_no} name={line.product.name} productKey={line.product.product_key} note={line.notes} /> },
    { key: "quantity", header: "Needed", numeric: true, cell: (line) => qty(line.quantity, line.unit) },
    { key: "ordered", header: "Ordered", numeric: true, cell: (line) => qty(line.qty_ordered, line.unit) },
    {
      key: "remaining",
      header: "Still to order",
      numeric: true,
      cell: (line) => <span className={isPositiveDecimalStr(line.qty_remaining) ? "t-label text-ink" : "text-ink-3"}>{qty(line.qty_remaining, line.unit)}</span>,
    },
    { key: "required", header: "Needed by", hideOnMobile: true, cell: (line) => <DateText value={line.required_by} style="business" /> },
  ];
  return (
    <div className="stack">
      <div className="flex min-w-0 flex-col gap-1">
        <h2 className="t-h3">Lines</h2>
        <p className="t-body-sm text-ink-3">What was asked for, how much of it is already on a purchase order, and what is left to order.</p>
      </div>
      <GlassPanel padding="none" className="rise min-w-0">
        <DataTable
          label={`Lines of ${r.requisition_number}`}
          columns={columns}
          rows={r.lines}
          rowKey={(line) => line.id}
          empty={<EmptyState compact icon="list" title="This requisition has no lines" text="It was raised without any products." />}
        />
      </GlassPanel>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------
// Convert to a purchase order

function ConvertDialog({
  r,
  openLines,
  isOpen,
  onClose,
  onConvert,
}: {
  r: RequisitionDetail;
  openLines: Line[];
  isOpen: boolean;
  onClose: () => void;
  onConvert: (vendorId: string, prices: Record<string, string>) => Promise<boolean>;
}) {
  const [text, setText] = useState("");
  const [vendor, setVendor] = useState<{ id: string; label: string; description?: string } | null>(null);
  const [prices, setPrices] = useState<Record<string, string>>({});
  const [error, setError] = useState(false);
  const [busy, setBusy] = useState(false);
  const vendors = useRolePartySearch(text, "vendor");
  const found = (vendors.data ?? []).map((party) => ({ id: party.id, label: party.display_name, description: party.party_number }));
  const options = [...(vendor ? [vendor] : []), ...found.filter((option) => option.id !== vendor?.id)];
  const close = () => {
    if (!busy) onClose();
  };
  const confirm = async () => {
    if (!vendor) {
      setError(true);
      return;
    }
    setBusy(true);
    try {
      if (await onConvert(vendor.id, Object.fromEntries(Object.entries(prices).filter(([, price]) => price !== "")))) onClose();
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      isOpen={isOpen}
      onOpenChange={(open) => (open ? undefined : close())}
      title="Create a purchase order"
      description={`A draft order is made from the ${count(openLines.length, "line", "lines")} of ${r.requisition_number} still to order. You check it before it goes for approval.`}
      actions={
        <>
          <Button variant="ghost" onPress={close} isDisabled={busy}>
            Not now
          </Button>
          <Button loading={busy} onPress={() => void confirm()}>
            Create purchase order
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-5">
        <ComboBox
          label="Vendor"
          placeholder="Type a vendor's name or number"
          items={options}
          inputValue={text}
          onInputChange={setText}
          selectedKey={vendor?.id ?? null}
          onSelectionChange={(id) => {
            const next = options.find((option) => option.id === id) ?? null;
            setVendor(next);
            if (next) {
              setText(next.label);
              setError(false);
            }
          }}
          isLoading={vendors.isFetching}
          emptyText={text.trim().length < 2 ? "Type at least two letters" : "No vendor matches. Check the spelling, or add the vendor first."}
          isRequired
          error={error ? "Choose the vendor this order goes to. Type at least two letters of their name." : undefined}
        />
        {openLines.length > 0 ? (
          <fieldset className="flex min-w-0 flex-col gap-4">
            <legend className="mb-1 flex flex-col gap-1">
              <span className="t-h4 text-ink">Unit prices</span>
              <span className="t-body-sm text-ink-3">Only needed where the vendor has no price on file for the product. Leave the rest empty.</span>
            </legend>
            {openLines.map((line) => (
              <DecimalField
                key={line.id}
                label={line.product.name}
                optional
                help={`${line.product.product_key} · per ${line.unit}`}
                value={prices[line.id] ?? ""}
                onChange={(value) => setPrices((all) => ({ ...all, [line.id]: value }))}
              />
            ))}
          </fieldset>
        ) : null}
      </div>
    </Modal>
  );
}
