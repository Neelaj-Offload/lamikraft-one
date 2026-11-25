"use client";

import { useState, type FormEvent } from "react";
import { fetchQuote, updateQuoteHeader } from "@/features/sales/api";
import { INCOTERMS, PRICE_TYPES, type QuoteDetail } from "@/features/sales/types";
import {
  dirtyHeaderFields,
  headerChanges,
  headerFormOf,
  mergeHeaderConflict,
  type HeaderConflictState,
  type HeaderForm,
} from "@/features/sales/workspace-model";
import { conflictFromError, type ConflictInfo } from "@/lib/api/errors";
import { PRICE_TYPE_LABEL, quotationStatus } from "~/data/sales-deals";
import { Banner, Button, DateText, FormActions, FormSection, GlassPanel, IntegerField, KeyValue, Select, Switch, Textarea, TextField } from "~/ui";
import type { QuoteCommands } from "./quotation-actions";

const FIELD_LABEL: Record<string, string> = {
  price_type: "price type",
  incoterm: "incoterm",
  incoterm_place: "incoterm place",
  payment_terms: "payment terms",
  validity_days: "validity",
  customer_reference: "customer reference",
  remarks: "remarks",
  apply_minimum_surcharge: "minimum order surcharge",
};
const NO_INCOTERM = "none";
const names = (fields: readonly string[]) => fields.map((field) => FIELD_LABEL[field] ?? field).join(", ");

export interface TermsDraft {
  form: HeaderForm;
  dirty: (keyof HeaderForm)[];
  conflict: { info: ConflictInfo; merge: HeaderConflictState } | null;
  error: string | null;
  set: <K extends keyof HeaderForm>(field: K, value: HeaderForm[K]) => void;
  save: () => Promise<void>;
  discard: () => void;
}

/**
 * The terms form's state, held by the record so unsaved edits survive a move to another view.
 * A 409 becomes a three-way merge: their changes are adopted, your edits stay in the form, and
 * nothing of theirs is overwritten unless you save again.
 */
export function useTermsDraft(quote: QuoteDetail, commands: QuoteCommands): TermsDraft {
  const [state, setState] = useState<{ base: HeaderForm; form: HeaderForm; version: number }>(() => {
    const base = headerFormOf(quote);
    return { base, form: base, version: quote.version };
  });
  const [conflict, setConflict] = useState<TermsDraft["conflict"]>(null);
  const [error, setError] = useState<string | null>(null);
  const dirty = dirtyHeaderFields(state.base, state.form);

  // A newer server version with no local edits: show it (someone else, or a line command, changed the quotation).
  if (quote.version !== state.version && dirty.length === 0 && !conflict) {
    const base = headerFormOf(quote);
    setState({ base, form: base, version: quote.version });
  }

  const set: TermsDraft["set"] = (field, value) => {
    setState((current) => ({ ...current, form: { ...current.form, [field]: value } }));
    if (field === "validity_days") setError(null);
  };

  const save = async () => {
    if (dirty.includes("validity_days") && !(state.form.validity_days && /^[1-9]\d*$/.test(state.form.validity_days))) {
      setError("Say how many days the prices hold, as a whole number. 30 is usual.");
      return;
    }
    const changes = headerChanges(state.base, state.form);
    if (Object.keys(changes).length === 0) return;
    const target = { id: quote.id, version: state.version };
    const outcome = await commands.run("update_header", [state.version, JSON.stringify(changes)], (key) => updateQuoteHeader(target, changes, key), {
      done: "Terms saved",
      failed: "The terms were not saved",
      onConflict: async (problem) => {
        const info = conflictFromError(problem)!;
        const fresh = await fetchQuote(quote.id);
        const merge = mergeHeaderConflict(state.base, state.form, fresh, { changedBy: info.changedBy, changedAt: info.changedAt });
        setConflict({ info, merge });
        setState({ base: merge.base, form: merge.form, version: merge.version });
        void commands.reload();
      },
    });
    if (outcome.ok) {
      const fresh = outcome.quote ?? quote;
      const base = headerFormOf(fresh);
      setConflict(null);
      setState({ base, form: base, version: fresh.version });
    }
  };

  const discard = () => {
    const base = conflict ? conflict.merge.base : headerFormOf(quote);
    setConflict(null);
    setError(null);
    setState({ base, form: base, version: conflict ? conflict.merge.version : quote.version });
  };

  return { form: state.form, dirty, conflict, error, set, save, discard };
}

/** Commercial terms: a form while the quotation is a draft or a revision, a record once it is issued. */
export function TermsView({ quote, editable, commands, draft }: { quote: QuoteDetail; editable: boolean; commands: QuoteCommands; draft: TermsDraft }) {
  if (!editable) return <TermsRecord quote={quote} />;
  const { form, dirty, conflict, set } = draft;
  const days = form.validity_days && /^\d+$/.test(form.validity_days) ? Number.parseInt(form.validity_days, 10) : null;
  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void draft.save();
  };

  return (
    <form onSubmit={onSubmit} className="stack" noValidate>
      {conflict ? (
        <Banner
          tone="amber"
          title={conflict.info.changedBy ? `${conflict.info.changedBy} changed this quotation while you were editing.` : "This quotation changed while you were editing."}
          action={
            <span className="flex flex-wrap gap-2">
              <Button size="sm" variant="secondary" onPress={draft.discard}>
                Use their version
              </Button>
              <Button size="sm" variant="inverse" onPress={() => void draft.save()} loading={commands.pending === "update_header"}>
                Save mine
              </Button>
            </span>
          }
        >
          {conflict.merge.conflicts.length > 0
            ? `You both changed: ${names(conflict.merge.conflicts)}. Your values are still in the form.`
            : "Your changes do not overlap with theirs. Save again to apply them."}
          {conflict.merge.adopted.length > 0 ? ` Taken over from them: ${names(conflict.merge.adopted)}.` : ""}
          {conflict.info.changedAt ? (
            <>
              {" "}
              Their change: <DateText value={conflict.info.changedAt} style="dayTime" />.
            </>
          ) : null}
        </Banner>
      ) : null}

      <FormSection title="Pricing and delivery" description="These decide the price every line gets and where your responsibility for the goods ends.">
        <Select
          label="Price type"
          options={PRICE_TYPES.map((type) => ({ value: type, label: PRICE_TYPE_LABEL[type] ?? type }))}
          value={form.price_type}
          onChange={(value) => set("price_type", PRICE_TYPES.find((type) => type === value) ?? form.price_type)}
          help="Changing it reprices the catalogue lines."
        />
        <IntegerField
          label="Valid for, days"
          value={days}
          onChange={(value) => set("validity_days", value === null ? null : String(value))}
          minValue={1}
          isRequired
          error={draft.error ?? undefined}
          help={quote.valid_until ? <>Currently valid until <DateText value={quote.valid_until} style="business" />.</> : "Counted from the day the quotation is sent."}
        />
        <Select
          label="Incoterm"
          options={[{ value: NO_INCOTERM, label: "None" }, ...INCOTERMS.map((term) => ({ value: term, label: term }))]}
          value={form.incoterm ?? NO_INCOTERM}
          onChange={(value) => set("incoterm", value === NO_INCOTERM ? null : value)}
        />
        <TextField label="Incoterm place" optional placeholder="Port or city" value={form.incoterm_place} onChange={(value) => set("incoterm_place", value)} maxLength={120} />
        <Switch
          className="col-span-full"
          label="Add the minimum order surcharge"
          description="Applied only when the quotation totals less than the customer's minimum order value."
          isSelected={form.apply_minimum_surcharge}
          onChange={(value) => set("apply_minimum_surcharge", value)}
        />
      </FormSection>

      <FormSection title="Payment and references" description="Printed on the quotation the customer receives.">
        <TextField
          label="Payment terms"
          optional
          placeholder="For example 30% advance, 70% before dispatch"
          value={form.payment_terms}
          onChange={(value) => set("payment_terms", value)}
          maxLength={200}
        />
        <TextField label="Their reference" optional value={form.customer_reference} onChange={(value) => set("customer_reference", value)} maxLength={120} />
        <Textarea className="col-span-full" label="Remarks" optional rows={3} value={form.remarks} onChange={(value) => set("remarks", value)} />
      </FormSection>

      <FormActions note={commands.offline ?? (dirty.length > 0 ? `Unsaved: ${names(dirty)}` : "No unsaved changes")}>
        {dirty.length > 0 ? (
          <Button variant="ghost" onPress={draft.discard}>
            Discard
          </Button>
        ) : null}
        <Button type="submit" variant="inverse" loading={commands.pending === "update_header"} isDisabled={dirty.length === 0 || Boolean(commands.offline)}>
          Save terms
        </Button>
      </FormActions>
    </form>
  );
}

function TermsRecord({ quote }: { quote: QuoteDetail }) {
  const status = quotationStatus(quote.status).label.toLowerCase();
  return (
    <div className="stack">
      <GlassPanel
        padding="lg"
        title="Terms"
        titleAs="h2"
        className="rise"
        action={<span className="t-caption text-ink-3">Locked while {status}{quote.status === "sent" ? ". Revise to change them" : ""}</span>}
      >
        <KeyValue
          columns={2}
          items={[
            { label: "Price type", value: PRICE_TYPE_LABEL[quote.price_type] ?? quote.price_type },
            { label: "Currency", value: quote.currency },
            { label: "Incoterm", value: [quote.incoterm, quote.incoterm_place].filter(Boolean).join(" · ") },
            { label: "Payment terms", value: quote.payment_terms },
            { label: "Valid for", value: quote.validity_days === 1 ? "1 day" : `${quote.validity_days} days` },
            { label: "Valid until", value: quote.valid_until ? <DateText value={quote.valid_until} style="business" /> : null },
            { label: "Their reference", value: quote.customer_reference },
            { label: "Minimum order surcharge", value: quote.apply_minimum_surcharge ? "Added when the total is below the minimum" : "Not added" },
            { label: "Remarks", value: quote.remarks ? <span className="whitespace-pre-line">{quote.remarks}</span> : null },
          ]}
        />
      </GlassPanel>
    </div>
  );
}
