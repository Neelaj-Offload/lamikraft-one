"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useMemo } from "react";
import { AreaNav } from "@/components/shell/area-nav";
import { StatusPill } from "@/components/ui/badge";
import { Button, unavailableWhen } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/choice";
import { DataTable, type DataTableColumn } from "@/components/ui/data-table";
import { LocalDate, LocalDateTime } from "@/components/ui/format";
import { KeyValueGrid, type KeyValue } from "@/components/ui/key-value-grid";
import { Link } from "@/components/ui/link";
import { PageHeader } from "@/components/ui/page-header";
import { MetaDot, RecordHeader } from "@/components/ui/record-header";
import { SectionCard } from "@/components/ui/section-card";
import { EmptyState, ErrorState, Loading } from "@/components/ui/states";
import { useCommand } from "@/features/inventory/use-command";
import { queryKeys } from "@/lib/api/query-keys";
import { procurementMessages as m } from "@/messages/procurement";
import { qualityMessages as qm } from "@/messages/quality";
import { fetchReceipt, fetchReceipts, postReceipt, type GrnDetail, type GrnSummary } from "./api";
import { dash, failure, OPERATIONS_LEADING, PurchasingTabs, qty } from "./shared";

type Push = Parameters<ReturnType<typeof useRouter>["push"]>[0];
const r = m.receipt;

export function ReceiptsScreen({ awaitingQc }: { awaitingQc: boolean }) {
  const router = useRouter();
  const l = m.receipts;
  const query = useQuery({ queryKey: queryKeys.procurement.receipts({ awaitingQc }), queryFn: ({ signal }) => fetchReceipts({ awaitingQc }, signal) });
  const columns: DataTableColumn<GrnSummary>[] = [
    { id: "number", header: l.columns.number, isRowHeader: true, mobile: "title", mobileCell: (g) => g.grn_number, cell: (g) => <Link href={g.path} className="font-mono">{g.grn_number}</Link> },
    { id: "po", header: l.columns.po, cell: (g) => <Link href={g.purchase_order.path} className="font-mono">{g.purchase_order.number}</Link> },
    { id: "vendor", header: l.columns.vendor, cell: (g) => g.vendor.display_name },
    { id: "warehouse", header: l.columns.warehouse, cell: (g) => g.warehouse.code },
    { id: "received", header: l.columns.received, mobile: "meta", cell: (g) => <LocalDate value={g.received_on} /> },
    { id: "status", header: l.columns.status, mobile: "status", cell: (g) => <StatusPill tone={g.status === "posted" ? "success" : "neutral"}>{m.grnStatus[g.status] ?? g.status}</StatusPill> },
    { id: "qc", header: l.columns.qc, numeric: true, cell: (g) => (g.awaiting_qc ? <StatusPill tone="warning">{g.awaiting_qc}</StatusPill> : dash) },
  ];
  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={l.title} intro={l.intro} nav={<AreaNav area="operations" label={m.area} leading={OPERATIONS_LEADING} />} />
      <PurchasingTabs current="receipts" />
      <Checkbox
        isSelected={awaitingQc}
        onChange={(on) => router.push((on ? "/operations/purchasing/receipts?awaiting_qc=1" : "/operations/purchasing/receipts") as Push)}
      >
        {l.awaitingQcOnly}
      </Checkbox>
      {query.isPending ? (
        <Loading label={l.loading} />
      ) : query.isError ? (
        <ErrorState error={query.error} what={l.loading} onRetry={() => void query.refetch()} />
      ) : (
        <DataTable caption={l.caption} hideCaption columns={columns} rows={query.data.items} rowId={(g) => g.id} rowHref={(g) => g.path} empty={<EmptyState title={l.emptyTitle}>{l.empty}</EmptyState>} />
      )}
    </div>
  );
}

export function ReceiptScreen({ grnId }: { grnId: string }) {
  const query = useQuery({ queryKey: queryKeys.procurement.receipt(grnId), queryFn: ({ signal }) => fetchReceipt(grnId, signal) });
  if (query.isPending) return <Loading label={r.loading} variant="detail" />;
  if (query.isError) return failure(query.error, r.permissionArea, r.loading, () => void query.refetch());
  return <Receipt grn={query.data} key={query.data.version} />;
}

function Receipt({ grn }: { grn: GrnDetail }) {
  const key = useMemo(() => queryKeys.procurement.receipt(grn.id), [grn.id]);
  const { run, pending, offline } = useCommand<GrnDetail>(key);
  const facts: KeyValue[] = [
    { term: r.facts.po, description: <Link href={grn.purchase_order.path}>{grn.purchase_order.number}</Link> },
    { term: r.facts.vendor, description: grn.vendor.display_name },
    { term: r.facts.warehouse, description: `${grn.warehouse.code} · ${grn.warehouse.name}` },
    { term: r.facts.challan, description: grn.vendor_challan_ref ?? "—" },
    { term: r.facts.posting, description: grn.posting_id ? r.posted : "—" },
  ];
  const c = r.columns;
  const columns: DataTableColumn<GrnDetail["lines"][number]>[] = [
    { id: "no", header: c.line, numeric: true, cell: (x) => x.line_no },
    { id: "product", header: c.product, isRowHeader: true, mobile: "title", cell: (x) => `${x.product.product_key} · ${x.product.name}` },
    { id: "qty", header: c.quantity, numeric: true, mobile: "amount", cell: (x) => qty(x.quantity, x.unit) },
    { id: "lot", header: c.lot, cell: (x) => x.lot_code ?? dash },
    { id: "location", header: c.location, cell: (x) => x.location_code ?? dash },
    {
      id: "qc",
      header: c.qc,
      mobile: "status",
      cell: (x) =>
        x.inspection ? (
          <span className="flex flex-wrap items-center gap-2">
            <Link href={x.inspection.path} className="font-mono">
              {x.inspection.number}
            </Link>
            <StatusPill tone={x.inspection.status === "pending" ? "warning" : x.inspection.status === "passed" ? "success" : "danger"}>
              {qm.status[x.inspection.status] ?? x.inspection.status}
            </StatusPill>
          </span>
        ) : (
          <span className="text-sm text-ink-muted">{r.qcFree}</span>
        ),
    },
  ];
  return (
    <div className="flex flex-col gap-6">
      <RecordHeader
        back={{ href: "/operations/purchasing/receipts", label: r.back }}
        recordKey={grn.grn_number}
        title={grn.vendor.display_name}
        status={<StatusPill tone={grn.status === "posted" ? "success" : "neutral"}>{m.grnStatus[grn.status] ?? grn.status}</StatusPill>}
        meta={
          <>
            <LocalDate value={grn.received_on} />
            {grn.posted_at ? (
              <>
                <MetaDot />
                <LocalDateTime value={grn.posted_at} />
              </>
            ) : null}
          </>
        }
        actions={
          grn.capabilities.post?.allowed ? (
            <Button variant="primary" isPending={pending === "post"} {...unavailableWhen(offline)} onPress={() => void run("post", (k) => postReceipt(grn, k), { done: r.posted, failed: m.failed, write: (x) => x })}>
              {r.post}
            </Button>
          ) : null
        }
      />
      <KeyValueGrid items={facts} />
      <SectionCard title={m.requisitions.linesHeading}>
        <DataTable caption={m.requisitions.linesHeading} hideCaption columns={columns} rows={grn.lines} rowId={(x) => x.id} />
      </SectionCard>
    </div>
  );
}
