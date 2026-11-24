"use client";

import { useRouter } from "next/navigation";
import { useMemo, useState, type ReactNode } from "react";
import { confirmPick, pickListAction, pickListChallan, type PickListRead } from "@/features/inventory/api";
import { useCommand } from "@/features/inventory/use-command";
import { queryKeys } from "@/lib/api/query-keys";
import { compareDecimalStr, isDecimalStr } from "@/lib/format/decimal";
import { asRoute, useCanOpen, usePickList } from "~/data/stock";
import { Page, RecordHeader, Split } from "~/shell/page";
import { StatusBadge, Steps, type StepItem } from "~/screens/sales/quotations/parts";
import {
  Badge,
  Button,
  ButtonLink,
  Code,
  ConfirmDialog,
  DataTable,
  DateText,
  DecimalField,
  FactStrip,
  FormActions,
  GlassPanel,
  KeyValue,
  Menu,
  Qty,
  Tabs,
  TextLink,
  toast,
  type Column,
  type MenuItem,
  type Tone,
} from "~/ui";
import { humanise, pickListStatus, plural, viewHref, type StockRecordView } from "./labels";
import { OfflineBanner, ProductCell, RecordError, RecordLoading } from "./parts";

type PickLine = PickListRead["lines"][number];

const FAILED = "That did not go through";
const LINE_TONE: Record<string, Tone> = { picked: "leaf", short: "amber", cancelled: "neutral" };

/** A pick list: what the warehouse collects for one order before the delivery challan is made. */
export function PickListRecord({ pickListId, view }: { pickListId: string; view: StockRecordView }) {
  const query = usePickList(pickListId);
  if (query.isPending) return <RecordLoading label="Loading the pick list" />;
  if (query.isError) return <RecordError error={query.error} what="This pick list" onRetry={() => void query.refetch()} backHref="/operations/inventory" backLabel="Stock" />;
  return <Loaded key={query.data.version} pickList={query.data} view={view} />;
}

function Loaded({ pickList, view }: { pickList: PickListRead; view: StockRecordView }) {
  const router = useRouter();
  const canOpen = useCanOpen();
  const key = useMemo(() => queryKeys.inventory.pickList(pickList.id), [pickList.id]);
  const { run, pending, offline } = useCommand<PickListRead>(key);
  const [picked, setPicked] = useState<Record<string, string>>(() => Object.fromEntries(pickList.lines.map((line) => [line.id, line.picked ?? line.requested])));
  const [missing, setMissing] = useState<ReadonlySet<string>>(new Set());
  const [dialog, setDialog] = useState<null | "short" | "cancel">(null);
  const caps = pickList.capabilities;
  const path = `/operations/inventory/pick-lists/${pickList.id}`;
  const orderPath = `/sales/orders/${pickList.order_id}`;
  const challanPath = pickList.challan_id ? `/operations/challans/${pickList.challan_id}` : null;
  const write = (result: PickListRead) => result;
  const busy = pending !== null;
  const off = Boolean(offline);
  const order = canOpen(orderPath) ? <TextLink href={asRoute(orderPath)}>{pickList.order_number}</TextLink> : pickList.order_number;

  const shortLines = pickList.lines.filter((line) => {
    const entry = picked[line.id] ?? "";
    return isDecimalStr(entry) && compareDecimalStr(entry, line.requested) < 0;
  }).length;

  const sendPick = () =>
    run(
      "pick",
      (k) =>
        confirmPick(
          pickList,
          pickList.lines.map((line) => ({ line_id: line.id, picked_quantity: picked[line.id] ?? "" })),
          k,
        ),
      { done: "Picked quantities recorded", failed: FAILED, write },
    );

  const confirmPicked = () => {
    const blank = pickList.lines.filter((line) => !isDecimalStr(picked[line.id] ?? "")).map((line) => line.id);
    if (blank.length > 0) {
      setMissing(new Set(blank));
      toast.error(blank.length === 1 ? "One line has no picked quantity" : `${blank.length} lines have no picked quantity`, { description: "Enter what was picked on each line. Use 0 where nothing was." });
      return;
    }
    if (shortLines > 0) setDialog("short");
    else void sendPick();
  };

  const menu: MenuItem[] = [];
  if (caps.cancel?.allowed) menu.push({ id: "cancel", label: "Cancel pick list", icon: "xCircle", tone: "danger", isDisabled: off, onAction: () => setDialog("cancel") });

  const setLine = (lineId: string, value: string) => {
    setPicked((previous) => ({ ...previous, [lineId]: value }));
    if (missing.has(lineId)) setMissing((previous) => new Set([...previous].filter((id) => id !== lineId)));
  };

  return (
    <Page>
      <RecordHeader
        breadcrumb={[{ label: "Operations", href: "/operations" }, { label: "Stock", href: "/operations/inventory" }, { label: pickList.number }]}
        code={pickList.number}
        title={`Pick list for ${pickList.order_number}`}
        status={<StatusBadge look={pickListStatus(pickList.status)} />}
        lead={<>What the warehouse collects for order {order} before it is dispatched.</>}
        facts={
          <FactStrip
            items={[
              { label: "Warehouse", icon: "warehouse", value: pickList.warehouse.name },
              { label: "Lines", icon: "list", value: pickList.lines.length },
              { label: "Picker", icon: "user", value: pickList.assignee?.display_name },
              { label: "Released", icon: "play", value: pickList.released_at ? <DateText value={pickList.released_at} style="dayTime" /> : null },
              { label: "Picked", icon: "check", value: pickList.picked_at ? <DateText value={pickList.picked_at} style="dayTime" /> : null },
            ]}
          />
        }
        actions={
          <>
            {caps.release?.allowed ? (
              <Button
                iconLeft="play"
                loading={pending === "release"}
                isDisabled={off || busy}
                onPress={() =>
                  void run("release", (k) => pickListAction(pickList, "release", k), { done: "Pick list released", failed: FAILED, write }).then((released) => {
                    if (released) router.push(asRoute(viewHref(path, "lines")));
                  })
                }
              >
                Release for picking
              </Button>
            ) : null}
            {caps.create_challan?.allowed ? (
              <Button
                iconLeft="truck"
                loading={pending === "challan"}
                isDisabled={off || busy}
                onPress={() => void run("challan", (k) => pickListChallan(pickList.id, k), { done: "Draft challan created", failed: FAILED, write })}
              >
                Create delivery challan
              </Button>
            ) : null}
            {menu.length > 0 ? (
              <Menu
                label="More pick list actions"
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
          label="Views of this pick list"
          selectedKey={view}
          tabs={[
            { id: "overview", label: "Overview", href: asRoute(path) },
            { id: "lines", label: "Pick lines", count: pickList.lines.length || undefined, href: asRoute(viewHref(path, "lines")) },
          ]}
        />
      </RecordHeader>

      {offline ? <OfflineBanner what="this pick list" /> : null}

      {view === "overview" ? (
        <Overview pickList={pickList} path={path} order={order} challanHref={challanPath && canOpen(challanPath) ? challanPath : null} />
      ) : null}

      {view === "lines" ? (
        <>
          <Lines pickList={pickList} picked={picked} missing={missing} onPicked={setLine} />
          {caps.pick?.allowed ? (
            <FormActions note={shortLines > 0 ? `${plural(shortLines, "line is", "lines are")} short. The rest of the reservation is released.` : "Each line starts at the quantity to pick. Change only what came up short."}>
              <Button iconLeft="check" loading={pending === "pick"} isDisabled={off || (busy && pending !== "pick")} onPress={confirmPicked}>
                Confirm picked quantities
              </Button>
            </FormActions>
          ) : null}
        </>
      ) : null}

      <ConfirmDialog
        isOpen={dialog === "short"}
        onOpenChange={(open) => (open ? undefined : setDialog(null))}
        title="Confirm a short pick"
        description={`${plural(shortLines, "line was", "lines were")} picked short. What was not picked is released from the reservation and is free to promise again.`}
        confirmLabel="Confirm short pick"
        cancelLabel="Check again"
        onConfirm={async () => {
          if (!(await sendPick())) throw new Error("pick failed");
        }}
      />
      <ConfirmDialog
        isOpen={dialog === "cancel"}
        onOpenChange={(open) => (open ? undefined : setDialog(null))}
        tone="danger"
        title="Cancel this pick list"
        description={`Nothing more is collected on ${pickList.number}. Order ${pickList.order_number} is not cancelled.`}
        confirmLabel="Cancel pick list"
        cancelLabel="Keep it"
        onConfirm={async () => {
          const cancelled = await run("cancel", (k) => pickListAction(pickList, "cancel", k), { done: "Pick list cancelled", failed: FAILED, write });
          if (!cancelled) throw new Error("cancel failed");
        }}
      />
    </Page>
  );
}

// ---------------------------------------------------------------------------------------------
// Overview

function progressOf(pickList: PickListRead): StepItem[] {
  const cancelled = pickList.status === "cancelled";
  const released = pickList.released_at !== null || pickList.status === "released" || pickList.status === "picked";
  const picked = pickList.status === "picked";
  const raw: { id: string; label: string; hint: ReactNode; done: boolean }[] = [
    { id: "release", label: "Released", hint: pickList.released_at ? <DateText value={pickList.released_at} style="date" /> : "Hand it to the warehouse", done: released },
    { id: "pick", label: "Picked", hint: pickList.picked_at ? <DateText value={pickList.picked_at} style="date" /> : "Collect each line", done: picked },
    { id: "challan", label: "On a challan", hint: pickList.challan_number ?? "The goods' delivery paper", done: pickList.challan_id !== null },
  ];
  const current = cancelled ? -1 : raw.findIndex((step) => !step.done);
  return raw.map((step, index) => ({ id: step.id, label: step.label, hint: step.hint, state: step.done && !cancelled ? "done" : index === current ? "current" : "todo" }));
}

function standingOf(pickList: PickListRead): { headline: ReactNode; body: string } {
  if (pickList.status === "cancelled") return { headline: "Cancelled", body: "Nothing more is collected on this pick list." };
  if (pickList.challan_id) return { headline: <>On its <em>challan</em></>, body: "The picked goods are on a delivery challan. Issuing the challan takes them out of stock." };
  if (pickList.status === "picked") return { headline: <>Picked. Next, the <em>challan</em></>, body: "Everything collected is waiting for its delivery challan. The challan travels with the goods." };
  if (pickList.status === "released") return { headline: <>Being <em>picked</em></>, body: "Collect each line from its location, then confirm what was picked." };
  return { headline: <>Ready to <em>release</em></>, body: "Releasing hands this list to the warehouse to start collecting." };
}

function Overview({ pickList, path, order, challanHref }: { pickList: PickListRead; path: string; order: ReactNode; challanHref: string | null }) {
  const standing = standingOf(pickList);
  const picking = Boolean(pickList.capabilities.pick?.allowed);
  return (
    <Split
      main={
        <GlassPanel padding="lg" className="rise flex flex-col gap-6" eyebrow="Where it stands">
          <Steps label="Progress of this pick list" steps={progressOf(pickList)} />
          <div className="flex max-w-prose flex-col gap-2">
            <h2 className="t-display-sm text-ink">{standing.headline}</h2>
            <p className="t-body text-ink-2">{standing.body}</p>
          </div>
          {picking ? (
            <div>
              <ButtonLink href={asRoute(viewHref(path, "lines"))} iconRight="arrowRight">
                Enter picked quantities
              </ButtonLink>
            </div>
          ) : null}
          <p className="t-body-sm hairline-top max-w-prose pt-4 text-ink-3">
            Picking moves no stock. Issuing the delivery challan is the one stock movement. A short pick releases the rest of the reservation.
          </p>
        </GlassPanel>
      }
      aside={
        <GlassPanel padding="md" className="rise" title="Linked records" titleAs="h2">
          <KeyValue
            rows
            items={[
              { label: "Order", value: order },
              {
                label: "Delivery challan",
                value: pickList.challan_id ? (
                  challanHref ? (
                    <TextLink href={asRoute(challanHref)}>
                      <Code>{pickList.challan_number ?? "Open challan"}</Code>
                    </TextLink>
                  ) : (
                    <Code>{pickList.challan_number}</Code>
                  )
                ) : null,
              },
              { label: "Warehouse", value: `${pickList.warehouse.code} · ${pickList.warehouse.name}` },
              { label: "Created", value: <DateText value={pickList.created_at} style="dayTime" /> },
            ]}
          />
        </GlassPanel>
      }
    />
  );
}

// ---------------------------------------------------------------------------------------------
// Pick lines

function Lines({ pickList, picked, missing, onPicked }: { pickList: PickListRead; picked: Record<string, string>; missing: ReadonlySet<string>; onPicked: (lineId: string, value: string) => void }) {
  const canPick = Boolean(pickList.capabilities.pick?.allowed);
  const columns: Column<PickLine>[] = [
    { key: "product", header: "Product", primary: true, cell: (line) => <ProductCell product={line.product} /> },
    {
      key: "location",
      header: "Pick from",
      cell: (line) => (
        <span className="flex min-w-0 flex-col gap-0.5">
          <span className="lk-mono text-ink">{line.location.code}</span>
          {line.lot ? <span className="t-caption text-ink-3">Lot {line.lot.lot_code}</span> : null}
        </span>
      ),
    },
    { key: "requested", header: "To pick", numeric: true, cell: (line) => <Qty value={{ value: line.requested, uom: line.unit }} /> },
    {
      key: "picked",
      header: "Picked",
      numeric: true,
      width: canPick ? "184px" : undefined,
      cell: (line) =>
        canPick ? (
          <DecimalField
            label={`Picked quantity of ${line.product.product_key} from ${line.location.code}`}
            hideLabel
            size="sm"
            className="ml-auto w-40"
            suffix={line.unit}
            value={picked[line.id] ?? ""}
            onChange={(value) => onPicked(line.id, value)}
            error={missing.has(line.id) ? "Enter what was picked. Use 0 if nothing was." : undefined}
          />
        ) : (
          <Qty value={line.picked === null ? null : { value: line.picked, uom: line.unit }} className="t-label text-ink" />
        ),
    },
    {
      key: "status",
      header: "Status",
      cell: (line) => (
        <Badge tone={LINE_TONE[line.status] ?? "neutral"} size="sm">
          {humanise(line.status)}
        </Badge>
      ),
    },
  ];
  return (
    <GlassPanel padding="none" className="rise min-w-0">
      <DataTable label={`Pick lines of ${pickList.number}`} columns={columns} rows={pickList.lines} rowKey={(line) => line.id} />
    </GlassPanel>
  );
}
