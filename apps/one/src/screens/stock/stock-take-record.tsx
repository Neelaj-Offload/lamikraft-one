"use client";

import { useRouter } from "next/navigation";
import { useMemo, useState, type ReactNode } from "react";
import { approveCount, countAction, enterCounts, type CountRead } from "@/features/inventory/api";
import { useCommand } from "@/features/inventory/use-command";
import { queryKeys } from "@/lib/api/query-keys";
import { compareDecimalStr, isDecimalStr } from "@/lib/format/decimal";
import { asRoute, useCanOpen, useStockTake } from "~/data/stock";
import { Page, RecordHeader, Split } from "~/shell/page";
import { StatusBadge, Steps, type StepItem } from "~/screens/sales/quotations/parts";
import {
  Button,
  ButtonLink,
  ConfirmDialog,
  DataTable,
  DateText,
  DecimalField,
  EmptyState,
  FactStrip,
  FormActions,
  GlassPanel,
  KeyValue,
  Menu,
  Qty,
  Tabs,
  toast,
  type Column,
  type MenuItem,
} from "~/ui";
import { MOVEMENTS_PATH, plural, stockTakeStatus, viewHref, type StockRecordView } from "./labels";
import { OfflineBanner, ProductCell, RecordError, RecordLoading } from "./parts";

type CountLine = CountRead["lines"][number];

const LIST = "/operations/inventory/stock-takes";
const FAILED = "That did not go through";

/** A stock take: freeze what the records hold, enter what is found, approve the difference. */
export function StockTakeRecord({ countId, view }: { countId: string; view: StockRecordView }) {
  const query = useStockTake(countId);
  if (query.isPending) return <RecordLoading label="Loading the stock take" />;
  if (query.isError) return <RecordError error={query.error} what="This stock take" onRetry={() => void query.refetch()} backHref={LIST} backLabel="All stock takes" />;
  // A new version means the server has the entries: start again from what it holds.
  return <Loaded key={query.data.version} count={query.data} view={view} />;
}

function Loaded({ count, view }: { count: CountRead; view: StockRecordView }) {
  const router = useRouter();
  const canOpen = useCanOpen();
  const key = useMemo(() => queryKeys.inventory.count(count.id), [count.id]);
  const { run, pending, offline } = useCommand<CountRead>(key);
  const [entries, setEntries] = useState<Record<string, string>>(() => Object.fromEntries(count.lines.map((line) => [line.id, line.counted_quantity ?? line.system_quantity])));
  const [missing, setMissing] = useState<ReadonlySet<string>>(new Set());
  const [dialog, setDialog] = useState<null | "approve" | "cancel">(null);
  const caps = count.capabilities;
  const path = `${LIST}/${count.id}`;
  const write = (result: CountRead) => result;
  const busy = pending !== null;
  const off = Boolean(offline);

  const changed = count.lines.filter((line) => {
    const entry = entries[line.id] ?? "";
    const saved = line.counted_quantity ?? line.system_quantity;
    return !isDecimalStr(entry) || compareDecimalStr(entry, saved) !== 0;
  }).length;

  /** Saves every line's count, as the old screen did. Returns the saved stock take, or null. */
  const saveEntries = async (): Promise<CountRead | null> => {
    const blank = count.lines.filter((line) => !isDecimalStr(entries[line.id] ?? "")).map((line) => line.id);
    if (blank.length > 0) {
      setMissing(new Set(blank));
      toast.error(blank.length === 1 ? "One line has no count" : `${blank.length} lines have no count`, { description: "Enter what you counted on each line. Use 0 where there is none." });
      if (view !== "lines") router.push(asRoute(viewHref(path, "lines")));
      return null;
    }
    return run(
      "save",
      (k) =>
        enterCounts(
          count,
          count.lines.map((line) => ({ line_id: line.id, counted_quantity: entries[line.id] ?? "" })),
          k,
        ),
      { done: "Counts saved", failed: "The counts could not be saved", write },
    );
  };

  const submit = async () => {
    const saved = await saveEntries();
    if (saved) await run("submit", (k) => countAction(saved, "submit", k), { done: "Counts sent for approval", failed: FAILED, write });
  };

  const freeze = async () => {
    const frozen = await run("freeze", (k) => countAction(count, "freeze", k), { done: "Snapshot taken. Enter what you count.", failed: FAILED, write });
    if (frozen) router.push(asRoute(viewHref(path, "lines")));
  };

  const menu: MenuItem[] = [];
  if (caps.cancel?.allowed) menu.push({ id: "cancel", label: "Cancel stock take", icon: "xCircle", tone: "danger", isDisabled: off, onAction: () => setDialog("cancel") });

  const setEntry = (lineId: string, value: string) => {
    setEntries((previous) => ({ ...previous, [lineId]: value }));
    if (missing.has(lineId)) setMissing((previous) => new Set([...previous].filter((id) => id !== lineId)));
  };

  return (
    <Page>
      <RecordHeader
        breadcrumb={[{ label: "Operations", href: "/operations" }, { label: "Stock", href: "/operations/inventory" }, { label: "Stock takes", href: LIST }, { label: count.number }]}
        code={count.number}
        title={count.warehouse.name}
        status={<StatusBadge look={stockTakeStatus(count.status)} />}
        lead={count.location ? `Counting location ${count.location.code} only.` : "Counting the whole warehouse."}
        facts={
          <FactStrip
            items={[
              { label: "Warehouse", icon: "warehouse", value: count.warehouse.code },
              { label: "Lines", icon: "list", value: count.lines.length },
              { label: "Counted", icon: "clipboardCheck", value: `${count.counted_lines} of ${count.lines.length}` },
              { label: "Differences", icon: "alert", value: count.variance_lines },
              { label: "Frozen", icon: "clock", value: count.frozen_at ? <DateText value={count.frozen_at} style="dayTime" /> : null },
            ]}
          />
        }
        actions={
          <>
            {caps.freeze?.allowed ? (
              <Button iconLeft="play" loading={pending === "freeze"} isDisabled={off || busy} onPress={() => void freeze()}>
                Freeze and start counting
              </Button>
            ) : null}
            {caps.approve?.allowed ? (
              <Button iconLeft="check" isDisabled={off || busy} onPress={() => setDialog("approve")}>
                Approve and post
              </Button>
            ) : null}
            {menu.length > 0 ? (
              <Menu
                label="More stock take actions"
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
          label="Views of this stock take"
          selectedKey={view}
          tabs={[
            { id: "overview", label: "Overview", href: asRoute(path) },
            { id: "lines", label: "Count sheet", count: count.lines.length || undefined, href: asRoute(viewHref(path, "lines")) },
          ]}
        />
      </RecordHeader>

      {offline ? <OfflineBanner what="this stock take" /> : null}

      {view === "overview" ? <Overview count={count} path={path} canSeeMovements={canOpen(MOVEMENTS_PATH)} /> : null}

      {view === "lines" ? (
        <>
          <Sheet count={count} entries={entries} missing={missing} onEntry={setEntry} />
          {caps.enter?.allowed || caps.submit?.allowed ? (
            <FormActions note={changed > 0 ? `${plural(changed, "line", "lines")} changed, not saved yet` : "Each line starts at the quantity on record. Change only what you find different."}>
              {caps.enter?.allowed ? (
                <Button variant="secondary" iconLeft="save" loading={pending === "save"} isDisabled={off || (busy && pending !== "save")} onPress={() => void saveEntries()}>
                  Save counts
                </Button>
              ) : null}
              {caps.submit?.allowed ? (
                <Button iconLeft="send" loading={pending === "submit"} isDisabled={off || (busy && pending !== "submit")} onPress={() => void submit()}>
                  Submit for approval
                </Button>
              ) : null}
            </FormActions>
          ) : null}
        </>
      ) : null}

      <ConfirmDialog
        isOpen={dialog === "approve"}
        onOpenChange={(open) => (open ? undefined : setDialog(null))}
        title="Approve this count and post the difference"
        description={
          count.variance_lines === 0
            ? "Every line matches the records, so stock does not change. The stock take is closed."
            : `${plural(count.variance_lines, "line differs", "lines differ")} from the records. Stock on hand changes to match the count. A posting is never edited: a mistake is put right with a reversal.`
        }
        confirmLabel="Approve and post"
        cancelLabel="Not yet"
        onConfirm={async () => {
          const posted = await run("approve", (k) => approveCount(count, k), { done: "Count approved and posted", failed: FAILED, write });
          if (!posted) throw new Error("approve failed");
        }}
      />
      <ConfirmDialog
        isOpen={dialog === "cancel"}
        onOpenChange={(open) => (open ? undefined : setDialog(null))}
        tone="danger"
        title="Cancel this stock take"
        description="The counts entered so far are set aside and nothing is posted. Stock stays as the records hold it."
        confirmLabel="Cancel stock take"
        cancelLabel="Keep counting"
        onConfirm={async () => {
          const cancelled = await run("cancel", (k) => countAction(count, "cancel", k), { done: "Stock take cancelled", failed: FAILED, write });
          if (!cancelled) throw new Error("cancel failed");
        }}
      />
    </Page>
  );
}

// ---------------------------------------------------------------------------------------------
// Overview: where the count stands and what is next

function progressOf(count: CountRead): StepItem[] {
  const cancelled = count.status === "cancelled";
  const frozen = count.frozen_at !== null || ["frozen", "submitted", "posted"].includes(count.status);
  const counted = count.status === "submitted" || count.status === "posted";
  const posted = count.status === "posted";
  const raw: { id: string; label: string; hint: ReactNode; done: boolean }[] = [
    { id: "freeze", label: "Freeze", hint: count.frozen_at ? <DateText value={count.frozen_at} style="date" /> : "Record what is held", done: frozen },
    { id: "count", label: "Count", hint: frozen ? `${count.counted_lines} of ${count.lines.length} lines` : "Enter what you find", done: counted },
    { id: "approve", label: "Approve and post", hint: count.approved_at ? <DateText value={count.approved_at} style="date" /> : "A second look, then the ledger", done: posted },
  ];
  const current = cancelled ? -1 : raw.findIndex((step) => !step.done);
  return raw.map((step, index) => ({ id: step.id, label: step.label, hint: step.hint, state: step.done && !cancelled ? "done" : index === current ? "current" : "todo" }));
}

function standingOf(count: CountRead): { headline: ReactNode; body: string } {
  const warehouse = count.warehouse.name;
  switch (count.status) {
    case "draft":
      return {
        headline: <>Ready to <em>freeze</em></>,
        body: `Freezing records what Lamikraft One holds in ${warehouse} at that moment and lists every line to count. Stock keeps moving while you count.`,
      };
    case "frozen":
      return {
        headline: <>Counting in <em>progress</em></>,
        body: `${count.counted_lines} of ${plural(count.lines.length, "line", "lines")} counted so far. Enter what you find on the count sheet, then submit it for approval.`,
      };
    case "submitted":
      return {
        headline: <>Waiting for <em>approval</em></>,
        body:
          count.variance_lines === 0
            ? "Every line matches the records. Approval closes the stock take without changing stock."
            : `${plural(count.variance_lines, "line differs", "lines differ")} from the records. Approval posts the difference to the stock ledger.`,
      };
    case "posted":
      return {
        headline: <>Counted and <em>posted</em></>,
        body: count.variance_lines === 0 ? "The count matched the records. Nothing had to change." : `The difference on ${plural(count.variance_lines, "line", "lines")} is in the stock ledger.`,
      };
    case "cancelled":
      return { headline: "Cancelled", body: "Nothing was posted from this stock take. Stock stayed as the records held it." };
    default:
      return { headline: stockTakeStatus(count.status).label, body: "" };
  }
}

function Overview({ count, path, canSeeMovements }: { count: CountRead; path: string; canSeeMovements: boolean }) {
  const standing = standingOf(count);
  const counting = count.status === "frozen" && Boolean(count.capabilities.enter?.allowed);
  const person = (who: CountRead["created_by"], when?: string | null) =>
    who?.display_name ? (
      <span className="flex flex-col items-end">
        <span>{who.display_name}</span>
        {when ? <DateText value={when} style="dayTime" className="t-caption text-ink-3" /> : null}
      </span>
    ) : null;
  return (
    <Split
      main={
        <GlassPanel padding="lg" className="rise flex flex-col gap-6" eyebrow="Where it stands">
          <Steps label="Progress of this stock take" steps={progressOf(count)} />
          <div className="flex max-w-prose flex-col gap-2">
            <h2 className="t-display-sm text-ink">{standing.headline}</h2>
            {standing.body ? <p className="t-body text-ink-2">{standing.body}</p> : null}
          </div>
          {counting ? (
            <div>
              <ButtonLink href={asRoute(viewHref(path, "lines"))} iconRight="arrowRight">
                Enter counts
              </ButtonLink>
            </div>
          ) : null}
          {count.posting_id && canSeeMovements ? (
            <div>
              <ButtonLink href={asRoute(MOVEMENTS_PATH)} variant="secondary" iconRight="arrowRight">
                See stock movements
              </ButtonLink>
            </div>
          ) : null}
        </GlassPanel>
      }
      aside={
        <GlassPanel padding="md" className="rise" title="Who did what" titleAs="h2">
          <KeyValue
            rows
            items={[
              { label: "Started by", value: person(count.created_by, count.created_at) },
              { label: "Frozen by", value: person(count.frozen_by, count.frozen_at) },
              { label: "Submitted by", value: person(count.submitted_by) },
              { label: "Approved by", value: person(count.approved_by, count.approved_at) },
              ...(count.notes ? [{ label: "Notes", value: count.notes }] : []),
            ]}
          />
        </GlassPanel>
      }
    />
  );
}

// ---------------------------------------------------------------------------------------------
// Count sheet

function Sheet({ count, entries, missing, onEntry }: { count: CountRead; entries: Record<string, string>; missing: ReadonlySet<string>; onEntry: (lineId: string, value: string) => void }) {
  const canEnter = Boolean(count.capabilities.enter?.allowed);
  const qty = (value: string | null, unit: string, className?: string) => <Qty value={value === null ? null : { value, uom: unit }} className={className} />;
  const columns: Column<CountLine>[] = [
    { key: "product", header: "Product", primary: true, cell: (line) => <ProductCell product={line.product} /> },
    {
      key: "location",
      header: "Location",
      cell: (line) => (
        <span className="flex min-w-0 flex-col gap-0.5">
          <span className="lk-mono text-ink">{line.location.code}</span>
          {line.lot ? <span className="t-caption text-ink-3">Lot {line.lot.lot_code}</span> : null}
        </span>
      ),
    },
    { key: "system", header: "On record", numeric: true, cell: (line) => qty(line.system_quantity, line.unit) },
    {
      key: "counted",
      header: "Counted",
      numeric: true,
      width: canEnter ? "184px" : undefined,
      cell: (line) =>
        canEnter ? (
          <DecimalField
            label={`Counted quantity of ${line.product.product_key} at ${line.location.code}`}
            hideLabel
            size="sm"
            className="ml-auto w-40"
            suffix={line.unit}
            value={entries[line.id] ?? ""}
            onChange={(value) => onEntry(line.id, value)}
            error={missing.has(line.id) ? "Enter what you counted. Use 0 if there is none." : undefined}
          />
        ) : (
          qty(line.counted_quantity, line.unit, "t-label text-ink")
        ),
    },
    {
      key: "variance",
      header: "Difference",
      numeric: true,
      cell: (line) => qty(line.variance, line.unit, line.variance !== null && isDecimalStr(line.variance) && compareDecimalStr(line.variance, "0") !== 0 ? "t-label text-ink" : "text-ink-3"),
    },
  ];
  return (
    <GlassPanel padding="none" className="rise min-w-0">
      <DataTable
        label={`Count sheet of ${count.number}`}
        columns={columns}
        rows={count.lines}
        rowKey={(line) => line.id}
        empty={
          <EmptyState
            compact
            icon="clipboardCheck"
            title="Nothing to count yet"
            text={count.status === "draft" ? "Freeze the stock take to list what Lamikraft One holds in this warehouse." : "This stock take has no lines."}
          />
        }
      />
    </GlassPanel>
  );
}
