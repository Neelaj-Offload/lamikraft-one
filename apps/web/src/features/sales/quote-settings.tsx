"use client";

import { useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Form } from "react-aria-components";
import { Button, unavailableWhen } from "@/components/ui/button";
import { Switch } from "@/components/ui/choice";
import { DescriptionList } from "@/components/ui/description-list";
import { NumberField } from "@/components/ui/number-field";
import { Select } from "@/components/ui/select";
import { ErrorState, Loading, PermissionDenied } from "@/components/ui/states";
import { TextField } from "@/components/ui/text-field";
import { api, requestUntyped, type ApiClient } from "@/lib/api/client";
import { isProblemError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { CURRENCIES } from "@/lib/format/money";
import { useSession } from "@/lib/session/context";
import { commercialMessages as c } from "@/messages/commercial";
import { salesMessages as sm } from "@/messages/sales";
import { useResourceCommand } from "./resource-command";
import { INCOTERMS, PRICE_TYPES } from "./types";

const m = c.settings;
const PATH = "/api/v1/sales/quote-settings";

export interface QuoteSettings {
  defaults: Record<string, unknown>;
  version: number;
  brands: string[];
  next_quote_numbers: Record<string, string>;
  next_custom_product_code: string;
  next_sample_number: string;
  quote_sequence_reset_policy: string;
  capabilities: Record<string, { allowed: boolean; reason_code?: string | null }>;
}

export async function fetchQuoteSettings(signal?: AbortSignal, client: ApiClient = api): Promise<QuoteSettings> {
  return requestUntyped<QuoteSettings>(client, "get", PATH, { signal });
}

export async function saveQuoteSettings(settings: Pick<QuoteSettings, "version">, defaults: Record<string, unknown>, reason: string | null, client: ApiClient = api) {
  return requestUntyped<QuoteSettings>(client, "put", PATH, {
    body: { defaults, expected_version: settings.version, ...(reason?.trim() ? { change_reason: reason.trim() } : {}) },
  });
}

export function QuoteSettingsPage() {
  const { permissionKeys } = useSession();
  const canRead = permissionKeys.has("sales.quote.read");
  const query = useQuery({ queryKey: queryKeys.sales.quoteSettings(), queryFn: ({ signal }) => fetchQuoteSettings(signal), enabled: canRead });
  if (!canRead) return <PermissionDenied area={m.title} />;
  if (query.isPending) return <Loading label={m.loading} variant="detail" />;
  if (query.isError) {
    if (isProblemError(query.error) && query.error.status === 403) return <PermissionDenied area={m.title} />;
    return <ErrorState error={query.error} what={m.loading} onRetry={() => void query.refetch()} />;
  }
  return <SettingsForm settings={query.data} />;
}

function SettingsForm({ settings }: { settings: QuoteSettings }) {
  const commands = useResourceCommand("quote_settings", [queryKeys.sales.quoteSettings()]);
  const [state, setState] = useState({ version: settings.version, form: settings.defaults });
  const [reason, setReason] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  if (settings.version !== state.version && JSON.stringify(state.form) === JSON.stringify(settings.defaults)) setState({ version: settings.version, form: settings.defaults });
  const canManage = settings.capabilities.manage?.allowed === true;
  const form = state.form;
  const set = (field: string, value: unknown) => setState({ ...state, form: { ...form, [field]: value } });
  const dirty = JSON.stringify(form) !== JSON.stringify(settings.defaults);
  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const outcome = await commands.run("save", [state.version, JSON.stringify(form)], () => saveQuoteSettings({ version: state.version }, form, reason), {
      done: m.saved,
      failed: c.common.failed(c.common.save),
      conflictMessage: c.common.conflict,
    });
    if (outcome.ok) {
      setState({ version: outcome.value.version, form: outcome.value.defaults });
      setReason("");
      setErrors({});
    } else setErrors(outcome.fieldErrors);
  };
  const f = (field: string) => m.fields[field] ?? field;
  return (
    <div className="flex max-w-3xl flex-col gap-8">
      <header className="flex flex-col gap-1">
        <h1 className="text-[28px] font-bold tracking-tight md:text-3xl">{m.title}</h1>
        <p className="text-ink-muted">{m.intro}</p>
        {!canManage ? <p className="text-sm text-ink-muted">{m.readOnly}</p> : null}
      </header>
      <section aria-label={m.defaults} className="flex flex-col gap-4">
        <h2 className="text-lg font-[650] text-ink">{m.defaults}</h2>
        <Form onSubmit={(event) => void save(event)} className="flex flex-col gap-4" validationBehavior="aria">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Select label={f("currency")} options={CURRENCIES.map((code) => ({ id: code, label: code }))} value={String(form.currency ?? "EUR")} onChange={(value) => set("currency", value)} isDisabled={!canManage} errorMessage={errors.currency} />
            <Select label={f("brand")} options={settings.brands.map((brand) => ({ id: brand, label: brand }))} value={String(form.brand ?? "LK")} onChange={(value) => set("brand", value)} isDisabled={!canManage} errorMessage={errors.brand} />
            <Select label={f("price_type")} options={PRICE_TYPES.map((type) => ({ id: type, label: sm.priceTypes[type] ?? type }))} value={String(form.price_type ?? "export")} onChange={(value) => set("price_type", value)} isDisabled={!canManage} />
            <Select label={f("incoterm")} options={INCOTERMS.map((term) => ({ id: term, label: term }))} value={String(form.incoterm ?? "FOB")} onChange={(value) => set("incoterm", value)} isDisabled={!canManage} errorMessage={errors.incoterm} />
            <NumberField label={f("validity_days")} value={String(form.validity_days ?? 30)} onChange={(value) => set("validity_days", value ? Number.parseInt(value, 10) : null)} maxFractionDigits={0} isDisabled={!canManage} errorMessage={errors.validity_days} />
          </div>
          <Switch isSelected={form.duplicate_copies_assignee === true} onChange={(value) => set("duplicate_copies_assignee", value)} isDisabled={!canManage}>
            {f("duplicate_copies_assignee")}
          </Switch>
          {canManage ? (
            <>
              <TextField label={f("change_reason")} value={reason} onChange={setReason} maxLength={500} />
              <div>
                <Button type="submit" variant={dirty ? "primary" : "secondary"} isPending={commands.pending === "save"} pendingLabel={c.common.saving} {...unavailableWhen(commands.offline ?? (dirty ? null : "No changes to save"))}>
                  {c.common.save}
                </Button>
              </div>
            </>
          ) : null}
        </Form>
      </section>
      <section aria-label={m.numbering} className="flex flex-col gap-3">
        <h2 className="text-lg font-[650] text-ink">{m.numbering}</h2>
        <DescriptionList
          items={[
            ...Object.entries(settings.next_quote_numbers).map(([brand, number]) => ({ term: m.nextQuote(brand), description: <span className="font-mono">{number}</span> })),
            { term: m.nextCustom, description: <span className="font-mono">{settings.next_custom_product_code}</span> },
            { term: m.nextSample, description: <span className="font-mono">{settings.next_sample_number}</span> },
          ]}
        />
        <p className="text-sm text-ink-muted">{m.resetPolicy(settings.quote_sequence_reset_policy)}</p>
      </section>
    </div>
  );
}
