"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { AreaNav } from "@/components/shell/area-nav";
import { StatusPill, type Tone } from "@/components/ui/badge";
import { Button, unavailableWhen } from "@/components/ui/button";
import { RadioGroup } from "@/components/ui/choice";
import { DataTable, OffsetPagination, type DataTableColumn } from "@/components/ui/data-table";
import { LocalDateTime } from "@/components/ui/format";
import { KeyValueGrid, type KeyValue } from "@/components/ui/key-value-grid";
import { Link } from "@/components/ui/link";
import { NumberField } from "@/components/ui/number-field";
import { PageHeader } from "@/components/ui/page-header";
import { MetaDot, RecordHeader } from "@/components/ui/record-header";
import { SectionCard } from "@/components/ui/section-card";
import { Select } from "@/components/ui/select";
import { EmptyState, Loading } from "@/components/ui/states";
import { TextArea } from "@/components/ui/text-field";
import { useCommand } from "@/features/inventory/use-command";
import { failure, OPERATIONS_LEADING, positive, qty } from "@/features/procurement/shared";
import { queryKeys } from "@/lib/api/query-keys";
import { qualityMessages as m } from "@/messages/quality";
import { addsUpTo, decideInspection, fetchInspection, fetchInspections, INSPECTION_STATUSES, PAGE_SIZE, type ChecklistItem, type InspectionDetail, type InspectionSummary } from "./api";
import { inspectionListHref, type InspectionListState } from "./list-state";

type Push = Parameters<ReturnType<typeof useRouter>["push"]>[0];

const TONES: Record<string, Tone> = { pending: "warning", passed: "success", failed: "danger", cancelled: "neutral" };

export function InspectionStatusPill({ status }: { status: string }) {
  return <StatusPill tone={TONES[status] ?? "neutral"}>{m.status[status] ?? status}</StatusPill>;
}

// =====================================================================================================
// /operations/quality
// =====================================================================================================
export function InspectionsScreen({ state }: { state: InspectionListState }) {
  const router = useRouter();
  const l = m.list;
  const query = useQuery({
    queryKey: queryKeys.quality.inspections({ status: state.status, offset: state.offset }),
    queryFn: ({ signal }) => fetchInspections(state, signal),
  });
  const columns: DataTableColumn<InspectionSummary>[] = [
    {
      id: "number",
      header: l.columns.number,
      isRowHeader: true,
      mobile: "title",
      mobileCell: (i) => `${i.inspection_number} · ${i.product.product_key}`,
      cell: (i) => (
        <Link href={i.path} className="font-mono">
          {i.inspection_number}
        </Link>
      ),
    },
    { id: "subject", header: l.columns.subject, mobile: "meta", cell: (i) => `${m.subjects[i.subject_type] ?? i.subject_type} · ${i.subject_label}` },
    { id: "product", header: l.columns.product, cell: (i) => `${i.product.product_key} · ${i.product.name}` },
    { id: "warehouse", header: l.columns.warehouse, cell: (i) => i.warehouse.code },
    { id: "quantity", header: l.columns.quantity, numeric: true, mobile: "amount", cell: (i) => qty(i.quantity, i.unit) },
    { id: "status", header: l.columns.status, mobile: "status", cell: (i) => <InspectionStatusPill status={i.status} /> },
    { id: "requested", header: l.columns.requested, cell: (i) => <LocalDateTime value={i.requested_at} /> },
  ];
  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={l.title} intro={l.intro} nav={<AreaNav area="operations" label={m.area} leading={OPERATIONS_LEADING} />} />
      <div className="flex flex-wrap items-end gap-3">
        <Select
          label={l.status}
          className="min-w-56"
          options={[{ id: "", label: l.anyStatus }, ...INSPECTION_STATUSES.map((s) => ({ id: s, label: m.status[s] ?? s }))]}
          value={state.status ?? ""}
          onChange={(value) => router.push(inspectionListHref({ status: INSPECTION_STATUSES.find((s) => s === value) ?? null, offset: 0 }) as Push)}
        />
      </div>
      {query.isPending ? (
        <Loading label={l.loading} />
      ) : query.isError ? (
        failure(query.error, l.title, l.loading, () => void query.refetch())
      ) : (
        <DataTable
          caption={l.caption}
          hideCaption
          columns={columns}
          rows={query.data.items}
          rowId={(i) => i.id}
          rowHref={(i) => i.path}
          empty={<EmptyState title={l.emptyTitle}>{state.status ? l.emptyFiltered : l.empty}</EmptyState>}
          footer={
            <OffsetPagination
              label={l.pages}
              total={query.data.total}
              limit={query.data.limit || PAGE_SIZE}
              offset={query.data.offset}
              shown={query.data.items.length}
              control={(offset) => ({ href: inspectionListHref({ ...state, offset }) })}
            />
          }
        />
      )}
    </div>
  );
}

// =====================================================================================================
// /operations/quality/[inspectionId]
// =====================================================================================================
export function InspectionScreen({ inspectionId }: { inspectionId: string }) {
  const d = m.detail;
  const query = useQuery({ queryKey: queryKeys.quality.inspection(inspectionId), queryFn: ({ signal }) => fetchInspection(inspectionId, signal) });
  if (query.isPending) return <Loading label={d.loading} variant="detail" />;
  if (query.isError) return failure(query.error, d.permissionArea, d.loading, () => void query.refetch());
  return <Inspection insp={query.data} key={query.data.version} />;
}

function Inspection({ insp }: { insp: InspectionDetail }) {
  const d = m.detail;
  const decided = insp.status !== "pending";
  const facts: KeyValue[] = [
    {
      term: d.facts.subject,
      description: insp.source_path ? (
        <Link href={insp.source_path}>{`${m.subjects[insp.subject_type] ?? insp.subject_type} · ${insp.subject_label}`}</Link>
      ) : (
        `${m.subjects[insp.subject_type] ?? insp.subject_type} · ${insp.subject_label}`
      ),
    },
    { term: d.facts.product, description: `${insp.product.product_key} · ${insp.product.name}` },
    { term: d.facts.warehouse, description: `${insp.warehouse.code} · ${insp.warehouse.name}` },
    { term: d.facts.lot, description: insp.lot_code ?? "—" },
    { term: d.facts.quantity, description: qty(insp.quantity, insp.unit), numeric: true },
    { term: d.facts.decidedBy, description: insp.decided_by_name ?? "—" },
  ];
  return (
    <div className="flex flex-col gap-6">
      <RecordHeader
        back={{ href: "/operations/quality", label: d.back }}
        recordKey={insp.inspection_number}
        title={`${insp.product.product_key} · ${insp.product.name}`}
        status={<InspectionStatusPill status={insp.status} />}
        meta={
          <>
            <LocalDateTime value={insp.requested_at} />
            {insp.decided_at ? (
              <>
                <MetaDot />
                <LocalDateTime value={insp.decided_at} />
              </>
            ) : null}
          </>
        }
      />
      <KeyValueGrid items={facts} />
      {decided ? <Result insp={insp} /> : insp.capabilities.decide?.allowed ? <DecideForm insp={insp} /> : <p className="text-sm text-ink-muted">{d.cannotDecide}</p>}
    </div>
  );
}

function Result({ insp }: { insp: InspectionDetail }) {
  const d = m.detail;
  const reason = m.rejectReasons.find((r) => r.id === insp.reject_reason_code)?.label ?? insp.reject_reason_code;
  return (
    <SectionCard title={d.resultHeading}>
      <div className="flex flex-col gap-4">
        <KeyValueGrid
          items={[
            { term: d.accepted, description: qty(insp.qty_accepted, insp.unit), numeric: true },
            { term: d.rejected, description: qty(insp.qty_rejected, insp.unit), numeric: true },
            { term: d.reason, description: reason ?? "—" },
            { term: d.findings, description: insp.findings ?? "—" },
          ]}
        />
        {insp.checklist.length ? (
          <ul className="flex flex-col gap-1 text-sm">
            {insp.checklist.map((c) => (
              <li key={c.code} className="flex flex-wrap gap-2">
                <span className="text-ink">{c.label}</span>
                <StatusPill tone={c.result === "pass" ? "success" : c.result === "fail" ? "danger" : "neutral"}>{m.results[c.result] ?? c.result}</StatusPill>
                {c.note ? <span className="text-ink-muted">{c.note}</span> : null}
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </SectionCard>
  );
}

function DecideForm({ insp }: { insp: InspectionDetail }) {
  const d = m.detail;
  const key = useMemo(() => queryKeys.quality.inspection(insp.id), [insp.id]);
  const { run, pending, offline } = useCommand<InspectionDetail>(key);
  const [accepted, setAccepted] = useState<string | null>(insp.quantity);
  const [rejected, setRejected] = useState<string | null>("0");
  const [checklist, setChecklist] = useState<ChecklistItem[]>(insp.suggested_checklist);
  const [findings, setFindings] = useState("");
  const [reason, setReason] = useState<string | null>(null);
  const addsUp = accepted != null && rejected != null && addsUpTo(accepted, rejected, insp.quantity);
  const rejecting = positive(rejected);
  const explained = checklist.some((c) => c.result === "fail") || findings.trim().length > 0;
  const blocked = !addsUp ? d.mustAddUp(insp.quantity) : rejecting && !reason ? d.reasonNeeded : rejecting && !explained ? d.explainNeeded : null;
  return (
    <SectionCard title={d.decideHeading} description={d.decideIntro}>
      <div className="flex flex-col gap-5">
        <div className="flex flex-wrap gap-2">
          <Button
            size="sm"
            onPress={() => {
              setAccepted(insp.quantity);
              setRejected("0");
            }}
          >
            {d.acceptAll}
          </Button>
          <Button
            size="sm"
            onPress={() => {
              setAccepted("0");
              setRejected(insp.quantity);
            }}
          >
            {d.rejectAll}
          </Button>
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <NumberField label={d.accepted} value={accepted} onChange={setAccepted} uom={insp.unit} />
          <NumberField label={d.rejected} value={rejected} onChange={setRejected} uom={insp.unit} />
        </div>
        {!addsUp ? <p className="text-sm text-danger-text">{d.mustAddUp(insp.quantity)}</p> : null}
        <fieldset className="flex flex-col gap-3">
          <legend className="mb-2 text-sm font-[650] text-ink">{d.checklist}</legend>
          {checklist.map((c) => (
            <RadioGroup
              key={c.code}
              label={c.label}
              orientation="horizontal"
              options={(["pass", "fail", "na"] as const).map((r) => ({ value: r, label: m.results[r] ?? r }))}
              value={c.result}
              onChange={(value) =>
                setChecklist((all) => all.map((x) => (x.code === c.code ? { ...x, result: value === "fail" ? "fail" : value === "na" ? "na" : "pass" } : x)))
              }
            />
          ))}
        </fieldset>
        {rejecting ? <Select label={d.reason} options={m.rejectReasons} value={reason} onChange={setReason} placeholder={d.reasonPlaceholder} /> : null}
        <TextArea label={d.findings} value={findings} onChange={setFindings} maxLength={2000} />
        <div className="flex flex-wrap items-center gap-3">
          <Button
            variant="primary"
            isPending={pending === "decide"}
            {...unavailableWhen(offline ?? blocked)}
            onPress={() =>
              void run(
                "decide",
                (k) =>
                  decideInspection(
                    insp,
                    { qty_accepted: accepted ?? "0", qty_rejected: rejected ?? "0", checklist, findings, reject_reason_code: rejecting ? reason : null },
                    k,
                  ),
                { done: d.decided, failed: d.failed, write: (x) => x },
              )
            }
          >
            {d.decide}
          </Button>
          {blocked ? <span className="text-sm text-ink-muted">{blocked}</span> : null}
        </div>
      </div>
    </SectionCard>
  );
}
