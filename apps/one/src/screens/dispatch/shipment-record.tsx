"use client";

import { useQuery } from "@tanstack/react-query";
import { useId, useMemo, useState, type ReactNode } from "react";
import { useCommand } from "@/features/inventory/use-command";
import {
  addTrackingRef,
  fetchPackingLists,
  fetchShipment,
  linkShipment,
  TRACKING_TYPES,
  transitionShipment,
  type EvidenceKind,
  type ExceptionCode,
  type ShipmentAction,
  type ShipmentDetail,
  type TrackingRefType,
} from "@/features/logistics/api";
import { fetchOrder } from "@/features/orders/api";
import { queryKeys } from "@/lib/api/query-keys";
import {
  asRoute,
  EVIDENCE_KINDS,
  EXCEPTION_CODES,
  evidenceLabel,
  exceptionLabel,
  FAILED,
  MODE_ICON,
  MODE_LABEL,
  packingStatus,
  TRACKING_LABEL,
} from "~/data/dispatch";
import { Steps, type StepItem } from "~/screens/sales/quotations/parts";
import { Page, RecordHeader, Split } from "~/shell/page";
import { ErrorBlock, LoadingBlock } from "~/shell/states";
import {
  Banner,
  Button,
  ButtonLink,
  Code,
  DateText,
  EmptyState,
  FactStrip,
  GlassPanel,
  KeyValue,
  Menu,
  Modal,
  ReasonDialog,
  Select,
  Skeleton,
  SkeletonText,
  Tabs,
  Textarea,
  TextField,
  TextLink,
  type IconName,
  type MenuItem,
} from "~/ui";
import { Cutoff, pastCutoff, ShipmentStatusBadge, stagger } from "./parts";
import { viewHref, type ShipmentView } from "./views";

/** A shipment: where it stands on the way to the customer, its documents and its tracking references. */
export function ShipmentRecord({ shipmentId, view }: { shipmentId: string; view: ShipmentView }) {
  const query = useQuery({ queryKey: queryKeys.logistics.shipment(shipmentId), queryFn: ({ signal }) => fetchShipment(shipmentId, signal) });
  if (query.isPending) {
    return (
      <Page>
        <div className="lk-glass record-head" role="status" aria-label="Loading the shipment">
          <Skeleton width="140px" height={14} />
          <Skeleton width="45%" height={32} />
          <SkeletonText lines={2} />
        </div>
        <LoadingBlock lines={6} label="Loading the shipment" />
      </Page>
    );
  }
  if (query.isError) {
    return (
      <Page>
        <ErrorBlock error={query.error} what="This shipment" onRetry={() => void query.refetch()} />
        <div>
          <ButtonLink href="/operations/dispatch" variant="secondary" iconLeft="arrowLeft">
            All shipments
          </ButtonLink>
        </div>
      </Page>
    );
  }
  return <Loaded shipment={query.data} view={view} />;
}

const FORWARD: { action: ShipmentAction; label: string; icon: IconName; done: string }[] = [
  { action: "book", label: "Mark booked", icon: "calendar", done: "Shipment booked" },
  { action: "dispatch", label: "Dispatch", icon: "truck", done: "Dispatched. The challan is issued." },
  { action: "in_transit", label: "Mark in transit", icon: "route", done: "Marked in transit" },
  { action: "deliver", label: "Record delivery", icon: "checkCircle", done: "Delivery recorded" },
  { action: "resolve_exception", label: "Resolve exception", icon: "check", done: "Exception resolved" },
];

function Loaded({ shipment, view }: { shipment: ShipmentDetail; view: ShipmentView }) {
  const key = useMemo(() => queryKeys.logistics.shipment(shipment.id), [shipment.id]);
  const { run, pending, offline } = useCommand<ShipmentDetail>(key);
  const [dialog, setDialog] = useState<null | "deliver" | "record_exception" | "cancel">(null);
  const caps = shipment.capabilities;
  const path = `/operations/dispatch/shipments/${shipment.id}`;

  const transition = (action: ShipmentAction, done: string, extras = {}) =>
    run(action, (k) => transitionShipment(shipment, action, extras, k), { done, failed: FAILED, write: (x) => x });

  const forward = FORWARD.filter((step) => caps[step.action]?.allowed);
  const press = (action: ShipmentAction, done: string) => (action === "deliver" ? setDialog("deliver") : void transition(action, done));
  const [lead, second, ...others] = forward;

  const menu: MenuItem[] = others.map((step) => ({ id: step.action, label: step.label, icon: step.icon, isDisabled: Boolean(offline), onAction: () => press(step.action, step.done) }));
  if (caps.record_exception?.allowed) {
    menu.push({ id: "record_exception", label: "Record an exception", icon: "alert", description: "Delayed, damaged, lost or refused", isDisabled: Boolean(offline), onAction: () => setDialog("record_exception") });
  }
  if (caps.cancel?.allowed) {
    if (menu.length > 0) menu.push({ id: "sep", separator: true });
    menu.push({ id: "cancel", label: "Cancel shipment", icon: "xCircle", tone: "danger", isDisabled: Boolean(offline), onAction: () => setDialog("cancel") });
  }

  const challanNeeded = caps.dispatch?.reason_code === "challan_required";

  return (
    <Page>
      <RecordHeader
        breadcrumb={[{ label: "Operations", href: "/operations" }, { label: "Dispatch", href: "/operations/dispatch" }, { label: shipment.shipment_number }]}
        code={shipment.shipment_number}
        title={shipment.party_name}
        status={<ShipmentStatusBadge status={shipment.status} />}
        lead={
          <>
            {MODE_LABEL[shipment.mode] ?? shipment.mode}
            {shipment.transporter_name ? ` with ${shipment.transporter_name}` : ""}
            {shipment.order ? (
              <>
                {", for order "}
                <TextLink href={asRoute(shipment.order.path)}>{shipment.order.number}</TextLink>
              </>
            ) : null}
            .
          </>
        }
        facts={
          <FactStrip
            items={[
              { label: "Cutoff", icon: "clock", value: shipment.cutoff_at ? <Cutoff shipment={shipment} /> : null },
              { label: "Mode", icon: MODE_ICON[shipment.mode] ?? "truck", value: MODE_LABEL[shipment.mode] ?? shipment.mode },
              { label: "Planned dispatch", icon: "calendar", value: shipment.planned_dispatch_date ? <DateText value={shipment.planned_dispatch_date} style="business" /> : null },
              { label: "Challan", icon: "fileText", value: shipment.challan ? <Code>{shipment.challan.number}</Code> : null },
              { label: "Tracking", icon: "hash", value: shipment.tracking_refs.length > 0 ? <span className="lk-tnum">{shipment.tracking_refs.length}</span> : null },
            ]}
          />
        }
        actions={
          <>
            {lead ? (
              <Button iconLeft={lead.icon} loading={pending === lead.action} isDisabled={Boolean(offline)} onPress={() => press(lead.action, lead.done)}>
                {lead.label}
              </Button>
            ) : null}
            {second ? (
              <Button variant="secondary" iconLeft={second.icon} loading={pending === second.action} isDisabled={Boolean(offline)} onPress={() => press(second.action, second.done)}>
                {second.label}
              </Button>
            ) : null}
            {menu.length > 0 ? (
              <Menu
                label="More shipment actions"
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
          label="Views of this shipment"
          selectedKey={view}
          tabs={[
            { id: "overview", label: "Overview", href: asRoute(path) },
            { id: "documents", label: "Challan and packing list", href: asRoute(viewHref(path, "documents")) },
            { id: "tracking", label: "Tracking", count: shipment.tracking_refs.length, href: asRoute(viewHref(path, "tracking")) },
          ]}
        />
      </RecordHeader>

      {offline ? (
        <Banner tone="amber" title="You are offline.">
          You can read this shipment. Actions work again once the connection is back.
        </Banner>
      ) : null}
      {challanNeeded ? (
        <Banner
          tone="amber"
          icon="fileText"
          title="Link the delivery challan before dispatch."
          action={
            view !== "documents" ? (
              <ButtonLink href={asRoute(viewHref(path, "documents"))} variant="secondary" size="sm">
                Link documents
              </ButtonLink>
            ) : undefined
          }
        >
          Dispatching issues that challan, and that is when the stock leaves.
        </Banner>
      ) : null}
      {pastCutoff(shipment) ? (
        <Banner tone="ember" icon="clock" title="The cutoff has passed.">
          {shipment.cutoff_local ? `It was ${shipment.cutoff_local}, company time.` : "The goods are still here."}
        </Banner>
      ) : null}
      {shipment.exception_code ? (
        <Banner tone="ember" title={`Exception: ${(exceptionLabel(shipment.exception_code) ?? "").toLowerCase()}.`}>
          {shipment.exception_note ?? "No note was recorded."}
          {shipment.exception_at ? (
            <>
              {" Recorded "}
              <DateText value={shipment.exception_at} style="dayTime" />.
            </>
          ) : null}
        </Banner>
      ) : null}

      {view === "overview" ? <Overview shipment={shipment} leadLabel={lead?.label ?? null} /> : null}
      {view === "documents" ? <DocumentsView shipment={shipment} /> : null}
      {view === "tracking" ? <TrackingView shipment={shipment} /> : null}

      <DeliverModal shipment={shipment} isOpen={dialog === "deliver"} onClose={() => setDialog(null)} />
      <ExceptionModal shipment={shipment} isOpen={dialog === "record_exception"} onClose={() => setDialog(null)} />
      <ReasonDialog
        isOpen={dialog === "cancel"}
        onOpenChange={(open) => (open ? undefined : setDialog(null))}
        tone="danger"
        title={`Cancel ${shipment.shipment_number}?`}
        description="The shipment leaves the dispatch board. The order stays as it is."
        confirmLabel="Cancel shipment"
        cancelLabel="Keep it"
        reasonHelp="Kept with the shipment for the record."
        onConfirm={async (reason) => {
          const result = await transition("cancel", "Shipment cancelled", { reason });
          if (!result) throw new Error("not cancelled");
        }}
      />
    </Page>
  );
}

// ---------------------------------------------------------------------------------------------
// Overview

const ORDER = ["planned", "booked", "dispatched", "in_transit", "delivered"] as const;

function progressOf(shipment: ShipmentDetail): StepItem[] {
  const reached = shipment.delivered_at
    ? 4
    : shipment.status === "in_transit"
      ? 3
      : shipment.dispatched_at || shipment.status === "dispatched"
        ? 2
        : shipment.status === "booked"
          ? 1
          : Math.max(0, ORDER.indexOf(shipment.status as (typeof ORDER)[number]));
  const cancelled = shipment.status === "cancelled";
  const steps: { id: string; label: string; hint: ReactNode }[] = [
    { id: "planned", label: "Planned", hint: shipment.cutoff_local ? `Cutoff ${shipment.cutoff_local}` : "No cutoff set" },
    { id: "booked", label: "Booked", hint: shipment.transporter_name ?? "With the carrier" },
    { id: "dispatched", label: "Dispatched", hint: shipment.dispatched_at ? <DateText value={shipment.dispatched_at} style="date" /> : "Challan issued" },
    { id: "in_transit", label: "In transit", hint: shipment.tracking_refs[0]?.value ?? "On the way" },
    { id: "delivered", label: "Delivered", hint: shipment.delivered_at ? <DateText value={shipment.delivered_at} style="date" /> : "With evidence" },
  ];
  return steps.map((step, index) => ({
    id: step.id,
    label: step.label,
    hint: step.hint,
    state: cancelled ? "todo" : index < reached || (index === 4 && reached === 4) ? "done" : index === reached ? "current" : "todo",
  }));
}

function standingOf(shipment: ShipmentDetail, leadLabel: string | null): { headline: ReactNode; body: string } {
  const next = leadLabel ? ` Next: ${leadLabel.toLowerCase()}.` : "";
  switch (shipment.status) {
    case "cancelled":
      return { headline: "Cancelled", body: "This shipment is off the dispatch board." };
    case "delivered":
      return { headline: <>Delivered to the <em>customer</em></>, body: shipment.evidence_kind ? `Evidence: ${(evidenceLabel(shipment.evidence_kind) ?? "").toLowerCase()}.` : "The delivery is on record." };
    case "exception":
      return { headline: <>Something went <em>wrong</em></>, body: `Resolve the exception once it is sorted out with the carrier or the customer.${next}` };
    case "in_transit":
      return { headline: <>On the <em>road</em></>, body: `The goods have left and are on their way.${next}` };
    case "dispatched":
      return { headline: <>Dispatched</>, body: `The challan is issued and the stock has left the warehouse.${next}` };
    case "booked":
      return { headline: <>Booked with the <em>carrier</em></>, body: `Dispatch issues the linked challan, which moves the stock.${next}` };
    default:
      return { headline: <>Planned, waiting to <em>go</em></>, body: `Book the carrier, link the challan, then dispatch before the cutoff.${next}` };
  }
}

function Overview({ shipment, leadLabel }: { shipment: ShipmentDetail; leadLabel: string | null }) {
  const standing = standingOf(shipment, leadLabel);
  return (
    <Split
      main={
        <>
          <GlassPanel padding="lg" className="rise flex flex-col gap-6" eyebrow="Where it stands">
            <Steps label="Progress of this shipment" steps={progressOf(shipment)} />
            <div className="flex max-w-prose flex-col gap-2">
              <h2 className="t-display-sm text-ink">{standing.headline}</h2>
              <p className="t-body text-ink-2">{standing.body}</p>
            </div>
          </GlassPanel>
          <GlassPanel padding="md" className="rise" style={stagger(1)} title="On the way" titleAs="h2">
            <KeyValue
              rows
              items={[
                { label: "Cutoff", value: shipment.cutoff_at ? <Cutoff shipment={shipment} className="justify-end" /> : "None set" },
                { label: "Planned dispatch", value: shipment.planned_dispatch_date ? <DateText value={shipment.planned_dispatch_date} style="business" /> : null },
                { label: "Dispatched", value: shipment.dispatched_at ? <DateText value={shipment.dispatched_at} style="dayTime" /> : null },
                { label: "Delivered", value: shipment.delivered_at ? <DateText value={shipment.delivered_at} style="dayTime" /> : null },
                { label: "Evidence", value: shipment.evidence_kind ? [evidenceLabel(shipment.evidence_kind), shipment.evidence_note].filter(Boolean).join(" · ") : null },
              ]}
            />
          </GlassPanel>
        </>
      }
      aside={
        <>
          <GlassPanel padding="md" className="rise" title="Linked records" titleAs="h2">
            <KeyValue
              rows
              items={[
                { label: "Order", value: shipment.order ? <TextLink href={asRoute(shipment.order.path)}>{shipment.order.number}</TextLink> : null },
                {
                  label: "Challan",
                  value: shipment.challan ? (
                    <span className="flex flex-col items-end gap-0.5">
                      <TextLink href={asRoute(shipment.challan.path)}>{shipment.challan.number}</TextLink>
                      <span className="t-caption text-ink-3">{shipment.challan.status.replace(/_/g, " ")}</span>
                    </span>
                  ) : null,
                },
                { label: "Packing list", value: shipment.packing_list ? <TextLink href={asRoute(shipment.packing_list.path)}>{shipment.packing_list.number}</TextLink> : null },
                { label: "Transporter", value: shipment.transporter_name },
              ]}
            />
          </GlassPanel>
          {shipment.notes ? (
            <GlassPanel padding="md" className="rise" title="Notes" titleAs="h2">
              <p className="t-body-sm whitespace-pre-line text-ink-2">{shipment.notes}</p>
            </GlassPanel>
          ) : null}
        </>
      }
    />
  );
}

// ---------------------------------------------------------------------------------------------
// Challan and packing list

function DocumentsView({ shipment }: { shipment: ShipmentDetail }) {
  const canLink = shipment.capabilities.update?.allowed === true && shipment.order !== null;
  return (
    <Split
      main={
        canLink && shipment.order ? (
          <LinkDocuments shipment={shipment} orderId={shipment.order.id} />
        ) : (
          <GlassPanel padding="lg" className="rise" title="Linked to this shipment" titleAs="h2">
            <KeyValue
              rows
              items={[
                { label: "Delivery challan", value: shipment.challan ? <TextLink href={asRoute(shipment.challan.path)}>{shipment.challan.number}</TextLink> : null },
                { label: "Packing list", value: shipment.packing_list ? <TextLink href={asRoute(shipment.packing_list.path)}>{shipment.packing_list.number}</TextLink> : null },
              ]}
            />
            <p className="t-caption mt-4 text-ink-3">
              {shipment.order ? "Changing the links is not open for this shipment." : "This shipment has no sales order, so there is nothing to link."}
            </p>
          </GlassPanel>
        )
      }
      aside={
        <GlassPanel padding="md" className="rise" title="Why the challan matters" titleAs="h2">
          <p className="t-body-sm text-ink-2">Dispatch issues the linked draft challan. That is the one stock movement for this shipment, so link the right one before the goods leave.</p>
        </GlassPanel>
      }
    />
  );
}

function LinkDocuments({ shipment, orderId }: { shipment: ShipmentDetail; orderId: string }) {
  const key = useMemo(() => queryKeys.logistics.shipment(shipment.id), [shipment.id]);
  const { run, pending, offline } = useCommand<ShipmentDetail>(key);
  const order = useQuery({ queryKey: queryKeys.orders.order(orderId), queryFn: ({ signal }) => fetchOrder(orderId, signal) });
  const lists = useQuery({
    queryKey: queryKeys.logistics.packingLists({ sales_order_id: orderId }),
    queryFn: ({ signal }) => fetchPackingLists({ salesOrderId: orderId }, signal),
  });
  const challans = (order.data?.documents ?? []).filter((doc) => doc.kind === "challan" && doc.status !== "cancelled");
  const packing = (lists.data?.items ?? []).filter((list) => list.status !== "cancelled");
  const [challan, setChallan] = useState<string | null>(shipment.challan?.id ?? null);
  const [packingList, setPackingList] = useState<string | null>(shipment.packing_list?.id ?? null);
  const changed = Boolean((challan && challan !== shipment.challan?.id) || (packingList && packingList !== shipment.packing_list?.id));

  const save = () =>
    void run(
      "link",
      (k) =>
        linkShipment(
          shipment,
          {
            ...(challan && challan !== shipment.challan?.id ? { challan_id: challan } : {}),
            ...(packingList && packingList !== shipment.packing_list?.id ? { packing_list_id: packingList } : {}),
          },
          k,
        ),
      { done: "Links saved", failed: FAILED, write: (x) => x },
    );

  return (
    <GlassPanel padding="lg" className="rise flex flex-col gap-5" title="Link the documents" titleAs="h2">
      <p className="t-body-sm text-ink-3">Both come from order {shipment.order?.number}. Cancelled documents are not offered.</p>
      <div className="grid min-w-0 grid-cols-1 gap-4 md:grid-cols-2">
        {order.isPending ? (
          <LoadingBlock lines={1} label="Loading the order's challans" />
        ) : order.isError ? (
          <p className="t-body-sm text-ink-3">The order&apos;s challans are not visible to you.</p>
        ) : (
          <Select
            label="Delivery challan"
            placeholder={challans.length ? "Choose a challan" : "The order has no challan yet"}
            options={challans.map((doc) => ({ value: doc.id, label: doc.number, description: doc.status.replace(/_/g, " ") }))}
            value={challan}
            onChange={setChallan}
            isDisabled={challans.length === 0}
          />
        )}
        {lists.isPending ? (
          <LoadingBlock lines={1} label="Loading the order's packing lists" />
        ) : lists.isError ? (
          <ErrorBlock error={lists.error} what="Packing lists" onRetry={() => void lists.refetch()} />
        ) : (
          <Select
            label="Packing list"
            placeholder={packing.length ? "Choose a packing list" : "The order has no packing list yet"}
            options={packing.map((list) => ({ value: list.id, label: list.packing_list_number, description: packingStatus(list.status).label }))}
            value={packingList}
            onChange={setPackingList}
            isDisabled={packing.length === 0}
          />
        )}
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <Button variant={changed ? "inverse" : "secondary"} iconLeft="link" loading={pending === "link"} isDisabled={Boolean(offline) || !changed} onPress={save}>
          Save links
        </Button>
        {!changed ? <span className="t-caption text-ink-3">Choose a different challan or packing list to save.</span> : null}
      </div>
    </GlassPanel>
  );
}

// ---------------------------------------------------------------------------------------------
// Tracking

function TrackingView({ shipment }: { shipment: ShipmentDetail }) {
  const key = useMemo(() => queryKeys.logistics.shipment(shipment.id), [shipment.id]);
  const { run, pending, offline } = useCommand<ShipmentDetail>(key);
  const [type, setType] = useState<TrackingRefType>("lr");
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | undefined>(undefined);
  const canAdd = shipment.capabilities.add_tracking_ref?.allowed === true;

  const add = async () => {
    if (!value.trim()) {
      setError("Enter the reference number.");
      return;
    }
    const saved = await run("track", (k) => addTrackingRef(shipment.id, type, value, k), { done: "Reference added", failed: FAILED, write: (x) => x });
    if (saved) {
      setValue("");
      setError(undefined);
    }
  };

  const list = (
    <GlassPanel padding="md" className="rise" title="Tracking references" titleAs="h2">
      {shipment.tracking_refs.length === 0 ? (
        <EmptyState compact icon="hash" title="No tracking reference yet" text="Add the lorry receipt, air waybill or bill of lading once the carrier issues it." />
      ) : (
        <ul className="flex flex-col divide-y divide-line">
          {shipment.tracking_refs.map((ref, index) => (
            <li key={ref.id} className="rise-plain flex min-w-0 flex-wrap items-baseline justify-between gap-3 py-3 first:pt-0 last:pb-0" style={stagger(index)}>
              <span className="t-body-sm text-ink-3">{TRACKING_LABEL[ref.ref_type] ?? ref.ref_type}</span>
              <span className="lk-mono t-label select-all text-ink">{ref.value}</span>
            </li>
          ))}
        </ul>
      )}
    </GlassPanel>
  );

  if (!canAdd) return list;
  return (
    <Split
      main={list}
      aside={
        <GlassPanel padding="lg" className="rise" title="Add a reference" titleAs="h2">
          <form
            noValidate
            className="flex flex-col gap-4"
            onSubmit={(event) => {
              event.preventDefault();
              void add();
            }}
          >
            <Select
              label="Type"
              options={TRACKING_TYPES.map((option) => ({ value: option, label: TRACKING_LABEL[option] ?? option }))}
              value={type}
              onChange={(next) => setType(TRACKING_TYPES.find((option) => option === next) ?? "other")}
            />
            <TextField
              label="Reference"
              value={value}
              onChange={(next) => {
                setValue(next);
                if (error && next.trim()) setError(undefined);
              }}
              maxLength={80}
              isRequired
              error={error}
            />
            <div>
              <Button type="submit" variant="inverse" iconLeft="plus" loading={pending === "track"} isDisabled={Boolean(offline)}>
                Add reference
              </Button>
            </div>
          </form>
        </GlassPanel>
      }
    />
  );
}

// ---------------------------------------------------------------------------------------------
// Delivery and exceptions

function DeliverModal({ shipment, isOpen, onClose }: { shipment: ShipmentDetail; isOpen: boolean; onClose: () => void }) {
  const formId = useId();
  const key = useMemo(() => queryKeys.logistics.shipment(shipment.id), [shipment.id]);
  const { run, pending, offline } = useCommand<ShipmentDetail>(key);
  const [kind, setKind] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | undefined>(undefined);
  const close = () => {
    if (pending === "deliver") return;
    setKind(null);
    setNote("");
    setError(undefined);
    onClose();
  };
  const submit = async () => {
    if (!kind) {
      setError("Choose the evidence you have for the delivery.");
      return;
    }
    const saved = await run("deliver", (k) => transitionShipment(shipment, "deliver", { evidence_kind: kind as EvidenceKind, evidence_note: note }, k), {
      done: "Delivery recorded",
      failed: FAILED,
      write: (x) => x,
    });
    if (saved) close();
  };
  return (
    <Modal
      isOpen={isOpen}
      onOpenChange={(open) => (open ? undefined : close())}
      title="Record the delivery"
      description="A delivery needs evidence: a signature, a photo, or the courier's or customer's confirmation."
      actions={
        <>
          <Button variant="ghost" onPress={close} isDisabled={pending === "deliver"}>
            Cancel
          </Button>
          <Button type="submit" form={formId} variant="primary" iconLeft="checkCircle" loading={pending === "deliver"} isDisabled={Boolean(offline)}>
            Record delivery
          </Button>
        </>
      }
    >
      <form
        id={formId}
        noValidate
        className="flex flex-col gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <Select
          label="Evidence"
          placeholder="Choose the evidence"
          options={EVIDENCE_KINDS.map((option) => ({ value: option.value, label: option.label }))}
          value={kind}
          onChange={(next) => {
            setKind(next);
            setError(undefined);
          }}
          isRequired
          error={error}
        />
        <Textarea label="Note" optional help="Who signed, or the confirmation reference." rows={2} maxLength={1000} value={note} onChange={setNote} />
      </form>
    </Modal>
  );
}

function ExceptionModal({ shipment, isOpen, onClose }: { shipment: ShipmentDetail; isOpen: boolean; onClose: () => void }) {
  const formId = useId();
  const key = useMemo(() => queryKeys.logistics.shipment(shipment.id), [shipment.id]);
  const { run, pending, offline } = useCommand<ShipmentDetail>(key);
  const [code, setCode] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | undefined>(undefined);
  const close = () => {
    if (pending === "record_exception") return;
    setCode(null);
    setNote("");
    setError(undefined);
    onClose();
  };
  const submit = async () => {
    if (!code) {
      setError("Choose what happened.");
      return;
    }
    const saved = await run("record_exception", (k) => transitionShipment(shipment, "record_exception", { exception_code: code as ExceptionCode, note }, k), {
      done: "Exception recorded",
      failed: FAILED,
      write: (x) => x,
    });
    if (saved) close();
  };
  return (
    <Modal
      isOpen={isOpen}
      onOpenChange={(open) => (open ? undefined : close())}
      title="Record an exception"
      description="The shipment is flagged until the exception is resolved."
      actions={
        <>
          <Button variant="ghost" onPress={close} isDisabled={pending === "record_exception"}>
            Cancel
          </Button>
          <Button type="submit" form={formId} variant="danger" iconLeft="alert" loading={pending === "record_exception"} isDisabled={Boolean(offline)}>
            Record exception
          </Button>
        </>
      }
    >
      <form
        id={formId}
        noValidate
        className="flex flex-col gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <Select
          label="What happened"
          placeholder="Choose what happened"
          options={EXCEPTION_CODES.map((option) => ({ value: option.value, label: option.label }))}
          value={code}
          onChange={(next) => {
            setCode(next);
            setError(undefined);
          }}
          isRequired
          error={error}
        />
        <Textarea label="Note" optional rows={3} maxLength={1000} value={note} onChange={setNote} />
      </form>
    </Modal>
  );
}

