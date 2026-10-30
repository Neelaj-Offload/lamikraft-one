"use client";

import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { DemoBadge, StatusPill, type Tone } from "@/components/ui/badge";
import { Button, unavailableWhen } from "@/components/ui/button";
import { Switch } from "@/components/ui/choice";
import { DataTable, type DataTableColumn } from "@/components/ui/data-table";
import { Dialog } from "@/components/ui/dialog";
import { LocalDate } from "@/components/ui/format";
import { NumberField } from "@/components/ui/number-field";
import { ReasonDialog } from "@/components/ui/reason-dialog";
import { Select } from "@/components/ui/select";
import { EmptyState, ErrorState, Loading, PermissionDenied } from "@/components/ui/states";
import { TextField } from "@/components/ui/text-field";
import { useResourceCommand } from "@/features/sales/resource-command";
import { isProblemError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { CURRENCIES } from "@/lib/format/money";
import { useSession } from "@/lib/session/context";
import { commercialMessages as c } from "@/messages/commercial";
import { decideFxRate, fetchFxPolicy, fetchFxRates, proposeFxRate, updateFxPolicy, withdrawFxRate, type FxPolicy, type FxRate } from "./api";

const m = c.fx;
const TONE: Record<string, Tone> = { proposed: "warning", approved: "success", rejected: "danger", withdrawn: "neutral" };
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

/** FX rates: propose (two-person approval), decide, withdraw, and the conversion policy. */
export function FxRates() {
  const { permissionKeys } = useSession();
  const canRead = permissionKeys.has("pricing.fx_rate.read");
  const query = useQuery({ queryKey: queryKeys.pricing.fxRates({}), queryFn: ({ signal }) => fetchFxRates({}, signal), enabled: canRead });
  const keys = useMemo(() => [queryKeys.pricing.all()], []);
  const commands = useResourceCommand("fx", keys);
  const [proposing, setProposing] = useState(false);
  const [rejecting, setRejecting] = useState<FxRate | null>(null);
  if (!canRead) return <PermissionDenied area={m.title} />;

  const columns: DataTableColumn<FxRate>[] = [
    {
      id: "pair",
      header: m.columns.pair,
      isRowHeader: true,
      mobile: "title",
      cell: (row) => (
        <span className="tabular">
          1 {row.base_currency} = {row.rate} {row.quote_currency} {row.is_demo ? <DemoBadge /> : null}
        </span>
      ),
    },
    { id: "date", header: m.columns.date, mobile: "meta", cell: (row) => <LocalDate value={row.rate_date} /> },
    { id: "source", header: m.columns.source, cell: (row) => `${m.sources[row.source_kind] ?? row.source_kind} · ${row.source_reference}` },
    { id: "status", header: m.columns.status, mobile: "status", cell: (row) => <StatusPill tone={TONE[row.status] ?? "neutral"}>{m.status[row.status] ?? row.status}</StatusPill> },
    { id: "proposed", header: m.columns.proposed, cell: (row) => row.proposed_by_name ?? "—" },
    {
      id: "decided",
      header: m.columns.decided,
      cell: (row) =>
        row.capabilities.decide?.allowed ? (
          <div className="flex gap-1">
            <Button size="sm" variant="primary" onPress={() => void commands.run(`approve:${row.id}`, [row.version], () => decideFxRate(row.id, "approve", null), { done: m.decided, failed: c.common.failed(m.approve), conflictMessage: c.common.conflict })}>
              {m.approve}
            </Button>
            <Button size="sm" variant="danger" onPress={() => setRejecting(row)}>
              {m.reject}
            </Button>
          </div>
        ) : row.capabilities.withdraw?.allowed ? (
          <Button size="sm" variant="quiet" onPress={() => void commands.run(`withdraw:${row.id}`, [row.version], () => withdrawFxRate(row.id), { done: m.withdraw, failed: c.common.failed(m.withdraw) })}>
            {m.withdraw}
          </Button>
        ) : row.status === "proposed" && row.capabilities.decide?.reason_code === "separation_of_duties" ? (
          <span className="text-sm text-ink-muted">{m.selfDecision}</span>
        ) : (
          (row.decided_by_name ?? "—")
        ),
    },
  ];

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h1 className="text-[28px] font-bold tracking-tight md:text-3xl">{m.title}</h1>
          <p className="text-ink-muted">{m.intro}</p>
        </div>
        {permissionKeys.has("pricing.fx_rate.create") ? (
          <Button variant="primary" onPress={() => setProposing(true)}>
            {m.propose}
          </Button>
        ) : null}
      </header>
      {query.isPending ? (
        <Loading label={m.loadingList} />
      ) : query.isError ? (
        isProblemError(query.error) && query.error.status === 403 ? (
          <PermissionDenied area={m.title} headingLevel={2} />
        ) : (
          <ErrorState error={query.error} what={`the ${m.loadingList}`} onRetry={() => void query.refetch()} />
        )
      ) : (
        <DataTable caption={m.caption} hideCaption columns={columns} rows={query.data.items} rowId={(row) => row.id} empty={<EmptyState title={m.emptyTitle}>{m.empty}</EmptyState>} />
      )}
      <PolicySection />
      <ProposeDialog isOpen={proposing} onOpenChange={setProposing} commands={commands} />
      <ReasonDialog
        title={m.reject}
        description={rejecting ? `1 ${rejecting.base_currency} = ${rejecting.rate} ${rejecting.quote_currency}` : ""}
        requireNote
        noteLabel={c.common.reason}
        confirmLabel={m.reject}
        isOpen={rejecting !== null}
        isPending={commands.pending !== null}
        disabledReason={commands.offline}
        onOpenChange={(open) => (open ? null : setRejecting(null))}
        onConfirm={(_, note) =>
          rejecting
            ? void commands
                .run(`reject:${rejecting.id}`, [rejecting.version, note], () => decideFxRate(rejecting.id, "reject", note), { done: m.decided, failed: c.common.failed(m.reject), conflictMessage: c.common.conflict })
                .then(() => setRejecting(null))
            : undefined
        }
      />
    </div>
  );
}

function ProposeDialog({ isOpen, onOpenChange, commands }: { isOpen: boolean; onOpenChange: (open: boolean) => void; commands: ReturnType<typeof useResourceCommand> }) {
  const [form, setForm] = useState({ base_currency: "EUR", quote_currency: "USD", rate: null as string | null, rate_date: "", source_kind: "bank", source_reference: "" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const submit = async () => {
    const local: Record<string, string> = {};
    if (!form.rate) local.rate = "Enter the rate.";
    if (!ISO_DATE.test(form.rate_date)) local.rate_date = "Use YYYY-MM-DD.";
    if (!form.source_reference.trim()) local.source_reference = "Name the source.";
    if (form.base_currency === form.quote_currency) local.quote_currency = "Choose two different currencies.";
    if (Object.keys(local).length) return setErrors(local);
    const body = { ...form, source_reference: form.source_reference.trim() };
    const outcome = await commands.run("propose", [JSON.stringify(body)], () => proposeFxRate(body), { done: m.proposed, failed: c.common.failed(m.propose) });
    if (outcome.ok) onOpenChange(false);
    else setErrors(outcome.fieldErrors);
  };
  const currencies = CURRENCIES.map((code) => ({ id: code, label: code }));
  return (
    <Dialog
      title={m.propose}
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      footer={(close) => (
        <>
          <Button variant="quiet" onPress={close}>
            {c.common.cancel}
          </Button>
          <Button variant="primary" onPress={() => void submit()} isPending={commands.pending === "propose"} {...unavailableWhen(commands.offline)}>
            {m.propose}
          </Button>
        </>
      )}
    >
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Select label={m.fields.base_currency!} options={currencies} value={form.base_currency} onChange={(value) => setForm({ ...form, base_currency: value ?? "EUR" })} />
        <Select label={m.fields.quote_currency!} options={currencies} value={form.quote_currency} onChange={(value) => setForm({ ...form, quote_currency: value ?? "USD" })} errorMessage={errors.quote_currency} />
        <NumberField label={m.fields.rate!} value={form.rate} onChange={(rate) => setForm({ ...form, rate })} maxFractionDigits={6} isRequired errorMessage={errors.rate} />
        <TextField label={m.fields.rate_date!} placeholder="2026-10-09" value={form.rate_date} onChange={(rate_date) => setForm({ ...form, rate_date })} isRequired errorMessage={errors.rate_date} />
        <Select label={m.fields.source_kind!} options={Object.entries(m.sources).filter(([id]) => id !== "seed").map(([id, label]) => ({ id, label }))} value={form.source_kind} onChange={(value) => setForm({ ...form, source_kind: value ?? "bank" })} />
        <TextField label={m.fields.source_reference!} value={form.source_reference} onChange={(source_reference) => setForm({ ...form, source_reference })} maxLength={200} isRequired errorMessage={errors.source_reference} />
      </div>
    </Dialog>
  );
}

function PolicySection() {
  const query = useQuery({ queryKey: queryKeys.pricing.fxPolicy(), queryFn: ({ signal }) => fetchFxPolicy(signal) });
  const commands = useResourceCommand("fx_policy", [queryKeys.pricing.fxPolicy()]);
  const [draft, setDraft] = useState<FxPolicy | null>(null);
  if (query.isPending) return <Loading label={m.policy} variant="inline" />;
  if (query.isError) return <ErrorState error={query.error} what={m.policy} compact headingLevel={2} backToToday={false} onRetry={() => void query.refetch()} />;
  const policy = draft && draft.version === query.data.version ? draft : query.data;
  const canManage = query.data.capabilities.manage?.allowed === true;
  const dirty = draft !== null && JSON.stringify({ ...draft, capabilities: null }) !== JSON.stringify({ ...query.data, capabilities: null });
  return (
    <section aria-label={m.policy} className="flex flex-col gap-3 border-t pt-6">
      <h2 className="text-lg font-[650] text-ink">{m.policy}</h2>
      <Switch isSelected={policy.conversion_enabled} onChange={(value) => setDraft({ ...policy, conversion_enabled: value })} isDisabled={!canManage}>
        {m.policyEnabled}
      </Switch>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Select label={m.policySource} options={CURRENCIES.map((code) => ({ id: code, label: code }))} value={policy.conversion_source_currency} onChange={(value) => setDraft({ ...policy, conversion_source_currency: value ?? "EUR" })} isDisabled={!canManage} />
        <NumberField label={m.policyAge} value={String(policy.max_rate_age_days)} onChange={(value) => setDraft({ ...policy, max_rate_age_days: value ? Number.parseInt(value, 10) : 0 })} maxFractionDigits={0} isDisabled={!canManage} />
      </div>
      {canManage ? (
        <div>
          <Button
            variant={dirty ? "primary" : "secondary"}
            isPending={commands.pending === "save"}
            onPress={() =>
              void commands
                .run("save", [policy.version], () => updateFxPolicy(query.data, { conversion_enabled: policy.conversion_enabled, conversion_source_currency: policy.conversion_source_currency, max_rate_age_days: policy.max_rate_age_days }), {
                  done: m.policySaved,
                  failed: c.common.failed(c.common.save),
                  conflictMessage: c.common.conflict,
                })
                .then(() => setDraft(null))
            }
            {...unavailableWhen(commands.offline ?? (dirty ? null : "No changes to save"))}
          >
            {c.common.save}
          </Button>
        </div>
      ) : null}
    </section>
  );
}
