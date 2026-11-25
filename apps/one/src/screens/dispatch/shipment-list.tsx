"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useId, useMemo, useState } from "react";
import { useCommand } from "@/features/inventory/use-command";
import { fetchShipments, PAGE_SIZE, planShipment, SHIPMENT_MODES, SHIPMENT_STATUSES, type ShipmentMode, type ShipmentSummary } from "@/features/logistics/api";
import { shipmentListHref, type ShipmentListState } from "@/features/logistics/list-state";
import { queryKeys } from "@/lib/api/query-keys";
import { useSession } from "@/lib/session/context";
import { asRoute, FAILED, MODE_ICON, MODE_LABEL, shipmentStatus, type OrderOption } from "~/data/dispatch";
import { Page, PageHeader } from "~/shell/page";
import { ErrorBlock } from "~/shell/states";
import {
  Button,
  ButtonLink,
  ChipGroup,
  ChipLink,
  Code,
  DataTable,
  DatePicker,
  EmptyState,
  GlassPanel,
  Icon,
  Modal,
  PageSummary,
  Pagination,
  SearchField,
  Select,
  TextField,
  type Column,
} from "~/ui";
import { Cutoff, DispatchSwitch, OrderPicker, ShipmentStatusBadge, stagger } from "./parts";

const TIME = /^([01]\d|2[0-3]):[0-5]\d$/;

const COLUMNS: Column<ShipmentSummary>[] = [
  {
    key: "shipment",
    header: "Shipment",
    primary: true,
    cell: (shipment) => (
      <span className="flex min-w-0 flex-col gap-0.5">
        <span className="t-label truncate text-ink" title={shipment.party_name}>
          {shipment.party_name}
        </span>
        <span className="t-caption text-ink-3">
          <Code>{shipment.shipment_number}</Code>
        </span>
      </span>
    ),
  },
  {
    key: "documents",
    header: "Order and challan",
    cell: (shipment) => (
      <span className="flex min-w-0 flex-col gap-0.5">
        {shipment.order ? <Code>{shipment.order.number}</Code> : <span className="text-ink-3">No order</span>}
        <span className="t-caption text-ink-3">{shipment.challan ? <>Challan {shipment.challan.number}</> : "No challan yet"}</span>
      </span>
    ),
  },
  {
    key: "mode",
    header: "Mode",
    hideOnMobile: true,
    cell: (shipment) => (
      <span className="flex min-w-0 flex-col gap-0.5">
        <span className="flex items-center gap-1.5 text-ink">
          <Icon name={MODE_ICON[shipment.mode] ?? "truck"} size={16} className="text-ink-3" />
          {MODE_LABEL[shipment.mode] ?? shipment.mode}
        </span>
        {shipment.transporter_name ? <span className="t-caption truncate text-ink-3">{shipment.transporter_name}</span> : null}
      </span>
    ),
  },
  { key: "cutoff", header: "Cutoff", cell: (shipment) => <Cutoff shipment={shipment} /> },
  { key: "status", header: "Status", cell: (shipment) => <ShipmentStatusBadge status={shipment.status} /> },
];

/** The dispatch board: every shipment, the nearest cutoff first. Search, status and page live in the URL. */
export function ShipmentList({ state }: { state: ShipmentListState }) {
  const router = useRouter();
  const { permissionKeys } = useSession();
  const [text, setText] = useState(state.q);
  const [planning, setPlanning] = useState(false);
  const query = useQuery({
    queryKey: queryKeys.logistics.shipments({ q: state.q, status: state.status, offset: state.offset }),
    queryFn: ({ signal }) => fetchShipments(state, signal),
  });
  const href = (next: Partial<ShipmentListState>) => asRoute(shipmentListHref({ ...state, offset: 0, ...next }));
  const canPlan = permissionKeys.has("logistics.shipment.create");
  const filtered = Boolean(state.q.trim() || state.status);
  const limit = query.data?.limit || PAGE_SIZE;
  const total = query.data?.total ?? 0;

  return (
    <Page>
      <PageHeader
        eyebrow="Operations"
        title="Dispatch"
        lead="Every shipment, the nearest cutoff first. Dispatching issues the linked challan, and that is when stock leaves."
        actions={
          canPlan ? (
            <Button iconLeft="plus" onPress={() => setPlanning(true)}>
              Plan a shipment
            </Button>
          ) : undefined
        }
      />

      <div className="rise flex min-w-0 flex-col gap-3" style={stagger(1)}>
        <div className="flex min-w-0 flex-wrap items-center gap-3">
          <DispatchSwitch current="shipments" />
          <SearchField
            className="min-w-0 flex-1 basis-64 md:max-w-xl"
            label="Search shipments"
            placeholder="Shipment, order, challan or customer"
            value={text}
            onChange={(value) => {
              setText(value);
              if (value === "" && state.q) router.push(href({ q: "" }));
            }}
            onSubmit={(value) => router.push(href({ q: value }))}
          />
        </div>
        <ChipGroup label="Filter by status">
          <ChipLink href={href({ status: null })} selected={state.status === null} scroll={false}>
            All
          </ChipLink>
          {SHIPMENT_STATUSES.map((status) => (
            <ChipLink key={status} href={href({ status })} selected={state.status === status} scroll={false}>
              {shipmentStatus(status).label}
            </ChipLink>
          ))}
        </ChipGroup>
      </div>

      {query.isError ? (
        <ErrorBlock error={query.error} what="Shipments" onRetry={() => void query.refetch()} />
      ) : (
        <GlassPanel padding="none" className="rise min-w-0" style={stagger(2)}>
          <DataTable
            label="Shipments"
            columns={COLUMNS}
            rows={query.data?.items ?? []}
            rowKey={(shipment) => shipment.id}
            rowHref={(shipment) => asRoute(shipment.path)}
            loading={query.isPending}
            skeletonRows={8}
            empty={
              filtered ? (
                <EmptyState
                  compact
                  icon="search"
                  title="No shipments match"
                  text="Nothing fits this search and status."
                  actions={
                    <ButtonLink href="/operations/dispatch" variant="secondary" size="sm">
                      Clear filters
                    </ButtonLink>
                  }
                />
              ) : (
                <EmptyState
                  icon="truck"
                  title="Nothing to dispatch yet"
                  text="Plan a shipment from a confirmed sales order. Its cutoff puts it on this board in company time."
                  actions={
                    canPlan ? (
                      <Button variant="inverse" iconLeft="plus" onPress={() => setPlanning(true)}>
                        Plan your first shipment
                      </Button>
                    ) : undefined
                  }
                />
              )
            }
          />
        </GlassPanel>
      )}

      {query.data && total > 0 ? (
        <div className="flex min-w-0 flex-wrap items-center justify-between gap-3">
          <PageSummary from={query.data.offset + 1} to={query.data.offset + query.data.items.length} total={total} noun="shipments" />
          {total > limit ? (
            <Pagination
              label="Shipment pages"
              page={Math.floor(query.data.offset / limit) + 1}
              pages={Math.ceil(total / limit)}
              hrefFor={(page) => asRoute(shipmentListHref({ ...state, offset: (page - 1) * limit }))}
            />
          ) : null}
        </div>
      ) : null}

      {canPlan ? <PlanShipmentModal isOpen={planning} onOpenChange={setPlanning} /> : null}
    </Page>
  );
}

/** Plan a shipment against a confirmed order: how it travels, who carries it, and the cutoff. */
function PlanShipmentModal({ isOpen, onOpenChange }: { isOpen: boolean; onOpenChange: (open: boolean) => void }) {
  const router = useRouter();
  const formId = useId();
  const key = useMemo(() => queryKeys.logistics.all(), []);
  const { run, pending, offline } = useCommand<null>(key);
  const [order, setOrder] = useState<OrderOption | null>(null);
  const [mode, setMode] = useState<ShipmentMode>("road");
  const [transporter, setTransporter] = useState("");
  const [cutoffDate, setCutoffDate] = useState<string | null>(null);
  const [cutoffTime, setCutoffTime] = useState("");
  const [errors, setErrors] = useState<{ order?: string; time?: string }>({});

  const close = (open: boolean) => {
    if (open || pending === "plan") return;
    setOrder(null);
    setMode("road");
    setTransporter("");
    setCutoffDate(null);
    setCutoffTime("");
    setErrors({});
    onOpenChange(false);
  };
  const timeError = (value: string) => (value.trim() !== "" && !TIME.test(value.trim()) ? "Enter the time as HH:MM, for example 17:30." : undefined);

  const submit = async () => {
    const next = { order: order ? undefined : "Choose the sales order to ship.", time: cutoffDate ? timeError(cutoffTime) : undefined };
    setErrors(next);
    if (!order || next.time) return;
    const shipment = await run(
      "plan",
      (k) => planShipment({ sales_order_id: order.id, mode, transporter_name: transporter, cutoff_date: cutoffDate, cutoff_time: cutoffTime.trim() || null }, k),
      { done: "Shipment planned", failed: FAILED },
    );
    if (shipment) {
      onOpenChange(false);
      router.push(asRoute(shipment.path));
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onOpenChange={close}
      title="Plan a shipment"
      description="Pick the confirmed order. A cutoff puts a dispatch task on the board, due in company time."
      actions={
        <>
          <Button variant="ghost" onPress={() => close(false)} isDisabled={pending === "plan"}>
            Cancel
          </Button>
          <Button type="submit" form={formId} variant="primary" loading={pending === "plan"} isDisabled={Boolean(offline)}>
            Plan shipment
          </Button>
        </>
      }
    >
      <form
        id={formId}
        className="flex flex-col gap-5"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <OrderPicker
          value={order}
          onChange={(next) => {
            setOrder(next);
            if (next) setErrors((current) => ({ ...current, order: undefined }));
          }}
          error={errors.order}
        />
        <div className="grid min-w-0 grid-cols-1 gap-4 sm:grid-cols-2">
          <Select
            label="Mode"
            options={SHIPMENT_MODES.map((value) => ({ value, label: MODE_LABEL[value] ?? value, icon: MODE_ICON[value] }))}
            value={mode}
            onChange={(value) => setMode(SHIPMENT_MODES.find((candidate) => candidate === value) ?? "road")}
          />
          <TextField label="Transporter" optional value={transporter} onChange={setTransporter} maxLength={200} />
          <DatePicker label="Cutoff date" optional value={cutoffDate} onChange={setCutoffDate} />
          <TextField
            label="Cutoff time"
            optional
            placeholder="17:30"
            help={cutoffDate ? "Company time. Without a time, the cutoff is the end of that day's shift." : "Set a cutoff date first."}
            value={cutoffTime}
            onChange={(value) => {
              setCutoffTime(value);
              if (errors.time) setErrors((current) => ({ ...current, time: timeError(value) }));
            }}
            onBlur={() => setErrors((current) => ({ ...current, time: timeError(cutoffTime) }))}
            maxLength={5}
            isDisabled={!cutoffDate}
            error={errors.time}
          />
        </div>
        {offline ? <p className="t-caption text-ink-3">You are offline. The shipment can be planned once the connection is back.</p> : null}
      </form>
    </Modal>
  );
}
