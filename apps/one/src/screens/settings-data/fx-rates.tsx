"use client";

import { useState } from "react";
import { decideFxRate, proposeFxRate, updateFxPolicy, withdrawFxRate, type FxPolicy, type FxRate } from "@/features/pricing/api";
import { useResourceCommand } from "@/features/sales/resource-command";
import { isProblemError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { CURRENCIES } from "@/lib/format/money";
import { useSession } from "@/lib/session/context";
import { FX_CREATE, FX_READ, useFxPolicy, useFxRates } from "~/data/settings-data";
import { Page, PageHeader } from "~/shell/page";
import { ErrorBlock, LoadingBlock, NotPermitted } from "~/shell/states";
import {
  Badge,
  Banner,
  Button,
  ConfirmDialog,
  DataTable,
  DatePicker,
  DateText,
  DecimalField,
  EmptyState,
  FormActions,
  FormSection,
  GlassPanel,
  IntegerField,
  Modal,
  ReasonDialog,
  Select,
  Switch,
  Tabs,
  TextField,
  type Column,
} from "~/ui";
import { asRoute, lookOf, Quiet, SETTINGS_CRUMBS, StatusBadge, type StatusLook } from "./shared";

/**
 * Exchange rates: dated, sourced, and only used once a second person approves them. The second
 * view (`?view=policy`) holds the rule for when an approved rate may convert a price.
 */

export type FxView = "rates" | "policy";

const RATE_KEYS = [queryKeys.pricing.all()];
const POLICY_KEYS = [queryKeys.pricing.fxPolicy()];
const CONFLICT = "Someone else changed this while you were working. The latest version is on screen; check it, then try again.";

const STATUS: Record<string, StatusLook> = {
  proposed: { label: "Waiting for approval", tone: "amber" },
  approved: { label: "Approved", tone: "leaf" },
  rejected: { label: "Rejected", tone: "ember" },
  withdrawn: { label: "Withdrawn", tone: "neutral" },
};
const SOURCE: Record<string, string> = { manual: "Entered by hand", bank: "Bank", ecb_reference: "ECB reference rate", seed: "Demo data", other: "Other" };
const PROPOSABLE_SOURCES = ["bank", "ecb_reference", "manual", "other"] as const;

type Commands = ReturnType<typeof useResourceCommand>;

function RateText({ rate }: { rate: FxRate }) {
  return (
    <span className="lk-tnum whitespace-nowrap">
      1 {rate.base_currency} = {rate.rate} {rate.quote_currency}
    </span>
  );
}

function ProposeDialog({ isOpen, onOpenChange, commands }: { isOpen: boolean; onOpenChange: (open: boolean) => void; commands: Commands }) {
  const [form, setForm] = useState({ base_currency: "EUR", quote_currency: "USD", rate: "", rate_date: null as string | null, source_kind: "bank", source_reference: "" });
  const [errors, setErrors] = useState<Record<string, string>>({});

  const submit = async () => {
    const local: Record<string, string> = {};
    if (!form.rate) local.rate = "Enter the rate, for example 1.0850.";
    if (!form.rate_date) local.rate_date = "Choose the day this rate was published.";
    if (!form.source_reference.trim()) local.source_reference = "Say where the rate comes from, so the approver can check it.";
    if (form.base_currency === form.quote_currency) local.quote_currency = "Choose two different currencies.";
    if (Object.keys(local).length > 0) return setErrors(local);
    const body = { ...form, source_reference: form.source_reference.trim() };
    const outcome = await commands.run("propose", [JSON.stringify(body)], () => proposeFxRate(body), { done: "Rate proposed. Someone else approves it.", failed: "The rate was not proposed" });
    if (outcome.ok) {
      setErrors({});
      setForm((current) => ({ ...current, rate: "", source_reference: "" }));
      onOpenChange(false);
    } else setErrors(outcome.fieldErrors);
  };

  const currencies = CURRENCIES.map((code) => ({ value: code, label: code }));
  return (
    <Modal
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      title="Propose a rate"
      description="A rate converts prices only after a second person approves it."
      actions={
        <>
          <Button variant="ghost" onPress={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onPress={() => void submit()} loading={commands.pending === "propose"} isDisabled={Boolean(commands.offline)}>
            Propose rate
          </Button>
        </>
      }
    >
      <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
        <Select label="From" options={currencies} value={form.base_currency} onChange={(base_currency) => setForm({ ...form, base_currency })} error={errors.base_currency || undefined} />
        <Select label="To" options={currencies} value={form.quote_currency} onChange={(quote_currency) => setForm({ ...form, quote_currency })} error={errors.quote_currency || undefined} />
        <DecimalField
          label="Rate"
          isRequired
          value={form.rate}
          onChange={(rate) => setForm({ ...form, rate })}
          maxFractionDigits={6}
          prefix={`1 ${form.base_currency} =`}
          suffix={form.quote_currency}
          error={errors.rate || undefined}
        />
        <DatePicker label="Rate date" isRequired value={form.rate_date} onChange={(rate_date) => setForm({ ...form, rate_date })} error={errors.rate_date || undefined} />
        <Select
          label="Source"
          options={PROPOSABLE_SOURCES.map((kind) => ({ value: kind, label: SOURCE[kind] ?? kind }))}
          value={form.source_kind}
          onChange={(source_kind) => setForm({ ...form, source_kind })}
          error={errors.source_kind || undefined}
        />
        <TextField
          label="Source reference"
          isRequired
          value={form.source_reference}
          onChange={(source_reference) => setForm({ ...form, source_reference })}
          maxLength={200}
          placeholder="Bank advice number, or the page it was read from"
          error={errors.source_reference || undefined}
        />
      </div>
    </Modal>
  );
}

function Rates({ commands, canPropose, onPropose }: { commands: Commands; canPropose: boolean; onPropose: () => void }) {
  const query = useFxRates();
  const [approving, setApproving] = useState<FxRate | null>(null);
  const [rejecting, setRejecting] = useState<FxRate | null>(null);
  const [withdrawing, setWithdrawing] = useState<FxRate | null>(null);
  const offline = Boolean(commands.offline);

  /** Holds the dialog open on a plain failure; a conflict reloads the list, so the dialog closes. */
  const settle = (outcome: { ok: true } | { ok: false; conflict: boolean; error: unknown }) => {
    if (!outcome.ok && !outcome.conflict) throw outcome.error;
  };

  if (query.isError && !query.data) {
    if (isProblemError(query.error) && query.error.status === 403) return <NotPermitted what="Exchange rates" icon="banknote" />;
    return <ErrorBlock error={query.error} what="Exchange rates" onRetry={() => void query.refetch()} />;
  }

  const columns: Column<FxRate>[] = [
    {
      key: "rate",
      header: "Rate",
      primary: true,
      cell: (rate) => (
        <span className="flex min-w-0 flex-wrap items-center gap-2">
          <span className="t-label text-ink">
            <RateText rate={rate} />
          </span>
          {rate.is_demo ? <Badge size="sm">Demo</Badge> : null}
        </span>
      ),
    },
    { key: "date", header: "Dated", mobileLabel: "Dated", cell: (rate) => <DateText value={rate.rate_date} style="business" /> },
    {
      key: "source",
      header: "Source",
      mobileLabel: "Source",
      hideOnMobile: true,
      cell: (rate) => (
        <span className="flex min-w-0 flex-col">
          <span>{SOURCE[rate.source_kind] ?? rate.source_kind}</span>
          <span className="t-caption text-ink-3 [overflow-wrap:anywhere]">{rate.source_reference}</span>
        </span>
      ),
    },
    { key: "status", header: "Status", mobileLabel: "Status", cell: (rate) => <StatusBadge look={lookOf(STATUS, rate.status)} size="sm" /> },
    { key: "proposed", header: "Proposed by", mobileLabel: "Proposed by", hideOnMobile: true, cell: (rate) => rate.proposed_by_name ?? <Quiet>Not recorded</Quiet> },
    {
      key: "decision",
      header: "Decision",
      mobileLabel: "Decision",
      cell: (rate) =>
        rate.capabilities.decide?.allowed ? (
          <span className="flex flex-wrap gap-2">
            <Button size="sm" variant="inverse" iconLeft="check" onPress={() => setApproving(rate)} isDisabled={offline}>
              Approve
            </Button>
            <Button size="sm" variant="ghost" onPress={() => setRejecting(rate)} isDisabled={offline}>
              Reject
            </Button>
          </span>
        ) : rate.capabilities.withdraw?.allowed ? (
          <Button size="sm" variant="secondary" iconLeft="undo" onPress={() => setWithdrawing(rate)} isDisabled={offline}>
            Withdraw
          </Button>
        ) : rate.status === "proposed" && rate.capabilities.decide?.reason_code === "separation_of_duties" ? (
          <span className="t-body-sm text-ink-3">You proposed it. Someone else decides.</span>
        ) : (
          (rate.decided_by_name ?? <Quiet>Not decided</Quiet>)
        ),
    },
  ];

  return (
    <>
      <GlassPanel padding="none" className="rise">
        <DataTable
          label="Exchange rates"
          columns={columns}
          rows={query.data?.items ?? []}
          rowKey={(rate) => rate.id}
          loading={query.isPending}
          skeletonRows={5}
          empty={
            <EmptyState
              icon="banknote"
              title="Propose your first exchange rate"
              text="Give it a date and a source. Once a second person approves it, it can convert prices."
              actions={
                canPropose ? (
                  <Button variant="secondary" iconLeft="plus" onPress={onPropose}>
                    Propose a rate
                  </Button>
                ) : undefined
              }
            />
          }
        />
      </GlassPanel>

      <ConfirmDialog
        isOpen={approving !== null}
        onOpenChange={(open) => (open ? undefined : setApproving(null))}
        title="Approve this rate?"
        description={
          approving ? (
            <>
              <RateText rate={approving} />, dated <DateText value={approving.rate_date} style="business" />. Once approved it can convert prices on quotations.
            </>
          ) : undefined
        }
        confirmLabel="Approve rate"
        onConfirm={async () => {
          if (!approving) return;
          settle(await commands.run(`approve:${approving.id}`, [approving.version], () => decideFxRate(approving.id, "approve", null), { done: "Rate approved", failed: "The rate was not approved", conflictMessage: CONFLICT }));
        }}
      />
      <ReasonDialog
        isOpen={rejecting !== null}
        onOpenChange={(open) => (open ? undefined : setRejecting(null))}
        title="Reject this rate?"
        description={rejecting ? `1 ${rejecting.base_currency} = ${rejecting.rate} ${rejecting.quote_currency}. It will not be used, and the proposer sees your reason.` : undefined}
        reasonLabel="Reason"
        reasonHelp="What is wrong with the rate, its date or its source."
        confirmLabel="Reject rate"
        tone="danger"
        onConfirm={async (reason) => {
          if (!rejecting) return;
          settle(await commands.run(`reject:${rejecting.id}`, [rejecting.version, reason], () => decideFxRate(rejecting.id, "reject", reason), { done: "Rate rejected", failed: "The rate was not rejected", conflictMessage: CONFLICT }));
        }}
      />
      <ConfirmDialog
        isOpen={withdrawing !== null}
        onOpenChange={(open) => (open ? undefined : setWithdrawing(null))}
        title="Withdraw this rate?"
        description={withdrawing ? `1 ${withdrawing.base_currency} = ${withdrawing.rate} ${withdrawing.quote_currency}. It leaves the approval queue; propose it again if you still need it.` : undefined}
        confirmLabel="Withdraw rate"
        tone="danger"
        onConfirm={async () => {
          if (!withdrawing) return;
          settle(await commands.run(`withdraw:${withdrawing.id}`, [withdrawing.version], () => withdrawFxRate(withdrawing.id), { done: "Rate withdrawn", failed: "The rate was not withdrawn" }));
        }}
      />
    </>
  );
}

type PolicyDraft = Pick<FxPolicy, "conversion_enabled" | "conversion_source_currency" | "max_rate_age_days">;
const draftOf = (policy: FxPolicy): PolicyDraft => ({
  conversion_enabled: policy.conversion_enabled,
  conversion_source_currency: policy.conversion_source_currency,
  max_rate_age_days: policy.max_rate_age_days,
});

function Policy() {
  const query = useFxPolicy();
  const commands = useResourceCommand("fx_policy", POLICY_KEYS);
  const [edit, setEdit] = useState<{ version: number; draft: PolicyDraft } | null>(null);

  if (query.isPending) return <LoadingBlock lines={5} label="Loading the conversion policy" />;
  if (query.isError || !query.data) return <ErrorBlock error={query.error} what="The conversion policy" onRetry={() => void query.refetch()} />;

  const saved = query.data;
  const policy = edit && edit.version === saved.version ? edit.draft : draftOf(saved);
  const canManage = saved.capabilities.manage?.allowed === true;
  const dirty = JSON.stringify(policy) !== JSON.stringify(draftOf(saved));
  const set = (patch: Partial<PolicyDraft>) => setEdit({ version: saved.version, draft: { ...policy, ...patch } });

  const save = async () => {
    const outcome = await commands.run("save", [saved.version], () => updateFxPolicy(saved, policy), { done: "Conversion policy saved", failed: "The conversion policy was not saved", conflictMessage: CONFLICT });
    // A failed save keeps what was typed; a save or a conflict shows what the server now holds.
    if (outcome.ok || outcome.conflict) setEdit(null);
  };

  return (
    <form
      className="stack"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        if (canManage && dirty) void save();
      }}
    >
      {canManage ? null : <Banner tone="neutral">You can read the policy. Only people who manage exchange rates can change it.</Banner>}
      {commands.offline ? (
        <Banner tone="amber" title="You are offline.">
          The policy can be saved once the connection is back.
        </Banner>
      ) : null}
      <FormSection title="When a rate may convert a price" description="Applies when a quotation is in a currency that has no price list of its own.">
        <Switch
          className="col-span-full"
          label="Convert prices with approved rates"
          description="Off: a quotation in a currency without a price list gets no price until someone enters one."
          isSelected={policy.conversion_enabled}
          onChange={(conversion_enabled) => set({ conversion_enabled })}
          isDisabled={!canManage}
        />
        <Select
          label="Convert from"
          help="The currency whose price list is the starting point."
          options={CURRENCIES.map((code) => ({ value: code, label: code }))}
          value={policy.conversion_source_currency}
          onChange={(conversion_source_currency) => set({ conversion_source_currency })}
          isDisabled={!canManage}
        />
        <IntegerField
          label="Oldest rate allowed, days"
          help="A rate dated before this many days ago is not used."
          value={policy.max_rate_age_days}
          onChange={(value) => set({ max_rate_age_days: value ?? 0 })}
          minValue={0}
          isDisabled={!canManage}
        />
      </FormSection>
      {canManage ? (
        <FormActions note={dirty ? "Unsaved changes" : "No changes to save"}>
          <Button variant="ghost" onPress={() => setEdit(null)} isDisabled={!dirty || commands.pending === "save"}>
            Discard changes
          </Button>
          <Button type="submit" loading={commands.pending === "save"} isDisabled={!dirty || Boolean(commands.offline)}>
            Save policy
          </Button>
        </FormActions>
      ) : null}
    </form>
  );
}

export function FxRates({ view }: { view: FxView }) {
  const { permissionKeys } = useSession();
  const canRead = permissionKeys.has(FX_READ);
  const canPropose = permissionKeys.has(FX_CREATE);
  const commands = useResourceCommand("fx", RATE_KEYS);
  const [proposing, setProposing] = useState(false);

  if (!canRead) {
    return (
      <Page>
        <PageHeader breadcrumb={SETTINGS_CRUMBS} title="Exchange rates" />
        <NotPermitted what="Exchange rates" icon="banknote" />
      </Page>
    );
  }

  return (
    <Page>
      <PageHeader
        breadcrumb={SETTINGS_CRUMBS}
        title="Exchange rates"
        lead="Dated, sourced rates between your currencies. A rate converts prices only after a second person approves it."
        actions={
          canPropose && view === "rates" ? (
            <Button iconLeft="plus" onPress={() => setProposing(true)}>
              Propose a rate
            </Button>
          ) : undefined
        }
      />
      <Tabs
        label="Exchange rate views"
        selectedKey={view}
        tabs={[
          { id: "rates", label: "Rates", href: "/settings/fx-rates" },
          { id: "policy", label: "Conversion policy", href: asRoute("/settings/fx-rates?view=policy") },
        ]}
      />
      {view === "policy" ? <Policy /> : <Rates commands={commands} canPropose={canPropose} onPropose={() => setProposing(true)} />}
      {canPropose ? <ProposeDialog isOpen={proposing} onOpenChange={setProposing} commands={commands} /> : null}
    </Page>
  );
}
