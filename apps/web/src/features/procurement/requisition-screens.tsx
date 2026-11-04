"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useMemo, useState, type FormEvent } from "react";
import { Form } from "react-aria-components";
import { AreaNav } from "@/components/shell/area-nav";
import { Button, unavailableWhen } from "@/components/ui/button";
import { DataTable, type DataTableColumn } from "@/components/ui/data-table";
import { DatePicker } from "@/components/ui/date-picker";
import { LocalDate, LocalDateTime } from "@/components/ui/format";
import { KeyValueGrid, type KeyValue } from "@/components/ui/key-value-grid";
import { Link } from "@/components/ui/link";
import { NumberField } from "@/components/ui/number-field";
import { PageHeader } from "@/components/ui/page-header";
import { ReasonDialog } from "@/components/ui/reason-dialog";
import { MetaDot, RecordHeader } from "@/components/ui/record-header";
import { SectionCard } from "@/components/ui/section-card";
import { ComboBox, Select } from "@/components/ui/select";
import { TextField } from "@/components/ui/text-field";
import { EmptyState, ErrorState, Loading } from "@/components/ui/states";
import { useRolePartySearch } from "@/features/challans/pickers";
import { fetchWarehouses } from "@/features/inventory/api";
import { useCommand } from "@/features/inventory/use-command";
import { useProductSearch, type ProductOption } from "@/features/sales/pickers";
import { queryKeys } from "@/lib/api/query-keys";
import { useSession } from "@/lib/session/context";
import { procurementMessages as m } from "@/messages/procurement";
import {
  convertRequisition,
  createRequisition,
  fetchRequisition,
  fetchRequisitions,
  REQUISITION_STATUSES,
  requisitionAction,
  type RequisitionDetail,
  type RequisitionSummary,
} from "./api";
import { failure, OPERATIONS_LEADING, positive, PurchasingTabs, qty, RequisitionStatusPill } from "./shared";

type Push = Parameters<ReturnType<typeof useRouter>["push"]>[0];

// =====================================================================================================
// /operations/purchasing/requisitions
// =====================================================================================================
export function RequisitionsScreen({ status }: { status: string | null }) {
  const router = useRouter();
  const { permissionKeys } = useSession();
  const l = m.requisitions;
  const query = useQuery({ queryKey: queryKeys.procurement.requisitions({ status }), queryFn: ({ signal }) => fetchRequisitions({ status }, signal) });
  const columns: DataTableColumn<RequisitionSummary>[] = [
    { id: "number", header: l.columns.number, isRowHeader: true, mobile: "title", mobileCell: (r) => r.requisition_number, cell: (r) => <Link href={r.path} className="font-mono">{r.requisition_number}</Link> },
    { id: "warehouse", header: l.columns.warehouse, cell: (r) => r.warehouse.code },
    { id: "status", header: l.columns.status, mobile: "status", cell: (r) => <RequisitionStatusPill status={r.status} /> },
    { id: "lines", header: l.columns.lines, numeric: true, cell: (r) => r.line_count },
    { id: "required", header: l.columns.requiredBy, mobile: "meta", cell: (r) => (r.required_by ? <LocalDate value={r.required_by} /> : "—") },
    { id: "owner", header: l.columns.owner, cell: (r) => r.owner.display_name ?? "—" },
    { id: "created", header: l.columns.created, cell: (r) => <LocalDateTime value={r.created_at} /> },
  ];
  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={l.title} intro={l.intro} nav={<AreaNav area="operations" label={m.area} leading={OPERATIONS_LEADING} />} />
      <PurchasingTabs current="requisitions" />
      <div className="flex flex-wrap items-end gap-3">
        <Select
          label={l.status}
          className="min-w-56"
          options={[{ id: "", label: l.anyStatus }, ...REQUISITION_STATUSES.map((s) => ({ id: s, label: m.requisitionStatus[s] ?? s }))]}
          value={status ?? ""}
          onChange={(value) => router.push((value ? `/operations/purchasing/requisitions?status=${value}` : "/operations/purchasing/requisitions") as Push)}
        />
      </div>
      {permissionKeys.has("procurement.requisition.create") ? <NewRequisition /> : null}
      {query.isPending ? (
        <Loading label={l.loading} />
      ) : query.isError ? (
        <ErrorState error={query.error} what={l.loading} onRetry={() => void query.refetch()} />
      ) : (
        <DataTable caption={l.caption} hideCaption columns={columns} rows={query.data.items} rowId={(r) => r.id} rowHref={(r) => r.path} empty={<EmptyState title={l.emptyTitle}>{l.empty}</EmptyState>} />
      )}
    </div>
  );
}

interface LineDraft {
  key: number;
  product: ProductOption | null;
  text: string;
  quantity: string | null;
}

function ProductLine({ line, onChange, onRemove }: { line: LineDraft; onChange: (next: LineDraft) => void; onRemove?: () => void }) {
  const l = m.requisitions;
  const search = useProductSearch(line.text);
  const options = [...(line.product ? [line.product] : []), ...(search.data ?? []).filter((p) => p.id !== line.product?.id)];
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_auto] sm:items-end">
      <ComboBox
        label={l.product}
        placeholder={l.productHint}
        emptyText={line.text.trim().length < 2 ? l.productHint : l.noProduct}
        options={options.map((p) => ({ id: p.id, label: p.product_name, detail: p.product_key }))}
        value={line.product?.id ?? null}
        inputValue={line.text}
        onInputChange={(text) => onChange({ ...line, text })}
        onChange={(id) => {
          const product = options.find((p) => p.id === id) ?? null;
          onChange({ ...line, product, text: product ? product.product_name : line.text });
        }}
      />
      <NumberField label={l.quantity} value={line.quantity} onChange={(quantity) => onChange({ ...line, quantity })} uom={line.product?.unit_of_sale ?? undefined} />
      {onRemove ? (
        <Button variant="quiet" onPress={onRemove}>
          {l.removeLine}
        </Button>
      ) : (
        <span />
      )}
    </div>
  );
}

function NewRequisition() {
  const router = useRouter();
  const l = m.requisitions;
  const warehouses = useQuery({ queryKey: queryKeys.inventory.warehouses(), queryFn: ({ signal }) => fetchWarehouses(signal) });
  const [warehouse, setWarehouse] = useState<string | null>(null);
  const [requiredBy, setRequiredBy] = useState<string | null>(null);
  const [notes, setNotes] = useState("");
  const [lines, setLines] = useState<LineDraft[]>([{ key: 1, product: null, text: "", quantity: null }]);
  const [submitted, setSubmitted] = useState(false);
  const listKey = useMemo(() => queryKeys.procurement.all(), []);
  const { run, pending, offline } = useCommand<null>(listKey);
  const chosen = warehouse ?? warehouses.data?.[0]?.id ?? null;
  const complete = lines.filter((x) => x.product && x.quantity);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitted(true);
    if (!chosen || complete.length === 0) return;
    const created = await run(
      "create",
      (k) =>
        createRequisition(
          { warehouse_id: chosen, required_by: requiredBy, notes, lines: complete.map((x) => ({ product_id: x.product!.id, quantity: x.quantity! })) },
          k,
        ),
      { done: l.created, failed: m.failed },
    );
    if (created) router.push(created.path as Push);
  };

  return (
    <SectionCard title={l.newTitle}>
      <Form onSubmit={submit} className="flex flex-col gap-4" validationBehavior="aria" aria-label={l.newTitle}>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <Select
            label={l.warehouse}
            options={(warehouses.data ?? []).map((wh) => ({ id: wh.id, label: `${wh.code} · ${wh.name}` }))}
            value={chosen ?? ""}
            onChange={setWarehouse}
          />
          <DatePicker label={l.requiredBy} value={requiredBy} onChange={setRequiredBy} />
          <TextField label={l.notes} value={notes} onChange={setNotes} maxLength={1000} />
        </div>
        <fieldset className="flex flex-col gap-3">
          <legend className="mb-2 text-sm font-[650] text-ink">{l.linesHeading}</legend>
          {lines.map((line) => (
            <ProductLine
              key={line.key}
              line={line}
              onChange={(next) => setLines((all) => all.map((x) => (x.key === line.key ? next : x)))}
              onRemove={lines.length > 1 ? () => setLines((all) => all.filter((x) => x.key !== line.key)) : undefined}
            />
          ))}
          {submitted && complete.length === 0 ? <p className="text-sm text-danger-text">{l.noLines}</p> : null}
        </fieldset>
        <div className="flex flex-wrap gap-3">
          <Button onPress={() => setLines((all) => [...all, { key: Math.max(...all.map((x) => x.key)) + 1, product: null, text: "", quantity: null }])}>{l.addLine}</Button>
          <Button type="submit" variant="primary" isPending={pending === "create"} {...unavailableWhen(offline)}>
            {l.create}
          </Button>
        </div>
      </Form>
    </SectionCard>
  );
}

// =====================================================================================================
// /operations/purchasing/requisitions/[requisitionId]
// =====================================================================================================
export function RequisitionScreen({ requisitionId }: { requisitionId: string }) {
  const d = m.requisition;
  const query = useQuery({ queryKey: queryKeys.procurement.requisition(requisitionId), queryFn: ({ signal }) => fetchRequisition(requisitionId, signal) });
  if (query.isPending) return <Loading label={d.loading} variant="detail" />;
  if (query.isError) return failure(query.error, d.permissionArea, d.loading, () => void query.refetch());
  return <Requisition r={query.data} key={query.data.version} />;
}

function Requisition({ r }: { r: RequisitionDetail }) {
  const router = useRouter();
  const d = m.requisition;
  const key = useMemo(() => queryKeys.procurement.requisition(r.id), [r.id]);
  const { run, pending, offline } = useCommand<RequisitionDetail>(key);
  const [dialog, setDialog] = useState<null | "reject" | "cancel">(null);
  const [converting, setConverting] = useState(false);
  const caps = r.capabilities;
  const act = (action: "submit" | "approve" | "reject" | "cancel", done: string, note?: string) =>
    void run(action, (k) => requisitionAction(r, action, k, note), { done, failed: m.failed, write: (x) => x });

  const facts: KeyValue[] = [
    { term: d.facts.warehouse, description: `${r.warehouse.code} · ${r.warehouse.name}` },
    { term: d.facts.requiredBy, description: r.required_by ? <LocalDate value={r.required_by} /> : "—" },
    { term: d.facts.raisedBy, description: r.owner.display_name ?? "—" },
    { term: d.facts.decidedBy, description: r.decided_by?.display_name ? `${r.decided_by.display_name}${r.decision_note ? ` · ${r.decision_note}` : ""}` : "—" },
  ];
  const columns: DataTableColumn<RequisitionDetail["lines"][number]>[] = [
    { id: "no", header: d.columns.line, numeric: true, cell: (x) => x.line_no },
    { id: "product", header: d.columns.product, isRowHeader: true, mobile: "title", cell: (x) => `${x.product.product_key} · ${x.product.name}` },
    { id: "qty", header: d.columns.quantity, numeric: true, mobile: "amount", cell: (x) => qty(x.quantity, x.unit) },
    { id: "ordered", header: d.columns.ordered, numeric: true, cell: (x) => qty(x.qty_ordered, x.unit) },
    { id: "remaining", header: d.columns.remaining, numeric: true, cell: (x) => qty(x.qty_remaining, x.unit) },
    { id: "required", header: d.columns.requiredBy, cell: (x) => (x.required_by ? <LocalDate value={x.required_by} /> : "—") },
  ];
  const actions = (
    <>
      {caps.submit?.allowed ? (
        <Button variant="primary" isPending={pending === "submit"} onPress={() => act("submit", d.submitted)} {...unavailableWhen(offline)}>
          {d.submit}
        </Button>
      ) : null}
      {caps.approve?.allowed ? (
        <Button variant="primary" isPending={pending === "approve"} onPress={() => act("approve", d.approved)} {...unavailableWhen(offline)}>
          {d.approve}
        </Button>
      ) : null}
      {caps.reject?.allowed ? <Button onPress={() => setDialog("reject")}>{d.reject}</Button> : null}
      {caps.convert?.allowed ? (
        <Button variant="primary" onPress={() => setConverting(true)}>
          {d.convert}
        </Button>
      ) : null}
      {caps.cancel?.allowed ? (
        <Button variant="quiet" onPress={() => setDialog("cancel")}>
          {d.cancel}
        </Button>
      ) : null}
    </>
  );
  return (
    <div className="flex flex-col gap-6">
      <RecordHeader
        back={{ href: "/operations/purchasing/requisitions", label: d.back }}
        recordKey={r.requisition_number}
        title={`${r.warehouse.code} · ${r.warehouse.name}`}
        status={<RequisitionStatusPill status={r.status} />}
        meta={
          <>
            <span>{r.owner.display_name}</span>
            <MetaDot />
            <LocalDateTime value={r.created_at} />
          </>
        }
        actions={actions}
      />
      {caps.approve?.reason_code === "approver_is_requester" ? <p className="text-sm text-ink-muted">{d.ownRequest}</p> : null}
      <KeyValueGrid items={facts} />
      <SectionCard title={m.requisitions.linesHeading}>
        <DataTable caption={m.requisitions.linesHeading} hideCaption columns={columns} rows={r.lines} rowId={(x) => x.id} />
      </SectionCard>
      {r.purchase_orders.length ? (
        <SectionCard title={d.purchaseOrders}>
          <ul className="flex flex-col gap-1">
            {r.purchase_orders.map((po) => (
              <li key={po.id}>
                <Link href={po.path} className="font-mono">
                  {po.number}
                </Link>{" "}
                <span className="text-sm text-ink-muted">{m.poStatus[po.status] ?? po.status}</span>
              </li>
            ))}
          </ul>
        </SectionCard>
      ) : null}
      {converting ? (
        <ConvertPanel
          r={r}
          pending={pending === "convert"}
          onCancel={() => setConverting(false)}
          onConvert={(vendor, prices) =>
            void run("convert", (k) => convertRequisition(r, vendor, prices, k), { done: d.converted, failed: m.failed }).then((po) => {
              if (po) router.push(po.path as Push);
            })
          }
        />
      ) : null}
      <ReasonDialog
        title={dialog === "reject" ? d.rejectTitle : d.cancelTitle}
        requireNote
        noteLabel={d.reasonLabel}
        confirmLabel={dialog === "reject" ? d.reject : d.cancel}
        isOpen={dialog !== null}
        isPending={pending === "reject" || pending === "cancel"}
        disabledReason={offline}
        onOpenChange={(open) => (open ? undefined : setDialog(null))}
        onConfirm={(_code, note) => {
          const which = dialog;
          setDialog(null);
          if (which) act(which, which === "reject" ? d.rejected : d.cancelled, note);
        }}
      />
    </div>
  );
}

function ConvertPanel({
  r,
  pending,
  onCancel,
  onConvert,
}: {
  r: RequisitionDetail;
  pending: boolean;
  onCancel: () => void;
  onConvert: (vendorId: string, prices: Record<string, string>) => void;
}) {
  const d = m.requisition;
  const [text, setText] = useState("");
  const [vendor, setVendor] = useState<{ id: string; label: string } | null>(null);
  const [prices, setPrices] = useState<Record<string, string | null>>({});
  const vendors = useRolePartySearch(text, "vendor");
  const options = [...(vendor ? [vendor] : []), ...(vendors.data ?? []).map((p) => ({ id: p.id, label: p.display_name, detail: p.party_number })).filter((p) => p.id !== vendor?.id)];
  const open = r.lines.filter((x) => positive(x.qty_remaining));
  return (
    <SectionCard title={d.convertTitle}>
      <div className="flex flex-col gap-4">
        <ComboBox
          label={d.vendor}
          placeholder={d.vendorHint}
          emptyText={text.trim().length < 2 ? d.vendorHint : d.noVendor}
          options={options}
          value={vendor?.id ?? null}
          inputValue={text}
          onInputChange={setText}
          onChange={(id) => {
            const found = options.find((o) => o.id === id) ?? null;
            setVendor(found ? { id: found.id, label: found.label } : null);
            if (found) setText(found.label);
          }}
        />
        {open.map((x) => (
          <NumberField
            key={x.id}
            label={d.priceFor(x.product.product_key)}
            value={prices[x.id] ?? null}
            onChange={(value) => setPrices((all) => ({ ...all, [x.id]: value }))}
          />
        ))}
        <div className="flex gap-3">
          <Button
            variant="primary"
            isPending={pending}
            {...unavailableWhen(vendor ? null : d.vendorHint)}
            onPress={() =>
              vendor ? onConvert(vendor.id, Object.fromEntries(Object.entries(prices).filter((e): e is [string, string] => Boolean(e[1])))) : undefined
            }
          >
            {d.convert}
          </Button>
          <Button variant="quiet" onPress={onCancel}>
            {d.cancel}
          </Button>
        </div>
      </div>
    </SectionCard>
  );
}
