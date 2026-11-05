"use client";

import { AreaNav } from "@/components/shell/area-nav";
import { PageHeader } from "@/components/ui/page-header";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { Link as RacLink } from "react-aria-components";
import { StatusPill, type Tone } from "@/components/ui/badge";
import { Button, unavailableWhen } from "@/components/ui/button";
import { DataTable, OffsetPagination, type DataTableColumn } from "@/components/ui/data-table";
import { DescriptionList } from "@/components/ui/description-list";
import { Dialog } from "@/components/ui/dialog";
import { LocalDate, LocalDateTime } from "@/components/ui/format";
import { Link } from "@/components/ui/link";
import { NumberField } from "@/components/ui/number-field";
import { SearchField } from "@/components/ui/search-field";
import { ComboBox, Select } from "@/components/ui/select";
import { EmptyState, ErrorState, Loading, PermissionDenied } from "@/components/ui/states";
import { linkClasses } from "@/components/ui/styles";
import { TextArea, TextField } from "@/components/ui/text-field";
import { usePartySearch } from "@/features/sales/pickers";
import { useResourceCommand } from "@/features/sales/resource-command";
import { isProblemError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { useSession } from "@/lib/session/context";
import { commercialMessages as c } from "@/messages/commercial";
import { createSample, fetchSample, fetchSamples, SAMPLE_STATUSES, SAMPLES_PAGE_SIZE, transitionSample, type Sample, type SampleTransitionRequest } from "./api";
import { SampleLineageSection } from "./lineage";
import { sampleListHref, type SampleListState } from "./list-state";

const m = c.samples;
export { sampleListStateFrom, sampleListHref, type SampleListState } from "./list-state";

const TONE: Record<string, Tone> = { requested: "neutral", dispatched: "info", delivered: "info", feedback_received: "success", closed: "neutral", cancelled: "neutral" };

export function SampleStatusPill({ status }: { status: string }) {
  return <StatusPill tone={TONE[status] ?? "neutral"}>{m.status[status] ?? c.human(status)}</StatusPill>;
}

function columns(): DataTableColumn<Sample>[] {
  return [
    {
      id: "number",
      header: m.columns.number,
      isRowHeader: true,
      mobile: "title",
      mobileCell: (row) => row.sample_number,
      cell: (row) => (
        <RacLink href={row.path} className={`${linkClasses} font-mono`}>
          {row.sample_number}
        </RacLink>
      ),
    },
    { id: "description", header: m.columns.description, mobile: "key", cell: (row) => row.description },
    { id: "customer", header: m.columns.customer, cell: (row) => row.party.display_name },
    { id: "linked", header: m.columns.linked, cell: (row) => [row.quote_number, row.custom_code].filter(Boolean).join(" · ") || c.common.noValue },
    { id: "status", header: m.columns.status, mobile: "status", cell: (row) => <SampleStatusPill status={row.status} /> },
    { id: "requested", header: m.columns.requested, mobile: "meta", cell: (row) => <LocalDate value={row.requested_on} /> },
  ];
}

export function SampleList({ state }: { state: SampleListState }) {
  const router = useRouter();
  const { permissionKeys } = useSession();
  const canRead = permissionKeys.has("sales.sample.read");
  const params = { q: state.q || null, status: state.status, offset: state.offset };
  const query = useQuery({ queryKey: queryKeys.sales.samples(params), queryFn: ({ signal }) => fetchSamples(params, signal), enabled: canRead });
  const [creating, setCreating] = useState(false);
  const go = (next: Partial<SampleListState>) => router.push(sampleListHref({ ...state, offset: 0, ...next }) as Parameters<typeof router.push>[0]);
  if (!canRead) return <PermissionDenied area={m.title} />;
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={m.title}
        intro={m.intro}
        nav={<AreaNav area="sales" label="Sales" leading={[{ id: "sales", label: "Overview", href: "/sales" }]} />}
        actions={
          <>
            {permissionKeys.has("sales.sample.create") ? (
              <Button variant="primary" onPress={() => setCreating(true)}>
                {m.newSample}
              </Button>
            ) : null}
          </>
        }
      />
      <div className="grid grid-cols-1 gap-4 md:grid-cols-[minmax(0,2fr)_minmax(0,1fr)] md:items-end">
        <SearchField label={c.common.search} placeholder={m.searchPlaceholder} defaultValue={state.q} onSubmit={(q) => go({ q })} onClear={() => go({ q: "" })} />
        <Select
          label={c.common.status}
          options={[{ id: "", label: c.common.anyStatus }, ...SAMPLE_STATUSES.map((status) => ({ id: status, label: m.status[status] ?? status }))]}
          value={state.status ?? ""}
          onChange={(value) => go({ status: SAMPLE_STATUSES.find((status) => status === value) ?? null })}
        />
      </div>
      {query.isPending ? (
        <Loading label={m.loadingList} />
      ) : query.isError ? (
        isProblemError(query.error) && query.error.status === 403 ? (
          <PermissionDenied area={m.title} headingLevel={2} />
        ) : (
          <ErrorState error={query.error} what={`the ${m.loadingList}`} onRetry={() => void query.refetch()} />
        )
      ) : (
        <DataTable
          caption={m.caption}
          hideCaption
          columns={columns()}
          rows={query.data.items}
          rowId={(row) => row.id}
          rowHref={(row) => row.path}
          empty={<EmptyState title={m.emptyTitle}>{m.empty}</EmptyState>}
          footer={
            <OffsetPagination
              label={c.common.pages}
              total={query.data.total}
              limit={query.data.limit || SAMPLES_PAGE_SIZE}
              offset={query.data.offset}
              shown={query.data.items.length}
              control={(offset) => ({ href: sampleListHref({ ...state, offset }) })}
            />
          }
        />
      )}
      <CreateSampleDialog isOpen={creating} onOpenChange={setCreating} />
    </div>
  );
}

function CreateSampleDialog({ isOpen, onOpenChange }: { isOpen: boolean; onOpenChange: (open: boolean) => void }) {
  const router = useRouter();
  const commands = useResourceCommand("sample:new", [["sales", "samples"]]);
  const [partyText, setPartyText] = useState("");
  const [party, setParty] = useState<string | null>(null);
  const [description, setDescription] = useState("");
  const [quantity, setQuantity] = useState<string | null>("1");
  const [unit, setUnit] = useState("pcs");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const parties = usePartySearch(partyText);
  const options = (parties.data ?? []).map((p) => ({ id: p.id, label: p.display_name, detail: p.party_number }));
  const submit = async () => {
    if (!party) return setErrors({ party_id: "Choose the customer." });
    const body = { party_id: party, description: description.trim() || undefined, quantity, unit_code: unit };
    const outcome = await commands.run("create", [JSON.stringify(body)], (key) => createSample(body, key), { failed: c.common.failed(m.create) });
    if (outcome.ok) router.push(outcome.value.path as Parameters<typeof router.push>[0]);
    else setErrors(outcome.fieldErrors);
  };
  return (
    <Dialog
      title={m.newSample}
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      footer={(close) => (
        <>
          <Button variant="quiet" onPress={close}>
            {c.common.cancel}
          </Button>
          <Button variant="primary" onPress={() => void submit()} isPending={commands.pending === "create"} {...unavailableWhen(commands.offline)}>
            {m.create}
          </Button>
        </>
      )}
    >
      <div className="flex flex-col gap-4">
        <ComboBox
          label={m.fields.party_id!}
          placeholder="Type a name or P-number"
          emptyText="No customer matches"
          options={options}
          value={party}
          inputValue={partyText}
          onInputChange={setPartyText}
          onChange={(id) => {
            setParty(id);
            const option = options.find((candidate) => candidate.id === id);
            if (option) setPartyText(option.label);
          }}
          isRequired
          errorMessage={errors.party_id}
        />
        <TextField label={m.fields.description!} value={description} onChange={setDescription} maxLength={500} errorMessage={errors.description} />
        <div className="grid grid-cols-2 gap-4">
          <NumberField label={m.fields.quantity!} value={quantity} onChange={setQuantity} maxFractionDigits={unit === "pcs" || unit === "set" ? 0 : 4} errorMessage={errors.quantity} />
          <Select label={m.fields.unit_code!} options={["pcs", "set", "sheets", "box", "sqm"].map((u) => ({ id: u, label: u }))} value={unit} onChange={(value) => setUnit(value ?? "pcs")} />
        </div>
      </div>
    </Dialog>
  );
}

export function SampleView({ sampleId }: { sampleId: string }) {
  const query = useQuery({ queryKey: queryKeys.sales.sample(sampleId), queryFn: ({ signal }) => fetchSample(sampleId, signal) });
  if (query.isPending) return <Loading label={m.loading} variant="detail" />;
  if (query.isError) {
    if (isProblemError(query.error) && query.error.status === 403) return <PermissionDenied area={m.title} />;
    return <ErrorState error={query.error} what={m.loading} onRetry={() => void query.refetch()} />;
  }
  return <SampleDetail sample={query.data} />;
}

function SampleDetail({ sample }: { sample: Sample }) {
  const keys = useMemo(() => [queryKeys.sales.sample(sample.id), ["sales", "samples"]], [sample.id]);
  const commands = useResourceCommand(`sample:${sample.id}`, keys);
  const [action, setAction] = useState<string | null>(null);
  const [form, setForm] = useState<SampleTransitionRequest>({ action: "" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const open = (next: string) => {
    setForm({ action: next, evidence_kind: next === "deliver" ? "courier_tracking" : null, feedback_outcome: next === "record_feedback" ? "positive" : null });
    setErrors({});
    setAction(next);
  };
  const confirm = async () => {
    const label = m.transitions[form.action] ?? c.human(form.action);
    const outcome = await commands.run(form.action, [sample.version, JSON.stringify(form)], (key) => transitionSample(sample, form, key), {
      done: label,
      failed: c.common.failed(label),
      conflictMessage: c.common.conflict,
    });
    if (outcome.ok) setAction(null);
    else setErrors(outcome.fieldErrors);
  };
  const d = (value: string | null | undefined) => (value && value.trim() ? value : c.common.noValue);
  return (
    <div className="flex flex-col gap-8">
      <header className="flex flex-col gap-2">
        <Link href="/sales/samples" className="text-sm">
          {m.back}
        </Link>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="font-mono text-[26px] font-bold tracking-tight text-ink md:text-3xl">{sample.sample_number}</h1>
          <SampleStatusPill status={sample.status} />
        </div>
        <p className="text-ink">
          {sample.description} <span className="text-ink-muted">· {sample.party.display_name}</span>
        </p>
      </header>
      <DescriptionList
        items={[
          { term: m.fields.quantity!, description: `${sample.quantity.replace(/\.?0+$/, "")} ${sample.unit_code}`, numeric: true },
          { term: m.fields.quote!, description: sample.quote_id && sample.quote_number ? <Link href={`/sales/quotes/${sample.quote_id}`}>{sample.quote_number}</Link> : c.common.noValue },
          { term: m.fields.custom_product!, description: sample.custom_product_id && sample.custom_code ? <Link href={`/sales/custom-products/${sample.custom_product_id}`}>{sample.custom_code}</Link> : c.common.noValue },
          { term: m.fields.requested_on!, description: <LocalDate value={sample.requested_on} /> },
          { term: m.fields.dispatched_at!, description: sample.dispatched_at ? <LocalDateTime value={sample.dispatched_at} /> : c.common.noValue },
          { term: m.fields.dispatch_reference!, description: d(sample.dispatch_reference) },
          { term: m.fields.delivered_at!, description: sample.delivered_at ? <LocalDateTime value={sample.delivered_at} /> : c.common.noValue },
          { term: m.fields.evidence_kind!, description: sample.delivery_evidence_kind ? (m.evidence[sample.delivery_evidence_kind] ?? sample.delivery_evidence_kind) : c.common.noValue },
          { term: m.fields.feedback!, description: <span className="whitespace-pre-line">{d(sample.feedback)}</span> },
          { term: m.fields.feedback_outcome!, description: sample.feedback_outcome ? (m.outcomes[sample.feedback_outcome] ?? sample.feedback_outcome) : c.common.noValue },
          { term: m.fields.notes!, description: d(sample.notes ?? sample.close_reason) },
        ]}
      />
      <SampleLineageSection sample={sample} />
      <section aria-label={c.customProducts.sections.actions} className="flex flex-col gap-3">
        <h2 className="text-lg font-[650] text-ink">{c.customProducts.sections.actions}</h2>
        {sample.allowed_transitions.length === 0 ? (
          <p className="text-ink-muted">{m.noTransitions}</p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {sample.allowed_transitions.map((t, index) => (
              <Button key={t.action} variant={t.action === "cancel" ? "danger" : index === 0 ? "primary" : "secondary"} onPress={() => open(t.action)} {...unavailableWhen(commands.offline)}>
                {m.transitions[t.action] ?? c.human(t.action)}
              </Button>
            ))}
          </div>
        )}
      </section>
      <Dialog
        title={action ? (m.transitions[action] ?? c.human(action)) : ""}
        description={sample.sample_number}
        isOpen={action !== null}
        onOpenChange={(next) => (next ? null : setAction(null))}
        footer={(close) => (
          <>
            <Button variant="quiet" onPress={close}>
              {c.common.cancel}
            </Button>
            <Button variant="primary" onPress={() => void confirm()} isPending={commands.pending !== null} {...unavailableWhen(commands.offline)}>
              {action ? (m.transitions[action] ?? c.human(action)) : ""}
            </Button>
          </>
        )}
      >
        <div className="flex flex-col gap-4">
          {action === "dispatch" ? (
            <TextField label={m.fields.dispatch_reference!} value={form.dispatch_reference ?? ""} onChange={(value) => setForm({ ...form, dispatch_reference: value })} maxLength={120} isRequired errorMessage={errors.dispatch_reference} />
          ) : null}
          {action === "deliver" ? (
            <Select label={m.fields.evidence_kind!} options={Object.entries(m.evidence).map(([id, label]) => ({ id, label }))} value={form.evidence_kind ?? null} onChange={(value) => setForm({ ...form, evidence_kind: value })} errorMessage={errors.evidence_kind} />
          ) : null}
          {action === "record_feedback" ? (
            <>
              <Select label={m.fields.feedback_outcome!} options={Object.entries(m.outcomes).map(([id, label]) => ({ id, label }))} value={form.feedback_outcome ?? null} onChange={(value) => setForm({ ...form, feedback_outcome: value })} />
              <TextArea label={m.fields.feedback!} value={form.feedback ?? ""} onChange={(value) => setForm({ ...form, feedback: value })} isRequired errorMessage={errors.feedback} />
            </>
          ) : null}
          {action === "cancel" || action === "close" ? (
            <TextArea label={c.common.reason} value={form.reason ?? ""} onChange={(value) => setForm({ ...form, reason: value })} isRequired={action === "cancel"} errorMessage={errors.reason} />
          ) : null}
        </div>
      </Dialog>
    </div>
  );
}
