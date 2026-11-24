"use client";

import { useQuery } from "@tanstack/react-query";
import { useMemo, type ReactNode } from "react";
import { useCommand } from "@/features/inventory/use-command";
import { fetchReceipt, postReceipt, type GrnDetail } from "@/features/procurement/api";
import { queryKeys } from "@/lib/api/query-keys";
import { Steps, type StepItem } from "~/screens/sales/quotations/parts";
import { inspectionStatus } from "~/screens/quality/labels";
import { Page, RecordHeader, Split } from "~/shell/page";
import { Badge, Button, Code, DataTable, DateText, EmptyState, FactStrip, GlassPanel, KeyValue, Qty, Tabs, TextLink, type Column } from "~/ui";
import { count, FAILED, receiptStatus } from "./labels";
import { LineName, OfflineBanner, RecordFailure, RecordLoading, stagger, StatusBadge } from "./parts";
import { asRoute, viewHref, type ReceiptView } from "./views";

type Line = GrnDetail["lines"][number];

/** A goods receipt: what arrived against which purchase order, whether it is in stock, and what waits for QC. */
export function ReceiptRecord({ grnId, view }: { grnId: string; view: ReceiptView }) {
  const query = useQuery({ queryKey: queryKeys.procurement.receipt(grnId), queryFn: ({ signal }) => fetchReceipt(grnId, signal) });
  if (query.isPending) return <RecordLoading label="Loading the goods receipt" />;
  if (query.isError) {
    return <RecordFailure error={query.error} what="This goods receipt" retry={() => void query.refetch()} backHref="/operations/purchasing/receipts" backLabel="All goods receipts" />;
  }
  return <Loaded grn={query.data} view={view} />;
}

function Loaded({ grn, view }: { grn: GrnDetail; view: ReceiptView }) {
  const key = useMemo(() => queryKeys.procurement.receipt(grn.id), [grn.id]);
  const { run, pending, offline } = useCommand<GrnDetail>(key);
  const path = `/operations/purchasing/receipts/${grn.id}`;
  const canPost = Boolean(grn.capabilities.post?.allowed);
  const post = () => void run("post", (k) => postReceipt(grn, k), { done: "Receipt posted", failed: FAILED, write: (next) => next });

  return (
    <Page>
      <RecordHeader
        breadcrumb={[{ label: "Operations", href: "/operations" }, { label: "Goods receipts", href: "/operations/purchasing/receipts" }, { label: grn.grn_number }]}
        code={grn.grn_number}
        title={grn.vendor.display_name}
        status={
          <>
            <StatusBadge look={receiptStatus(grn.status)} />
            {grn.awaiting_qc > 0 ? (
              <Badge tone="amber" icon="flask">
                {grn.awaiting_qc} in QC
              </Badge>
            ) : null}
          </>
        }
        lead={
          <>
            Received <DateText value={grn.received_on} style="business" /> against{" "}
            <TextLink href={asRoute(grn.purchase_order.path)}>{grn.purchase_order.number}</TextLink>
            {grn.posted_at ? (
              <>
                , posted <DateText value={grn.posted_at} style="dayTime" />
              </>
            ) : null}
            .
          </>
        }
        facts={
          <FactStrip
            items={[
              { label: "Purchase order", icon: "cart", value: <span className="lk-mono">{grn.purchase_order.number}</span> },
              { label: "Into", icon: "warehouse", value: grn.warehouse.name },
              { label: "Lines", icon: "list", value: grn.line_count },
              { label: "Waiting for QC", icon: "flask", value: count(grn.awaiting_qc, "line", "lines") },
              { label: "Vendor challan", icon: "fileText", value: grn.vendor_challan_ref },
            ]}
          />
        }
        actions={
          canPost ? (
            <Button iconLeft="packageOpen" loading={pending === "post"} isDisabled={Boolean(offline)} onPress={post}>
              Post receipt
            </Button>
          ) : null
        }
      >
        <Tabs
          label="Views of this goods receipt"
          selectedKey={view}
          tabs={[
            { id: "overview", label: "Overview", href: viewHref(path, "overview") },
            { id: "lines", label: "Lines", count: grn.lines.length, href: viewHref(path, "lines") },
          ]}
        />
      </RecordHeader>

      {offline ? <OfflineBanner what="this goods receipt" /> : null}

      {view === "overview" ? <Overview grn={grn} canPost={canPost} /> : null}
      {view === "lines" ? <LinesView grn={grn} /> : null}
    </Page>
  );
}

// ---------------------------------------------------------------------------------------------
// Overview: from the dock to stock

function progressOf(grn: GrnDetail): StepItem[] {
  const posted = grn.status === "posted" || grn.posted_at !== null;
  const qcLines = grn.lines.filter((line) => line.qc_required).length;
  const raw: { id: string; label: string; hint: ReactNode; done: boolean }[] = [
    { id: "received", label: "Received", hint: <DateText value={grn.received_on} style="business" />, done: true },
    { id: "posted", label: "Posted to stock", hint: grn.posted_at ? <DateText value={grn.posted_at} style="date" /> : "Adds the goods to stock", done: posted },
  ];
  if (qcLines > 0) {
    raw.push({ id: "inspected", label: "Inspected", hint: grn.awaiting_qc > 0 ? `${grn.awaiting_qc} of ${qcLines} still in QC` : count(qcLines, "line checked", "lines checked"), done: posted && grn.awaiting_qc === 0 });
  }
  const current = grn.status === "cancelled" ? -1 : raw.findIndex((step) => !step.done);
  return raw.map((step, index) => ({ id: step.id, label: step.label, hint: step.hint, state: step.done ? "done" : index === current ? "current" : "todo" }));
}

function standingOf(grn: GrnDetail, canPost: boolean): { headline: ReactNode; body: string } {
  switch (grn.status) {
    case "draft":
      return {
        headline: <>Not yet <em>posted</em></>,
        body: canPost ? `Check the lines, then post the receipt to add the goods to stock at ${grn.warehouse.name}.` : `The goods reach stock at ${grn.warehouse.name} once someone posts this receipt.`,
      };
    case "posted":
      return grn.awaiting_qc > 0
        ? { headline: <>Posted. Waiting for <em>QC</em></>, body: `${count(grn.awaiting_qc, "line waits", "lines wait")} in QC hold. Those goods join usable stock once they pass inspection.` }
        : { headline: <>In <em>stock</em></>, body: `Every line is in stock at ${grn.warehouse.name}.` };
    case "cancelled":
      return { headline: "Cancelled", body: "Nothing from this receipt reached stock." };
    default:
      return { headline: receiptStatus(grn.status).label, body: "" };
  }
}

function Overview({ grn, canPost }: { grn: GrnDetail; canPost: boolean }) {
  const standing = standingOf(grn, canPost);
  const checked = grn.lines.filter((line) => line.qc_required || line.inspection);
  return (
    <Split
      main={
        <>
          <GlassPanel padding="lg" className="rise flex flex-col gap-6" eyebrow="Where it stands">
            <Steps label="Progress of this goods receipt" steps={progressOf(grn)} />
            <div className="flex max-w-prose flex-col gap-2">
              <h2 className="t-display-sm text-ink">{standing.headline}</h2>
              {standing.body ? <p className="t-body text-ink-2">{standing.body}</p> : null}
            </div>
          </GlassPanel>
          <GlassPanel padding="md" className="rise" title="Quality checks" titleAs="h2">
            {checked.length === 0 ? (
              <p className="t-body-sm text-ink-3">No line on this receipt needs a quality check. The goods go straight to stock.</p>
            ) : (
              <ul className="flex flex-col">
                {checked.map((line, index) => (
                  <li key={line.id} className="rise-plain flex min-w-0 flex-wrap items-center justify-between gap-3 border-t border-line py-3 first:border-t-0 first:pt-0 last:pb-0" style={stagger(index)}>
                    <span className="flex min-w-0 flex-col gap-0.5">
                      <span className="t-label truncate text-ink" title={line.product.name}>
                        {line.product.name}
                      </span>
                      <span className="t-caption text-ink-3">
                        Line {line.line_no} · <Qty value={{ value: line.quantity, uom: line.unit }} />
                      </span>
                    </span>
                    {line.inspection ? (
                      <span className="flex flex-wrap items-center gap-2">
                        <TextLink href={asRoute(line.inspection.path)}>
                          <Code>{line.inspection.number}</Code>
                        </TextLink>
                        <StatusBadge look={inspectionStatus(line.inspection.status)} size="sm" />
                      </span>
                    ) : (
                      <Badge tone="cobalt" size="sm" icon="flask">
                        Needs QC
                      </Badge>
                    )}
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
              {
                label: "Purchase order",
                value: (
                  <TextLink href={asRoute(grn.purchase_order.path)}>
                    <Code>{grn.purchase_order.number}</Code>
                  </TextLink>
                ),
              },
              { label: "Vendor", value: grn.vendor.display_name },
              { label: "Into", value: `${grn.warehouse.code} · ${grn.warehouse.name}` },
              { label: "Vendor challan", value: grn.vendor_challan_ref },
              { label: "Vendor invoice", value: grn.vendor_invoice_ref },
              { label: "Posted by", value: grn.posted_by?.display_name },
              { label: "Notes", value: grn.notes },
            ]}
          />
        </GlassPanel>
      }
    />
  );
}

// ---------------------------------------------------------------------------------------------
// Lines

function LinesView({ grn }: { grn: GrnDetail }) {
  const columns: Column<Line>[] = [
    { key: "item", header: "Line", primary: true, cell: (line) => <LineName lineNo={line.line_no} name={line.product.name} productKey={line.product.product_key} note={`PO line ${line.po_line_no}`} /> },
    { key: "quantity", header: "Received", numeric: true, cell: (line) => <Qty value={{ value: line.quantity, uom: line.unit }} className="t-label text-ink" /> },
    { key: "lot", header: "Lot", cell: (line) => (line.lot_code ? <span className="lk-mono">{line.lot_code}</span> : null) },
    { key: "location", header: "Location", hideOnMobile: true, cell: (line) => (line.location_code ? <span className="lk-mono">{line.location_code}</span> : null) },
    {
      key: "qc",
      header: "Quality",
      cell: (line) =>
        line.inspection ? (
          <span className="flex flex-wrap items-center gap-2">
            <TextLink href={asRoute(line.inspection.path)}>
              <Code>{line.inspection.number}</Code>
            </TextLink>
            <StatusBadge look={inspectionStatus(line.inspection.status)} size="sm" />
          </span>
        ) : line.qc_required ? (
          <Badge tone="cobalt" size="sm" icon="flask">
            Needs QC
          </Badge>
        ) : (
          <span className="t-caption text-ink-3">No QC needed</span>
        ),
    },
  ];
  return (
    <div className="stack">
      <div className="flex min-w-0 flex-col gap-1">
        <h2 className="t-h3">Lines</h2>
        <p className="t-body-sm text-ink-3">What arrived on each line, the lot and location it went to, and its quality inspection.</p>
      </div>
      <GlassPanel padding="none" className="rise min-w-0">
        <DataTable
          label={`Lines of ${grn.grn_number}`}
          columns={columns}
          rows={grn.lines}
          rowKey={(line) => line.id}
          empty={<EmptyState compact icon="list" title="This receipt has no lines" text="Nothing was entered as received." />}
        />
      </GlassPanel>
    </div>
  );
}
