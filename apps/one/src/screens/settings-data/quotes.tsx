"use client";

import { useState } from "react";
import { useResourceCommand } from "@/features/sales/resource-command";
import { INCOTERMS, PRICE_TYPES } from "@/features/sales/types";
import { isProblemError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { CURRENCIES } from "@/lib/format/money";
import { useSession } from "@/lib/session/context";
import { QUOTATIONS_READ, saveQuoteSettings, useQuoteSettings, type QuoteSettings } from "~/data/settings-data";
import { Page, PageHeader, Split } from "~/shell/page";
import { ErrorBlock, LoadingBlock, NotPermitted } from "~/shell/states";
import { Banner, Button, FormActions, FormSection, GlassPanel, IntegerField, KeyValue, Select, Switch, TextField } from "~/ui";
import { Mono, SETTINGS_CRUMBS } from "./shared";

/**
 * What a new quotation starts with, and the numbers the next quotation, custom product and sample
 * will take. Saving replaces the defaults against the version on screen (409 if someone saved first).
 */

const QUOTE_KEYS = [queryKeys.sales.quoteSettings()] as const;
const PRICE_TYPE_LABEL: Record<string, string> = { export: "Export", domestic: "Domestic", sample: "Sample", distributor: "Distributor" };
const CONFLICT = "Someone else saved the quotation defaults first. The latest values are on screen; make your change again.";

const header = (
  <PageHeader
    breadcrumb={SETTINGS_CRUMBS}
    title="Quotations"
    lead="What every new quotation starts with, and the numbers the next ones will take. Previews never use up a number."
  />
);

function resetText(policy: string): string {
  if (policy === "never") return "Quotation numbers never reset, so they carry on from the old system.";
  return `Quotation numbers reset ${policy.replace(/_/g, " ")}.`;
}

function Numbering({ settings }: { settings: QuoteSettings }) {
  return (
    <GlassPanel title="Next numbers" titleAs="h2" eyebrow="Numbering" className="rise">
      <div className="flex min-w-0 flex-col gap-4">
        <KeyValue
          rows
          items={[
            ...Object.entries(settings.next_quote_numbers).map(([brand, number]) => ({ label: `Next ${brand} quotation`, value: <Mono>{number}</Mono> })),
            { label: "Next custom product", value: <Mono>{settings.next_custom_product_code}</Mono> },
            { label: "Next sample", value: <Mono>{settings.next_sample_number}</Mono> },
          ]}
        />
        <p className="t-body-sm text-ink-3">{resetText(settings.quote_sequence_reset_policy)}</p>
      </div>
    </GlassPanel>
  );
}

function DefaultsForm({ settings }: { settings: QuoteSettings }) {
  const commands = useResourceCommand("quote_settings", QUOTE_KEYS);
  const [edit, setEdit] = useState<{ version: number; form: Record<string, unknown> } | null>(null);
  const [reason, setReason] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const canManage = settings.capabilities.manage?.allowed === true;
  // A draft belongs to the version it was started on; a newer version on screen replaces an untouched draft.
  const form = edit && edit.version === settings.version ? edit.form : settings.defaults;
  const dirty = JSON.stringify(form) !== JSON.stringify(settings.defaults);
  const set = (field: string, value: unknown) => setEdit({ version: settings.version, form: { ...form, [field]: value } });

  const save = async () => {
    const outcome = await commands.run("save", [settings.version, JSON.stringify(form)], () => saveQuoteSettings({ version: settings.version }, form, reason), {
      done: "Quotation defaults saved",
      failed: "The quotation defaults were not saved",
      conflictMessage: CONFLICT,
    });
    if (outcome.ok) {
      setEdit(null);
      setReason("");
      setErrors({});
    } else {
      setErrors(outcome.fieldErrors);
      if (outcome.conflict) setEdit(null);
    }
  };

  const validity = form.validity_days;
  return (
    <form
      className="stack"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        if (canManage && dirty && !commands.offline) void save();
      }}
    >
      {canManage ? null : <Banner tone="neutral">You can read these defaults. Only people who manage quotation settings can change them.</Banner>}
      {commands.offline ? (
        <Banner tone="amber" title="You are offline.">
          The defaults can be saved once the connection is back.
        </Banner>
      ) : null}
      <FormSection title="A new quotation starts with" description="Anyone writing a quotation can still change each of these on it.">
        <Select
          label="Currency"
          options={CURRENCIES.map((code) => ({ value: code, label: code }))}
          value={String(form.currency ?? "EUR")}
          onChange={(value) => set("currency", value)}
          isDisabled={!canManage}
          error={errors.currency}
        />
        <Select
          label="Brand"
          options={settings.brands.map((brand) => ({ value: brand, label: brand }))}
          value={String(form.brand ?? "LK")}
          onChange={(value) => set("brand", value)}
          isDisabled={!canManage}
          error={errors.brand}
        />
        <Select
          label="Price type"
          options={PRICE_TYPES.map((type) => ({ value: type, label: PRICE_TYPE_LABEL[type] ?? type }))}
          value={String(form.price_type ?? "export")}
          onChange={(value) => set("price_type", value)}
          isDisabled={!canManage}
          error={errors.price_type}
        />
        <Select
          label="Incoterm"
          options={INCOTERMS.map((term) => ({ value: term, label: term }))}
          value={String(form.incoterm ?? "FOB")}
          onChange={(value) => set("incoterm", value)}
          isDisabled={!canManage}
          error={errors.incoterm}
        />
        <IntegerField
          label="Valid for, days"
          help="How long the price holds once the quotation is sent."
          value={typeof validity === "number" ? validity : validity === null ? null : 30}
          onChange={(value) => set("validity_days", value)}
          minValue={0}
          isDisabled={!canManage}
          error={errors.validity_days}
        />
        <Switch
          className="col-span-full"
          label="A duplicated quotation keeps its owner"
          description="Applies when the person duplicating it may assign quotations. Otherwise the copy is theirs."
          isSelected={form.duplicate_copies_assignee === true}
          onChange={(value) => set("duplicate_copies_assignee", value)}
          isDisabled={!canManage}
        />
        {canManage ? (
          <TextField
            className="col-span-full"
            label="Reason for the change"
            optional
            help="Kept with this version, for whoever looks back at it."
            value={reason}
            onChange={setReason}
            maxLength={500}
            error={errors.change_reason}
          />
        ) : null}
      </FormSection>
      {canManage ? (
        <FormActions note={dirty ? "Unsaved changes" : "No changes to save"}>
          <Button
            variant="ghost"
            onPress={() => {
              setEdit(null);
              setErrors({});
            }}
            isDisabled={!dirty || commands.pending === "save"}
          >
            Discard changes
          </Button>
          <Button type="submit" loading={commands.pending === "save"} isDisabled={!dirty || Boolean(commands.offline)}>
            Save defaults
          </Button>
        </FormActions>
      ) : null}
    </form>
  );
}

export function QuotationSettings() {
  const { permissionKeys } = useSession();
  const canRead = permissionKeys.has(QUOTATIONS_READ);
  const query = useQuoteSettings(canRead);

  if (!canRead || (query.isError && isProblemError(query.error) && query.error.status === 403)) {
    return (
      <Page>
        {header}
        <NotPermitted what="Quotation settings" icon="fileText" />
      </Page>
    );
  }
  if (query.isPending) {
    return (
      <Page>
        {header}
        <LoadingBlock lines={8} label="Loading the quotation settings" />
      </Page>
    );
  }
  if (query.isError || !query.data) {
    return (
      <Page>
        {header}
        <ErrorBlock error={query.error} what="The quotation settings" onRetry={() => void query.refetch()} />
      </Page>
    );
  }
  return (
    <Page>
      {header}
      <Split main={<DefaultsForm settings={query.data} />} aside={<Numbering settings={query.data} />} />
    </Page>
  );
}
